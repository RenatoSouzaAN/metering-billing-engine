from uuid import UUID

import stripe
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Plan, ProcessedStripeEvent, Subscription, Tenant
from app.services.meter import MeterError


def _require_test_stripe() -> None:
    key = settings.stripe_secret_key
    if not key.startswith("sk_test_"):
        raise MeterError(500, "stripe secret key must be test mode")
    if "REPLACE_ME" in key or "REPLACE_ME" in settings.stripe_price_pro:
        raise MeterError(503, "stripe is not configured")
    stripe.api_key = key


def _as_dict(obj) -> dict:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, dict):
            return result
    raise TypeError(f"cannot convert {type(obj)} to dict")


def _stripe_id(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        raw = value.get("id")
        return str(raw) if raw else None
    return getattr(value, "id", None)


def _plan_by_code(session: Session, code: str) -> Plan:
    return session.query(Plan).filter(Plan.code == code).one()


def _lock_subscription(session: Session, tenant_id: UUID) -> Subscription | None:
    return (
        session.query(Subscription)
        .filter(Subscription.tenant_id == tenant_id)
        .with_for_update()
        .one_or_none()
    )


def _map_status(stripe_status: str) -> str:
    if stripe_status in ("active", "trialing"):
        return "active"
    if stripe_status in ("past_due", "unpaid", "incomplete", "paused"):
        return "past_due"
    return "canceled"


def _tenant_id_from(obj) -> UUID | None:
    meta = obj.get("metadata") or {}
    raw = meta.get("tenant_id") or obj.get("client_reference_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def create_checkout_url(session: Session, tenant_id: UUID) -> str:
    _require_test_stripe()
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise MeterError(404, "tenant not found")
    sub = (
        session.query(Subscription)
        .filter(Subscription.tenant_id == tenant_id)
        .one_or_none()
    )
    if sub is None:
        raise MeterError(404, "tenant has no subscription")
    plan = session.get(Plan, sub.plan_id)
    if plan is not None and plan.code == "pro" and sub.status == "active":
        raise MeterError(409, "tenant already has an active Pro subscription")

    params = {
        "mode": "subscription",
        "line_items": [{"price": settings.stripe_price_pro, "quantity": 1}],
        "success_url": f"{settings.app_base_url.rstrip('/')}/health?checkout=success",
        "cancel_url": f"{settings.app_base_url.rstrip('/')}/health?checkout=cancel",
        "client_reference_id": str(tenant_id),
        "metadata": {"tenant_id": str(tenant_id)},
        "subscription_data": {"metadata": {"tenant_id": str(tenant_id)}},
    }
    if tenant.stripe_customer_id:
        params["customer"] = tenant.stripe_customer_id

    checkout = stripe.checkout.Session.create(**params)
    if not checkout.url:
        raise MeterError(502, "stripe checkout did not return a url")
    return checkout.url


def handle_webhook(session: Session, payload: bytes, signature: str | None) -> dict:
    if not signature:
        raise MeterError(400, "missing Stripe-Signature header")
    if "REPLACE_ME" in settings.stripe_webhook_secret:
        raise MeterError(503, "stripe webhook secret is not configured")
    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            settings.stripe_webhook_secret,
        )
    except stripe.SignatureVerificationError:
        raise MeterError(400, "invalid stripe signature")
    except ValueError:
        raise MeterError(400, "invalid stripe payload")

    session.add(
        ProcessedStripeEvent(event_id=event["id"], event_type=event["type"])
    )
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return {"status": "already processed"}

    _apply_event(session, event)
    session.commit()
    return {"status": "processed"}


def _apply_event(session: Session, event) -> None:
    etype = event["type"]
    obj = _as_dict(event["data"]["object"])
    if etype == "checkout.session.completed":
        _on_checkout_completed(session, obj)
    elif etype in (
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        _on_subscription_change(session, obj, deleted=False)
    elif etype == "customer.subscription.deleted":
        _on_subscription_change(session, obj, deleted=True)


def _find_subscription(session: Session, obj) -> Subscription | None:
    tenant_id = _tenant_id_from(obj)
    if tenant_id is not None:
        return _lock_subscription(session, tenant_id)

    stripe_sub_id = _stripe_id(obj.get("id"))
    if stripe_sub_id:
        found = (
            session.query(Subscription)
            .filter(Subscription.stripe_subscription_id == stripe_sub_id)
            .with_for_update()
            .one_or_none()
        )
        if found is not None:
            return found

    customer_id = _stripe_id(obj.get("customer"))
    if customer_id is None:
        return None
    tenant = (
        session.query(Tenant)
        .filter(Tenant.stripe_customer_id == customer_id)
        .one_or_none()
    )
    if tenant is None:
        return None
    return _lock_subscription(session, tenant.id)


def _price_ids(obj) -> list[str]:
    items_wrapper = obj.get("items")
    if items_wrapper is None:
        return []
    data = (
        items_wrapper.get("data")
        if hasattr(items_wrapper, "get")
        else getattr(items_wrapper, "data", None)
    ) or []
    ids: list[str] = []
    for item in data:
        price = item.get("price") if hasattr(item, "get") else getattr(item, "price", None)
        price_id = _stripe_id(price)
        if price_id:
            ids.append(price_id)
    return ids


def _on_checkout_completed(session: Session, obj) -> None:
    tenant_id = _tenant_id_from(obj)
    if tenant_id is None:
        return
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        return
    customer_id = _stripe_id(obj.get("customer"))
    if customer_id:
        tenant.stripe_customer_id = customer_id
    sub = _lock_subscription(session, tenant_id)
    if sub is None:
        return
    sub.plan_id = _plan_by_code(session, "pro").id
    sub.status = "active"
    subscription_id = _stripe_id(obj.get("subscription"))
    if subscription_id:
        sub.stripe_subscription_id = subscription_id


def _on_subscription_change(session: Session, obj, deleted: bool) -> None:
    sub = _find_subscription(session, obj)
    if sub is None:
        return
    stripe_sub_id = _stripe_id(obj.get("id"))
    if stripe_sub_id:
        sub.stripe_subscription_id = stripe_sub_id
    if deleted:
        sub.status = "canceled"
        sub.plan_id = _plan_by_code(session, "free").id
        return
    sub.status = _map_status(str(obj.get("status") or "canceled"))
    if settings.stripe_price_pro in _price_ids(obj) and sub.status == "active":
        sub.plan_id = _plan_by_code(session, "pro").id
    elif sub.status == "canceled":
        sub.plan_id = _plan_by_code(session, "free").id
