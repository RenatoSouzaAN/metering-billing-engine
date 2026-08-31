from uuid import UUID

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Tenant, UsageMonthlySnapshot
from app.services.meter import get_usage


def snapshot_tenant(session: Session, tenant_id: UUID) -> None:
    payload = get_usage(session, tenant_id)
    row = (
        session.query(UsageMonthlySnapshot)
        .filter_by(tenant_id=tenant_id, period_yyyy_mm=payload["period"])
        .one_or_none()
    )
    if row is None:
        session.add(UsageMonthlySnapshot(
            tenant_id=tenant_id,
            period_yyyy_mm=payload["period"],
            api_calls_used=payload["api_calls"]["used"],
            tokens_used=payload["ai_tokens"]["used"],
            cost_micro_usd=payload["cost_micro_usd"],
        ))
    else:
        row.api_calls_used = payload["api_calls"]["used"]
        row.tokens_used = payload["ai_tokens"]["used"]
        row.cost_micro_usd = payload["cost_micro_usd"]

def run() -> None:
    with SessionLocal() as session:
        tenants = session.query(Tenant).all()
        for tenant in tenants:
            for attempt in (1, 2):
                try:
                    snapshot_tenant(session, tenant.id)
                    session.commit()
                    live = get_usage(session, tenant.id)
                    row = (
                        session.query(UsageMonthlySnapshot)
                        .filter_by(
                            tenant_id=tenant.id,
                            period_yyyy_mm=live["period"],
                        )
                        .one()
                    )
                    drifted = (
                        live["api_calls"]["used"] != row.api_calls_used
                        or live["ai_tokens"]["used"] != row.tokens_used
                        or live["cost_micro_usd"] != row.cost_micro_usd
                    )
                    if drifted:
                        print(f"DRIFT {tenant.id}")
                    else:
                        print(f"snapshotted {tenant.id} {live['period']}")
                    break
                except Exception as exc:
                    session.rollback()
                    print(f"attempt {attempt} failed {tenant.id}: {exc}")

if __name__ == "__main__":
    run()