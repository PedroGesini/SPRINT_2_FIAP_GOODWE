"""Indicadores, séries e alertas dos dashboards. Todo o cálculo é feito aqui (backend).

Convenções: sessões contam apenas se ENCERRADAS; datas/horas dos gráficos usam o fuso de exibição
(`display_timezone`); valores devolvidos como número (kWh com 3 casas, R$ com 2) para os gráficos.
"""
import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (Charger, ChargerStatus, ChargingSession, Invoice, InvoiceStatus, Role,
                        SessionStatus, Tariff, User, UserStatus)
from app.services.billing_service import money, paid_amount

OPEN_STATUSES = (InvoiceStatus.ISSUED, InvoiceStatus.PENDING, InvoiceStatus.OVERDUE)
MONTHS_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().display_timezone)


def kwh_f(v) -> float:
    return round(float(v or 0), 3)


def brl_f(v) -> float:
    return round(float(v or 0), 2)


def local(dt: datetime) -> datetime:
    return dt.astimezone(tz())


def local_today() -> date:
    return datetime.now(timezone.utc).astimezone(tz()).date()


def bounds(d_from: date, d_to: date) -> tuple[datetime, datetime]:
    """[início, fim] em datas locais -> intervalo UTC [lo, hi)."""
    lo = datetime.combine(d_from, time.min, tzinfo=tz()).astimezone(timezone.utc)
    hi = datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=tz()).astimezone(timezone.utc)
    return lo, hi


