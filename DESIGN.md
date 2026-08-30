# Design: metering-billing-engine

One-page design for the FlyRank Usage Metering & Billing Engine capstone.
Stack: Python + FastAPI + PostgreSQL (Docker). Stripe test mode only.

## Problem

A tenant belongs to a plan. Every billable action must (1) record **exactly one** usage event for a given idempotency key, (2) refuse work that would exceed the plan's monthly quota, (3) expose used / limit / cost, (4) mirror Stripe subscription state through **signature-verified** webhooks only.

Dummy billable action: `POST /generate` (no real model). It records either 1 API call, or a simulated token breakdown, then returns.

## Non-goal (explicit)

No invoicing, proration, overage billing, live Stripe, public tunnels, or real model calls. One subscription per tenant. Calendar month UTC is the quota window (not Stripe's billing period).

## Data model

```
tenants
  id, name, stripe_customer_id NULL, created_at

plans                          # seeded, not user-editable
  id, code (free|pro), api_call_limit, token_limit, stripe_price_id NULL

subscriptions
  id, tenant_id UNIQUE, plan_id, status (active|canceled|past_due),
  stripe_subscription_id NULL, updated_at

usage_events
  id, tenant_id, meter (api_call|ai_tokens),
  quantity,                         # api_call: 1; ai_tokens: billed output-equivalent count for quota
  input_tokens, cached_input_tokens, output_tokens, reasoning_tokens,  # 0 on api_call rows
  idempotency_key, created_at
  UNIQUE (tenant_id, idempotency_key)

processed_stripe_events
  event_id PK, event_type, processed_at

usage_monthly_snapshots         # written only by the background job
  tenant_id, period_yyyy_mm, api_calls_used, tokens_used, cost_micro_usd, computed_at
  UNIQUE (tenant_id, period_yyyy_mm)
```

**Idempotency lock (metering):** `UNIQUE (tenant_id, idempotency_key)`. The key *names* the client intent. The unique index is what makes a concurrent retry safe: first `INSERT` wins; conflict returns that same row and the original success payload. We do **not** rely on a Python `if` check.

**Idempotency lock (Stripe):** `processed_stripe_events.event_id` primary key. Replay of the same webhook is a no-op.

**Quota race (different keys):** uniqueness on the idempotency key does not stop two *different* requests from both seeing "999 used" and both inserting. Record + quota increment happen in **one transaction**, locking the tenant's subscription row (`SELECT … FOR UPDATE`) so only one writer at a time can decide allow vs 429.

**Money:** integer **micro-USD** (1_000_000 = $1.00), never floats. Token prices are tiny; cents would round many events to zero.

## Plans (quotas)

| Plan | API calls / UTC month | AI tokens / UTC month |
|------|------------------------|------------------------|
| Free | 1,000                  | 100,000                |
| Pro  | 10,000                 | 1,000,000              |

Pro numbers are our choice (10× Free). Documented here and in the README.

## Boundary rule (429 / 402)

Allow when `used + requested <= limit` (exactly at the cap is allowed). The next request that would pass the cap is rejected. **No usage row** on a rejection.

- **429** + `Retry-After` + message: plan is **active**, meter exhausted (API calls or tokens).
- **402** + message: plan/payment state does not allow the action (canceled / past_due, or a Pro-only action on Free).

Duplicate key on a *successful* first request: return the stored result even if quota is now full (the event already exists).

## API surface

Demo auth: required header `X-Tenant-Id` (UUID). Not real auth; isolation is still per tenant in every query.

| Method | Path | Role |
|--------|------|------|
| POST | `/generate` | Billable. Header `Idempotency-Key` required. Body: meter + optional token breakdown. |
| GET  | `/usage` | Live rollup from `usage_events` for the current UTC month: used, limit, cost per meter. |
| POST | `/checkout` | Create Stripe Checkout Session (Pro). Returns the Checkout URL. |
| POST | `/webhooks/stripe` | Raw body, verify `Stripe-Signature`. Handle `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`. |
| GET  | `/health` | Liveness. |

Validation at the HTTP boundary: missing key, bad UUID, unknown meter, negative tokens → **4xx**, never 500.

Payment truth is Stripe. `subscriptions` and `tenants.stripe_customer_id` change only after a verified webhook.

## Layers

```
HTTP (FastAPI routers, status codes, request validation)
  → services (meter, quota, cost, stripe_sync)
    → persistence (SQLAlchemy models, Alembic migrations)
jobs/rollup  → snapshots + drift alert (off the request path)
```

`GET /usage` always sums `usage_events` (source of truth). The background job writes `usage_monthly_snapshots` and logs an alert if snapshot ≠ live sum. Retries on failure. This satisfies the internship "≥1 background job" rule without making the read path eventually-consistent.

## Cost (pinned later in config)

Token categories are **not** added as one pile:

- cached input: cheaper than fresh input
- reasoning: priced as output
- output: output price
- fresh input: input price

API-call monthly cost is a pinned per-call micro-USD amount. Exact constants live in config; Probe 5 proofs go in `EVIDENCE.md`.

## Stripe (test mode)

Secrets only in `.env` (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`). Local delivery: Stripe CLI `listen --forward-to localhost:8000/webhooks/stripe`. No live mode, no card, no tunnel.
