# EVIDENCE

One pasted proof per Section 6 box. A box without a paste is not done.

## Metering

### Exactly-once usage event under retries

_Pending — Probe 1._

### Proof that double-counting cannot happen

_Pending — same request twice, one row._

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
