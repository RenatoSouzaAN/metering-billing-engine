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

Free cap is 1000 API calls. After fill, `COUNT(*)` was 1000. A **new** key `over-1` / `over-2` must not insert.

```
curl -X POST http://127.0.0.1:8000/generate -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111" -H "Idempotency-Key: over-1" -H "Content-Type: application/json" -d "{\"meter\":\"api_call\"}"
{"detail":"usage quota exceeded: 1000 of 1000 API calls used"}

curl -i -X POST http://127.0.0.1:8000/generate -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111" -H "Idempotency-Key: over-2" -H "Content-Type: application/json" -d "{\"meter\":\"api_call\"}"
HTTP/1.1 429 Too Many Requests
{"detail":"usage quota exceeded: 1000 of 1000 API calls used"}

docker compose exec db psql -U metering -d metering -c "SELECT COUNT(*) FROM usage_events;"
 count
-------
  1000
(1 row)
```

Date: 2026-08-30. `used + 1 > limit` rejected the insert. Later: `Retry-After` present on 429 (`retry-after: 87061` on `over-3`).

### 429 / 402 with a clear message

429 (quota, active plan): proved above. Message states used/limit. `Retry-After` is seconds until next UTC month, not prose.

402 (plan/payment): `UPDATE subscriptions SET status = 'canceled'` for the demo tenant, then a **new** key. Status check runs **before** quota, so we get 402 not 429. No `Retry-After`. `COUNT(*)` stayed 1000.

```
docker compose exec db psql -U metering -d metering -c "UPDATE subscriptions SET status = 'canceled' WHERE tenant_id = '11111111-1111-1111-1111-111111111111';"
UPDATE 1

curl -i -X POST http://127.0.0.1:8000/generate -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111" -H "Idempotency-Key: probe-402" -H "Content-Type: application/json" -d "{\"meter\":\"api_call\"}"
HTTP/1.1 402 Payment Required
date: Mon, 31 Aug 2026 00:09:10 GMT
server: uvicorn
content-length: 55
content-type: application/json

{"detail":"upgrade or pay: subscription is not active"}
```

Then set `status` back to `active` so later probes work.

## Cost calculation

### Monthly rollup per tenant

`GET /usage` live-sums this UTC month. Demo tenant after API fill + two token events:

```
curl -i http://127.0.0.1:8000/usage -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111"
HTTP/1.1 200 OK

{"tenant_id":"11111111-1111-1111-1111-111111111111","period":"2026-08","subscription_status":"active","api_calls":{"used":1000,"limit":1000},"ai_tokens":{"used":2000,"limit":100000},"cost_micro_usd":100637}
```

Date: 2026-08-31.

### Cached input, reasoning, output priced correctly

Reasoning billed as output (`1000 * 600_000 // 1_000_000` = 600). Cached cheaper than input (`1000 * 37_500 // 1_000_000` = 37). Not one pile at one rate.

```
curl -i -X POST http://127.0.0.1:8000/generate -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111" -H "Idempotency-Key: cost-reason" -H "Content-Type: application/json" -d "{\"meter\":\"ai_tokens\",\"reasoning_tokens\":1000}"
HTTP/1.1 200 OK
{"id":"94186764-3474-4cff-9d7e-b62f54551a45","meter":"ai_tokens","quantity":1000,"idempotency_key":"cost-reason"}

curl -i -X POST http://127.0.0.1:8000/generate -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111" -H "Idempotency-Key: cost-cache" -H "Content-Type: application/json" -d "{\"meter\":\"ai_tokens\",\"cached_input_tokens\":1000}"
HTTP/1.1 200 OK
{"id":"a05a2a15-9a1a-47f6-ad67-186712bf04a2","meter":"ai_tokens","quantity":1000,"idempotency_key":"cost-cache"}
```

### Pricing constants pinned in config

`app/config.py` defaults: API call 100 micro-USD; input 150_000 / million; cached 37_500 / million; output (and reasoning) 600_000 / million.

Expected total: `1000*100` + `600` + `37` = **100637**. Matches `GET /usage` above.

## Stripe integration

### Checkout end-to-end in test mode

Test-mode Checkout for demo tenant `11111111-1111-1111-1111-111111111111`. First `checkout.session.completed` hit a 500 (`Session` is not a dict). After converting the payload with `to_dict()`, we resent `evt_1UAXjfDowGOJC2PgSeU4vrsI` (CLI forwarded HTTP 200). Plan flipped Free → Pro. Limits on `GET /usage` are 10000 / 1000000.

```
curl -s http://127.0.0.1:8000/usage -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111"
{"tenant_id":"11111111-1111-1111-1111-111111111111","period":"2026-08","subscription_status":"active","api_calls":{"used":1000,"limit":10000},"ai_tokens":{"used":2000,"limit":1000000},"cost_micro_usd":100637}
```

```
docker compose exec db psql -U metering -d metering -c "SELECT s.status, p.code, p.api_call_limit, p.token_limit FROM subscriptions s JOIN plans p ON p.id = s.plan_id;"
 status | code | api_call_limit | token_limit
--------+------+----------------+-------------
 active | pro  |          10000 |     1000000
(1 row)
```

