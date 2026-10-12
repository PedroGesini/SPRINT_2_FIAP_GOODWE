"""Executa a IA analítica e persiste os resultados (ConsumptionAnomaly / ConsumptionProfile)."""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.anomaly_detection import analyze_anomalies
from app.ai.clustering import analyze_profiles
from app.models import (Charger, ChargingSession, ConsumptionAnomaly, ConsumptionProfile, User)
from app.models.core import utcnow
from app.services.audit_service import log_action


def run_and_store(db: Session, condo_id: int, actor: User | None = None) -> dict:
    anomalies = analyze_anomalies(db, condo_id)
    profiles = analyze_profiles(db, condo_id)
    now = utcnow()
    db.execute(delete(ConsumptionAnomaly).where(ConsumptionAnomaly.condominium_id == condo_id))
    db.execute(delete(ConsumptionProfile).where(ConsumptionProfile.condominium_id == condo_id))
    for it in anomalies["items"]:
        db.add(ConsumptionAnomaly(
            condominium_id=condo_id, session_id=it["session_id"], resident_id=it["resident_id"],
            score=it["score"], severity=it["severity"], kind=",".join(it["kinds"]),
            method=anomalies["method"], reasons=it["reasons"], run_at=now))
    for r in profiles["residents"]:
        db.add(ConsumptionProfile(
            condominium_id=condo_id, resident_id=r["resident_id"], label=r["label"],
            monthly_kwh=r["monthly_kwh"], sessions_per_month=r["sessions_per_month"],
            avg_kwh_session=r["avg_kwh_session"], method=profiles["method"], computed_at=now))
    log_action(db, condominium_id=condo_id, actor_id=actor.id if actor else None,
               action="ai.analysis_run", entity="analysis",
               details={"anomalies": len(anomalies["items"]), "profiles": len(profiles["residents"]),
                        "anomaly_method": anomalies["method"], "profile_method": profiles["method"]})
    anomalies["run_at"], profiles["computed_at"] = now, now
    return {"anomalies": anomalies, "profiles": profiles}


def stored_anomalies(db: Session, condo_id: int) -> dict | None:
    rows = db.scalars(select(ConsumptionAnomaly).where(ConsumptionAnomaly.condominium_id == condo_id)).all()
    if not rows:
        return None
    users = {u.id: u for u in db.scalars(select(User).where(User.condominium_id == condo_id))}
    chargers = {c.id: c for c in db.scalars(select(Charger).where(Charger.condominium_id == condo_id))}
    items = []
    for r in rows:
        s = db.get(ChargingSession, r.session_id)
        u = users[r.resident_id]
        items.append({"session_id": r.session_id, "resident_id": r.resident_id, "resident_name": u.name,
                      "unit": f"{u.block or ''}-{u.unit or ''}", "charger": chargers[s.charger_id].code,
                      "started_at": s.started_at, "energy_kwh": float(s.energy_kwh), "score": r.score,
                      "severity": r.severity, "kinds": r.kind.split(","), "reasons": r.reasons})
    items.sort(key=lambda x: (x["severity"] != "alta", x["score"] if x["score"] is not None else 0))
    return {"method": rows[0].method, "run_at": rows[0].run_at, "items": items, "source": "armazenado"}


def stored_profiles(db: Session, condo_id: int) -> dict | None:
    rows = db.scalars(select(ConsumptionProfile).where(ConsumptionProfile.condominium_id == condo_id)).all()
    if not rows:
        return None
    users = {u.id: u for u in db.scalars(select(User).where(User.condominium_id == condo_id))}
    residents = [{"resident_id": r.resident_id, "name": users[r.resident_id].name,
                  "unit": f"{users[r.resident_id].block or ''}-{users[r.resident_id].unit or ''}",
                  "label": r.label, "monthly_kwh": r.monthly_kwh, "sessions_per_month": r.sessions_per_month,
                  "avg_kwh_session": r.avg_kwh_session} for r in rows]
    residents.sort(key=lambda x: -x["monthly_kwh"])
    clusters = []
    for lab in ("Baixo", "Moderado", "Alto"):
        g = [x for x in residents if x["label"] == lab]
        if g:
            clusters.append({"label": lab, "residents": len(g),
                             "avg_monthly_kwh": round(sum(x["monthly_kwh"] for x in g) / len(g), 1),
                             "avg_sessions_per_month": round(sum(x["sessions_per_month"] for x in g) / len(g), 1),
                             "avg_kwh_session": round(sum(x["avg_kwh_session"] for x in g) / len(g), 1)})
    return {"method": rows[0].method, "computed_at": rows[0].computed_at, "residents": residents,
            "clusters": clusters, "source": "armazenado"}
