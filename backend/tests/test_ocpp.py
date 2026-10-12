"""Valida isolamento de condomínios e transações OCPP 1.6J.
Executar: python -m pytest tests/test_ocpp.py -q
"""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from app.models import (ChargingSession, ChargerStatus, OCPPDevice, OCPPMeterReading,
                        SessionSource, SessionStatus, OCPPTag)
from app.services import ocpp_gateway as gateway

class WS:
    async def send_json(self, body):
        self.last=body


def test_station_transactions(world,db,monkeypatch):
    station_maker=sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(gateway,'SessionLocal',station_maker)
    device=OCPPDevice(charger_id=world['charger'].id,ocpp_id='CH-01',
                      secret_hash=gateway.digest_secret('SENSITIVE_DEVICE_SECRET'))
    db.add(device);db.commit()
    tag=OCPPTag(condominium_id=world['condo'].id,resident_id=world['ana'].id,id_tag='RFID001')
    db.add(tag);db.commit()

    async def flow():
        st=gateway.Station(WS(),device.id)
        assert (await st.handle('BootNotification',{'chargePointVendor':'Test'}))['status']=='Accepted'
        assert (await st.handle('Authorize',{'idTag':'RFID001'}))['idTagInfo']['status']=='Accepted'
        assert (await st.handle('Authorize',{'idTag':'UNKNOWN'}))['idTagInfo']['status']=='Invalid'
        await st.handle('StatusNotification',{'connectorId':1,'status':'Available'})
        response=await st.handle('StartTransaction',{'idTag':'RFID001','meterStart':1000})
        assert response['idTagInfo']['status']=='Accepted'
        session_id=response['transactionId']
        await st.handle('MeterValues',{'transactionId':session_id,'meterValue':[
            {'timestamp':datetime.now(timezone.utc).isoformat(),'sampledValue':[
                {'value':'2600','unit':'Wh','measurand':'Energy.Active.Import.Register'}]}]})
        await st.handle('StopTransaction',{'transactionId':session_id,'meterStop':3500})
        return session_id

    session_id=asyncio.run(flow())
    db.expire_all()
    s=db.get(ChargingSession,session_id)
    assert s.source==SessionSource.INTEGRATION
    assert s.status==SessionStatus.COMPLETED
    assert s.energy_kwh==Decimal('2.500')
    assert s.resident_id==world['ana'].id
    assert db.get(type(world['charger']),world['charger'].id).status==ChargerStatus.AVAILABLE
    assert db.scalar(select(OCPPMeterReading.id)) is not None


def test_device_secret_and_meter_validation():
    assert gateway.digest_secret('ABC')!=gateway.digest_secret('DEF')
    assert gateway.meter_kwh(3500)==Decimal('3.500')
    assert gateway.meter_kwh('3.5','kWh')==Decimal('3.500')
