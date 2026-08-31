from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Plan, Subscription, UsageEvent
from app.schemas import GenerateRequest

class MeterError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail

def _month_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

def _sum_for_meter(session: Session, tenant_id: UUID, meter: str) -> int:
    return session.query(
        func.coalesce(func.sum(UsageEvent.quantity), 0)
    ).filter(
        UsageEvent.tenant_id == tenant_id,
        UsageEvent.meter == meter,
        UsageEvent.created_at >= _month_start_utc(),
    ).scalar()
 
def record_generate(
    session: Session,
    tenant_id: UUID,
    idempotency_key: str,
    body: GenerateRequest,
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
        
    if body.meter == "api_call":
        used = int(_sum_for_meter(session, tenant_id, "api_call"))
        requested = 1
        limit = plan.api_call_limit
        label = "API calls"
    else:
        used = int(_sum_for_meter(session, tenant_id, "ai_tokens"))
        requested = (
            body.input_tokens
            + body.cached_input_tokens
            + body.output_tokens
            + body.reasoning_tokens
        )
        limit = plan.token_limit
        label = "AI tokens"

    if used + requested > limit:
        raise MeterError(429, f"usage quota exceeded: {used} of {limit} {label} used")

    event = UsageEvent(
        tenant_id=tenant_id,
        meter=body.meter,
        quantity=requested,
        input_tokens=body.input_tokens,
        cached_input_tokens=body.cached_input_tokens,
        output_tokens=body.output_tokens,
        reasoning_tokens=body.reasoning_tokens,
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

def get_usage(session: Session, tenant_id: UUID) -> dict:
    sub = (
        session.query(Subscription)
        .filter(Subscription.tenant_id == tenant_id)
        .one_or_none()
    )
    if sub is None:
        raise MeterError(404, "tenant has no subscription")

    plan = session.get(Plan, sub.plan_id)
    if plan is None:
        raise MeterError(500, "subscription points at a missing plan")

    api_used = int(_sum_for_meter(session, tenant_id, "api_call"))
    token_used = int(_sum_for_meter(session, tenant_id, "ai_tokens"))
    events = (
        session.query(UsageEvent)
        .filter(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.created_at >= _month_start_utc(),
        )
        .all()
    )
    cost = sum(event_cost_micro_usd(event) for event in events)
    now = datetime.now(timezone.utc)

    return {
        "tenant_id": tenant_id,
        "period": now.strftime("%Y-%m"),
        "subscription_status": sub.status,
        "api_calls": {"used": api_used, "limit": plan.api_call_limit},
        "ai_tokens": {"used": token_used, "limit": plan.token_limit},
        "cost_micro_usd": cost,
    }

def event_cost_micro_usd(event: UsageEvent) -> int:
    if event.meter == "api_call":
        return event.quantity * settings.api_call_micro_usd
    billed_output = event.output_tokens + event.reasoning_tokens
    return (
        event.input_tokens * settings.input_micro_usd_per_million
        + event.cached_input_tokens * settings.cached_input_micro_usd_per_million
        + billed_output * settings.output_micro_usd_per_million
    ) // 1_000_000