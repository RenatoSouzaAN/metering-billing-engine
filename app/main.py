from uuid import UUID
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import SessionLocal
from app.schemas import GenerateRequest
from app.services.meter import MeterError, record_generate

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
                body.meter,
            )
        except MeterError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)
        return {
            "id": str(event.id),
            "meter": event.meter,
            "quantity": event.quantity,
            "idempotency_key": event.idempotency_key,
        }