"""Motor de rateio e geração de faturas.

Regra principal: o consumo individual em kWh é a base da cobrança.
    custo_energia = kWh x tarifa_por_kWh
Taxas fixas e custos compartilhados são itens separados e explícitos na fatura.
Valores monetários usam Decimal com arredondamento ROUND_HALF_UP em 2 casas.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (ChargingSession, Invoice, InvoiceItem, InvoiceItemKind,
                        InvoiceStatus, SessionStatus, Tariff, User)
from app.services.audit_service import log_action

CENT = Decimal("0.01")


class BillingError(Exception):
    pass


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def consumption_from_readings(start_kwh: Decimal, end_kwh: Decimal) -> Decimal:
    """Consumo em kWh = leitura final - leitura inicial."""
    start, end = Decimal(start_kwh), Decimal(end_kwh)
    if end < start:
        raise BillingError("A leitura final não pode ser menor que a inicial.")
    return (end - start).quantize(Decimal("0.001"))


def energy_cost(kwh: Decimal, price_per_kwh: Decimal) -> Decimal:
    if Decimal(kwh) < 0 or Decimal(price_per_kwh) < 0:
        raise BillingError("Consumo e tarifa não podem ser negativos.")
    return money(Decimal(kwh) * Decimal(price_per_kwh))


def allocate_shared_cost(total: Decimal, resident_kwh: Decimal, condo_kwh: Decimal) -> Decimal:
    """Rateio de custo compartilhado proporcional ao consumo (critério explícito)."""
    if Decimal(condo_kwh) <= 0 or Decimal(total) <= 0:
        return money(0)
    return money(Decimal(total) * Decimal(resident_kwh) / Decimal(condo_kwh))


@dataclass
class LineItem:
    kind: InvoiceItemKind
    description: str
    amount: Decimal
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    session_id: int | None = None


@dataclass
class Breakdown:
    total_kwh: Decimal
    items: list[LineItem] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return money(sum((i.amount for i in self.items), Decimal("0")))


def build_breakdown(sessions: list[ChargingSession], *, fixed_fee: Decimal = Decimal("0"),
                    shared_total: Decimal = Decimal("0"), condo_kwh: Decimal = Decimal("0"),
                    adjustments: list[tuple[str, Decimal]] | None = None) -> Breakdown:
    """Calcula os itens da fatura a partir das sessões já encerradas."""
    total_kwh = sum((Decimal(s.energy_kwh) for s in sessions), Decimal("0"))
    bd = Breakdown(total_kwh=total_kwh.quantize(Decimal("0.001")))
    for s in sessions:
        bd.items.append(LineItem(
            InvoiceItemKind.ENERGY, f"Recarga #{s.id} - {s.started_at:%d/%m/%Y %H:%M}",
            money(s.energy_cost), Decimal(s.energy_kwh), Decimal(s.tariff_price_per_kwh), s.id))
    if Decimal(fixed_fee) > 0:
        bd.items.append(LineItem(InvoiceItemKind.FIXED_FEE, "Taxa fixa de infraestrutura",
                                 money(fixed_fee)))
    share = allocate_shared_cost(shared_total, bd.total_kwh, condo_kwh)
    if share > 0:
        bd.items.append(LineItem(InvoiceItemKind.SHARED_COST,
                                 "Custo compartilhado (rateio proporcional ao consumo em kWh)", share))
    for reason, amount in adjustments or []:
        if not reason.strip():
            raise BillingError("Todo ajuste administrativo exige justificativa.")
        bd.items.append(LineItem(InvoiceItemKind.ADJUSTMENT, f"Ajuste: {reason}", money(amount)))
    return bd


def _period_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    lo = datetime.combine(start, time.min, tzinfo=timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return lo, hi


def generate_invoice(db: Session, *, resident: User, period_start: date, period_end: date,
                     actor: User, due_in_days: int = 10, shared_total: Decimal = Decimal("0"),
                     adjustments: list[tuple[str, Decimal]] | None = None,
                     correction: bool = False) -> Invoice:
    """Gera a fatura de um morador para o período, sem duplicar sessões nem faturas."""
    if period_end < period_start:
        raise BillingError("Período inválido.")
    existing = db.scalars(select(Invoice).where(
        Invoice.resident_id == resident.id, Invoice.period_start == period_start,
        Invoice.period_end == period_end,
        Invoice.status != InvoiceStatus.CANCELLED)).first()
    if existing and not correction:
        raise BillingError("Já existe fatura ativa para este morador e período.")
    version = 1 + (db.scalars(select(Invoice.version).where(
        Invoice.resident_id == resident.id, Invoice.period_start == period_start,
        Invoice.period_end == period_end).order_by(Invoice.version.desc())).first() or 0)

    lo, hi = _period_bounds(period_start, period_end)
    base = (ChargingSession.condominium_id == resident.condominium_id,
            ChargingSession.status == SessionStatus.COMPLETED,
            ChargingSession.started_at >= lo, ChargingSession.started_at < hi)
    sessions = list(db.scalars(select(ChargingSession).where(
        *base, ChargingSession.resident_id == resident.id,
        ChargingSession.invoice_id.is_(None))))
    if not sessions and not adjustments:
        raise BillingError("Não há sessões encerradas a faturar neste período.")
    condo_kwh = sum((Decimal(s.energy_kwh) for s in db.scalars(select(ChargingSession).where(*base))),
                    Decimal("0"))

    tariff = db.scalars(select(Tariff).where(
        Tariff.condominium_id == resident.condominium_id, Tariff.active.is_(True))
        .order_by(Tariff.valid_from.desc())).first()
    fixed = Decimal(tariff.fixed_fee) if tariff else Decimal("0")
    price = Decimal(sessions[0].tariff_price_per_kwh) if sessions else (
        Decimal(tariff.price_per_kwh) if tariff else Decimal("0"))

    bd = build_breakdown(sessions, fixed_fee=fixed, shared_total=shared_total,
                         condo_kwh=condo_kwh, adjustments=adjustments)
    today = datetime.now(timezone.utc).date()
    invoice = Invoice(
        condominium_id=resident.condominium_id, resident_id=resident.id,
        period_start=period_start, period_end=period_end, version=version,
        total_kwh=bd.total_kwh, tariff_price_per_kwh=price,
        allocation_criterion="consumo_kwh", total_amount=bd.total,
        status=InvoiceStatus.ISSUED, issued_at=today, due_date=today + timedelta(days=due_in_days))
    invoice.items = [InvoiceItem(kind=i.kind, description=i.description, quantity=i.quantity,
                                 unit_price=i.unit_price, amount=i.amount, session_id=i.session_id)
                     for i in bd.items]
    db.add(invoice)
    db.flush()
    for s in sessions:
        s.invoice_id = invoice.id  # impede contabilizar a mesma sessão duas vezes
    log_action(db, condominium_id=resident.condominium_id, actor_id=actor.id,
               action="invoice.issued", entity="invoice", entity_id=invoice.id,
               details={"resident_id": resident.id, "total": str(bd.total), "version": version})
    return invoice


# ---------------------------------------------------------------- ciclo de vida da fatura
# Transições: ISSUED/PENDING -> PAID | OVERDUE | CANCELLED ; OVERDUE -> PAID | CANCELLED.
# PAID e CANCELLED são estados finais. (DRAFT ainda não é produzido: a geração já emite.)
_OPEN = (InvoiceStatus.ISSUED, InvoiceStatus.PENDING, InvoiceStatus.OVERDUE)


def paid_amount(invoice: Invoice) -> Decimal:
    return money(sum((Decimal(p.amount) for p in invoice.payments), Decimal("0")))


def refresh_overdue(db: Session, condominium_id: int) -> int:
    today = datetime.now(timezone.utc).date()
    rows = db.scalars(select(Invoice).where(
        Invoice.condominium_id == condominium_id,
        Invoice.status.in_((InvoiceStatus.ISSUED, InvoiceStatus.PENDING)),
        Invoice.due_date < today)).all()
    for inv in rows:
        inv.status = InvoiceStatus.OVERDUE
    return len(rows)


def register_payment(db: Session, invoice: Invoice, amount: Decimal, actor: User):
    """Pagamento SIMULADO: apenas registra no banco, nunca movimenta dinheiro real."""
    from app.models import Payment
    if invoice.status not in _OPEN:
        raise BillingError(f"Fatura {invoice.status.value} não aceita pagamentos.")
    amount = money(amount)
    balance = money(Decimal(invoice.total_amount) - paid_amount(invoice))
    if amount <= 0 or amount > balance:
        raise BillingError(f"Valor inválido. Saldo em aberto: R$ {balance}.")
    payment = Payment(invoice_id=invoice.id, amount=amount, simulated=True, registered_by=actor.id)
    db.add(payment)
    db.flush()
    db.refresh(invoice)
    if paid_amount(invoice) >= money(invoice.total_amount):
        invoice.status = InvoiceStatus.PAID
    log_action(db, condominium_id=invoice.condominium_id, actor_id=actor.id,
               action="payment.registered", entity="invoice", entity_id=invoice.id,
               details={"amount": str(amount), "simulated": True})
    return payment


def cancel_invoice(db: Session, invoice: Invoice, reason: str, actor: User) -> Invoice:
    if invoice.status not in _OPEN:
        raise BillingError(f"Fatura {invoice.status.value} não pode ser cancelada.")
    if len(reason.strip()) < 5:
        raise BillingError("Informe uma justificativa (mínimo de 5 caracteres).")
    invoice.status = InvoiceStatus.CANCELLED
    invoice.cancel_reason = reason.strip()
    for s in db.scalars(select(ChargingSession).where(ChargingSession.invoice_id == invoice.id)):
        s.invoice_id = None  # libera as sessões para uma nova versão da fatura
    log_action(db, condominium_id=invoice.condominium_id, actor_id=actor.id,
               action="invoice.cancelled", entity="invoice", entity_id=invoice.id,
               details={"reason": reason.strip()})
    return invoice
