import uuid

from app.db import SessionLocal
from app.models import Plan, Subscription, Tenant


TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PLAN_FREE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
PLAN_PRO_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")

def seed() -> None:
    with SessionLocal() as session:
        if session.get(Plan, PLAN_FREE_ID) is None:
            session.add(
                Plan(
                    id=PLAN_FREE_ID,
                    code="free",
                    api_call_limit=1_000,
                    token_limit=100_000,
                )
            )
        if session.get(Plan, PLAN_PRO_ID) is None:
            session.add(
                Plan(
                    id=PLAN_PRO_ID,
                    code="pro",
                    api_call_limit=10_000,
                    token_limit=1_000_000,
                )
            )
        if session.get(Tenant, TENANT_ID) is None:
            session.add(Tenant(id=TENANT_ID, name="Demo Tenant"))

        existing_sub = (
            session.query(Subscription)
            .filter(Subscription.tenant_id == TENANT_ID)
            .one_or_none()
        )
        if existing_sub is None:
            session.add(
                Subscription(
                    tenant_id=TENANT_ID,
                    plan_id=PLAN_FREE_ID,
                    status="active",
                )
            )
        session.commit()
        print(f"Seeded. Demo X-Tenant-Id: {TENANT_ID}")

if __name__ == "__main__":
    seed()