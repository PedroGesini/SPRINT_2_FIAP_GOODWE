"""Perfis de consumo por morador com K-Means (baixo / moderado / alto).

Os grupos nascem dos dados (não de limites fixos): os clusters são ordenados pelo consumo mensal médio
do centróide e só então recebem o nome. Silhouette é calculado de verdade; nada é inventado.
Com poucos moradores (< 6) usa-se divisão por tercis, informada na resposta.
"""
from datetime import timedelta

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.services import dashboard_service as ds

LABELS = ["Baixo", "Moderado", "Alto"]
MIN_RESIDENTS_KMEANS = 6


def analyze_profiles(db: Session, condo_id: int, window_days: int = 90) -> dict:
    today = ds.local_today()
    sessions = ds.completed_sessions(db, condo_id, today - timedelta(days=window_days), today)
    users = {u.id: u for u in db.scalars(select(User).where(User.condominium_id == condo_id))}
    months = window_days / 30
    agg: dict[int, list[float]] = {}
    for s in sessions:
        agg.setdefault(s.resident_id, []).append(float(s.energy_kwh))
    rids = sorted(agg)
    out = {"window_days": window_days, "n_residents": len(rids), "residents": [], "clusters": [],
           "silhouette": None, "notes": []}
    if len(rids) < 3:
        out.update(method="nenhum", notes=[
            f"Dados insuficientes: {len(rids)} morador(es) com recargas no período (mínimo de 3)."])
        return out

    feats = np.array([[sum(agg[r]) / months, len(agg[r]) / months, sum(agg[r]) / len(agg[r])] for r in rids])
    monthly = feats[:, 0]
    distinct = len({tuple(np.round(f, 3)) for f in feats})
    if len(rids) >= MIN_RESIDENTS_KMEANS and distinct >= 3:
        out["method"] = "kmeans"
        km = KMeans(n_clusters=3, n_init=10, random_state=42).fit(StandardScaler().fit_transform(feats))
        raw = km.labels_
        order = sorted(range(3), key=lambda c: feats[raw == c, 0].mean())
        label_of = {c: LABELS[rank] for rank, c in enumerate(order)}
        labels = [label_of[c] for c in raw]
        if len(set(raw)) > 1:
            out["silhouette"] = round(float(silhouette_score(StandardScaler().fit_transform(feats), raw)), 3)
        out["notes"].append(f"K-Means (k=3) sobre consumo mensal, recargas por mês e kWh médio por recarga "
                            f"dos últimos {window_days} dias.")
    else:
        out["method"] = "tercis"
        lo, hi = np.quantile(monthly, [1 / 3, 2 / 3])
        labels = ["Baixo" if m <= lo else "Moderado" if m <= hi else "Alto" for m in monthly]
        out["notes"].append(f"Poucos moradores ({len(rids)}): usada divisão por tercis do consumo mensal, "
                            "em vez do K-Means (mínimo de 6 moradores).")

    for r, f, lab in zip(rids, feats, labels):
        u = users[r]
        out["residents"].append({"resident_id": r, "name": u.name, "unit": f"{u.block or ''}-{u.unit or ''}",
                                 "label": lab, "monthly_kwh": round(float(f[0]), 1),
                                 "sessions_per_month": round(float(f[1]), 1),
                                 "avg_kwh_session": round(float(f[2]), 1)})
    for lab in LABELS:
        grp = [x for x in out["residents"] if x["label"] == lab]
        if grp:
            out["clusters"].append({
                "label": lab, "residents": len(grp),
                "avg_monthly_kwh": round(sum(x["monthly_kwh"] for x in grp) / len(grp), 1),
                "avg_sessions_per_month": round(sum(x["sessions_per_month"] for x in grp) / len(grp), 1),
                "avg_kwh_session": round(sum(x["avg_kwh_session"] for x in grp) / len(grp), 1)})
    out["residents"].sort(key=lambda x: -x["monthly_kwh"])
    return out
