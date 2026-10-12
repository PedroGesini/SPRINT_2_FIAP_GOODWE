from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import invoice_in_scope, resident_in_scope
from app.core.permissions import get_current_user, is_staff, require_staff
from app.db.session import get_db
from app.models import (Condominium, Invoice, InvoiceDelivery, InvoiceStatus, Role, User,
                        UserStatus)
from app.schemas.common import Page
from app.schemas.invoice import (CancelIn, DeliveryOut, InvoiceGenerateIn, InvoiceOut,
                                 InvoicePeriodIn, PaymentIn, PaymentOut)
from app.services import billing_service as bs
from app.services.notification_service import send_invoice
from app.services.pdf_service import build_invoice_pdf

router = APIRouter(prefix="/invoices", tags=["Faturas"])


def to_out(inv: Invoice) -> InvoiceOut:
    out = InvoiceOut.model_validate(inv)
    out.paid_amount = bs.paid_amount(inv)
    out.balance = bs.money(inv.total_amount) - out.paid_amount
    return out


@router.get("", response_model=Page[InvoiceOut])
def list_invoices(status: InvoiceStatus | None = None, resident_id: int | None = None,
                  page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    bs.refresh_overdue(db, user.condominium_id)
    db.commit()
    stmt = select(Invoice).where(Invoice.condominium_id == user.condominium_id)
    if not is_staff(user):
        stmt = stmt.where(Invoice.resident_id == user.id)
    elif resident_id:
        stmt = stmt.where(Invoice.resident_id == resident_id)
    if status:
        stmt = stmt.where(Invoice.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Invoice.issued_at.desc(), Invoice.id.desc())
                      .offset((page - 1) * size).limit(size)).all()
    return Page(items=[to_out(i) for i in rows], total=total, page=page, size=size)


@router.post("/generate", response_model=InvoiceOut, status_code=201)
def generate(data: InvoiceGenerateIn, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    resident = resident_in_scope(db, staff, data.resident_id)
    inv = bs.generate_invoice(db, resident=resident, period_start=data.period_start,
                              period_end=data.period_end, actor=staff, due_in_days=data.due_in_days,
                              shared_total=data.shared_total, correction=data.correction,
                              adjustments=[(a.reason, a.amount) for a in data.adjustments])
    db.commit()
    return to_out(inv)


@router.post("/generate-period")
def generate_period(data: InvoicePeriodIn, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Gera faturas de todos os moradores ativos; informa quem foi gerado e quem foi ignorado."""
    residents = db.scalars(select(User).where(
        User.condominium_id == staff.condominium_id, User.role == Role.RESIDENT,
        User.status == UserStatus.ACTIVE)).all()
    created, skipped = [], []
    for r in residents:
        try:
            with db.begin_nested():
                inv = bs.generate_invoice(db, resident=r, period_start=data.period_start,
                                          period_end=data.period_end, actor=staff,
                                          due_in_days=data.due_in_days, shared_total=data.shared_total)
            created.append(inv.id)
        except bs.BillingError as exc:
            skipped.append({"resident_id": r.id, "reason": str(exc)})
    db.commit()
    return {"created_invoice_ids": created, "skipped": skipped}


@router.get("/{invoice_id}", response_model=InvoiceOut)
def detail(invoice_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return to_out(invoice_in_scope(db, user, invoice_id))


@router.post("/{invoice_id}/payments", response_model=PaymentOut, status_code=201)
def pay(invoice_id: int, data: PaymentIn, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Pagamento SIMULADO registrado pelo síndico."""
    inv = invoice_in_scope(db, staff, invoice_id)
    payment = bs.register_payment(db, inv, data.amount, staff)
    db.commit()
    return payment


@router.post("/{invoice_id}/cancel", response_model=InvoiceOut)
def cancel(invoice_id: int, data: CancelIn, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    inv = bs.cancel_invoice(db, invoice_in_scope(db, staff, invoice_id), data.reason, staff)
    db.commit()
    return to_out(inv)


@router.post("/{invoice_id}/send", response_model=list[DeliveryOut], status_code=201)
def send(invoice_id: int, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    inv = invoice_in_scope(db, staff, invoice_id)
    deliveries = send_invoice(db, inv, staff)
    db.commit()
    return deliveries


@router.get("/{invoice_id}/deliveries", response_model=list[DeliveryOut])
def deliveries(invoice_id: int, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    inv = invoice_in_scope(db, staff, invoice_id)
    return db.scalars(select(InvoiceDelivery).where(InvoiceDelivery.invoice_id == inv.id)
                      .order_by(InvoiceDelivery.sent_at)).all()


@router.get("/{invoice_id}/pdf")
def download_pdf(invoice_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """PDF da fatura: o síndico baixa qualquer uma do condomínio; o morador, apenas as suas."""
    inv = invoice_in_scope(db, user, invoice_id)
    resident = db.get(User, inv.resident_id)
    condo = db.get(Condominium, inv.condominium_id)
    pdf = build_invoice_pdf(inv, resident, condo.name)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=fatura-{inv.id}.pdf"})
