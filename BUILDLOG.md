# BUILDLOG

Honesty is graded, not perfection. Each entry: where AI helped, where it was wrong, what I changed.

## 2026-08-29 — pre-Phase 1 / Phase 1 design

**Where AI helped**

- Read the capstone brief and turned Section 6 + probes into a scoreboard.
- Flagged the shared "≥1 background job" requirement that the four flavor concerns do not mention.
- Drafted `DESIGN.md` after we locked stack (Python + FastAPI) and repo name (`metering-billing-engine`).

**Where AI was wrong or incomplete**

- First check question: I described idempotency as "the key guarantees no double processing." That names the *intent*, not the *lock*. The lock is `UNIQUE (tenant_id, idempotency_key)` (and a second unique on Stripe `event_id`).
- I used the generic HTTP meaning of 429 (rate limit / abuse). In this product 429 is **quota exhausted** on an active plan; 402 is **plan/payment permission**.

**What I changed / own**

- Stack and repo name.
- 429 vs 402 rule: quota vs permission.
- Boundary: allow when `used + requested <= limit`; reject the next one that would pass the cap.
- Pro quotas: 10,000 API calls / 1,000,000 tokens (10× Free), unless we revise before Phase 2.
- Money as integer micro-USD, not floats.
- `GET /usage` is a live sum; the background job only snapshots and alerts on drift.

## 2026-08-30 — two races (before git init)

**Where AI helped**

- Pushed the distinction between the unique index and `SELECT FOR UPDATE`.

**Where I was wrong**

- I treated both locks as one “identify the request / don’t update the wrong row” check. That is tenant isolation plus generic caution, not the two races. Unique index = same key, same intent, retry must not insert twice. `FOR UPDATE` = different keys, two real requests, last remaining quota unit must not be given to both.

**What I own now**

- Those are two different bugs: double-count a retry vs oversell the cap.
