"""Previsão simples do consumo do condomínio (kWh) com base no histórico mensal.

- 6+ meses completos: o retroteste (previsão de 1 passo à frente) escolhe entre tendência linear
  (LinearRegression) e média dos últimos 3 meses, ficando com o método de menor erro (MAE).
- 3 a 5 meses: média dos últimos 3 meses (sem tendência).
- 1 a 2 meses: média disponível, com aviso de limitação.
É uma estimativa indicativa, não uma garantia. O erro de retroteste (MAE) só é informado se puder ser calculado.
"""
import statistics
from decimal import Decimal

import numpy as np
from sklearn.linear_model import LinearRegression
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tariff
from app.services import dashboard_service as ds
from app.services.billing_service import money as bs_money


def _linear(y: list[float], target: int) -> float:
    x = np.arange(len(y)).reshape(-1, 1)
    return float(LinearRegression().fit(x, y).predict([[target]])[0])


def monthly_history(db: Session, condo_id: int, months: int = 12) -> list[dict]:
    t = ds.local_today()
    rows = []
    for i in range(months, 0, -1):  # apenas meses COMPLETOS (exclui o mês corrente)
        y, m = ds.shift_month(t.year, t.month, -i)
        k, c = ds._totals(ds.completed_sessions(db, condo_id, *ds.month_span(y, m)))
        rows.append({"month": f"{y}-{m:02d}", "label": ds.month_label(y, m), "kwh": ds.kwh_f(k)})
    while rows and rows[0]["kwh"] == 0:
        rows.pop(0)
    return rows


def forecast_consumption(db: Session, condo_id: int) -> dict:
    hist = monthly_history(db, condo_id)
    y = [h["kwh"] for h in hist]
    n = len(y)
    t = ds.local_today()
    ny, nm = ds.shift_month(t.year, t.month, 1)
    tariff = db.scalars(select(Tariff).where(Tariff.condominium_id == condo_id, Tariff.active.is_(True))
                        .order_by(Tariff.valid_from.desc())).first()
    price = Decimal(tariff.price_per_kwh) if tariff else Decimal("0")
    out = {"history": hist, "next_month": f"{ny}-{nm:02d}", "next_month_label": ds.month_label(ny, nm),
           "notes": ["Estimativa indicativa baseada no histórico simulado; não é uma garantia."]}
    if n == 0:
        out.update(method="nenhum", forecast_kwh=None, range_kwh=None, forecast_cost=None,
                   notes=["Dados insuficientes: não há meses completos com recargas."])
        return out

    if n >= 6:
        mae_lin = [abs(_linear(y[:i], i) - y[i]) for i in range(3, n)]
        mae_avg = [abs(statistics.mean(y[i - 3:i]) - y[i]) for i in range(3, n)]
        out["backtest"] = {"folds": len(mae_lin), "mae_linear_kwh": round(statistics.mean(mae_lin), 1),
                           "mae_media_3m_kwh": round(statistics.mean(mae_avg), 1)}
        if statistics.mean(mae_lin) < statistics.mean(mae_avg):
            method, pred = "regressão_linear", _linear(y, n + 1)
            fitted = LinearRegression().fit(np.arange(n).reshape(-1, 1), y).predict(np.arange(n).reshape(-1, 1))
            spread = float(np.std(np.array(y) - fitted))
        else:
            method, pred = "média_3_meses", statistics.mean(y[-3:])
            spread = statistics.pstdev(y[-3:])
        out["notes"].append("Método escolhido pelo menor erro absoluto médio (MAE) no retroteste com o histórico disponível.")
    elif n >= 3:
        method, pred = "média_3_meses", statistics.mean(y[-3:])
        spread = statistics.pstdev(y[-3:])
        out["notes"].append(f"Apenas {n} meses completos: usada a média dos últimos 3 meses, sem tendência.")
    else:
        method, pred = "média_simples", statistics.mean(y)
        spread = statistics.pstdev(y) if n > 1 else 0.0
        out["notes"].append(f"Histórico muito curto ({n} mês/meses): previsão pouco confiável.")
    pred = round(max(pred, 0.0), 1)

    mtd = ds._totals(ds.completed_sessions(db, condo_id, t.replace(day=1), t))[0]
    days_in_month = ds.month_span(t.year, t.month)[1].day
    out.update(method=method, forecast_kwh=pred,
               range_kwh=[round(max(pred - spread, 0), 1), round(pred + spread, 1)],
               forecast_cost=float(bs_money(Decimal(str(pred)) * price)), tariff_per_kwh=float(price),
               current_month={"label": ds.month_label(t.year, t.month), "kwh_so_far": ds.kwh_f(mtd),
                              "projection_kwh": round(float(mtd) / t.day * days_in_month, 1)})
    return out
