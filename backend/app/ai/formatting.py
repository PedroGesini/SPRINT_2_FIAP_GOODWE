"""Formatação em pt-BR: moeda e unidades."""


def _num(v: float, decimals: int) -> str:
    return f"{float(v):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_num(v, decimals: int = 1) -> str:
    return _num(v, decimals)


def fmt_brl(v) -> str:
    v = float(v)
    return ("-" if v < 0 else "") + "R$ " + _num(abs(v), 2)


def fmt_kwh(v) -> str:
    return _num(v, 2) + " kWh"


def fmt_pct(v) -> str:
    return "sem base de comparação" if v is None else f"{'+' if v > 0 else ''}{_num(v, 1)}%"


def fmt_date(d) -> str:
    return d.strftime("%d/%m/%Y")


STATUS_PT = {"draft": "rascunho", "issued": "emitida", "pending": "pendente", "paid": "paga",
             "overdue": "vencida", "cancelled": "cancelada", "available": "disponível",
             "in_use": "em uso", "maintenance": "em manutenção", "unavailable": "indisponível"}
