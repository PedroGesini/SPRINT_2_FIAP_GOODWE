"""Provisionamento e comandos OCPP restritos ao síndico; sem credenciais no frontend de moradores."""
import re
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.api.deps import charger_in_scope
from app.core.permissions import get_current_user, require_staff
from app.db.session import get_db
from app.models import Charger, OCPPDevice, OCPPTag, User, Role
from app.services.ocpp_gateway import (connections, digest_secret, issue_secret,
                                         OCPP_ID_RE)
from app.services.audit_service import log_action

router = APIRouter(prefix='/ocpp', tags=['OCPP 1.6J'])

class TagIn(BaseModel):
    resident_id: int = Field(gt=0)
    id_tag: str = Field(min_length=1,max_length=20,pattern=r'^[A-Za-z0-9_.-]+$')

@router.get('/tags')
def list_tags(staff: User = Depends(require_staff),db: Session = Depends(get_db)):
    tags = db.scalars(select(OCPPTag).where(OCPPTag.condominium_id==staff.condominium_id)).all()
    return [{'id':tag.id,'resident_id':tag.resident_id,'id_tag':tag.id_tag} for tag in tags]

@router.post('/tags',status_code=201)
def add_tag(data:TagIn,staff: User = Depends(require_staff),db: Session = Depends(get_db)):
    resident=db.get(User,data.resident_id)
    if not resident or resident.condominium_id!=staff.condominium_id or resident.role!=Role.RESIDENT:
        raise HTTPException(404,'Morador não encontrado')
    if db.scalar(select(OCPPTag.id).where(OCPPTag.condominium_id==staff.condominium_id,OCPPTag.id_tag==data.id_tag)):
        raise HTTPException(409,'Tag já cadastrada neste condomínio')
    tag=OCPPTag(condominium_id=staff.condominium_id,resident_id=resident.id,id_tag=data.id_tag)
    db.add(tag)
    db.flush()
    log_action(db,condominium_id=staff.condominium_id,actor_id=staff.id,action='ocpp.tag_registered',entity='ocpp_tag',entity_id=tag.id)
    db.commit()
    return {'id':tag.id,'resident_id':tag.resident_id,'id_tag':tag.id_tag}

@router.delete('/tags/{tag_id}',status_code=204)
def delete_tag(tag_id:int,staff: User = Depends(require_staff),db: Session = Depends(get_db)):
    tag=db.scalar(select(OCPPTag).where(OCPPTag.id==tag_id,OCPPTag.condominium_id==staff.condominium_id))
    if not tag: raise HTTPException(404,'Tag não encontrada')
    db.delete(tag)
    log_action(db,condominium_id=staff.condominium_id,actor_id=staff.id,action='ocpp.tag_removed',entity='ocpp_tag',entity_id=tag_id)
    db.commit()


class AvailabilityIn(BaseModel):
    type: str  # Operative | Inoperative


def _device_view(d: OCPPDevice, c: Charger):
    return {'charger_id':c.id, 'code':c.code,'name':c.name,'ocpp_id':d.ocpp_id,
            'connected':d.id in connections,'last_seen':d.last_seen,
            'connector_status':d.connector_status,'last_meter_kwh':d.last_meter_kwh,
            'vendor':d.vendor,'model':d.model,'firmware':d.firmware}

