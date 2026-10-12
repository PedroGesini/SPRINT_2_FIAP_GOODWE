"""Simulador OCPP 1.6J para testes locais (NÃO controla equipamento físico).

Uso: python scripts/ocpp_simulator.py --url ws://127.0.0.1:8000/ocpp/CH-01 --tag U2
Solicita o segredo interativamente para não deixá-lo no histórico do terminal.
Requer websockets (instalado por uvicorn[standard]).
"""
import argparse
import asyncio
import base64
from datetime import datetime, timezone
from getpass import getpass
from json import dumps, loads
from urllib.parse import urlsplit

import websockets


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')


async def call(ws, uid: str, name: str, body: dict):
    await ws.send(dumps([2,uid,name,body]))
    while True:
        frame=loads(await ws.recv())
        if frame[0]==2:
            _,remote_id,action,payload=frame
            print('Comando recebido:',action, payload)
            if action=='ChangeAvailability':
                await ws.send(dumps([3,remote_id,{'status':'Accepted'}]))
                next_state='Available' if payload.get('type')=='Operative' else 'Unavailable'
                await call(ws,'status-after-command','StatusNotification',{
                    'connectorId':1,'errorCode':'NoError','status':next_state,'timestamp':now()})
            else:
                await ws.send(dumps([4,remote_id,'NotImplemented','Não implementado',{}]))
            continue
        if frame[1]==uid:
            if frame[0]==4: raise RuntimeError(f'OCPP CallError: {frame}')
            return frame[2]


async def main():
    p=argparse.ArgumentParser(description='Simulador OCPP 1.6J ChargeOps')
    p.add_argument('--url',required=True,help='ws://127.0.0.1:8000/ocpp/CH-01')
    p.add_argument('--tag',required=True,help='ID OCPP de morador autorizado, como U2 ou RFID cadastrado')
    p.add_argument('--hold',type=int,default=0,help='Segundos conectado para aceitar comandos remotos')
    args=p.parse_args()
    station_id=urlsplit(args.url).path.rstrip('/').split('/')[-1]
    pwd=getpass(f'Senha OCPP de {station_id}: ')
    basic=base64.b64encode(f'{station_id}:{pwd}'.encode()).decode()
    async with websockets.connect(args.url,subprotocols=['ocpp1.6'],
                                  additional_headers={'Authorization':f'Basic {basic}'}) as ws:
        print('BootNotification:',await call(ws,'boot','BootNotification',{
            'chargePointVendor':'Simulador ChargeOps','chargePointModel':'Demo 1.6J'}))
        print('StatusNotification:',await call(ws,'available','StatusNotification',{
            'connectorId':1,'errorCode':'NoError','status':'Available','timestamp':now()}))
        print('Authorize:',await call(ws,'authorize','Authorize',{'idTag':args.tag}))
        started=await call(ws,'start','StartTransaction',{
            'connectorId':1,'idTag':args.tag,'meterStart':1000,'timestamp':now()})
        print('StartTransaction:',started)
        if started.get('idTagInfo',{}).get('status')!='Accepted':return
        tx=started['transactionId']
        await call(ws,'charging','StatusNotification',{
            'connectorId':1,'errorCode':'NoError','status':'Charging','timestamp':now()})
        print('MeterValues:',await call(ws,'reading','MeterValues',{
            'connectorId':1,'transactionId':tx,'meterValue':[{'timestamp':now(),
             'sampledValue':[{'value':'2450','unit':'Wh','measurand':'Energy.Active.Import.Register'}]}]}))
        await asyncio.sleep(1)
        print('StopTransaction:',await call(ws,'stop','StopTransaction',{
            'transactionId':tx,'meterStop':3500,'timestamp':now()}))
        await call(ws,'finish','StatusNotification',{
            'connectorId':1,'errorCode':'NoError','status':'Available','timestamp':now()})
        print('Recarga de teste registrada: 2,500 kWh.')
        if args.hold>0:
            print('Mantendo conexão OCPP por',args.hold,'segundos')
            end=asyncio.get_running_loop().time()+args.hold
            while asyncio.get_running_loop().time()<end:
                try:
                    frame=loads(await asyncio.wait_for(ws.recv(),timeout=1))
                    if frame[0]==2:
                        _,remote_id,action,payload=frame
                        if action=='ChangeAvailability':
                            print('ChangeAvailability',payload)
                            await ws.send(dumps([3,remote_id,{'status':'Accepted'}]))
                            await call(ws,'status-after-command','StatusNotification',{
                                'connectorId':1,'errorCode':'NoError',
                                'status':'Available' if payload.get('type')=='Operative' else 'Unavailable',
                                'timestamp':now()})
                        else:
                            await ws.send(dumps([4,remote_id,'NotImplemented','Não implementado',{}]))
                except asyncio.TimeoutError: pass

if __name__=='__main__': asyncio.run(main())