Date: 2026-08-31. Payment truth was the webhook, not `/health?checkout=success`.

### Webhooks: verify, dedupe, update plan/status

Forged `Stripe-Signature` is rejected before `session.add`. Replay of the same real `evt_1UAXjfDowGOJC2PgSeU4vrsI` is HTTP 200 from the CLI forwarder; `processed_stripe_events` still has **one** row for that id. Plan stays Pro.

```
curl -i -X POST http://127.0.0.1:8000/webhooks/stripe -H "Stripe-Signature: t=1,v1=deadbeef" -H "Content-Type: application/json" -d "{\"type\":\"checkout.session.completed\"}"
HTTP/1.1 400 Bad Request
{"detail":"invalid stripe signature"}
```

```
stripe events resend evt_1UAXjfDowGOJC2PgSeU4vrsI
# CLI listen:
# --> checkout.session.completed [evt_1UAXjfDowGOJC2PgSeU4vrsI]
# <-- [200] POST http://localhost:8000/webhooks/stripe [evt_1UAXjfDowGOJC2PgSeU4vrsI]
```

```
docker compose exec db psql -U metering -d metering -c "SELECT event_id, event_type FROM processed_stripe_events WHERE event_id = 'evt_1UAXjfDowGOJC2PgSeU4vrsI';"
           event_id           |         event_type
------------------------------+----------------------------
 evt_1UAXjfDowGOJC2PgSeU4vrsI | checkout.session.completed
(1 row)
```

```
curl -s http://127.0.0.1:8000/usage -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111"
{"tenant_id":"11111111-1111-1111-1111-111111111111","period":"2026-08","subscription_status":"active","api_calls":{"used":1000,"limit":10000},"ai_tokens":{"used":2000,"limit":1000000},"cost_micro_usd":100637}
```

Date: 2026-08-31. `construct_event` failed on the fake seal. `IntegrityError` on `flush` of the already-committed id made the replay a no-op.



## Data model, tests & documentation

### tenants, plans, subscriptions, usage_events; tenant isolation

Two tenants. Header `X-Tenant-Id` selects whose rows `GET /usage` sums. A is Pro with this month's events. B is Free with **zero** `usage_events` rows. `GROUP BY tenant_id` does not even list B.

```
python -m app.seed
Seeded. HTTP header is always X-Tenant-Id.
  tenant A: 11111111-1111-1111-1111-111111111111
  tenant B: 44444444-4444-4444-4444-444444444444
```

```
curl -s http://127.0.0.1:8000/usage -H "X-Tenant-Id: 11111111-1111-1111-1111-111111111111"
{"tenant_id":"11111111-1111-1111-1111-111111111111","period":"2026-08","subscription_status":"active","api_calls":{"used":1000,"limit":10000},"ai_tokens":{"used":2000,"limit":1000000},"cost_micro_usd":100637}

curl -s http://127.0.0.1:8000/usage -H "X-Tenant-Id: 44444444-4444-4444-4444-444444444444"
{"tenant_id":"44444444-4444-4444-4444-444444444444","period":"2026-08","subscription_status":"active","api_calls":{"used":0,"limit":1000},"ai_tokens":{"used":0,"limit":100000},"cost_micro_usd":0}
```

```
docker compose exec db psql -U metering -d metering -c "SELECT tenant_id, COUNT(*) FROM usage_events GROUP BY tenant_id;"
              tenant_id               | count
--------------------------------------+-------
 11111111-1111-1111-1111-111111111111 |  1002
(1 row)
```

Date: 2026-08-31. 1002 = 1000 API + 2 token events, all tenant A. B is absent from that grouping. Isolation is the `tenant_id` filter on every usage query, not a second password.

### Background snapshot job vs live SUM

`python -m app.jobs.snapshot` photocopies `get_usage` into `usage_monthly_snapshots`. No `DRIFT` line. A matches live 1000 / 2000 / 100637. B is zeros. `GET /usage` is still the live tape, not this table.

```
python -m app.jobs.snapshot
snapshotted 11111111-1111-1111-1111-111111111111 2026-08
snapshotted 44444444-4444-4444-4444-444444444444 2026-08
```

```
docker compose exec db psql -U metering -d metering -c "SELECT tenant_id, period_yyyy_mm, api_calls_used, tokens_used, cost_micro_usd FROM usage_monthly_snapshots ORDER BY tenant_id;"
              tenant_id               | period_yyyy_mm | api_calls_used | tokens_used | cost_micro_usd
--------------------------------------+----------------+----------------+-------------+----------------
 11111111-1111-1111-1111-111111111111 | 2026-08        |           1000 |        2000 |         100637
 44444444-4444-4444-4444-444444444444 | 2026-08        |              0 |           0 |              0
(2 rows)
```

Date: 2026-08-31.

### README, diagram, setup; required pack files

`README.md` (what it does, mermaid, run/seed, Stripe CLI, honest limits). `capstone.yaml` (run, seed, job, base_url, endpoints, probes). `BUILDLOG.md` and `.env.example` (host port **5435**). Diagram is the mermaid block in the README.

Date: 2026-08-31.
