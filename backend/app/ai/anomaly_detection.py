"""Detecção de consumo atípico.

- Com dados suficientes (>= 50 sessões): Isolation Forest (scikit-learn).
- Com poucos dados (8 a 49): método estatístico (IQR), informado na resposta.
- Com menos de 8 sessões: nenhuma análise (mensagem explicativa).
Nenhuma métrica de desempenho é inventada: não há rótulos reais de fraude/erro para avaliar o modelo.
O resultado indica "consumo atípico" / "sessão que merece análise" e nunca acusa um morador.
"""
import math
import statistics
from collections import defaultdict
from datetime import timedelta

import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.formatting import fmt_num
from app.models import Charger, User
from app.services import dashboard_service as ds

MIN_SESSIONS_ML = 50
MIN_SESSIONS_STAT = 8
HIGH_SCORE = -0.10
ASSUMED_ATYPICAL_RATE = 0.02  # hiperparâmetro assumido (não medido): ~2% das sessões como atípicas


def _fences(values: list[float]) -> tuple[float, float, float]:
    q1, q2, q3 = statistics.quantiles(values, n=4)
    return q2, q3, q3 + 1.5 * (q3 - q1)


def analyze_anomalies(db: Session, condo_id: int, window_days: int = 180) -> dict:
    today = ds.local_today()
    sessions = ds.completed_sessions(db, condo_id, today - timedelta(days=window_days), today)
    n = len(sessions)
    users = {u.id: u for u in db.scalars(select(User).where(User.condominium_id == condo_id))}
    chargers = {c.id: c for c in db.scalars(select(Charger).where(Charger.condominium_id == condo_id))}
    base = {"window_days": window_days, "n_sessions": n, "items": [], "notes": []}
    if n < MIN_SESSIONS_STAT:
        base.update(method="nenhum", notes=[
            f"Dados insuficientes: {n} sessão(ões) no período. São necessárias ao menos "
            f"{MIN_SESSIONS_STAT} para a análise estatística e {MIN_SESSIONS_ML} para o modelo de IA."])
        return base

    kwh = [float(s.energy_kwh) for s in sessions]
    dur = [max((s.ended_at - s.started_at).total_seconds() / 3600, 0.05) for s in sessions]
    by_res = defaultdict(list)
    for s, v in zip(sessions, kwh):
        by_res[s.resident_id].append(v)
    stats = {r: (statistics.mean(v), statistics.pstdev(v)) for r, v in by_res.items()}
    starts = defaultdict(list)
    for s in sessions:
        starts[s.resident_id].append(s.started_at)

    def z_res(s, v):
        mean, sd = stats[s.resident_id]
        return 0.0 if len(by_res[s.resident_id]) < 5 or sd == 0 else (v - mean) / sd

    def freq7(s):
        lo = s.started_at - timedelta(days=7)
        return sum(1 for t in starts[s.resident_id] if lo <= t < s.started_at)

    hours = [ds.local(s.started_at).hour for s in sessions]
    z = [z_res(s, v) for s, v in zip(sessions, kwh)]
    f7 = [freq7(s) for s in sessions]
    med_kwh, _, kwh_fence = _fences(kwh)
    med_dur, _, dur_fence = _fences(dur)

    flagged: dict[int, dict] = {}

    def flag(i, kind, severity, score, reasons):
        s = sessions[i]
        item = flagged.setdefault(s.id, {"session": s, "kinds": [], "reasons": [], "score": score,
                                         "severity": severity})
        if kind not in item["kinds"]:
            item["kinds"].append(kind)
        item["reasons"] += [r for r in reasons if r not in item["reasons"]]
        if severity == "alta":
            item["severity"] = "alta"

    def describe(i) -> list[str]:
        r = []
        if kwh[i] > kwh_fence:
            r.append(f"Energia de {fmt_num(kwh[i])} kWh, acima da faixa usual do condomínio "
                     f"(mediana de {fmt_num(med_kwh)} kWh).")
        if z[i] >= 2.5:
            r.append(f"Consumo {fmt_num(z[i])} desvios-padrão acima da média do próprio morador "
                     f"({fmt_num(stats[sessions[i].resident_id][0])} kWh).")
        if dur[i] > dur_fence:
            r.append(f"Duração de {fmt_num(dur[i])} h, acima do usual (mediana de {fmt_num(med_dur)} h).")
        if hours[i] < 5:
            r.append(f"Início de madrugada ({hours[i]:02d}h).")
        if f7[i] >= 5:
            r.append(f"{f7[i]} recargas nos 7 dias anteriores.")
        return r or ["Combinação incomum de energia, duração e horário em relação ao restante do condomínio."]

    if n >= MIN_SESSIONS_ML:
        method = "isolation_forest"
        h_rad = [2 * math.pi * h / 24 for h in hours]
        X = np.array([[kwh[i], dur[i], kwh[i] / dur[i], math.sin(h_rad[i]), math.cos(h_rad[i]),
                       z[i], f7[i]] for i in range(n)])
        model = IsolationForest(n_estimators=200, contamination=ASSUMED_ATYPICAL_RATE, random_state=42).fit(X)
        scores = model.decision_function(X)
        for i in np.where(model.predict(X) == -1)[0]:
            sev = "alta" if scores[i] <= HIGH_SCORE else "média"
            flag(int(i), "modelo", sev, round(float(scores[i]), 4), describe(int(i)))
        base["notes"].append(f"Isolation Forest treinado com {n} sessões dos últimos {window_days} dias "
                             "(sem rótulos reais; o resultado indica sessões que merecem análise, não erros ou fraudes).")
    else:
        method = "estatístico_iqr"
        for i in range(n):
            if kwh[i] > kwh_fence or dur[i] > dur_fence:
                sev = "alta" if kwh[i] > 1.5 * kwh_fence else "média"
                flag(i, "estatístico", sev, None, describe(i))
        base["notes"].append(f"Poucos dados ({n} sessões): foi usado o método estatístico (IQR) em vez do modelo "
                             f"de IA, que exige ao menos {MIN_SESSIONS_ML} sessões.")

    # regra determinística: sessões sobrepostas do mesmo morador (possível duplicidade)
    ordered = defaultdict(list)
    for i, s in enumerate(sessions):
        ordered[s.resident_id].append(i)
    for idxs in ordered.values():
        idxs.sort(key=lambda i: sessions[i].started_at)
        for a, b in zip(idxs, idxs[1:]):
            if sessions[b].started_at < sessions[a].ended_at:
                flag(b, "sobreposição", "média", None,
                     [f"Sobreposta no tempo à sessão #{sessions[a].id} do mesmo morador (possível duplicidade)."])

    items = []
    for sid, it in flagged.items():
        s = it["session"]
        u = users[s.resident_id]
        items.append({
            "session_id": sid, "resident_id": s.resident_id, "resident_name": u.name,
            "unit": f"{u.block or ''}-{u.unit or ''}", "charger": chargers[s.charger_id].code,
            "started_at": s.started_at, "energy_kwh": float(s.energy_kwh), "score": it["score"],
            "severity": it["severity"], "kinds": it["kinds"], "reasons": it["reasons"]})
    items.sort(key=lambda x: (x["severity"] != "alta", x["score"] if x["score"] is not None else 0))
    base.update(method=method, items=items)
    return base