@router.get('/devices')
def devices(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Moradores veem apenas disponibilidade/medição pública; síndico vê identidade técnica."""
    rows = db.execute(select(OCPPDevice,Charger).join(Charger,Charger.id==OCPPDevice.charger_id)
                 .where(Charger.condominium_id==user.condominium_id).order_by(Charger.code)).all()
    staff = user.role.value in ('syndic','platform_admin')
    if staff: return [_device_view(d,c) for d,c in rows]
    return [{'charger_id':c.id,'connected':d.id in connections,
             'connector_status':d.connector_status,'last_meter_kwh':d.last_meter_kwh} for d,c in rows]

@router.get('/my-tag')
def my_tag(user: User = Depends(get_current_user)):
    return {'id_tag': f'U{user.id}' if user.role.value=='resident' else None,
            'note':'Identificador lógico de teste. Não substitui credencial RFID física.'}

@router.post('/chargers/{charger_id}/provision')
def provision(charger_id: int, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    charger = charger_in_scope(db,staff,charger_id)
    if not OCPP_ID_RE.fullmatch(charger.code):
        raise HTTPException(422,'Código do carregador inválido para identificação OCPP.')
    device = db.scalar(select(OCPPDevice).where(OCPPDevice.charger_id==charger.id))
    if device:
        raise HTTPException(409,'Já provisionado. Use a opção de rotacionar credenciais se necessário.')
    if db.scalar(select(OCPPDevice.id).where(OCPPDevice.ocpp_id==charger.code)):
        raise HTTPException(409,'ID OCPP em uso.')
    secret=issue_secret()
    device=OCPPDevice(charger_id=charger.id,ocpp_id=charger.code,secret_hash=digest_secret(secret))
    db.add(device)
    log_action(db,condominium_id=staff.condominium_id,actor_id=staff.id,
               action='ocpp.provisioned',entity='charger',entity_id=charger.id,
               details={'ocpp_id':device.ocpp_id})
    db.commit()
    return {'ocpp_id':device.ocpp_id,'username':device.ocpp_id,'password':secret,
            'websocket_path':f'/ocpp/{device.ocpp_id}', 'subprotocol':'ocpp1.6',
            'notice':'Guarde esta senha. Ela só será exibida uma vez. Utilize WSS (TLS) na rede real.'}

@router.post('/chargers/{charger_id}/rotate')
async def rotate(charger_id: int, staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    charger = charger_in_scope(db,staff,charger_id)
    device=db.scalar(select(OCPPDevice).where(OCPPDevice.charger_id==charger.id))
    if device is None: raise HTTPException(404,'Carregador não provisionado')
    secret=issue_secret()
    device.secret_hash=digest_secret(secret)
    log_action(db,condominium_id=staff.condominium_id,actor_id=staff.id,
               action='ocpp.secret_rotated',entity='charger',entity_id=charger.id)
    db.commit()
    station=connections.get(device.id)
    if station:
        await station.ws.close(code=1008,reason='Credencial alterada')
    return {'ocpp_id':device.ocpp_id,'username':device.ocpp_id,'password':secret,
            'websocket_path':f'/ocpp/{device.ocpp_id}', 'subprotocol':'ocpp1.6'}

@router.post('/chargers/{charger_id}/availability')
async def change_availability(charger_id: int, data: AvailabilityIn,
                              staff: User = Depends(require_staff), db: Session = Depends(get_db)):
    """Solicita comando REAL ao carregador. Estado final só muda com StatusNotification."""
    if data.type not in ('Operative','Inoperative'):
        raise HTTPException(422, 'type deve ser Operative ou Inoperative')
    charger=charger_in_scope(db,staff,charger_id)
    device=db.scalar(select(OCPPDevice).where(OCPPDevice.charger_id==charger.id))
    if device is None: raise HTTPException(409,'Carregador não provisionado OCPP')
    station=connections.get(device.id)
    if not station: raise HTTPException(409,'Carregador OCPP desconectado')
    try:
        reply=await station.call('ChangeAvailability',{'connectorId':0,'type':data.type})
    except (TimeoutError,ValueError,ConnectionError) as exc:
        raise HTTPException(504,'Sem resposta válida do carregador') from exc
    state=reply.get('status') if isinstance(reply,dict) else None
    if state not in ('Accepted','Rejected','Scheduled'):
        raise HTTPException(502,'Resposta OCPP inválida')
    log_action(db,condominium_id=staff.condominium_id,actor_id=staff.id,
               action='ocpp.change_availability',entity='charger',entity_id=charger.id,
               details={'requested':data.type,'result':state})
    db.commit()
    return {'status':state,'notice':'Aguarde StatusNotification do carregador para refletir o novo estado.'}
