# =========================================================
# integrar-dashboard.ps1
# Roda de dentro da pasta "goodwe-chargeops" (onde esta o
# docker-compose.yml). Substitui o App.jsx pelo dashboard
# real e configura Tailwind + dependencias que ele usa.
# =========================================================

$frontend = "frontend"

# ---------- App.jsx (seu dashboard) ----------
@'
import React, { useState, useMemo, useRef, useCallback } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar,
} from "recharts";
import * as XLSX from "xlsx";
import {
  Zap, Plug, Users, FileSpreadsheet, Mail, MessageCircle, LogOut, ChevronRight,
  CheckCircle2, AlertTriangle, Upload, User as UserIcon, Home, Clock, ShieldCheck,
  ArrowLeft, Search, Loader2, X,
} from "lucide-react";

/* ---------------------------------------------------------------------- */
/* Tokens                                                                   */
/* ---------------------------------------------------------------------- */
const C = {
  bg: "#0A1F1D",
  bgSolid: "#0A1F1D",
  bgSoft: "#0F2926",
  surface: "#123330",
  surfaceHi: "#17423E",
  line: "#20514B",
  text: "#EAF3EF",
  textMuted: "#8FB0A9",
  textFaint: "#5C7D77",
  brand: "#3ED598",
  brandSoft: "#1E5C4C",
  green: "#3ED598",
  greenSoft: "#1E5C4C",
  blue: "#3AA0FF",
  amber: "#F0A83C",
  amberSoft: "#4A3A1C",
  red: "#E8615D",
  redSoft: "#4A2222",
};

const FONTS = `
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap');
`;

/* ---------------------------------------------------------------------- */
/* Mock data                                                                */
/* ---------------------------------------------------------------------- */
const MESES = ["Mar", "Abr", "Mai", "Jun", "Jul", "Ago"];

function gerarConsumo(base, variação) {
  return MESES.map((m, i) => ({
    mes: m,
    kwh: Math.max(8, Math.round(base + Math.sin(i * 1.3) * variação + (Math.random() - 0.5) * 6)),
  }));
}

function gerarFaturas(seed) {
  const hoje = new Date(2026, 7, 21);
  const faturas = [];
  for (let i = 0; i < 3; i++) {
    const venc = new Date(2026, 7 - i, 10);
    const valor = Math.round((60 + seed * 7 + i * 12) * 100) / 100;
    let status;
    if (i === 0) status = "aberta";
    else if (venc < hoje && i === 2) status = "vencida";
    else status = "paga";
    faturas.push({
      id: `FAT-2026-${String(seed).padStart(3, "0")}-${6 - i}`,
      mes: MESES[5 - i] + "/2026",
      valor,
      vencimento: venc.toLocaleDateString("pt-BR"),
      status,
    });
  }
  return faturas;
}

const MORADORES_MOCK = [
  { nome: "Fernanda Alves", unidade: "Bloco A · Apto 302", cpf: "123.456.789-00", email: "fernanda.alves@email.com" },
  { nome: "Ricardo Nogueira", unidade: "Bloco B · Apto 118", cpf: "234.567.891-02", email: "ricardo.nog@email.com" },
  { nome: "Juliana Prado", unidade: "Bloco A · Apto 405", cpf: "345.678.912-03", email: "juliana.prado@email.com" },
  { nome: "Marcos Vinícius Lima", unidade: "Bloco C · Apto 201", cpf: "456.789.123-04", email: "marcos.lima@email.com" },
  { nome: "Beatriz Coutinho", unidade: "Bloco B · Apto 512", cpf: "567.891.234-05", email: "bia.coutinho@email.com" },
  { nome: "André Salgado", unidade: "Bloco C · Apto 309", cpf: "678.912.345-06", email: "andre.salgado@email.com" },
].map((m, i) => ({
  ...m,
  id: `GW-2026-${String(140 + i).padStart(4, "0")}`,
  consumo: gerarConsumo(28 + i * 4, 10),
  faturas: gerarFaturas(i + 1),
}));

/* ---------------------------------------------------------------------- */
/* Helpers                                                                   */
/* ---------------------------------------------------------------------- */
function maskCPF(v) {
  return v.replace(/\D/g, "").slice(0, 11)
    .replace(/(\d{3})(\d)/, "$1.$2")
    .replace(/(\d{3})(\d)/, "$1.$2")
    .replace(/(\d{3})(\d{1,2})$/, "$1-$2");
}

function gerarID() {
  return `GW-2026-${Math.floor(1000 + Math.random() * 8999)}`;
}

