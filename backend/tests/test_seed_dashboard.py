from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import rate_limit
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (Charger, ChargerStatus, ChargingSession, Invoice, InvoiceStatus, SessionStatus,
                        User, UserStatus)
from app.seed import RESIDENT_PASSWORD, SYNDIC_EMAIL, SYNDIC_PASSWORD, run_seed
from app.services import dashboard_service as ds


@pytest.fixture(scope="module")
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        result = run_seed(db)

    def _get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    rate_limit.reset()
    with TestClient(app) as client:
        yield {"client": client, "factory": factory, "result": result}
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def db(env):
    with env["factory"]() as s:
        yield s


def _login(client, email, password):
    r = client.post("/api/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def syndic_h(env):
    return _login(env["client"], SYNDIC_EMAIL, SYNDIC_PASSWORD)


@pytest.fixture(scope="module")
def ana_h(env):
    return _login(env["client"], "ana.souza@example.com", RESIDENT_PASSWORD)


@pytest.fixture(scope="module")
def bruno_h(env):
    return _login(env["client"], "bruno.lima@example.com", RESIDENT_PASSWORD)


# ------------------------------------------------------------------------- seed
def test_seed_cria_volume_esperado(db):
    done = db.scalar(select(func.count(ChargingSession.id)).where(ChargingSession.status == SessionStatus.COMPLETED))
    assert done >= 100
    assert db.scalar(select(func.count(User.id)).where(User.status == UserStatus.ACTIVE, User.role == "resident")) == 15
    assert db.scalar(select(func.count(User.id)).where(User.status == UserStatus.PENDING)) == 2
    assert db.scalar(select(func.count(Charger.id))) == 6


def test_seed_e_idempotente(env, db):
    before = db.scalar(select(func.count(ChargingSession.id)))
    with env["factory"]() as s:
        assert run_seed(s)["created"] is False
    assert db.scalar(select(func.count(ChargingSession.id))) == before


def test_status_dos_carregadores_coerentes_com_sessoes(db):
    active = defaultdict(int)
    for s in db.scalars(select(ChargingSession).where(ChargingSession.status == SessionStatus.IN_PROGRESS)):
        active[s.charger_id] += 1
    for c in db.scalars(select(Charger)):
        if c.status == ChargerStatus.IN_USE:
            assert active[c.id] == 1
        else:
            assert active[c.id] == 0
    assert any(c.status == ChargerStatus.MAINTENANCE for c in db.scalars(select(Charger)))


def test_sem_sobreposicao_no_mesmo_carregador(db):
    by_charger = defaultdict(list)
    for s in db.scalars(select(ChargingSession).where(ChargingSession.status == SessionStatus.COMPLETED)):
        by_charger[s.charger_id].append((s.started_at, s.ended_at))
    for spans in by_charger.values():
        spans.sort()
        for (_, e1), (s2, _) in zip(spans, spans[1:]):
            assert s2 >= e1


def test_faturas_variadas_e_consistentes(db):
    invoices = list(db.scalars(select(Invoice)))
    statuses = {i.status for i in invoices}
    assert InvoiceStatus.PAID in statuses and InvoiceStatus.OVERDUE in statuses
    assert statuses & {InvoiceStatus.PENDING, InvoiceStatus.ISSUED}
    for inv in invoices:
        assert inv.total_amount == sum((i.amount for i in inv.items), Decimal("0"))
        energy_kwh = sum((i.quantity for i in inv.items if i.quantity is not None), Decimal("0"))
        assert inv.total_kwh == energy_kwh


# --------------------------------------------------------------- dashboard do síndico
def test_resumo_do_sindico_bate_com_o_banco(env, db, syndic_h):
    r = env["client"].get("/api/dashboard/syndic/summary", headers=syndic_h).json()
    t = ds.local_today()
    lo, hi = ds.bounds(*ds.month_span(t.year, t.month))
    rows = list(db.scalars(select(ChargingSession).where(
        ChargingSession.status == SessionStatus.COMPLETED, ChargingSession.started_at >= lo,
        ChargingSession.started_at < hi)))
    assert r["consumption"]["kwh"] == pytest.approx(float(sum(s.energy_kwh for s in rows)), abs=0.01)
    assert r["consumption"]["sessions"] == len(rows)
    assert r["residents"] == {"total": 15, "pending_approval": 2}
    assert r["chargers"] == {"total": 6, "available": 3, "in_use": 2, "maintenance": 1, "unavailable": 0}
    open_inv = [i for i in db.scalars(select(Invoice)) if i.status in ds.OPEN_STATUSES]
    assert r["invoices"]["open_count"] == len(open_inv)
    assert r["invoices"]["open_amount"] == pytest.approx(
        float(sum(ds._invoice_balance(i) for i in open_inv)), abs=0.01)
    assert r["invoices"]["overdue_count"] > 0 and r["data_source"] == "simulado"


def test_resumo_aceita_mes_e_valida_formato(env, syndic_h):
    c = env["client"]
    ok = c.get("/api/dashboard/syndic/summary?month=2026-08", headers=syndic_h)
    assert ok.status_code == 200 and ok.json()["period"]["month"] == "2026-08"
    assert c.get("/api/dashboard/syndic/summary?month=agosto", headers=syndic_h).status_code == 422


def test_graficos_consistentes_entre_si(env, syndic_h):
    c = env["client"]
    ch = c.get("/api/dashboard/syndic/charts", headers=syndic_h).json()
    total_series = sum(p["kwh"] for p in ch["consumption_series"])
    assert len(ch["consumption_series"]) == 30
    assert sum(h["kwh"] for h in ch["hourly_usage"]) == pytest.approx(total_series, abs=0.05)
    assert len(ch["hourly_usage"]) == 24
    assert sum(x["kwh"] for x in ch["by_charger"]) == pytest.approx(total_series, abs=0.05)
    assert sum(x["share_pct"] for x in ch["by_charger"]) == pytest.approx(100, abs=0.5)
    assert {s["status"] for s in ch["invoice_status"]} == {"paid", "pending", "overdue", "cancelled"}
    assert len(ch["monthly_energy_vs_billed"]) == 6


def test_filtros_dos_graficos(env, db, syndic_h):
    c = env["client"]
    charger = db.scalars(select(Charger).where(Charger.code == "CH-03")).one()
    r = c.get(f"/api/dashboard/syndic/charts?charger_id={charger.id}&granularity=month", headers=syndic_h).json()
    assert [x["code"] for x in r["by_charger"]] == ["CH-03"] and len(r["consumption_series"]) == 6
    ana = db.scalars(select(User).where(User.email == "ana.souza@example.com")).one()
    r2 = c.get(f"/api/dashboard/syndic/charts?resident_id={ana.id}", headers=syndic_h).json()
    assert [x["name"] for x in r2["by_resident"]] == ["Ana Souza"]
    r3 = c.get("/api/dashboard/syndic/charts?unit=202", headers=syndic_h).json()
    assert {x["unit"] for x in r3["by_resident"]} <= {"A-202", "B-202", "C-202", "D-202"}
    bad = c.get("/api/dashboard/syndic/charts?date_from=2026-09-10&date_to=2026-09-01", headers=syndic_h)
    assert bad.status_code == 422


def test_alertas_cobrem_os_registros_atipicos_controlados(env, syndic_h):
    data = env["client"].get("/api/dashboard/syndic/alerts", headers=syndic_h).json()
    types = {a["type"] for a in data["alerts"]}
    assert {"charger_down", "overdue_invoices", "atypical_consumption", "possible_duplicate"} <= types
    atyp = [a for a in data["alerts"] if a["type"] == "atypical_consumption"]
    assert any("Carla Mendes" in a["message"] for a in atyp)
    dup = [a for a in data["alerts"] if a["type"] == "possible_duplicate"]
    assert any("Elaine Costa" in a["message"] for a in dup)
    text = " ".join(a["message"].lower() for a in data["alerts"])
    assert "fraude" not in text  # linguagem neutra


# ---------------------------------------------------------------- dashboard do morador
def test_painel_do_morador_so_mostra_dados_proprios(env, db, ana_h):
    c = env["client"]
    ana = db.scalars(select(User).where(User.email == "ana.souza@example.com")).one()
    s = c.get("/api/dashboard/resident/summary", headers=ana_h).json()
    t = ds.local_today()
    lo, hi = ds.bounds(*ds.month_span(t.year, t.month))
    mine = list(db.scalars(select(ChargingSession).where(
        ChargingSession.resident_id == ana.id, ChargingSession.status == SessionStatus.COMPLETED,
        ChargingSession.started_at >= lo, ChargingSession.started_at < hi)))
    assert s["month"]["kwh"] == pytest.approx(float(sum(x.energy_kwh for x in mine)), abs=0.01)
    assert s["month"]["sessions"] == len(mine)
    total = db.scalar(select(func.count(ChargingSession.id)).where(
        ChargingSession.resident_id == ana.id, ChargingSession.status == SessionStatus.COMPLETED))
    assert s["total_sessions"] == total
    charts = c.get("/api/dashboard/resident/charts", headers=ana_h)
    assert charts.status_code == 200
    body = charts.text
    for other in ("Bruno Lima", "Carla Mendes", "Elaine Costa", "Henrique Dias"):
        assert other not in body  # a média do condomínio é agregada, sem dados pessoais
    assert all("condo_avg_kwh" in m for m in charts.json()["monthly"])
    assert len(charts.json()["hourly_usage"]) == 24


def test_paineis_respeitam_perfil(env, syndic_h, ana_h):
    c = env["client"]
    assert c.get("/api/dashboard/syndic/summary", headers=ana_h).status_code == 403
    assert c.get("/api/dashboard/syndic/charts", headers=ana_h).status_code == 403
    assert c.get("/api/dashboard/syndic/alerts", headers=ana_h).status_code == 403
    assert c.get("/api/dashboard/resident/summary", headers=syndic_h).status_code == 403
    assert c.get("/api/dashboard/syndic/summary").status_code == 401


# ------------------------------------------------------------------------------- PDF
def test_pdf_da_fatura_com_controle_de_acesso(env, db, syndic_h, ana_h, bruno_h):
    c = env["client"]
    ana = db.scalars(select(User).where(User.email == "ana.souza@example.com")).one()
    inv = db.scalars(select(Invoice).where(Invoice.resident_id == ana.id)).first()
    own = c.get(f"/api/invoices/{inv.id}/pdf", headers=ana_h)
    assert own.status_code == 200 and own.content.startswith(b"%PDF")
    assert c.get(f"/api/invoices/{inv.id}/pdf", headers=syndic_h).status_code == 200
    assert c.get(f"/api/invoices/{inv.id}/pdf", headers=bruno_h).status_code == 404
    assert c.get(f"/api/invoices/{inv.id}/pdf").status_code == 401


def test_comparacao_do_mes_corrente_usa_mesmo_periodo_do_mes_anterior(env, db, syndic_h):
    r = env["client"].get("/api/dashboard/syndic/summary", headers=syndic_h).json()["consumption"]
    t = ds.local_today()
    first, last = ds.comparable_prev_span(t.year, t.month)
    assert last.day == t.day  # mesmo dia do mês, não o mês anterior inteiro
    lo, hi = ds.bounds(first, last)
    rows = list(db.scalars(select(ChargingSession).where(
        ChargingSession.status == SessionStatus.COMPLETED, ChargingSession.started_at >= lo,
        ChargingSession.started_at < hi)))
    assert r["previous_kwh"] == pytest.approx(float(sum(s.energy_kwh for s in rows)), abs=0.01)
    assert r["comparison_basis"] == "mesmo período do mês anterior"
    assert abs(r["kwh_change_pct"]) < 60  # antes da correção aparecia ~ -61% (mês parcial x mês cheio)


def test_alertas_de_duplicidade_nao_sao_ruido(env, syndic_h):
    alerts = env["client"].get("/api/dashboard/syndic/alerts", headers=syndic_h).json()["alerts"]
    dups = [a for a in alerts if a["type"] == "possible_duplicate"]
    assert len(dups) == 1 and "Elaine Costa" in dups[0]["message"]
