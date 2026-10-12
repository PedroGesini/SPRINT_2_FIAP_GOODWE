import re
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.permissions import get_current_user, is_staff, require_staff
from app.db.session import get_db
from app.models import User
from app.services import billing_service as bs
from app.services import dashboard_service as ds

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _month(value: str | None) -> tuple[int, int]:
    if value is not None and not _MONTH.match(value):
        raise HTTPException(422, "Use o formato AAAA-MM.")
    return ds.parse_month(value)


@router.get("/syndic/summary")
def syndic_summary(month: str | None = None, staff: User = Depends(require_staff),
                   db: Session = Depends(get_db)):
    bs.refresh_overdue(db, staff.condominium_id)
    db.commit()
    return ds.syndic_summary(db, staff.condominium_id, *_month(month))


@router.get("/syndic/charts")
def syndic_charts(date_from: date | None = None, date_to: date | None = None,
                  granularity: str = Query("day", pattern="^(day|week|month)$"),
                  resident_id: int | None = None, charger_id: int | None = None,
                  unit: str | None = None, top: int = Query(10, ge=1, le=50),
                  staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    if date_from and date_to and date_to < date_from:
        raise HTTPException(422, "date_to deve ser maior ou igual a date_from.")
    return ds.syndic_charts(db, staff.condominium_id, d_from=date_from, d_to=date_to,
                            granularity=granularity, resident_id=resident_id,
                            charger_id=charger_id, unit=unit, top=top)


@router.get("/syndic/alerts")
def syndic_alerts(staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    bs.refresh_overdue(db, staff.condominium_id)
    db.commit()
    alerts = ds.syndic_alerts(db, staff.condominium_id)
    return {"count": len(alerts), "alerts": alerts, "data_source": "simulado"}


def _resident_only(user: User = Depends(get_current_user)) -> User:
    if is_staff(user):
        raise HTTPException(403, "Painel disponível apenas para moradores.")
    return user


@router.get("/resident/summary")
def resident_summary(user: User = Depends(_resident_only), db: Session = Depends(get_db)):
    return ds.resident_summary(db, user)


@router.get("/resident/charts")
def resident_charts(months: int = Query(6, ge=2, le=12), user: User = Depends(_resident_only),
                    db: Session = Depends(get_db)):
    return ds.resident_charts(db, user, months)