function statusMeta(status) {
  switch (status) {
    case "paga": return { label: "Paga", color: C.green, bg: C.greenSoft, icon: CheckCircle2 };
    case "aberta": return { label: "Em aberto", color: C.amber, bg: C.amberSoft, icon: Clock };
    case "vencida": return { label: "Vencida", color: C.red, bg: C.redSoft, icon: AlertTriangle };
    default: return { label: status, color: C.textMuted, bg: C.surfaceHi, icon: Clock };
  }
}

/* ---------------------------------------------------------------------- */
/* Small UI atoms                                                           */
/* ---------------------------------------------------------------------- */
function Badge({ status }) {
  const m = statusMeta(status);
  const Icon = m.icon;
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold"
      style={{ background: m.bg, color: m.color }}
    >
      <Icon size={12} strokeWidth={2.5} />
      {m.label}
    </span>
  );
}

function Toast({ message, onClose }) {
  return (
    <div
      className="fixed bottom-6 right-6 z-50 flex items-center gap-3 px-5 py-4 rounded-xl shadow-2xl max-w-sm"
      style={{ background: C.surfaceHi, border: `1px solid ${C.line}`, color: C.text }}
    >
      <CheckCircle2 size={20} color={C.green} className="shrink-0" />
      <p className="text-sm leading-snug" style={{ fontFamily: "Inter" }}>{message}</p>
      <button onClick={onClose} className="shrink-0 opacity-60 hover:opacity-100">
        <X size={16} />
      </button>
    </div>
  );
}

/* Signature element: charging-ring radial gauge */
function ChargeRing({ percent, label, sublabel }) {
  const clamped = Math.min(percent, 130);
  const r = 54;
  const circ = 2 * Math.PI * r;
  const color = percent > 100 ? C.red : percent > 80 ? C.amber : C.green;
  const offset = circ - (Math.min(clamped, 100) / 100) * circ;
  return (
    <div className="relative flex items-center justify-center" style={{ width: 150, height: 150 }}>
      <svg width="150" height="150" viewBox="0 0 150 150" className="-rotate-90">
        <circle cx="75" cy="75" r={r} fill="none" stroke={C.line} strokeWidth="10" />
        <circle
          cx="75" cy="75" r={r} fill="none" stroke={color} strokeWidth="10"
          strokeDasharray={circ} strokeDashoffset={offset} strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 900ms ease, stroke 400ms ease" }}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <Plug size={18} color={color} strokeWidth={2.2} />
        <span className="text-2xl font-bold mt-1" style={{ fontFamily: "Space Grotesk", color: C.text }}>
          {Math.round(percent)}%
        </span>
        <span className="text-[10px] uppercase tracking-wider" style={{ color: C.textFaint }}>{sublabel}</span>
      </div>
    </div>
  );
}

