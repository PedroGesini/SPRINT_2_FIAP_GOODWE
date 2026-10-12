import React, { useEffect, useRef, useState } from 'react';
import {
  BrainCircuit, X, Send, ArrowUpRight, Zap, BarChart3, Activity,
  Power, ShieldCheck, AlertTriangle, LoaderCircle, Check, Sparkles,
  PlugZap, RefreshCw, ChevronRight, History, TrendingUp
} from 'lucide-react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api, num, type User } from './api';

type Metric = { label: string; value: string };
type Charger = { id: number; code: string; name: string; status: string; status_label: string; power_kw: number; location: string; parking_spot: string };
type Proposal = { action: 'set_charger_status' | 'start_session' | 'end_session'; charger_id: number; charger_code: string; session_id?: number; status: 'available' | 'maintenance' | 'unavailable' | 'in_progress' | 'completed'; status_label: string };
type HistoryPoint = { label: string; kwh: number; cost: number; sessions: number };
type Answer = {
  answer: string; mode?: string; conversation_id?: number;
  cards?: Metric[]; chart?: { title: string; data: HistoryPoint[] } | null;
  chargers?: Charger[]; proposal?: Proposal | null; sources?: string[]; simulated?: boolean;
};
type Message = { role: 'user' | 'assistant'; content: string; info?: Answer; actionState?: 'done' | 'cancelled' | 'working' };

const ADMIN_EXAMPLES = [
  'Quanto o condomínio consumiu neste mês?',
  'Quais carregadores estão disponíveis?',
  'Mostre o consumo do CH-01',
  'Qual carregador é mais utilizado?',
  'Qual a previsão do próximo mês?',
  'Coloque CH-05 em manutenção',
];
const RESIDENT_EXAMPLES = [
  'Quanto eu consumi neste mês?',
  'Quais carregadores estão disponíveis?',
  'Quanto custou minha última recarga?',
  'Qual é o valor da minha fatura?',
  'Como posso economizar energia?',
  'Inicie uma recarga no CH-01',
  'Encerre minha recarga',
];
const ACCENT = '#ff174f';
const staff = (u: User) => u.role === 'syndic' || u.role === 'platform_admin';

function CopilotMetric({ item }: { item: Metric }) {
  return <div className="copilot-metric"><p>{item.label}</p><strong>{item.value}</strong></div>;
}

function StatusCircle({ status }: { status: string }) {
  return <span className={'copilot-status-dot '+(status === 'available' ? 'is-available' : status === 'in_use' ? 'is-busy' : 'is-offline')} />;
}

