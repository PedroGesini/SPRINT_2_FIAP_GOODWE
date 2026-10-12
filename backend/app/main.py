import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import User
from app.services.realtime import publish, router as realtime_router
from app.services.ocpp_gateway import router as ocpp_ws_router
from app.api.routes import ocpp
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import ai, auth, chargers, dashboard, invoices, residents, sessions
from app.core.config import get_settings
from app.services.billing_service import BillingError
from app.services.charging_service import ChargingError
from app.services.resident_service import ResidentError

settings = get_settings()
log = logging.getLogger("chargeops")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.environment == "development":
        # Atalho de desenvolvimento; em produção o esquema vem do Alembic.
        from app.db.base import Base
        from app.db.session import engine
        import app.models  # noqa: F401
        Base.metadata.create_all(engine)
    yield


app = FastAPI(title=settings.app_name, version="0.4.0", lifespan=lifespan,
              description="API do EV ChargeOps (projeto acadêmico). Dados, pagamentos e "
                          "notificações da demonstração são SIMULADOS.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list,
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(BillingError)
@app.exception_handler(ChargingError)
@app.exception_handler(ResidentError)
async def business_rule_handler(_: Request, exc: Exception):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unexpected_handler(_: Request, exc: Exception):
    log.exception("Erro não tratado")
    return JSONResponse(status_code=500, content={"detail": "Erro interno. Tente novamente."})


for r in (auth.router, residents.router, chargers.router, sessions.router, invoices.router, dashboard.router, ai.router, ocpp.router, realtime_router):
    app.include_router(r, prefix="/api")


app.include_router(ocpp_ws_router)

@app.middleware('http')
async def broadcast_mutations(request: Request, call_next):
    response = await call_next(request)
    if request.method in ('POST','PUT','PATCH','DELETE') and response.status_code < 400 and request.url.path.startswith('/api/'):
        auth = request.headers.get('authorization','')
        if auth.lower().startswith('bearer '):
            payload = decode_access_token(auth[7:])
            if payload and str(payload.get('sub','')).isdigit():
                with SessionLocal() as db:
                    user = db.get(User,int(payload['sub']))
                    if user: await publish(user.condominium_id)
    return response

@app.get("/api/health", tags=["Sistema"])
def health():
    return {"status": "ok", "mode": "demonstração (dados simulados)"}