function StatCard({ icon: Icon, label, value, hint, accent }) {
  return (
    <div className="rounded-2xl p-5 flex flex-col gap-3" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wider font-semibold" style={{ color: C.textFaint }}>{label}</span>
        <div className="p-2 rounded-lg" style={{ background: `${accent}22` }}>
          <Icon size={16} color={accent} />
        </div>
      </div>
      <span className="text-2xl font-bold" style={{ fontFamily: "Space Grotesk", color: C.text }}>{value}</span>
      {hint && <span className="text-xs" style={{ color: C.textMuted }}>{hint}</span>}
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Conta única do síndico — provisionada uma vez na instalação, sem       */
/* autocadastro. Em produção isso vive no banco (hash de senha), nunca    */
/* hardcoded no front-end como aqui neste protótipo.                      */
/* ---------------------------------------------------------------------- */
const SINDICO_ADMIN = { email: "sindico@residencialgoodwe.com.br", senha: "GoodWe@2026" };

function SindicoLoginScreen({ onEntrar, onVoltar }) {
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");

  const entrar = () => {
    if (email.trim().toLowerCase() === SINDICO_ADMIN.email && senha === SINDICO_ADMIN.senha) {
      setErro("");
      onEntrar();
    } else {
      setErro("E-mail ou senha inválidos.");
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center px-4" style={{ background: C.bg }}>
      <div className="w-full max-w-sm">
        <button onClick={onVoltar} className="flex items-center gap-1.5 text-xs mb-6" style={{ color: C.textMuted }}>
          <ArrowLeft size={14} /> voltar
        </button>

        <div className="rounded-2xl p-8" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
          <div className="w-11 h-11 rounded-xl flex items-center justify-center mb-5" style={{ background: C.brandSoft }}>
            <ShieldCheck size={20} color={C.brand} />
          </div>
          <h1 className="text-lg font-semibold mb-1" style={{ fontFamily: "Space Grotesk", color: C.text }}>
            Acesso do síndico
          </h1>
          <p className="text-sm mb-6" style={{ color: C.textMuted, fontFamily: "Inter" }}>
            Conta única de administração, criada uma vez na implantação do condomínio.
          </p>

          <div className="flex flex-col gap-4">
            <Field label="E-mail" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="sindico@seucondominio.com.br" />
            <Field label="Senha" type="password" value={senha} onChange={(e) => setSenha(e.target.value)} placeholder="••••••••" />
          </div>

          {erro && <p className="text-xs mt-4" style={{ color: C.red }}>{erro}</p>}

          <button
            onClick={entrar}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm mt-6 transition-transform active:scale-[0.98]"
            style={{ background: C.brand, color: C.bgSolid, fontFamily: "Inter" }}
          >
            Entrar <ChevronRight size={16} />
          </button>

          <p className="text-xs mt-5 text-center" style={{ color: C.textFaint, fontFamily: "Inter" }}>
            demo: {SINDICO_ADMIN.email} / {SINDICO_ADMIN.senha}
          </p>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Login / Cadastro                                                         */
/* ---------------------------------------------------------------------- */
function LoginScreen({ onGoogleLogin, onSindicoLogin }) {
  const [showPicker, setShowPicker] = useState(false);
  const contas = [
    { nome: "Pedro Andrade", email: "pedro.andrade@gmail.com" },
    { nome: "Camila Reis", email: "camila.reis@gmail.com" },
  ];

  return (
    <div className="min-h-screen w-full flex items-center justify-center px-4" style={{ background: C.bg }}>
      <div className="w-full max-w-md">
        <div className="flex items-center gap-2.5 mb-10 justify-center">
          <div className="p-2 rounded-xl" style={{ background: C.brandSoft }}>
            <Zap size={20} color={C.brand} strokeWidth={2.5} />
          </div>
          <span className="text-xl font-bold tracking-tight" style={{ fontFamily: "Space Grotesk", color: C.text }}>
            GoodWe ChargeOps
          </span>
        </div>

        <div className="rounded-2xl p-8" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
          <h1 className="text-lg font-semibold mb-1" style={{ fontFamily: "Space Grotesk", color: C.text }}>
            Carregador compartilhado
          </h1>
          <p className="text-sm mb-7" style={{ color: C.textMuted, fontFamily: "Inter" }}>
            Acesse com sua conta Google para acompanhar consumo e faturas, ou entre como síndico para gerenciar o condomínio.
          </p>

          <button
            onClick={() => setShowPicker(true)}
            className="w-full flex items-center justify-center gap-3 py-3 rounded-xl font-semibold text-sm mb-3 transition-transform active:scale-[0.98]"
            style={{ background: C.text, color: C.bgSolid, fontFamily: "Inter" }}
          >
            <svg width="18" height="18" viewBox="0 0 18 18"><path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"/><path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.81.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.94v2.33A9 9 0 0 0 9 18z"/><path fill="#FBBC05" d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.94A9 9 0 0 0 0 9c0 1.45.35 2.83.94 4.05z"/><path fill="#EA4335" d="M9 3.58c1.32 0 2.51.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .94 4.95l3.03 2.33C4.68 5.16 6.66 3.58 9 3.58z"/></svg>
            Entrar com Google
          </button>

          <button
            onClick={onSindicoLogin}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm transition-colors"
            style={{ background: "transparent", color: C.textMuted, border: `1px solid ${C.line}`, fontFamily: "Inter" }}
          >
            <ShieldCheck size={16} />
            Entrar como síndico
          </button>
        </div>

        <p className="text-center text-xs mt-6" style={{ color: C.textFaint, fontFamily: "Inter" }}>
          Protótipo acadêmico — Enterprise Challenge 2026 · Grupo 14
        </p>
      </div>

      {showPicker && (
        <div className="fixed inset-0 flex items-center justify-center z-50 px-4" style={{ background: "#000000AA" }}>
          <div className="w-full max-w-sm rounded-2xl overflow-hidden" style={{ background: "#FFFFFF" }}>
            <div className="p-6 border-b" style={{ borderColor: "#E5E5E5" }}>
              <p className="text-sm font-medium" style={{ color: "#1F1F1F", fontFamily: "Inter" }}>Escolha uma conta</p>
              <p className="text-xs mt-0.5" style={{ color: "#5F6368" }}>para continuar em GoodWe ChargeOps</p>
            </div>
            {contas.map((c) => (
              <button
                key={c.email}
                onClick={() => onGoogleLogin(c)}
                className="w-full flex items-center gap-3 px-6 py-3.5 hover:bg-gray-50 text-left"
              >
                <div className="w-9 h-9 rounded-full flex items-center justify-center text-white font-semibold text-sm" style={{ background: C.blue }}>
                  {c.nome[0]}
                </div>
                <div>
                  <p className="text-sm font-medium" style={{ color: "#1F1F1F" }}>{c.nome}</p>
                  <p className="text-xs" style={{ color: "#5F6368" }}>{c.email}</p>
                </div>
              </button>
            ))}
            <button onClick={() => setShowPicker(false)} className="w-full text-center py-3.5 text-sm border-t" style={{ color: C.blue, borderColor: "#E5E5E5" }}>
              Cancelar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function CadastroScreen({ conta, onConcluir, onVoltar }) {
  const [form, setForm] = useState({ nome: conta?.nome || "", cpf: "", endereco: "", email: conta?.email || "" });
  const [erro, setErro] = useState("");

  const set = (k) => (e) => {
    const v = k === "cpf" ? maskCPF(e.target.value) : e.target.value;
    setForm((f) => ({ ...f, [k]: v }));
  };

  const submeter = () => {
    if (!form.nome || form.cpf.length < 14 || !form.endereco || !form.email) {
      setErro("Preencha todos os campos — o CPF deve estar completo.");
      return;
    }
    setErro("");
    onConcluir({ ...form, id: gerarID() });
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center px-4" style={{ background: C.bg }}>
      <div className="w-full max-w-md">
        <button onClick={onVoltar} className="flex items-center gap-1.5 text-xs mb-6" style={{ color: C.textMuted }}>
          <ArrowLeft size={14} /> voltar
        </button>

        <div className="rounded-2xl p-8" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
          <h1 className="text-lg font-semibold mb-1" style={{ fontFamily: "Space Grotesk", color: C.text }}>
            Cadastro do morador
          </h1>
          <p className="text-sm mb-6" style={{ color: C.textMuted, fontFamily: "Inter" }}>
            Esses dados identificam sua unidade no carregador compartilhado do condomínio.
          </p>

          <div className="flex flex-col gap-4">
            <Field label="Nome completo" value={form.nome} onChange={set("nome")} placeholder="Ex: Ana Beatriz Souza" />
            <Field label="CPF" value={form.cpf} onChange={set("cpf")} placeholder="000.000.000-00" />
            <Field label="Endereço (bloco / apto)" value={form.endereco} onChange={set("endereco")} placeholder="Ex: Bloco A · Apto 304" />
            <Field label="E-mail" value={form.email} onChange={set("email")} placeholder="voce@email.com" type="email" />
          </div>

          {erro && <p className="text-xs mt-4" style={{ color: C.red }}>{erro}</p>}

          <button
            onClick={submeter}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm mt-6 transition-transform active:scale-[0.98]"
            style={{ background: C.brand, color: C.bgSolid, fontFamily: "Inter" }}
          >
            Concluir cadastro <ChevronRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, ...props }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs font-medium" style={{ color: C.textMuted, fontFamily: "Inter" }}>{label}</span>
      <input
        {...props}
        className="px-3.5 py-2.5 rounded-lg text-sm outline-none focus:ring-2"
        style={{ background: C.bgSoft, border: `1px solid ${C.line}`, color: C.text, fontFamily: "Inter" }}
      />
    </label>
  );
}

function IDCard({ id, nome }) {
  return (
    <div className="min-h-screen w-full flex items-center justify-center px-4" style={{ background: C.bg }}>
      <div className="w-full max-w-sm text-center">
        <div className="rounded-2xl p-8" style={{ background: `linear-gradient(160deg, ${C.surfaceHi}, ${C.surface})`, border: `1px solid ${C.line}` }}>
          <div className="mx-auto mb-5 w-14 h-14 rounded-full flex items-center justify-center" style={{ background: C.greenSoft }}>
            <CheckCircle2 size={26} color={C.green} />
          </div>
          <p className="text-sm mb-1" style={{ color: C.textMuted, fontFamily: "Inter" }}>Cadastro concluído, {nome.split(" ")[0]}</p>
          <p className="text-xs uppercase tracking-wider mb-2" style={{ color: C.textFaint }}>Seu ID de usuário</p>
          <p className="text-3xl font-bold mb-1" style={{ fontFamily: "JetBrains Mono", color: C.green }}>{id}</p>
          <p className="text-xs mt-4" style={{ color: C.textFaint, fontFamily: "Inter" }}>
            Use este ID para identificar sua sessão no carregador do condomínio.
          </p>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Shell (sidebar + topbar)                                                 */
/* ---------------------------------------------------------------------- */
function Shell({ role, activeUser, onLogout, children }) {
  return (
    <div className="min-h-screen w-full flex" style={{ background: C.bg }}>
      <aside className="w-60 shrink-0 flex flex-col p-5 hidden md:flex" style={{ borderRight: `1px solid ${C.line}` }}>
        <div className="flex items-center gap-2.5 mb-10">
          <div className="p-2 rounded-xl" style={{ background: C.brandSoft }}>
            <Zap size={18} color={C.brand} strokeWidth={2.5} />
          </div>
          <span className="text-base font-bold tracking-tight" style={{ fontFamily: "Space Grotesk", color: C.text }}>
            GoodWe ChargeOps
          </span>
        </div>

        <nav className="flex flex-col gap-1 text-sm" style={{ fontFamily: "Inter" }}>
          <NavItem icon={Home} label={role === "sindico" ? "Visão geral" : "Meu consumo"} active />
          {role === "sindico" ? (
            <>
              <NavItem icon={Users} label="Moradores" />
              <NavItem icon={FileSpreadsheet} label="Importar dados" />
            </>
          ) : (
            <>
              <NavItem icon={Zap} label="Faturas" />
              <NavItem icon={UserIcon} label="Meus dados" />
            </>
          )}
        </nav>

        <div className="mt-auto pt-6" style={{ borderTop: `1px solid ${C.line}` }}>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-9 h-9 rounded-full flex items-center justify-center font-semibold text-sm shrink-0" style={{ background: C.surfaceHi, color: C.text }}>
              {activeUser?.nome?.[0] || "S"}
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium truncate" style={{ color: C.text }}>{activeUser?.nome || "Síndico"}</p>
              <p className="text-xs truncate" style={{ color: C.textFaint, fontFamily: "JetBrains Mono" }}>{activeUser?.id || "Administração"}</p>
            </div>
          </div>
          <button onClick={onLogout} className="flex items-center gap-2 text-xs" style={{ color: C.textMuted }}>
            <LogOut size={14} /> Sair
          </button>
        </div>
      </aside>

      <main className="flex-1 min-w-0 p-5 md:p-8 overflow-y-auto" style={{ maxHeight: "100vh" }}>
        {children}
      </main>
    </div>
  );
}

function NavItem({ icon: Icon, label, active }) {
  return (
    <div
      className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg cursor-pointer"
      style={{ background: active ? C.surfaceHi : "transparent", color: active ? C.text : C.textMuted }}
    >
      <Icon size={16} />
      <span className="font-medium">{label}</span>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Morador dashboard                                                        */
/* ---------------------------------------------------------------------- */
function MoradorDashboard({ user }) {
  const consumo = user.consumo;
  const faturas = user.faturas;
  const consumoMes = consumo[consumo.length - 1].kwh;
  const franquia = 40;
  const percentUso = (consumoMes / franquia) * 100;
  const gastoMes = faturas.find((f) => f.mes.startsWith(MESES[MESES.length - 1]))?.valor
    ?? Math.round(consumoMes * 1.9 * 100) / 100;
  const pendentes = faturas.filter((f) => f.status === "aberta");
  const vencidas = faturas.filter((f) => f.status === "vencida");

  return (
    <div className="max-w-5xl">
      <header className="mb-8">
        <p className="text-xs uppercase tracking-wider mb-1" style={{ color: C.textFaint, fontFamily: "Inter" }}>Bem-vindo(a)</p>
        <h1 className="text-2xl font-bold" style={{ fontFamily: "Space Grotesk", color: C.text }}>{user.nome.split(" ")[0]}, aqui está seu consumo</h1>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-6">
        <div className="rounded-2xl p-6 flex items-center gap-6 lg:col-span-1" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
          <ChargeRing percent={percentUso} sublabel="da franquia" />
          <div>
            <p className="text-xs" style={{ color: C.textFaint }}>Consumo do mês</p>
            <p className="text-xl font-bold" style={{ fontFamily: "Space Grotesk", color: C.text }}>{consumoMes} kWh</p>
            <p className="text-xs mt-2" style={{ color: C.textFaint }}>Franquia mensal</p>
            <p className="text-sm" style={{ color: C.textMuted }}>{franquia} kWh</p>
          </div>
        </div>

        <div className="lg:col-span-2 grid grid-cols-2 gap-5">
          <StatCard icon={Zap} label="Gasto este mês" value={`R$ ${gastoMes.toFixed(2)}`} hint="referente à recarga do veículo" accent={C.blue} />
          <StatCard icon={Clock} label="Faturas em aberto" value={pendentes.length + vencidas.length} hint={vencidas.length ? `${vencidas.length} vencida(s)` : "nenhuma vencida"} accent={vencidas.length ? C.red : C.amber} />
        </div>
      </div>

      <div className="rounded-2xl p-6 mb-6" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
        <h2 className="text-sm font-semibold mb-4" style={{ fontFamily: "Space Grotesk", color: C.text }}>Consumo — últimos 6 meses</h2>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={consumo}>
            <CartesianGrid stroke={C.line} vertical={false} />
            <XAxis dataKey="mes" tick={{ fill: C.textFaint, fontSize: 12 }} axisLine={{ stroke: C.line }} tickLine={false} />
            <YAxis tick={{ fill: C.textFaint, fontSize: 12 }} axisLine={false} tickLine={false} unit=" kWh" width={64} />
            <Tooltip contentStyle={{ background: C.bgSoft, border: `1px solid ${C.line}`, borderRadius: 10, color: C.text, fontFamily: "Inter" }} />
            <Line type="monotone" dataKey="kwh" stroke={C.green} strokeWidth={2.5} dot={{ r: 3, fill: C.green }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-2xl p-6" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
        <h2 className="text-sm font-semibold mb-4" style={{ fontFamily: "Space Grotesk", color: C.text }}>Faturas</h2>
        <div className="flex flex-col gap-2.5">
          {faturas.map((f) => (
            <div key={f.id} className="flex items-center justify-between px-4 py-3 rounded-xl" style={{ background: C.bgSoft }}>
              <div>
                <p className="text-sm font-medium" style={{ color: C.text, fontFamily: "Inter" }}>{f.mes}</p>
                <p className="text-xs" style={{ color: C.textFaint }}>Vencimento {f.vencimento} · {f.id}</p>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-sm font-semibold" style={{ fontFamily: "JetBrains Mono", color: C.text }}>R$ {f.valor.toFixed(2)}</span>
                <Badge status={f.status} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Síndico dashboard                                                        */
/* ---------------------------------------------------------------------- */
function SindicoDashboard({ moradores, setMoradores, notify }) {
  const [busca, setBusca] = useState("");
  const [enviando, setEnviando] = useState(null); // 'email' | 'whatsapp' | null
  const fileRef = useRef(null);

  const totalConsumo = moradores.reduce((s, m) => s + m.consumo[m.consumo.length - 1].kwh, 0);
  const totalAberto = moradores.reduce(
    (s, m) => s + m.faturas.filter((f) => f.status !== "paga").reduce((x, f) => x + f.valor, 0), 0
  );
  const inadimplentes = moradores.filter((m) => m.faturas.some((f) => f.status === "vencida"));

  const filtrados = useMemo(
    () => moradores.filter((m) => m.nome.toLowerCase().includes(busca.toLowerCase()) || m.unidade.toLowerCase().includes(busca.toLowerCase())),
    [moradores, busca]
  );

  const chartData = moradores.map((m) => ({ nome: m.nome.split(" ")[0], kwh: m.consumo[m.consumo.length - 1].kwh }));

  const importarExcel = useCallback((file) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const wb = XLSX.read(e.target.result, { type: "binary" });
        const sheet = wb.Sheets[wb.SheetNames[0]];
        const rows = XLSX.utils.sheet_to_json(sheet);
        if (!rows.length) {
          notify("A planilha não tem linhas para importar.");
          return;
        }
        setMoradores((prev) =>
          prev.map((m) => {
            const linha = rows.find(
              (r) => (r.CPF || r.cpf || "") === m.cpf || (r.Nome || r.nome || "").toLowerCase() === m.nome.toLowerCase()
            );
            if (!linha) return m;
            const novoConsumo = Number(linha["Consumo (kWh)"] ?? linha.Consumo ?? linha.kwh);
            if (!novoConsumo) return m;
            const consumo = [...m.consumo];
            consumo[consumo.length - 1] = { ...consumo[consumo.length - 1], kwh: novoConsumo };
            return { ...m, consumo };
          })
        );
        notify(`Planilha importada — ${rows.length} linha(s) processada(s) e consumo atualizado.`);
      } catch {
        notify("Não foi possível ler essa planilha. Verifique o formato (.xlsx ou .csv).");
      }
    };
    reader.readAsBinaryString(file);
  }, [notify, setMoradores]);

  const dispararEnvio = (canal) => {
    setEnviando(canal);
    setTimeout(() => {
      setEnviando(null);
      const alvo = inadimplentes.length || moradores.length;
      notify(
        canal === "email"
          ? `Cobrança por e-mail enviada para ${alvo} morador(es) com fatura pendente.`
          : `Lembrete por WhatsApp enviado para ${alvo} morador(es) com fatura pendente.`
      );
    }, 1400);
  };

  return (
    <div className="max-w-6xl">
      <header className="mb-8">
        <p className="text-xs uppercase tracking-wider mb-1" style={{ color: C.textFaint, fontFamily: "Inter" }}>Painel do síndico</p>
        <h1 className="text-2xl font-bold" style={{ fontFamily: "Space Grotesk", color: C.text }}>Visão geral do condomínio</h1>
      </header>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5 mb-6">
        <StatCard icon={Users} label="Moradores cadastrados" value={moradores.length} accent={C.blue} />
        <StatCard icon={Zap} label="Consumo total (mês)" value={`${totalConsumo} kWh`} accent={C.green} />
        <StatCard icon={FileSpreadsheet} label="Valor em aberto" value={`R$ ${totalAberto.toFixed(2)}`} accent={C.amber} />
        <StatCard icon={AlertTriangle} label="Inadimplentes" value={inadimplentes.length} accent={inadimplentes.length ? C.red : C.green} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 mb-6">
        <div className="lg:col-span-2 rounded-2xl p-6" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
          <h2 className="text-sm font-semibold mb-4" style={{ fontFamily: "Space Grotesk", color: C.text }}>Consumo por morador — mês atual</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData}>
              <CartesianGrid stroke={C.line} vertical={false} />
              <XAxis dataKey="nome" tick={{ fill: C.textFaint, fontSize: 11 }} axisLine={{ stroke: C.line }} tickLine={false} />
              <YAxis tick={{ fill: C.textFaint, fontSize: 11 }} axisLine={false} tickLine={false} unit=" kWh" width={56} />
              <Tooltip contentStyle={{ background: C.bgSoft, border: `1px solid ${C.line}`, borderRadius: 10, color: C.text, fontFamily: "Inter" }} />
              <Bar dataKey="kwh" fill={C.blue} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-2xl p-6 flex flex-col" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
          <h2 className="text-sm font-semibold mb-1" style={{ fontFamily: "Space Grotesk", color: C.text }}>Importar dados</h2>
          <p className="text-xs mb-4" style={{ color: C.textFaint, fontFamily: "Inter" }}>
            Planilha .xlsx/.csv com colunas Nome ou CPF e Consumo (kWh) atualiza o consumo do mês.
          </p>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            className="hidden"
            onChange={(e) => e.target.files[0] && importarExcel(e.target.files[0])}
          />
          <button
            onClick={() => fileRef.current?.click()}
            className="flex-1 flex flex-col items-center justify-center gap-2 rounded-xl py-6 border-2 border-dashed text-sm"
            style={{ borderColor: C.line, color: C.textMuted, fontFamily: "Inter" }}
          >
            <Upload size={20} color={C.blue} />
            Selecionar planilha
          </button>
        </div>
      </div>

      <div className="rounded-2xl p-6 mb-6" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <h2 className="text-sm font-semibold" style={{ fontFamily: "Space Grotesk", color: C.text }}>Cobrança automática</h2>
          <div className="flex gap-2">
            <ActionButton icon={Mail} label="Enviar por e-mail" busy={enviando === "email"} onClick={() => dispararEnvio("email")} color={C.blue} />
            <ActionButton icon={MessageCircle} label="Enviar por WhatsApp" busy={enviando === "whatsapp"} onClick={() => dispararEnvio("whatsapp")} color={C.green} />
          </div>
        </div>
        <p className="text-xs" style={{ color: C.textFaint, fontFamily: "Inter" }}>
          Envia cobrança para {inadimplentes.length || moradores.length} morador(es) com fatura pendente ou vencida. Neste protótipo o envio é simulado — em produção conectaria a um provedor de e-mail (ex: SendGrid) e à API do WhatsApp Business.
        </p>
      </div>

      <div className="rounded-2xl p-6" style={{ background: C.surface, border: `1px solid ${C.line}` }}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold" style={{ fontFamily: "Space Grotesk", color: C.text }}>Moradores</h2>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg" style={{ background: C.bgSoft, border: `1px solid ${C.line}` }}>
            <Search size={14} color={C.textFaint} />
            <input
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              placeholder="Buscar morador ou unidade"
              className="bg-transparent outline-none text-xs w-40"
              style={{ color: C.text, fontFamily: "Inter" }}
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm" style={{ fontFamily: "Inter" }}>
            <thead>
              <tr className="text-left" style={{ color: C.textFaint }}>
                <th className="pb-3 font-medium">Morador</th>
                <th className="pb-3 font-medium">Unidade</th>
                <th className="pb-3 font-medium">ID</th>
                <th className="pb-3 font-medium">Consumo (mês)</th>
                <th className="pb-3 font-medium">Situação</th>
              </tr>
            </thead>
            <tbody>
              {filtrados.map((m) => {
                const situacao = m.faturas.some((f) => f.status === "vencida") ? "vencida"
                  : m.faturas.some((f) => f.status === "aberta") ? "aberta" : "paga";
                return (
                  <tr key={m.id} style={{ borderTop: `1px solid ${C.line}` }}>
                    <td className="py-3" style={{ color: C.text }}>{m.nome}</td>
                    <td className="py-3" style={{ color: C.textMuted }}>{m.unidade}</td>
                    <td className="py-3" style={{ color: C.textFaint, fontFamily: "JetBrains Mono", fontSize: 12 }}>{m.id}</td>
                    <td className="py-3" style={{ color: C.textMuted }}>{m.consumo[m.consumo.length - 1].kwh} kWh</td>
                    <td className="py-3"><Badge status={situacao} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ActionButton({ icon: Icon, label, busy, onClick, color }) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-opacity"
      style={{ background: `${color}22`, color, fontFamily: "Inter", opacity: busy ? 0.7 : 1 }}
    >
      {busy ? <Loader2 size={14} className="animate-spin" /> : <Icon size={14} />}
      {busy ? "Enviando…" : label}
    </button>
  );
}

/* ---------------------------------------------------------------------- */
/* Root                                                                      */
/* ---------------------------------------------------------------------- */
export default function App() {
  const [screen, setScreen] = useState("login"); // login | cadastro | id | dashboard
  const [role, setRole] = useState(null); // 'morador' | 'sindico'
  const [contaGoogle, setContaGoogle] = useState(null);
  const [usuario, setUsuario] = useState(null);
  const [moradores, setMoradores] = useState(MORADORES_MOCK);
  const [toast, setToast] = useState(null);

  const notify = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4200);
  };

  const handleGoogleLogin = (conta) => {
    setContaGoogle(conta);
    setScreen("cadastro");
  };

  const handleCadastroConcluido = (dados) => {
    const novo = { ...dados, consumo: gerarConsumo(24, 8), faturas: gerarFaturas(9) };
    setUsuario(novo);
    setMoradores((prev) => [...prev, novo]);
    setRole("morador");
    setScreen("id");
    setTimeout(() => setScreen("dashboard"), 1800);
  };

  const handleSindicoLogin = () => setScreen("login-sindico");

  const handleSindicoAutenticado = () => {
    setRole("sindico");
    setScreen("dashboard");
  };

  const handleLogout = () => {
    setScreen("login");
    setRole(null);
    setUsuario(null);
    setContaGoogle(null);
  };

  return (
    <div style={{ fontFamily: "Inter, sans-serif" }}>
      <style>{FONTS}</style>

      {screen === "login" && <LoginScreen onGoogleLogin={handleGoogleLogin} onSindicoLogin={handleSindicoLogin} />}
      {screen === "login-sindico" && <SindicoLoginScreen onEntrar={handleSindicoAutenticado} onVoltar={() => setScreen("login")} />}
      {screen === "cadastro" && <CadastroScreen conta={contaGoogle} onConcluir={handleCadastroConcluido} onVoltar={() => setScreen("login")} />}
      {screen === "id" && <IDCard id={usuario.id} nome={usuario.nome} />}
      {screen === "dashboard" && role === "morador" && (
        <Shell role="morador" activeUser={usuario} onLogout={handleLogout}>
          <MoradorDashboard user={usuario} />
        </Shell>
      )}
      {screen === "dashboard" && role === "sindico" && (
        <Shell role="sindico" activeUser={null} onLogout={handleLogout}>
          <SindicoDashboard moradores={moradores} setMoradores={setMoradores} notify={notify} />
        </Shell>
      )}

      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
    </div>
  );
}
'@ | Set-Content -Path "$frontend/src/App.jsx" -Encoding UTF8

# ---------- package.json (com as libs que o dashboard usa) ----------
@'
{
  "name": "goodwe-chargeops-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "recharts": "^2.12.7",
    "lucide-react": "^0.441.0",
    "xlsx": "^0.18.5"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "vite": "^5.4.8",
    "tailwindcss": "^3.4.13",
    "postcss": "^8.4.47",
    "autoprefixer": "^10.4.20"
  }
}
'@ | Set-Content -Path "$frontend/package.json" -Encoding UTF8

# ---------- vite.config.js ----------
@'
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
  },
});
'@ | Set-Content -Path "$frontend/vite.config.js" -Encoding UTF8

# ---------- tailwind.config.js ----------
@'
/** @type {import("tailwindcss").Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};
'@ | Set-Content -Path "$frontend/tailwind.config.js" -Encoding UTF8

# ---------- postcss.config.js ----------
@'
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
'@ | Set-Content -Path "$frontend/postcss.config.js" -Encoding UTF8

# ---------- src/index.css ----------
@'
@tailwind base;
@tailwind components;
@tailwind utilities;
'@ | Set-Content -Path "$frontend/src/index.css" -Encoding UTF8

# ---------- src/main.jsx (agora importando o index.css) ----------
@'
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
'@ | Set-Content -Path "$frontend/src/main.jsx" -Encoding UTF8

Write-Host "Dashboard integrado com sucesso ao frontend!" -ForegroundColor Green
Write-Host "Proximo passo:" -ForegroundColor Cyan
Write-Host "  cd frontend" -ForegroundColor Cyan
Write-Host "  npm install" -ForegroundColor Cyan
Write-Host "  npm run dev" -ForegroundColor Cyan
