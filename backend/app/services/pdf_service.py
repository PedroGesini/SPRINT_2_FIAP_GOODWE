"""PDF da fatura (reportlab). Documento de DEMONSTRAÇÃO: não possui valor fiscal."""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.validators import mask_cpf
from app.models import Invoice, User
from app.services.billing_service import money, paid_amount

STATUS_PT = {"draft": "Rascunho", "issued": "Emitida", "pending": "Pendente", "paid": "Paga",
             "overdue": "Vencida", "cancelled": "Cancelada"}
KIND_PT = {"energy": "Energia", "fixed_fee": "Taxa fixa", "shared_cost": "Rateio", "adjustment": "Ajuste"}


def _brl(v) -> str:
    return "R$ " + f"{money(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_invoice_pdf(invoice: Invoice, resident: User, condominium_name: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm,
                            title=f"Fatura {invoice.id} - EV ChargeOps")
    base = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=base["Title"], textColor=colors.HexColor("#0b2545"), alignment=0)
    small = ParagraphStyle("small", parent=base["Normal"], fontSize=8, textColor=colors.grey)
    body = base["Normal"]
    el = [Paragraph("EV ChargeOps", h1),
          Paragraph(f"Fatura de recarga de veículo elétrico - {condominium_name}", body), Spacer(1, 12)]

    info = [["Morador", resident.name], ["Unidade", f"{resident.block or '-'} / {resident.unit or '-'}"],
            ["CPF", mask_cpf(resident.cpf) or "-"],
            ["Período de referência", f"{invoice.period_start:%d/%m/%Y} a {invoice.period_end:%d/%m/%Y}"],
            ["Emissão", f"{invoice.issued_at:%d/%m/%Y}"], ["Vencimento", f"{invoice.due_date:%d/%m/%Y}"],
            ["Situação", STATUS_PT.get(invoice.status.value, invoice.status.value)],
            ["Versão", str(invoice.version)]]
    t = Table(info, colWidths=[5 * cm, 12 * cm])
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey)]))
    el += [t, Spacer(1, 14), Paragraph("Detalhamento do cálculo", base["Heading3"])]

    rows = [["Tipo", "Descrição", "kWh", "R$/kWh", "Valor"]]
    for i in invoice.items:
        rows.append([KIND_PT.get(i.kind.value, i.kind.value), Paragraph(i.description, small),
                     f"{i.quantity:.3f}" if i.quantity is not None else "",
                     f"{i.unit_price:.4f}" if i.unit_price is not None else "", _brl(i.amount)])
    rows.append(["", "Total", f"{invoice.total_kwh:.3f}", "", _brl(invoice.total_amount)])
    items = Table(rows, colWidths=[2.2 * cm, 8 * cm, 2 * cm, 2 * cm, 2.8 * cm], repeatRows=1)
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b2545")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8), ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f2f6fa")])]))
    el += [items, Spacer(1, 10)]

    paid = paid_amount(invoice)
    el.append(Paragraph(f"Pago (simulado): {_brl(paid)} &nbsp;|&nbsp; Saldo em aberto: "
                        f"{_brl(money(invoice.total_amount) - paid)}", body))
    el += [Spacer(1, 8), Paragraph(
        f"Critério: {invoice.allocation_criterion.replace('_', ' ')}. Custo de energia = consumo individual "
        f"em kWh x tarifa aplicada (R$ {invoice.tariff_price_per_kwh:.4f}/kWh, congelada no momento da recarga). "
        "Taxas adicionais, quando existirem, aparecem como itens separados.", small)]
    if invoice.cancel_reason:
        el.append(Paragraph(f"Cancelada. Justificativa: {invoice.cancel_reason}", small))
    el += [Spacer(1, 18), Paragraph("DOCUMENTO DE DEMONSTRAÇÃO - projeto acadêmico (Enterprise Challenge "
                                    "GoodWe + FIAP). Dados, pagamentos e notificações são simulados e não "
                                    "representam operações reais.", small)]
    doc.build(el)
    return buf.getvalue()
