import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Cpu, Wifi, WifiOff, ShieldCheck, RefreshCw, Copy, AlertTriangle, Power } from 'lucide-react';
import { api, num, type Page, type User, type Charger } from './api';

type Device={charger_id:number; code?:string; ocpp_id?:string; connected:boolean; connector_status?:string; last_seen?:string; last_meter_kwh?:number; vendor?:string; model?:string};
type Tag={id:number;resident_id:number;id_tag:string};
type Credentials={ocpp_id:string; username:string; password:string; websocket_path:string; subprotocol:string; notice?:string};

export function OcppPanel({chargers,devices,staff,changed,toast}: {
  chargers:Charger[];devices:Device[];staff:boolean;changed:()=>void;toast:(s:string)=>void;
}) {
  const [busy,setBusy]=useState<number|null>(null);
  const [tags,setTags]=useState<Tag[]>([]);
  const [residents,setResidents]=useState<User[]>([]);
  const [residentId,setResidentId]=useState('');
  const [tagValue,setTagValue]=useState('');
  useEffect(()=>{
    if(!staff)return;
    void api<Tag[]>('/ocpp/tags').then(setTags).catch(()=>{});
    void api<Page<User>>('/residents?page=1&size=100').then(d=>setResidents(d.items||[])).catch(()=>{});
  },[staff]);
  const [credentials,setCredentials]=useState<Credentials|null>(null);
  const deviceMap=useMemo(()=>new Map(devices.map(d=>[d.charger_id,d])),[devices]);
  async function addTag(e: FormEvent) {
    e.preventDefault();
    if(!residentId || !tagValue.trim())return;
    try {
      const tag=await api<Tag>('/ocpp/tags',{method:'POST',body:JSON.stringify({resident_id:Number(residentId),id_tag:tagValue.trim()})});
      setTags(t=>[...t,tag]);setTagValue('');toast('Cartão RFID vinculado ao morador.');changed();
    }catch(e){toast((e as Error).message)}
  }
  async function removeTag(tag:Tag) {
    if(!window.confirm(`Desvincular a tag ${tag.id_tag}?`))return;
    try {await api(`/ocpp/tags/${tag.id}`,{method:'DELETE'});setTags(t=>t.filter(x=>x.id!==tag.id));toast('Tag desvinculada.');changed()}
    catch(e){toast((e as Error).message)}
  }
  async function configure(charger:Charger,rotate=false){
    if(rotate && !window.confirm(`Gerar nova credencial para ${charger.code}? O dispositivo conectado será desconectado.`))return;
    setBusy(charger.id);
    try {
      const data=await api<Credentials>(`/ocpp/chargers/${charger.id}/${rotate?'rotate':'provision'}`,{method:'POST'});
      setCredentials(data); changed();
      toast('Credencial OCPP criada. Salve agora: ela não será exibida novamente.');
    }catch(e){toast((e as Error).message)} finally{setBusy(null)}
  }
  async function availability(charger:Charger,type:'Operative'|'Inoperative'){
    if(!window.confirm(`Enviar comando ${type} para o equipamento físico ${charger.code}?`))return;
    setBusy(charger.id);
    try {
      const result=await api<{status:string}>(`/ocpp/chargers/${charger.id}/availability`,{
        method:'POST',body:JSON.stringify({type})
      });
      toast(`Carregador respondeu: ${result.status}. Aguardando atualização do equipamento.`);
      changed();
    }catch(e){toast((e as Error).message)}finally{setBusy(null)}
  }
  return <section className="panel p-6 space-y-5">
    <div className="flex flex-wrap justify-between gap-3 items-start">
      <div><p className="text-xs tracking-widest uppercase text-red-400 font-bold">Integração OCPP 1.6J</p>
        <h3 className="text-lg text-white font-extrabold mt-2">Estações conectadas</h3>
        <p className="text-sm text-slate-400 mt-1">Telemetria real, disponibilidade e comandos confirmados.</p></div>
      <div className="text-xs text-slate-400 flex items-center gap-2"><Cpu size={17}/>{devices.length} provisionado(s)</div>
    </div>
    <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
      {chargers.map(charger=>{
        const device=deviceMap.get(charger.id);
        return <div key={charger.id} className="rounded-2xl bg-[#0a0e14] border border-white/10 p-4 space-y-3">
          <div className="flex items-center justify-between gap-2"><strong className="text-white">{charger.code}</strong>
            {device?.connected?<span className="text-xs text-green-400 inline-flex items-center gap-1"><Wifi size={15}/> Online</span>:<span className="text-xs text-slate-400 inline-flex items-center gap-1"><WifiOff size={15}/> {device?'Offline':'Não provisionado'}</span>}
          </div>
          <p className="text-xs text-slate-400">{device?.connector_status||'Sem StatusNotification'} · {device?.last_meter_kwh!=null?`${num(device.last_meter_kwh)} kWh no medidor`:'Sem telemetria'}</p>
          {staff && <div className="flex flex-wrap gap-2">
            {!device?<button disabled={busy!==null} className="btn-soft text-xs" onClick={()=>configure(charger)}>Provisionar</button>:
            <><button disabled={busy!==null} className="btn-soft text-xs" onClick={()=>configure(charger,true)}><RefreshCw size={13}/> Credencial</button>
            <button disabled={busy!==null||!device.connected} className="btn-soft text-xs" onClick={()=>availability(charger,'Operative')}><Power size={13}/> Ativar</button>
            <button disabled={busy!==null||!device.connected} className="btn-soft text-xs" onClick={()=>availability(charger,'Inoperative')}>Desativar</button></>}
          </div>}
        </div>
      })}
    </div>
    {staff && <div className="rounded-2xl border border-white/10 bg-[#080c12] p-5 space-y-3">
      <h4 className="font-bold text-white">Cartões RFID / Identificadores OCPP</h4>
      <p className="text-xs text-slate-400">Vincule o ID impresso ou lido do cartão físico ao morador. O OCPP autoriza apenas moradores ativos do mesmo condomínio.</p>
      <form onSubmit={addTag} className="flex flex-wrap gap-2">
        <select className="field !w-auto min-w-[200px]" value={residentId} onChange={e=>setResidentId(e.target.value)} required>
          <option value="">Selecionar morador</option>
          {residents.filter(r=>r.role==='resident').map(r=><option key={r.id} value={r.id}>{r.name}</option>)}
        </select>
        <input className="field !w-auto flex-1 min-w-[180px]" maxLength={20} pattern="[A-Za-z0-9_.-]+" placeholder="ID do cartão RFID" value={tagValue} onChange={e=>setTagValue(e.target.value)} required/>
        <button className="btn-primary" type="submit">Vincular cartão</button>
      </form>
      {tags.length>0 && <div className="flex flex-wrap gap-2">{tags.map(t=><div key={t.id} className="flex items-center gap-2 text-xs border border-white/10 rounded-xl px-3 py-2 text-slate-300"><span>{t.id_tag} → {residents.find(r=>r.id===t.resident_id)?.name||`Morador ${t.resident_id}`}</span><button title="Desvincular tag" className="text-red-400" onClick={()=>removeTag(t)}>Remover</button></div>)}</div>}
    </div>}
    {credentials && <div className="rounded-xl border border-amber-500/30 bg-amber-900/10 p-5 space-y-3">
      <div className="flex items-center gap-2 text-amber-300 font-bold"><AlertTriangle size={17}/> Credencial exibida uma única vez</div>
      <p className="text-sm text-slate-300">Configure no carregador um WebSocket com subprotocolo <code>ocpp1.6</code> e autenticação Basic.</p>
      <p className="text-sm break-all">Endpoint: <code>wss://SEU-DOMINIO{credentials.websocket_path}</code></p>
      <p className="text-sm">Usuário: <code>{credentials.username}</code></p>
      <p className="text-sm break-all">Senha: <code>{credentials.password}</code></p>
      <button className="btn-primary text-xs" onClick={()=>{void navigator.clipboard.writeText(`ID OCPP: ${credentials.ocpp_id}\nUsuário: ${credentials.username}\nSenha: ${credentials.password}\nSubprotocolo: ocpp1.6\nWSS: wss://SEU-DOMINIO${credentials.websocket_path}`);toast('Credenciais copiadas. Guarde em local seguro.')}}><Copy size={14}/> Copiar credenciais</button>
      <button className="btn-soft text-xs ml-2" onClick={()=>setCredentials(null)}><ShieldCheck size={14}/> Já salvei</button>
    </div>}
    <p className="text-xs text-slate-500">Não use credenciais de demonstração em produção. Para dispositivos físicos, configure WSS/TLS e rede segura. Recursos não suportados pelo firmware não funcionarão.</p>
  </section>;
}
