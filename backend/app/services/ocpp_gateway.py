"""OCPP 1.6J Central System (subset interoperável): JSON frames via WebSocket.

Fluxos cobertos: BootNotification, Heartbeat, StatusNotification, Authorize,
StartTransaction, MeterValues, StopTransaction e ChangeAvailability remoto.
Não implementa Smart Charging, reservas, atualização de firmware ou OCPP 2.0.1.
"""
import asyncio
import base64
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from fastapi import APIRouter, WebSocket
from sqlalchemy import select
from app.db.session import SessionLocal
from app.core.config import get_settings
from app.models import (Charger, ChargerStatus, ChargingSession, OCPPDevice, OCPPMeterReading, OCPPTag,
                        SessionSource, SessionStatus, User, UserStatus)
from app.models.core import utcnow
from app.services import charging_service as cs
from app.services.realtime import publish

logger = logging.getLogger('chargeops.ocpp')
router = APIRouter(tags=['OCPP 1.6J'])
OCPP_ID_RE = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')
connections: dict[int, 'Station'] = {}


def digest_secret(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def issue_secret() -> str:
    return secrets.token_urlsafe(32)


def parse_ts(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else utcnow()
        if not result.tzinfo: result = result.replace(tzinfo=timezone.utc)
        result = result.astimezone(timezone.utc)
        # Evita confiar em relógios de carregadores com diferença exagerada.
        return result if abs((utcnow() - result).total_seconds()) < 86400 else utcnow()
    except (ValueError, TypeError):
        return utcnow()


def meter_kwh(raw, unit='Wh'):
    value = Decimal(str(raw))
    if not value.is_finite() or value < 0: raise ValueError('Leitura inválida')
    if unit == 'Wh': value /= Decimal(1000)
    elif unit != 'kWh': raise ValueError('Unidade inválida')
    return value.quantize(Decimal('.001'))


def find_meter(payload):
    """Encontra medidor cumulativo importado: OCPP Wh ou kWh."""
    for value in payload.get('meterValue', [])[:50]:
        for sample in value.get('sampledValue', [])[:30]:
            if sample.get('measurand', 'Energy.Active.Import.Register') == 'Energy.Active.Import.Register':
                try:
                    return meter_kwh(sample.get('value'), sample.get('unit', 'Wh')), parse_ts(value.get('timestamp'))
                except (InvalidOperation, ValueError, TypeError):
                    continue
    return None, None


class Station:
    def __init__(self, ws: WebSocket, device_id: int):
        self.ws = ws
        self.device_id = device_id
        self.waiting: dict[str, asyncio.Future] = {}
        self.send_lock = asyncio.Lock()

    async def call(self, action: str, payload: dict, timeout: int = 12):
        uid = uuid4().hex
        pending = asyncio.get_running_loop().create_future()
        self.waiting[uid] = pending
        try:
            async with self.send_lock:
                await self.ws.send_json([2, uid, action, payload])
            return await asyncio.wait_for(pending, timeout=timeout)
        finally:
            self.waiting.pop(uid, None)

    async def reply(self, uid: str, result: dict):
        async with self.send_lock:
            await self.ws.send_json([3, uid, result])

    async def fail(self, uid: str, code: str, desc: str):
        async with self.send_lock:
            await self.ws.send_json([4, uid, code, desc, {}])

    def settle(self, frame):
        future = self.waiting.get(frame[1])
        if future is not None and not future.done():
            if frame[0] == 3: future.set_result(frame[2])
            else: future.set_exception(ValueError(str(frame[3]) if len(frame)>3 else 'OCPP CallError'))

    async def handle(self, action: str, p: dict):
        with SessionLocal() as db:
            dev = db.get(OCPPDevice, self.device_id)
            if dev is None: raise ValueError('Estação não cadastrada')
            charger = db.get(Charger, dev.charger_id)
            if charger is None: raise ValueError('Carregador não encontrado')
            dev.last_seen = utcnow()
            changed = action not in ('Heartbeat', 'Authorize')
            out: dict = {}
            if action == 'BootNotification':
                dev.vendor = str(p.get('chargePointVendor',''))[:100]
                dev.model = str(p.get('chargePointModel',''))[:100]
                dev.firmware = str(p.get('firmwareVersion',''))[:100] or None
                out = {'status':'Accepted','currentTime':utcnow().isoformat(), 'interval':60}
            elif action == 'Heartbeat':
                out = {'currentTime':utcnow().isoformat()}
            elif action == 'StatusNotification':
                status = p.get('status')
                if status not in ('Available','Preparing','Charging','SuspendedEV','SuspendedEVSE',
                                  'Finishing','Reserved','Unavailable','Faulted'):
                    raise ValueError('Estado inválido')
                dev.connector_status = status
                active = db.scalars(select(ChargingSession).where(ChargingSession.charger_id == charger.id,
                     ChargingSession.status == SessionStatus.IN_PROGRESS)).first()
                if status == 'Faulted': next_status = ChargerStatus.MAINTENANCE
                elif status == 'Unavailable': next_status = ChargerStatus.UNAVAILABLE
                elif active or status in ('Charging','SuspendedEV','SuspendedEVSE'):
                    next_status = ChargerStatus.IN_USE
                elif status in ('Available','Preparing','Finishing'):
                    next_status = ChargerStatus.AVAILABLE
                else: next_status = charger.status
                charger.status = next_status
                charger.status_updated_at = utcnow()
                out = {}
            elif action == 'Authorize':
                tag = str(p.get('idTag', ''))
                resident = self._resident(db, charger, tag)
                out = {'idTagInfo': {'status': 'Accepted' if resident else 'Invalid'}}
            elif action == 'StartTransaction':
                tag = str(p.get('idTag', ''))
                resident = self._resident(db, charger, tag)
                if not resident:
                    out = {'transactionId': 0, 'idTagInfo':{'status':'Invalid'}}
                else:
                    reading = meter_kwh(p.get('meterStart',0))
                    # OCPP pode anunciar Charging antes de StartTransaction.
                    if charger.status == ChargerStatus.IN_USE and not db.scalar(select(ChargingSession.id).where(
                        ChargingSession.charger_id == charger.id, ChargingSession.status == SessionStatus.IN_PROGRESS)):
                        charger.status = ChargerStatus.AVAILABLE
                    try:
                        session = cs.start_session(db, charger=charger, resident=resident, actor=resident,
                            start_reading_kwh=reading, source=SessionSource.INTEGRATION,
                            started_at=parse_ts(p.get('timestamp')))
                        out = {'transactionId':session.id,'idTagInfo':{'status':'Accepted'}}
                    except cs.ChargingError as exc:
                        logger.warning('Recarga OCPP recusada: %s', exc)
                        out = {'transactionId':0,'idTagInfo':{'status':'Blocked'}}
            elif action == 'MeterValues':
                kwh, when = find_meter(p)
                transaction_id = p.get('transactionId')
                session = db.get(ChargingSession, transaction_id) if isinstance(transaction_id, int) and transaction_id>0 else None
                if session is not None and (session.charger_id != charger.id or session.source != SessionSource.INTEGRATION):
                    session = None
                if kwh is not None:
                    dev.last_meter_kwh = kwh
                    db.add(OCPPMeterReading(device_id=dev.id,
                        session_id=session.id if session else None, meter_kwh=kwh, timestamp=when))
                    if session and session.status == SessionStatus.IN_PROGRESS and session.start_reading_kwh is not None:
                        # Parcial exibido em ambas as telas; a fatura usa apenas sessões concluídas.
                        session.energy_kwh = max(Decimal('0'), kwh - session.start_reading_kwh)
                out = {}
            elif action == 'StopTransaction':
                tx = p.get('transactionId')
                session = db.get(ChargingSession, tx) if isinstance(tx, int) and tx>0 else None
                if not session or session.charger_id != charger.id or session.source != SessionSource.INTEGRATION:
                    raise ValueError('Transação desconhecida')
                if session.status == SessionStatus.IN_PROGRESS:
                    reading = meter_kwh(p['meterStop'])
                    cs.end_session(db, session=session, actor=db.get(User,session.resident_id),
                                   end_reading_kwh=reading, ended_at=max(parse_ts(p.get('timestamp')),
                                                session.started_at + timedelta(seconds=1)))
                out = {'idTagInfo': {'status':'Accepted'}}
            else:
                raise KeyError(action)
            db.commit()
            condo_id = charger.condominium_id
        if changed: await publish(condo_id)
        return out

    @staticmethod
    def _resident(db, charger: Charger, tag: str):
        if get_settings().environment in ('development','test') and re.fullmatch(r'U[1-9][0-9]{0,17}',tag):
            u = db.get(User,int(tag[1:]))
        else:
            link = db.scalar(select(OCPPTag).where(OCPPTag.condominium_id == charger.condominium_id,
                         OCPPTag.id_tag == tag))
            u = db.get(User,link.resident_id) if link else None
        return u if u and u.condominium_id == charger.condominium_id and u.status == UserStatus.ACTIVE and u.role.value == 'resident' else None


@router.websocket('/ocpp/{ocpp_id}')
async def ocpp_websocket(ws: WebSocket, ocpp_id: str):
    if not OCPP_ID_RE.fullmatch(ocpp_id):
        await ws.close(code=1008); return
    if 'ocpp1.6' not in ws.scope.get('subprotocols',[]):
        await ws.close(code=1002); return
    authorization = ws.headers.get('authorization','')
    try:
        scheme, payload = authorization.split(' ',1)
        if scheme.lower() != 'basic': raise ValueError()
        name, password = base64.b64decode(payload,validate=True).decode('utf-8').split(':',1)
    except (ValueError, UnicodeError):
        await ws.close(code=1008); return
    with SessionLocal() as db:
        dev = db.scalar(select(OCPPDevice).where(OCPPDevice.ocpp_id == ocpp_id))
        if not dev or not hmac.compare_digest(name,ocpp_id) or not hmac.compare_digest(
                digest_secret(password),dev.secret_hash):
            await ws.close(code=1008); return
        device_id, charger_id = dev.id, dev.charger_id
        charger = db.get(Charger,charger_id)
        condo_id = charger.condominium_id
    if device_id in connections:
        await ws.close(code=1008); return
    await ws.accept(subprotocol='ocpp1.6')
    station = Station(ws, device_id)
    connections[device_id] = station
    await publish(condo_id)
    try:
        while True:
            raw = await asyncio.wait_for(ws.receive_text(),timeout=180)
            if len(raw)>65536: await ws.close(code=1009); break
            import json
            try:
                frame = json.loads(raw)
                if not isinstance(frame,list) or len(frame)<3 or frame[0] not in (2,3,4): raise ValueError()
                if frame[0] in (3,4):
                    station.settle(frame)
                    continue
                if len(frame)!=4 or not isinstance(frame[1],str) or not isinstance(frame[2],str) or not isinstance(frame[3],dict): raise ValueError()
                uid, action, payload = frame[1],frame[2],frame[3]
                try:
                    result = await station.handle(action,payload)
                    await station.reply(uid,result)
                except KeyError:
                    await station.fail(uid,'NotImplemented',f'Ação não implementada: {action}')
                except (ValueError,InvalidOperation,cs.ChargingError) as exc:
                    logger.warning('OCPP mensagem inválida %s: %s',action,exc)
                    await station.fail(uid,'FormationViolation','Dados OCPP inválidos')
                except Exception:
                    logger.exception('OCPP erro inesperado ao processar %s',action)
                    await station.fail(uid,'InternalError','Falha do servidor')
            except (ValueError,TypeError):
                await ws.close(code=1002); break
    except (asyncio.TimeoutError,RuntimeError):
        logger.info('OCPP conexão finalizada por inatividade: %s',ocpp_id)
    except Exception:
        logger.info('OCPP desconectado: %s',ocpp_id)
    finally:
        if connections.get(device_id) is station: connections.pop(device_id,None)
        for pending in station.waiting.values():
            if not pending.done(): pending.cancel()
        await publish(condo_id)