export default function Copilot({ user, onClose, notify, onDataChanged }: {
  user: User; onClose: () => void; notify: (message: string) => void; onDataChanged: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([
    { role: 'assistant', content: 'Olá! Sou o Copiloto EV ChargeOps. Posso analisar consumo, recargas, custos, carregadores e previsões a partir dos dados do seu painel. O que gostaria de consultar?' }
  ]);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [conversationId, setConversationId] = useState<number | undefined>();
  const [activeTab, setActiveTab] = useState<'chat' | 'atalhos'>('chat');
  const [chargerChoices, setChargerChoices] = useState<Charger[]>([]);
  const [actionLoading, setActionLoading] = useState<number | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const examples = staff(user) ? ADMIN_EXAMPLES : RESIDENT_EXAMPLES;

  useEffect(() => {
    let alive = true;
    api<Charger[]>('/chargers').then(rows => { if (alive) setChargerChoices(rows); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  useEffect(() => { if (activeTab === 'chat') scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' }); }, [messages, busy, activeTab]);

  async function send(message: string) {
    const clean = message.trim();
    if (!clean || busy || actionLoading !== null) return;
    setQuery('');
    setActiveTab('chat');
    setMessages(old => [...old, { role: 'user', content: clean }]);
    setBusy(true);
    try {
      const result = await api<Answer>('/ai/copilot/chat', { method: 'POST', body: JSON.stringify({ message: clean, conversation_id: conversationId }) });
      setConversationId(result.conversation_id);
      setMessages(old => [...old, { role: 'assistant', content: result.answer, info: result }]);
    } catch (e) {
      setMessages(old => [...old, { role: 'assistant', content: 'A consulta não pôde ser concluída. Verifique o backend e tente novamente.' }]);
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function execute(proposal: Proposal, index: number) {
    if (actionLoading !== null) return;
    setActionLoading(index);
    setMessages(old => old.map((m, i) => i === index ? { ...m, actionState: 'working' } : m));
    try {
      const result = await api<{ success: boolean; message: string }>('/ai/copilot/execute', {
        method: 'POST',
        body: JSON.stringify({ action: proposal.action, charger_id: proposal.charger_id, session_id: proposal.session_id, status: proposal.status })
      });
      setMessages(old => old.map((m, i) => i === index ? { ...m, actionState: 'done' } : m).concat([
        { role: 'assistant', content: result.message + ' A alteração foi registrada pela API do EV ChargeOps.' }
      ]));
      onDataChanged();
      api<Charger[]>('/chargers').then(setChargerChoices).catch(() => {});
    } catch (e) {
      setMessages(old => old.map((m, i) => i === index ? { ...m, actionState: undefined } : m));
      notify((e as Error).message);
    } finally { setActionLoading(null); }
  }

  const cancel = (index: number) => setMessages(old => old.map((m, i) => i === index ? { ...m, actionState: 'cancelled' } : m));

  return <div className="fixed inset-0 z-[80] flex justify-end" role="dialog" aria-modal="true" aria-label="Copiloto de inteligência artificial">
    <button aria-label="Fechar copiloto" className="absolute inset-0 bg-[#02040b]/80 backdrop-blur-[3px]" onClick={onClose} />
    <section className="copilot-drawer relative h-full w-full max-w-[560px] flex flex-col overflow-hidden">
      <header className="copilot-header px-6 py-6 flex items-center gap-4">
        <div className="copilot-logo"><BrainCircuit size={24}/></div>
        <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><h2 className="text-[18px] font-extrabold tracking-tight text-white">Copiloto <span className="text-[#ff3768]">ChargeAI</span></h2><span className="copilot-online"><span/>DEMO</span></div><p className="text-xs text-slate-400 mt-1">Análise inteligente · Dados do EV ChargeOps</p></div>
        <button className="copilot-icon-btn" onClick={onClose} aria-label="Fechar chat"><X size={20}/></button>
      </header>
      <div className="copilot-top-strip"><ShieldCheck size={14}/><span>Consultas protegidas por perfil. Ações exigem confirmação.</span></div>
      <div className="flex gap-1 border-b border-white/5 p-3 bg-[#080b13]">
        <button className={'copilot-tab '+(activeTab === 'chat' ? 'active' : '')} onClick={() => setActiveTab('chat')}><Sparkles size={15}/> Conversa</button>
        <button className={'copilot-tab '+(activeTab === 'atalhos' ? 'active' : '')} onClick={() => setActiveTab('atalhos')}><PlugZap size={15}/> Consultas rápidas</button>
      </div>
      {activeTab === 'chat' ? <div className="flex-1 min-h-0 overflow-y-auto copilot-scroll px-4 sm:px-6 py-5 space-y-6" ref={scroller}>
        {messages.map((msg, index) => <div key={index} className={'copilot-message '+(msg.role === 'user' ? 'from-user' : '')}>
          {msg.role === 'assistant' && <div className="copilot-avatar"><BrainCircuit size={17}/></div>}
          <div className="min-w-0 flex-1">
            <div className={msg.role === 'user' ? 'copilot-user-bubble' : 'copilot-assistant-bubble'}>{msg.content}</div>
            {msg.info?.cards && msg.info.cards.length > 0 && <div className="copilot-metrics mt-3">{msg.info.cards.map((card, n) => <CopilotMetric item={card} key={n}/>)}</div>}
            {msg.info?.chart && msg.info.chart.data.length > 0 && <div className="copilot-chart mt-3">
              <div className="flex items-center gap-2 mb-3"><BarChart3 size={15} color={ACCENT}/><p className="text-xs font-bold text-slate-200">{msg.info.chart.title}</p></div>
              <div className="h-[175px] w-full"><ResponsiveContainer width="100%" height="100%"><AreaChart data={msg.info.chart.data} margin={{top:8,right:0,left:-26,bottom:0}}><defs><linearGradient id={'copilotArea'+index} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={ACCENT} stopOpacity={.40}/><stop offset="100%" stopColor={ACCENT} stopOpacity={.01}/></linearGradient></defs><CartesianGrid vertical={false} stroke="#293040" strokeDasharray="3 4"/><XAxis dataKey="label" tick={{fontSize:10,fill:'#94a3b8'}} axisLine={false} tickLine={false}/><YAxis tick={{fontSize:10,fill:'#94a3b8'}} axisLine={false} tickLine={false}/><Tooltip formatter={(value:any) => `${num(value)} kWh`} contentStyle={{background:'#0a0e17',border:'1px solid #293040',borderRadius:12}}/><Area dataKey="kwh" name="Consumo" type="monotone" stroke={ACCENT} strokeWidth={2.8} fill={'url(#copilotArea'+index+')'}/></AreaChart></ResponsiveContainer></div>
            </div>}
            {msg.info?.chargers && msg.info.chargers.length > 0 && <div className="space-y-2 mt-3">{msg.info.chargers.map(charger => <button key={charger.id} onClick={() => send(`Mostre os detalhes do ${charger.code}`)} className="copilot-charger w-full text-left">
              <div className="flex items-center gap-2"><StatusCircle status={charger.status}/><span className="font-bold text-white text-sm">{charger.code}</span><span className="text-[11px] ml-auto text-slate-400">{charger.status_label}</span><ChevronRight size={14} className="text-slate-500"/></div>
              <div className="text-[11px] mt-1 ml-[15px] text-slate-400">{charger.location} · {num(charger.power_kw)} kW · {charger.parking_spot}</div>
            </button>)}</div>}
            {msg.info?.proposal && <div className="copilot-action mt-3">
              <div className="flex items-center gap-2 text-xs text-rose-300 font-extrabold"><AlertTriangle size={15}/> Confirmação necessária</div>
              <p className="text-[13px] text-slate-300 mt-2">Confirmar <strong className="text-white">{msg.info.proposal.status_label}</strong> no <strong className="text-white">{msg.info.proposal.charger_code}</strong> no ambiente de simulação?</p>
              {msg.actionState === 'done' ? <p className="copilot-action-ok"><Check size={15}/> Operação executada</p> : msg.actionState === 'cancelled' ? <p className="text-xs text-slate-400 mt-3">Operação cancelada.</p> : <div className="flex gap-2 mt-4">
                <button disabled={actionLoading !== null} className="copilot-confirm" onClick={() => execute(msg.info!.proposal!, index)}>{msg.actionState === 'working' ? <LoaderCircle size={14} className="animate-spin"/> : <Check size={14}/>} Confirmar alteração</button>
                <button disabled={actionLoading !== null} className="copilot-cancel" onClick={() => cancel(index)}>Cancelar</button>
              </div>}
            </div>}
            {msg.info && <div className="text-[10px] text-slate-500 mt-2 flex items-center gap-1.5"><Activity size={12}/>{msg.info.mode === 'externo' ? 'Resposta assistida por LLM' : 'Consulta ao banco do sistema'} · Dados simulados</div>}
          </div>
        </div>)}
        {busy && <div className="flex gap-3 text-xs text-slate-400 items-center"><LoaderCircle className="animate-spin text-[#ff174f]" size={18}/> Consultando dados do sistema...</div>}
        {messages.length < 3 && <div className="space-y-3 pl-9"><p className="text-[10px] font-extrabold text-slate-500 uppercase tracking-[.2em]">Experimente perguntar</p>{examples.slice(0,4).map(item => <button className="copilot-example" key={item} onClick={() => send(item)}><ArrowUpRight size={14}/>{item}</button>)}</div>}
      </div> : <div className="flex-1 min-h-0 overflow-y-auto copilot-scroll p-6 space-y-7">
        <div><div className="flex gap-2 items-center text-xs font-bold text-slate-200 mb-4"><TrendingUp size={16} className="text-[#ff174f]"/> Perguntas recomendadas</div><div className="grid gap-2">{examples.map(q => <button className="copilot-shortcut" key={q} onClick={() => send(q)}><span>{q}</span><ArrowUpRight size={15}/></button>)}</div></div>
        <div><div className="flex gap-2 items-center text-xs font-bold text-slate-200 mb-4"><PlugZap size={16} className="text-[#ff174f]"/> Carregadores cadastrados</div><div className="grid grid-cols-2 gap-2">{chargerChoices.map(c => <button key={c.id} className="copilot-charger text-left" onClick={() => send(`Mostre os dados do ${c.code}`)}><span className="text-white font-extrabold text-sm flex items-center gap-2"><StatusCircle status={c.status}/>{c.code}</span><span className="text-[11px] block mt-2 text-slate-400">{c.location}</span></button>)}</div></div>
        {staff(user) && <div className="copilot-tip"><Power size={19} className="text-[#ff174f]"/><div><p className="font-extrabold text-slate-100 text-sm">Gestão assistida</p><p className="text-xs text-slate-400 mt-1">Exemplo: “Coloque CH-05 em manutenção”. O copiloto prepara a alteração, mas só executa após sua confirmação.</p></div></div>}
      </div>}
      <form className="copilot-compose" onSubmit={e => { e.preventDefault(); send(query); }}>
        <div className="copilot-input-box"><textarea rows={1} maxLength={500} value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(query); } }} placeholder="Pergunte sobre consumo, custos ou carregadores..." aria-label="Mensagem para o copiloto"/><button type="submit" disabled={busy || !query.trim()} aria-label="Enviar pergunta"><Send size={17}/></button></div>
        <div className="text-[10px] text-slate-500 mt-3 flex items-center justify-between"><span className="flex items-center gap-1"><ShieldCheck size={12}/> Consultas conforme seu perfil</span><span>Dados de demonstração</span></div>
      </form>
    </section>
  </div>;
}
