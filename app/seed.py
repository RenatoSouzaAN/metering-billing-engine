import uuid

from app.config import settings
from app.db import SessionLocal
from app.models import Plan, Subscription, Tenant


TENANT_A_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TENANT_B_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
PLAN_FREE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
PLAN_PRO_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")

def _ensure_tenant(session, tenant_id: uuid.UUID, name: str) -> None:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        session.add(Tenant(id=tenant_id, name=name))
        return
    tenant.name = name


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
        _ensure_tenant(session, TENANT_A_ID, "Demo Tenant A")
        _ensure_tenant(session, TENANT_B_ID, "Demo Tenant B")

        existing_sub_a = (
            session.query(Subscription)
            .filter(Subscription.tenant_id == TENANT_A_ID)
            .one_or_none()
        )
        if existing_sub_a is None:
            session.add(
                Subscription(
                    tenant_id=TENANT_A_ID,
                    plan_id=PLAN_FREE_ID,
                    status="active",
                )
            )
        existing_sub_b = (
            session.query(Subscription)
            .filter(Subscription.tenant_id == TENANT_B_ID)
            .one_or_none()
        )
        if existing_sub_b is None:
            session.add(
                Subscription(
                    tenant_id=TENANT_B_ID,
                    plan_id=PLAN_FREE_ID,
                    status="active",
                )
            )
        pro = session.get(Plan, PLAN_PRO_ID)
        if pro is not None and "REPLACE_ME" not in settings.stripe_price_pro:
            pro.stripe_price_id = settings.stripe_price_pro
        session.commit()
        print("Seeded. HTTP header is always X-Tenant-Id.")
        print(f"  tenant A: {TENANT_A_ID}")
        print(f"  tenant B: {TENANT_B_ID}")

if __name__ == "__main__":
    seed()