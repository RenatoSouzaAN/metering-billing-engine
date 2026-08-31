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

_Pending — Probe 3._

### Webhooks: verify, dedupe, update plan/status

_Pending — Probe 4._

## Data model, tests & documentation

### tenants, plans, subscriptions, usage_events; tenant isolation

_Pending — schema + a cross-tenant query that returns nothing._

### README, diagram, setup; required pack files

_Pending — Phase 4._
