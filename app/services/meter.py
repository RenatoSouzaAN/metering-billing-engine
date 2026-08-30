from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Plan, Subscription, UsageEvent

class MeterError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail

def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
 
def record_generate(
    session: Session,
    tenant_id: UUID,
    idempotency_key: str,
    meter: str,
) -> UsageEvent:
    sub = (
        session.query(Subscription)
        .filter(Subscription.tenant_id == tenant_id)
        .with_for_update()
        .one_or_none()
    )
    if sub is None:
        raise MeterError(404, "tenant has no subscription")
    if sub.status != "active":
        raise MeterError(402, "upgrade or pay: subscription is not active")
    
    plan = session.get(Plan, sub.plan_id)
    if plan is None:
        raise MeterError(500, "subscription points at a missing plan")
        
    used = session.query(
        func.coalesce(func.sum(UsageEvent.quantity), 0)
    ).filter(
        UsageEvent.tenant_id == tenant_id,
        UsageEvent.meter == "api_call",
        UsageEvent.created_at >= _month_start_utc(),
    ).scalar()

    if used + 1 > plan.api_call_limit:
        raise MeterError(429, f"usage quota exceeded: {used} of {plan.api_call_limit} API calls used")

    event = UsageEvent(
        tenant_id=tenant_id,
        meter=meter,
        quantity=1,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        reasoning_tokens=0,
        idempotency_key=idempotency_key,
    )
    try:
        session.add(event)
        session.commit()
    except IntegrityError:
        session.rollback()
        event = (
            session.query(UsageEvent)
            .filter_by(tenant_id=tenant_id, idempotency_key=idempotency_key)
            .one()
        )
    return event