def month_span(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


def comparable_prev_span(year: int, month: int) -> tuple[date, date]:
    """Mês anterior; se o mês escolhido ainda está em curso, apenas até o mesmo dia do mês."""
    py, pm = shift_month(year, month, -1)
    first, last = month_span(py, pm)
    today = local_today()
    if (year, month) == (today.year, today.month):
        last = min(last, date(py, pm, min(today.day, last.day)))
    return first, last


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def month_label(year: int, month: int) -> str:
    return f"{MONTHS_PT[month - 1]}/{str(year)[2:]}"


def parse_month(value: str | None) -> tuple[int, int]:
    if not value:
        t = local_today()
        return t.year, t.month
    y, m = value.split("-")
    return int(y), int(m)


def completed_sessions(db: Session, condo_id: int, d_from: date, d_to: date, *,
                       resident_id: int | None = None, charger_id: int | None = None,
                       unit: str | None = None) -> list[ChargingSession]:
    lo, hi = bounds(d_from, d_to)
    stmt = select(ChargingSession).where(
        ChargingSession.condominium_id == condo_id, ChargingSession.status == SessionStatus.COMPLETED,
        ChargingSession.started_at >= lo, ChargingSession.started_at < hi)
    if resident_id:
        stmt = stmt.where(ChargingSession.resident_id == resident_id)
    if charger_id:
        stmt = stmt.where(ChargingSession.charger_id == charger_id)
    if unit:
        stmt = stmt.join(User, User.id == ChargingSession.resident_id).where(User.unit == unit)
    return list(db.scalars(stmt.order_by(ChargingSession.started_at)))


def _totals(sessions) -> tuple[Decimal, Decimal]:
    return (sum((Decimal(s.energy_kwh) for s in sessions), Decimal("0")),
            sum((Decimal(s.energy_cost) for s in sessions), Decimal("0")))


def _pct(cur: float, prev: float) -> float | None:
    return None if not prev else round((cur - prev) / prev * 100, 1)


def hourly_usage(sessions) -> list[dict]:
    buckets = [{"hour": h, "label": f"{h:02d}h", "sessions": 0, "kwh": 0.0} for h in range(24)]
    for s in sessions:
        b = buckets[local(s.started_at).hour]
        b["sessions"] += 1
        b["kwh"] += float(s.energy_kwh)
    for b in buckets:
        b["kwh"] = kwh_f(b["kwh"])
    return buckets


def _invoice_balance(inv: Invoice) -> Decimal:
    return money(Decimal(inv.total_amount) - paid_amount(inv))


# =========================================================================== SÍNDICO
def syndic_summary(db: Session, condo_id: int, year: int, month: int) -> dict:
    d_from, d_to = month_span(year, month)
    sessions = completed_sessions(db, condo_id, d_from, d_to)
    prev = completed_sessions(db, condo_id, *comparable_prev_span(year, month))
    kwh, cost = _totals(sessions)
    pkwh, pcost = _totals(prev)

    users = db.scalars(select(User).where(User.condominium_id == condo_id, User.role == Role.RESIDENT)).all()
    active = [u for u in users if u.status == UserStatus.ACTIVE]
    chargers = db.scalars(select(Charger).where(Charger.condominium_id == condo_id)).all()
    counts = {s.value: 0 for s in ChargerStatus}
    # Carregadores OCPP desconectados nunca aparecem como disponíveis.
    from app.models import OCPPDevice
    from app.services.ocpp_gateway import connections
    assigned = {d.charger_id: d.id for d in db.scalars(select(OCPPDevice).where(
        OCPPDevice.charger_id.in_([c.id for c in chargers]))) } if chargers else {}
    for c in chargers:
        shown_status = 'unavailable' if c.id in assigned and assigned[c.id] not in connections else c.status.value
        counts[shown_status] += 1

    invoices = db.scalars(select(Invoice).where(Invoice.condominium_id == condo_id,
                                                Invoice.status != InvoiceStatus.CANCELLED)).all()
    issued_month = [i for i in invoices if d_from <= i.issued_at <= d_to]
    open_inv = [i for i in invoices if i.status in OPEN_STATUSES]
    overdue = [i for i in open_inv if i.status == InvoiceStatus.OVERDUE]
    return {
        "period": {"month": f"{year}-{month:02d}", "label": month_label(year, month),
                   "from": d_from, "to": d_to},
        "residents": {"total": len(active), "pending_approval": sum(u.status == UserStatus.PENDING for u in users)},
        "chargers": {"total": len(chargers), "available": counts["available"], "in_use": counts["in_use"],
                     "maintenance": counts["maintenance"], "unavailable": counts["unavailable"]},
        "consumption": {"kwh": kwh_f(kwh), "cost": brl_f(cost), "sessions": len(sessions),
                        "avg_kwh_per_resident": kwh_f(kwh / len(active)) if active else 0.0,
                        "kwh_change_pct": _pct(float(kwh), float(pkwh)),
                        "cost_change_pct": _pct(float(cost), float(pcost)),
                        "previous_kwh": kwh_f(pkwh), "previous_cost": brl_f(pcost),
                        "comparison_basis": "mesmo período do mês anterior"},
        "invoices": {"issued_in_month": len(issued_month),
                     "issued_amount": brl_f(sum((Decimal(i.total_amount) for i in issued_month), Decimal("0"))),
                     "open_count": len(open_inv),
                     "open_amount": brl_f(sum((_invoice_balance(i) for i in open_inv), Decimal("0"))),
                     "overdue_count": len(overdue),
                     "overdue_amount": brl_f(sum((_invoice_balance(i) for i in overdue), Decimal("0")))},
        "data_source": "simulado",
    }


def _series(sessions, granularity: str, d_from: date, d_to: date) -> list[dict]:
    def key(d: date) -> date:
        if granularity == "week":
            return d - timedelta(days=d.weekday())
        if granularity == "month":
            return d.replace(day=1)
        return d

    keys, cur = [], key(d_from)
    while cur <= d_to:
        keys.append(cur)
        if granularity == "week":
            cur += timedelta(days=7)
        elif granularity == "month":
            cur = (cur + timedelta(days=32)).replace(day=1)
        else:
            cur += timedelta(days=1)
    acc = {k: {"kwh": Decimal("0"), "cost": Decimal("0"), "sessions": 0} for k in keys}
    for s in sessions:
        k = key(local(s.started_at).date())
        if k in acc:
            acc[k]["kwh"] += Decimal(s.energy_kwh)
            acc[k]["cost"] += Decimal(s.energy_cost)
            acc[k]["sessions"] += 1
    fmt = {"day": lambda d: d.strftime("%d/%m"), "week": lambda d: f"sem {d.strftime('%d/%m')}",
           "month": lambda d: month_label(d.year, d.month)}[granularity]
    return [{"label": fmt(k), "start": k, "kwh": kwh_f(v["kwh"]), "cost": brl_f(v["cost"]),
             "sessions": v["sessions"]} for k, v in acc.items()]


def default_range(granularity: str) -> tuple[date, date]:
    today = local_today()
    if granularity == "month":
        y, m = shift_month(today.year, today.month, -5)
        return date(y, m, 1), today
    return today - timedelta(days=83 if granularity == "week" else 29), today


def syndic_charts(db: Session, condo_id: int, *, d_from: date | None, d_to: date | None,
                  granularity: str = "day", resident_id: int | None = None,
                  charger_id: int | None = None, unit: str | None = None, top: int = 10) -> dict:
    dflt_from, dflt_to = default_range(granularity)
    d_from, d_to = d_from or dflt_from, d_to or dflt_to
    sessions = completed_sessions(db, condo_id, d_from, d_to, resident_id=resident_id,
                                  charger_id=charger_id, unit=unit)
    total_kwh, _ = _totals(sessions)

    # consumo x custo faturado por mês (últimos 6 meses)
    t = local_today()
    months = [shift_month(t.year, t.month, -i) for i in range(5, -1, -1)]
    inv_by_month = defaultdict(Decimal)
    for inv in db.scalars(select(Invoice).where(Invoice.condominium_id == condo_id,
                                                Invoice.status != InvoiceStatus.CANCELLED)):
        inv_by_month[(inv.period_start.year, inv.period_start.month)] += Decimal(inv.total_amount)
    monthly = []
    for y, m in months:
        ms = completed_sessions(db, condo_id, *month_span(y, m), resident_id=resident_id,
                                charger_id=charger_id, unit=unit)
        k, c = _totals(ms)
        monthly.append({"label": month_label(y, m), "month": f"{y}-{m:02d}", "kwh": kwh_f(k),
                        "energy_cost": brl_f(c), "billed": brl_f(inv_by_month.get((y, m), 0))})

    users = {u.id: u for u in db.scalars(select(User).where(User.condominium_id == condo_id))}
    chargers = {c.id: c for c in db.scalars(select(Charger).where(Charger.condominium_id == condo_id))}
    per_res = defaultdict(lambda: {"kwh": Decimal("0"), "cost": Decimal("0"), "sessions": 0})
    per_chg = defaultdict(lambda: {"kwh": Decimal("0"), "sessions": 0})
    for s in sessions:
        r = per_res[s.resident_id]
        r["kwh"] += Decimal(s.energy_kwh); r["cost"] += Decimal(s.energy_cost); r["sessions"] += 1
        c = per_chg[s.charger_id]
        c["kwh"] += Decimal(s.energy_kwh); c["sessions"] += 1
    by_resident = sorted(
        ({"resident_id": rid, "name": users[rid].name, "unit": f"{users[rid].block or ''}-{users[rid].unit or ''}",
          "kwh": kwh_f(v["kwh"]), "cost": brl_f(v["cost"]), "sessions": v["sessions"]}
         for rid, v in per_res.items()), key=lambda x: -x["kwh"])[:top]
    by_charger = sorted(
        ({"charger_id": cid, "code": chargers[cid].code, "name": chargers[cid].name,
          "kwh": kwh_f(v["kwh"]), "sessions": v["sessions"],
          "share_pct": round(float(v["kwh"] / total_kwh * 100), 1) if total_kwh else 0.0}
         for cid, v in per_chg.items()), key=lambda x: -x["kwh"])

    status_acc = {"paid": [0, Decimal("0")], "pending": [0, Decimal("0")],
                  "overdue": [0, Decimal("0")], "cancelled": [0, Decimal("0")]}
    for inv in db.scalars(select(Invoice).where(Invoice.condominium_id == condo_id)):
        bucket = {InvoiceStatus.PAID: "paid", InvoiceStatus.OVERDUE: "overdue",
                  InvoiceStatus.CANCELLED: "cancelled"}.get(inv.status, "pending")
        status_acc[bucket][0] += 1
        status_acc[bucket][1] += Decimal(inv.total_amount)
    labels = {"paid": "Pagas", "pending": "Pendentes", "overdue": "Vencidas", "cancelled": "Canceladas"}
    return {
        "range": {"from": d_from, "to": d_to, "granularity": granularity},
        "consumption_series": _series(sessions, granularity, d_from, d_to),
        "monthly_energy_vs_billed": monthly,
        "by_resident": by_resident,
        "by_charger": by_charger,
        "invoice_status": [{"status": k, "label": labels[k], "count": v[0], "amount": brl_f(v[1])}
                           for k, v in status_acc.items()],
        "hourly_usage": hourly_usage(sessions),
        "data_source": "simulado",
    }


def syndic_alerts(db: Session, condo_id: int) -> list[dict]:
    """Regras estatísticas simples. Linguagem neutra: 'consumo atípico', 'merece análise'."""
    alerts: list[dict] = []
    today = local_today()
    users = {u.id: u for u in db.scalars(select(User).where(User.condominium_id == condo_id))}
    label = lambda uid: f"{users[uid].name} (unid. {users[uid].block or ''}-{users[uid].unit or ''})"

    for c in db.scalars(select(Charger).where(Charger.condominium_id == condo_id,
                                              Charger.status.in_((ChargerStatus.MAINTENANCE,
                                                                  ChargerStatus.UNAVAILABLE)))):
        alerts.append({"type": "charger_down", "severity": "warning",
                       "title": f"{c.code} fora de operação",
                       "message": f"{c.name} está em {'manutenção' if c.status == ChargerStatus.MAINTENANCE else 'indisponível'}.",
                       "entity": {"charger_id": c.id}})

    history = completed_sessions(db, condo_id, today - timedelta(days=180), today)
    values = sorted(float(s.energy_kwh) for s in history)
    if len(values) >= 20:
        q1, q3 = statistics.quantiles(values, n=4)[0], statistics.quantiles(values, n=4)[2]
        limit = q3 + 1.5 * (q3 - q1)
        for s in history:
            if local(s.started_at).date() >= today - timedelta(days=30) and float(s.energy_kwh) > limit:
                alerts.append({"type": "atypical_consumption", "severity": "warning",
                               "title": "Consumo atípico em uma sessão",
                               "message": f"Sessão #{s.id} de {label(s.resident_id)}: {float(s.energy_kwh):.1f} kWh "
                                          f"(referência do condomínio: até {limit:.1f} kWh). Merece análise.",
                               "entity": {"session_id": s.id, "resident_id": s.resident_id}})

    recent = [s for s in history if local(s.started_at).date() >= today - timedelta(days=90)]
    by_res = defaultdict(list)
    for s in recent:
        by_res[s.resident_id].append(s)
    for rid, ss in by_res.items():
        ss.sort(key=lambda s: s.started_at)
        for a, b in zip(ss, ss[1:]):
            if b.started_at < a.ended_at:
                alerts.append({"type": "possible_duplicate", "severity": "info",
                               "title": "Possível sessão duplicada",
                               "message": f"{label(rid)} tem as sessões #{a.id} e #{b.id} sobrepostas no tempo. Merece análise.",
                               "entity": {"session_ids": [a.id, b.id], "resident_id": rid}})

    cur = defaultdict(Decimal); prv = defaultdict(Decimal)
    for s in history:
        d = local(s.started_at).date()
        if d >= today - timedelta(days=30):
            cur[s.resident_id] += Decimal(s.energy_kwh)
        elif d >= today - timedelta(days=60):
            prv[s.resident_id] += Decimal(s.energy_kwh)
    for rid, v in cur.items():
        base = prv.get(rid, Decimal("0"))
        if base > 0 and v - base >= 15 and (v - base) / base >= Decimal("0.6"):
            alerts.append({"type": "consumption_increase", "severity": "info",
                           "title": "Aumento significativo de consumo",
                           "message": f"{label(rid)}: {float(v):.1f} kWh nos últimos 30 dias contra "
                                      f"{float(base):.1f} kWh nos 30 dias anteriores ({float((v - base) / base * 100):.0f}%).",
                           "entity": {"resident_id": rid}})

    last30 = [s for s in history if local(s.started_at).date() >= today - timedelta(days=30)]
    if len(last30) >= 20:
        hours = hourly_usage(last30)
        top = max(hours, key=lambda h: h["sessions"])
        share = top["sessions"] / len(last30) * 100
        if share >= 12:
            alerts.append({"type": "peak_hour", "severity": "info", "title": "Pico de utilização",
                           "message": f"O horário das {top['label']} concentra {share:.0f}% das recargas dos últimos 30 dias.",
                           "entity": {"hour": top["hour"]}})

    overdue = [i for i in db.scalars(select(Invoice).where(Invoice.condominium_id == condo_id,
                                                           Invoice.status == InvoiceStatus.OVERDUE))]
    if overdue:
        total = sum((_invoice_balance(i) for i in overdue), Decimal("0"))
        alerts.append({"type": "overdue_invoices", "severity": "critical",
                       "title": f"{len(overdue)} fatura(s) vencida(s)",
                       "message": f"Saldo vencido em aberto: R$ {total}.", "entity": {}})
    order = {"critical": 0, "warning": 1, "info": 2}
    return sorted(alerts, key=lambda a: order[a["severity"]])


# =========================================================================== MORADOR
def _sess_view(s: ChargingSession, chargers: dict) -> dict:
    return {"id": s.id, "charger": chargers[s.charger_id].code, "started_at": s.started_at,
            "ended_at": s.ended_at, "duration_minutes": s.duration_minutes,
            "kwh": kwh_f(s.energy_kwh), "cost": brl_f(s.energy_cost)}


def resident_summary(db: Session, user: User) -> dict:
    t = local_today()
    d_from, d_to = month_span(t.year, t.month)
    cur = completed_sessions(db, user.condominium_id, d_from, d_to, resident_id=user.id)
    prev = completed_sessions(db, user.condominium_id, *comparable_prev_span(t.year, t.month),
                              resident_id=user.id)
    kwh, cost = _totals(cur)
    pkwh, _ = _totals(prev)
    unbilled = [s for s in cur if s.invoice_id is None]
    tariff = db.scalars(select(Tariff).where(Tariff.condominium_id == user.condominium_id,
                                             Tariff.active.is_(True)).order_by(Tariff.valid_from.desc())).first()
    estimated = sum((Decimal(s.energy_cost) for s in unbilled), Decimal("0"))
    if unbilled and tariff:
        estimated += Decimal(tariff.fixed_fee)
    all_done = list(db.scalars(select(ChargingSession).where(
        ChargingSession.resident_id == user.id, ChargingSession.status == SessionStatus.COMPLETED)
        .order_by(ChargingSession.started_at.desc())))
    chargers = {c.id: c for c in db.scalars(select(Charger).where(Charger.condominium_id == user.condominium_id))}
    invoice = db.scalars(select(Invoice).where(Invoice.resident_id == user.id,
                                               Invoice.status != InvoiceStatus.CANCELLED)
                         .order_by(Invoice.issued_at.desc(), Invoice.id.desc())).first()
    active = db.scalars(select(ChargingSession).where(
        ChargingSession.resident_id == user.id, ChargingSession.status == SessionStatus.IN_PROGRESS)).first()
    return {
        "month": {"label": month_label(t.year, t.month), "kwh": kwh_f(kwh), "cost": brl_f(cost),
                  "sessions": len(cur), "previous_kwh": kwh_f(pkwh),
                  "kwh_change_pct": _pct(float(kwh), float(pkwh)),
                  "comparison_basis": "mesmo período do mês anterior"},
        "estimated_invoice": {"amount": brl_f(estimated), "note": "Estimativa com base nas recargas "
                              "ainda não faturadas do mês (inclui taxa fixa, se houver)."},
        "last_session": _sess_view(all_done[0], chargers) if all_done else None,
        "active_session": {"id": active.id, "charger": chargers[active.charger_id].code,
                           "started_at": active.started_at} if active else None,
        "total_sessions": len(all_done),
        "current_invoice": None if not invoice else {
            "id": invoice.id, "period": month_label(invoice.period_start.year, invoice.period_start.month),
            "status": invoice.status.value, "total": brl_f(invoice.total_amount),
            "due_date": invoice.due_date, "balance": brl_f(_invoice_balance(invoice))},
        "data_source": "simulado",
    }


def resident_charts(db: Session, user: User, months: int = 6) -> dict:
    t = local_today()
    span = [shift_month(t.year, t.month, -i) for i in range(months - 1, -1, -1)]
    active_count = db.scalar(select(__import__("sqlalchemy").func.count(User.id)).where(
        User.condominium_id == user.condominium_id, User.role == Role.RESIDENT,
        User.status == UserStatus.ACTIVE)) or 1
    monthly = []
    for y, m in span:
        mine = completed_sessions(db, user.condominium_id, *month_span(y, m), resident_id=user.id)
        allc = completed_sessions(db, user.condominium_id, *month_span(y, m))
        k, c = _totals(mine)
        ak, _ = _totals(allc)
        monthly.append({"label": month_label(y, m), "kwh": kwh_f(k), "cost": brl_f(c), "sessions": len(mine),
                        "condo_avg_kwh": kwh_f(ak / active_count)})  # média agregada, sem dados pessoais
    mine_all = completed_sessions(db, user.condominium_id, span_first(span), t, resident_id=user.id)
    chargers = {c.id: c for c in db.scalars(select(Charger).where(Charger.condominium_id == user.condominium_id))}
    recent = sorted(mine_all, key=lambda s: s.started_at, reverse=True)[:15]
    return {"monthly": monthly, "hourly_usage": hourly_usage(mine_all),
            "recent_sessions": [_sess_view(s, chargers) for s in recent], "data_source": "simulado"}


def span_first(span: list[tuple[int, int]]) -> date:
    return date(span[0][0], span[0][1], 1)
