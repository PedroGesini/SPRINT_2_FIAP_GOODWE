"""Ferramentas EXPLÍCITAS que a assistente pode chamar.

Regras de segurança:
- a autorização é validada aqui, no backend, antes de executar qualquer ferramenta (`run_tool`);
- não existe SQL arbitrário: cada ferramenta é uma função Python com consultas fixas;
- ferramentas de morador usam SEMPRE o usuário autenticado (não aceitam resident_id);
- nenhuma ferramenta altera dados (pagamentos, tarifas etc.); todas são somente leitura.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.anomaly_detection import analyze_anomalies
from app.ai.clustering import analyze_profiles
from app.ai.forecasting import forecast_consumption
from app.models import (Charger, ChargerStatus, ChargingSession, Invoice, InvoiceItemKind,
                        InvoiceStatus, Role, SessionStatus, Tariff, User)
from app.services import billing_service as bs
from app.services import dashboard_service as ds

RESIDENT = frozenset({Role.RESIDENT})
STAFF = frozenset({Role.SYNDIC, Role.PLATFORM_ADMIN})
ANY = RESIDENT | STAFF


class ToolPermissionError(PermissionError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    fn: Callable
    roles: frozenset


def _tariff(db: Session, condo_id: int) -> Tariff | None:
    return db.scalars(select(Tariff).where(Tariff.condominium_id == condo_id, Tariff.active.is_(True))
                      .order_by(Tariff.valid_from.desc())).first()


def _period(period: str) -> tuple[int, int]:
    t = ds.local_today()
    return ds.shift_month(t.year, t.month, -1) if period == "previous" else (t.year, t.month)


# ------------------------------------------------------------------ morador (somente o próprio)
def consultar_consumo_morador(db: Session, user: User, period: str = "current") -> dict:
    y, m = _period(period)
    sessions = ds.completed_sessions(db, user.condominium_id, *ds.month_span(y, m), resident_id=user.id)
    prev_span = ds.comparable_prev_span(y, m) if period != "previous" else ds.month_span(*ds.shift_month(y, m, -1))
    prev = ds.completed_sessions(db, user.condominium_id, *prev_span, resident_id=user.id)
    kwh, cost = ds._totals(sessions)
    pkwh, _ = ds._totals(prev)
    t = _tariff(db, user.condominium_id)
    return {"period_label": ds.month_label(y, m), "kwh": float(kwh), "cost": float(cost),
            "sessions": len(sessions), "avg_kwh_session": float(kwh / len(sessions)) if sessions else 0.0,
            "tariff_per_kwh": float(t.price_per_kwh) if t else None,
            "previous_kwh": float(pkwh), "change_pct": ds._pct(float(kwh), float(pkwh)),
            "comparison_basis": "mesmo período do mês anterior" if period != "previous" else "mês anterior completo"}


def _invoice_view(inv: Invoice) -> dict:
    energy = [i for i in inv.items if i.kind == InvoiceItemKind.ENERGY]
    other = lambda k: sum((Decimal(i.amount) for i in inv.items if i.kind == k), Decimal("0"))
    return {"id": inv.id, "period_label": ds.month_label(inv.period_start.year, inv.period_start.month),
            "status": inv.status.value, "total": float(inv.total_amount), "due_date": inv.due_date,
            "balance": float(bs.money(inv.total_amount) - bs.paid_amount(inv)),
            "total_kwh": float(inv.total_kwh), "tariff_per_kwh": float(inv.tariff_price_per_kwh),
            "energy_total": float(sum((Decimal(i.amount) for i in energy), Decimal("0"))),
            "energy_sessions": len(energy), "fixed_fee": float(other(InvoiceItemKind.FIXED_FEE)),
            "shared_cost": float(other(InvoiceItemKind.SHARED_COST)),
            "adjustments": float(other(InvoiceItemKind.ADJUSTMENT))}


def consultar_faturas_morador(db: Session, user: User) -> dict:
    invs = db.scalars(select(Invoice).where(Invoice.resident_id == user.id,
                                            Invoice.status != InvoiceStatus.CANCELLED)
                      .order_by(Invoice.period_start.desc(), Invoice.id.desc()).limit(6)).all()
    views = [_invoice_view(i) for i in invs]
    factors = None
    if len(views) >= 2:
        cur, prv = views[0], views[1]
        factors = {"total_delta": round(cur["total"] - prv["total"], 2),
                   "kwh_delta": round(cur["total_kwh"] - prv["total_kwh"], 3),
                   "energy_delta": round(cur["energy_total"] - prv["energy_total"], 2),
                   "tariff_changed": abs(cur["tariff_per_kwh"] - prv["tariff_per_kwh"]) > 1e-9,
                   "tariff_current": cur["tariff_per_kwh"], "tariff_previous": prv["tariff_per_kwh"],
                   "fixed_fee_delta": round(cur["fixed_fee"] - prv["fixed_fee"], 2),
                   "other_delta": round((cur["shared_cost"] + cur["adjustments"]) - (prv["shared_cost"] + prv["adjustments"]), 2)}
    return {"latest": views[0] if views else None, "previous": views[1] if len(views) > 1 else None,
            "invoices": views, "factors": factors,
            "estimated_current_month": ds.resident_summary(db, user)["estimated_invoice"]["amount"]}


def consultar_historico_recargas(db: Session, user: User, limit: int = 5) -> dict:
    rows = db.scalars(select(ChargingSession).where(
        ChargingSession.resident_id == user.id, ChargingSession.status == SessionStatus.COMPLETED)
        .order_by(ChargingSession.started_at.desc())).all()
    chargers = {c.id: c for c in db.scalars(select(Charger).where(Charger.condominium_id == user.condominium_id))}
    t = ds.local_today()
    this_month = ds.completed_sessions(db, user.condominium_id, *ds.month_span(t.year, t.month), resident_id=user.id)
    return {"total_sessions": len(rows), "sessions_this_month": len(this_month),
            "recent": [{"id": s.id, "charger": chargers[s.charger_id].code, "started_at": ds.local(s.started_at),
                        "duration_minutes": s.duration_minutes, "kwh": float(s.energy_kwh),
                        "cost": float(s.energy_cost), "tariff_per_kwh": float(s.tariff_price_per_kwh)}
                       for s in rows[:limit]]}


# ---------------------------------------------------------------- qualquer usuário do condomínio
def consultar_carregadores_disponiveis(db: Session, user: User) -> dict:
    rows = db.scalars(select(Charger).where(Charger.condominium_id == user.condominium_id)
                      .order_by(Charger.code)).all()
    view = lambda c: {"code": c.code, "name": c.name, "location": c.location, "power_kw": float(c.power_kw),
                      "status": c.status.value}
    return {"available": [view(c) for c in rows if c.status == ChargerStatus.AVAILABLE],
            "in_use": [view(c) for c in rows if c.status == ChargerStatus.IN_USE],
            "down": [view(c) for c in rows if c.status in (ChargerStatus.MAINTENANCE, ChargerStatus.UNAVAILABLE)],
            "total": len(rows), "data_source": "simulado"}


def consultar_regras_de_cobranca(db: Session, user: User) -> dict:
    t = _tariff(db, user.condominium_id)
    return {"tariff_per_kwh": float(t.price_per_kwh) if t else None,
            "fixed_fee": float(t.fixed_fee) if t else 0.0, "criterion": "consumo individual em kWh"}


# ------------------------------------------------------------------------------------ síndico
def consultar_consumo_condominio(db: Session, user: User, period: str = "current") -> dict:
    return ds.syndic_summary(db, user.condominium_id, *_period(period))


def consultar_ranking_moradores(db: Session, user: User, period: str = "current") -> dict:
    y, m = _period(period)
    first, last = ds.month_span(y, m)
    ch = ds.syndic_charts(db, user.condominium_id, d_from=first, d_to=min(last, ds.local_today()), top=5)
    return {"period_label": ds.month_label(y, m), "ranking": ch["by_resident"]}


def consultar_uso_carregadores(db: Session, user: User) -> dict:
    ch = ds.syndic_charts(db, user.condominium_id, d_from=None, d_to=None)
    return {"window": "últimos 30 dias", "by_charger": ch["by_charger"]}


def consultar_horarios_uso(db: Session, user: User) -> dict:
    ch = ds.syndic_charts(db, user.condominium_id, d_from=None, d_to=None)
    hours = sorted(ch["hourly_usage"], key=lambda h: -h["sessions"])
    total = sum(h["sessions"] for h in hours)
    return {"window": "últimos 30 dias", "total_sessions": total,
            "top_hours": [{**h, "share_pct": round(h["sessions"] / total * 100, 1) if total else 0.0}
                          for h in hours[:3]]}


def consultar_evolucao_custos(db: Session, user: User) -> dict:
    ch = ds.syndic_charts(db, user.condominium_id, d_from=None, d_to=None)
    return {"months": ch["monthly_energy_vs_billed"]}


def consultar_aumentos_consumo(db: Session, user: User) -> dict:
    alerts = [a for a in ds.syndic_alerts(db, user.condominium_id) if a["type"] == "consumption_increase"]
    return {"alerts": alerts}


def consultar_carregadores_indisponiveis(db: Session, user: User) -> dict:
    data = consultar_carregadores_disponiveis(db, user)
    return {"down": data["down"], "total": data["total"]}


def consultar_faturas_pendentes(db: Session, user: User, kind: str = "all") -> dict:
    bs.refresh_overdue(db, user.condominium_id)
    db.flush()
    users = {u.id: u for u in db.scalars(select(User).where(User.condominium_id == user.condominium_id))}
    invs = db.scalars(select(Invoice).where(
        Invoice.condominium_id == user.condominium_id,
        Invoice.status.in_(ds.OPEN_STATUSES)).order_by(Invoice.due_date)).all()
    rows = [{"invoice_id": i.id, "resident": users[i.resident_id].name,
             "unit": f"{users[i.resident_id].block or ''}-{users[i.resident_id].unit or ''}",
             "period_label": ds.month_label(i.period_start.year, i.period_start.month),
             "status": i.status.value, "due_date": i.due_date,
             "balance": float(bs.money(i.total_amount) - bs.paid_amount(i))} for i in invs]
    overdue = [r for r in rows if r["status"] == "overdue"]
    return {"open_count": len(rows), "open_amount": round(sum(r["balance"] for r in rows), 2),
            "overdue_count": len(overdue), "overdue_amount": round(sum(r["balance"] for r in overdue), 2),
            "overdue": overdue[:10], "kind": kind}


def analisar_padroes_consumo(db: Session, user: User) -> dict:
    an = analyze_anomalies(db, user.condominium_id)
    pr = analyze_profiles(db, user.condominium_id)
    return {"anomalies": {k: an[k] for k in ("method", "n_sessions", "notes")} | {"count": len(an["items"]),
                                                                                   "top": an["items"][:5]},
            "profiles": {k: pr[k] for k in ("method", "silhouette", "clusters", "notes")}}


def prever_consumo(db: Session, user: User) -> dict:
    return forecast_consumption(db, user.condominium_id)


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool("consultar_consumo_morador", consultar_consumo_morador, RESIDENT),
    Tool("consultar_faturas_morador", consultar_faturas_morador, RESIDENT),
    Tool("consultar_historico_recargas", consultar_historico_recargas, RESIDENT),
    Tool("consultar_carregadores_disponiveis", consultar_carregadores_disponiveis, ANY),
    Tool("consultar_regras_de_cobranca", consultar_regras_de_cobranca, ANY),
    Tool("consultar_consumo_condominio", consultar_consumo_condominio, STAFF),
    Tool("consultar_ranking_moradores", consultar_ranking_moradores, STAFF),
    Tool("consultar_uso_carregadores", consultar_uso_carregadores, STAFF),
    Tool("consultar_horarios_uso", consultar_horarios_uso, STAFF),
    Tool("consultar_evolucao_custos", consultar_evolucao_custos, STAFF),
    Tool("consultar_aumentos_consumo", consultar_aumentos_consumo, STAFF),
    Tool("consultar_carregadores_indisponiveis", consultar_carregadores_indisponiveis, STAFF),
    Tool("consultar_faturas_pendentes", consultar_faturas_pendentes, STAFF),
    Tool("analisar_padroes_consumo", analisar_padroes_consumo, STAFF),
    Tool("prever_consumo", prever_consumo, STAFF),
)}


def is_allowed(name: str, user: User) -> bool:
    tool = TOOLS.get(name)
    return tool is not None and user.role in tool.roles


def run_tool(name: str, db: Session, user: User, **params) -> dict:
    """Único ponto de execução: valida a permissão ANTES de consultar qualquer dado."""
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolPermissionError(f"Ferramenta desconhecida: {name}")
    if user.role not in tool.roles:
        raise ToolPermissionError(f"Perfil '{user.role.value}' não pode usar {name}.")
    return tool.fn(db, user, **params)
