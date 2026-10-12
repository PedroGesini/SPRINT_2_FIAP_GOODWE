"""Envio de faturas. Sem SMTP configurado, o e-mail é apenas SIMULADO e registrado como tal."""
from sqlalchemy.orm import Session

from app.models import Invoice, InvoiceDelivery, InvoiceStatus, Notification, User
from app.services.audit_service import log_action
from app.services.billing_service import BillingError


class EmailProvider:
    """Interface para futuro envio real (SMTP, SES, etc.)."""

    configured = False

    def send(self, to: str, subject: str, body: str) -> None:  # pragma: no cover
        raise NotImplementedError


def send_invoice(db: Session, invoice: Invoice, actor: User,
                 email_provider: EmailProvider | None = None) -> list[InvoiceDelivery]:
    if invoice.status == InvoiceStatus.CANCELLED:
        raise BillingError("Faturas canceladas não podem ser enviadas.")
    resident = db.get(User, invoice.resident_id)
    db.add(Notification(user_id=resident.id, title="Nova fatura disponível",
                        body=f"Fatura {invoice.period_start:%m/%Y}: R$ {invoice.total_amount} "
                             f"com vencimento em {invoice.due_date:%d/%m/%Y}."))
    deliveries = [InvoiceDelivery(invoice_id=invoice.id, recipient_id=resident.id,
                                  channel="in_app", status="sent")]
    provider = email_provider
    if provider is not None and provider.configured:
        try:
            provider.send(resident.email, "Sua fatura EV ChargeOps", "Acesse o sistema.")
            deliveries.append(InvoiceDelivery(invoice_id=invoice.id, recipient_id=resident.id,
                                              channel="email", status="sent"))
        except Exception:
            deliveries.append(InvoiceDelivery(invoice_id=invoice.id, recipient_id=resident.id,
                                              channel="email", status="error"))
    else:
        deliveries.append(InvoiceDelivery(invoice_id=invoice.id, recipient_id=resident.id,
                                          channel="email_simulated", status="simulated"))
    db.add_all(deliveries)
    log_action(db, condominium_id=invoice.condominium_id, actor_id=actor.id,
               action="invoice.sent", entity="invoice", entity_id=invoice.id,
               details={"channels": [d.channel for d in deliveries]})
    return deliveries
