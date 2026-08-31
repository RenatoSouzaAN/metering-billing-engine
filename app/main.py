from datetime import datetime, timezone, tzinfo
from uuid import UUID
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import SessionLocal
from app.schemas import GenerateRequest
from app.services.meter import MeterError, get_usage, record_generate

app = FastAPI(title="metering-billing-engine")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/ready")
def ready():
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return JSONResponse({"status": "not ready"}, status_code=503)

def seconds_until_next_utc_month() -> int:
    now = datetime.now(timezone.utc)
    if now.month == 12:
        nxt = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return max(0, int((nxt - now).total_seconds()))

@app.post("/generate")
def generate(
    body: GenerateRequest,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    with SessionLocal() as session:
        try:
            event = record_generate(
                session,
                x_tenant_id,
                idempotency_key,
                body,
            )
        except MeterError as exc:
            headers = None
            if exc.status_code == 429:
                headers = {
                    "Retry-After": str(seconds_until_next_utc_month())
                }
            raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers)
        return {
            "id": str(event.id),
            "meter": event.meter,
            "quantity": event.quantity,
            "idempotency_key": event.idempotency_key,
        }

@app.get("/usage")
def usage(x_tenant_id: UUID = Header(..., alias="X-Tenant-ID")):
    with SessionLocal() as session:
        try: 
            payload = get_usage(session, x_tenant_id)
        except MeterError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)
        return payload