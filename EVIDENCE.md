# EVIDENCE

One pasted proof per Section 6 box. A box without a paste is not done.

## Metering

### Exactly-once usage event under retries

Same `POST /generate` twice, same tenant, same `Idempotency-Key: probe-1`. Both responses share one event id.

```
curl -X POST http://127.0.0.1:8000/generate -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111" -H "Idempotency-Key: probe-1" -H "Content-Type: application/json" -d "{\"meter\":\"api_call\"}"
{"id":"61dca148-a1f6-4cc1-aa52-785f6d682958","meter":"api_call","quantity":1,"idempotency_key":"probe-1"}

curl -X POST http://127.0.0.1:8000/generate -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111" -H "Idempotency-Key: probe-1" -H "Content-Type: application/json" -d "{\"meter\":\"api_call\"}"
{"id":"61dca148-a1f6-4cc1-aa52-785f6d682958","meter":"api_call","quantity":1,"idempotency_key":"probe-1"}
```

Date: 2026-08-30. Tenant: demo `11111111-1111-1111-1111-111111111111`.

### Proof that double-counting cannot happen

Postgres after those two requests: one row, same id. The unique index `uq_usage_events_tenant_idempotency` on `(tenant_id, idempotency_key)` rejected a second insert; the handler returned the first row.

```
docker compose exec db psql -U metering -d metering -c "SELECT id, idempotency_key FROM usage_events;"
                  id                  | idempotency_key
--------------------------------------+-----------------
 61dca148-a1f6-4cc1-aa52-785f6d682958 | probe-1
(1 row)
```

## Quotas

### Over-limit requests rejected

_Pending — Probe 2._

### 429 / 402 with a clear message

_Pending — quota vs plan/payment._

## Cost calculation

### Monthly rollup per tenant

_Pending — GET /usage._

### Cached input, reasoning, output priced correctly

_Pending — Probe 5._

### Pricing constants pinned in config

_Pending — totals match this file._

## Stripe integration

### Checkout end-to-end in test mode

_Pending — Probe 3._

### Webhooks: verify, dedupe, update plan/status

_Pending — Probe 4._

## Data model, tests & documentation

### tenants, plans, subscriptions, usage_events; tenant isolation

_Pending — schema + a cross-tenant query that returns nothing._

### README, diagram, setup; required pack files

_Pending — Phase 4._
