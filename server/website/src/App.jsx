import { useState, useEffect, useRef, useCallback, useMemo, useId } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

// ═══════════════════════════════════════════════════════════
// DESIGN TOKENS
// ═══════════════════════════════════════════════════════════
const C = {
  bg:"#080808", bg2:"#101010", bg3:"#181818",
  brd:"rgba(255,255,255,0.08)", brd2:"rgba(255,255,255,0.16)",
  t:"#E6E6E6", t2:"#A0A0A0", t3:"#707070",
  gold:"#C8C8C8", gold2:"#F0F0F0", goldBg:"rgba(200,200,200,0.08)", goldBrd:"rgba(255,255,255,0.16)",
  g:"#00D26A", gBg:"rgba(0,210,106,0.12)",
  r:"#FF4D4F", rBg:"rgba(255,77,79,0.12)",
  glass:"rgba(255,255,255,0.02)", glass2:"rgba(255,255,255,0.04)",
  panel:"rgba(14,14,14,0.88)", neon:"#C8C8C8", neonDeep:"#6A6A6A", cyan:"#A8A8A8",
};
const ADMIN_EMAIL = "admin@aurum.finance";

// ═══════════════════════════════════════════════════════════
// LOGO
// ═══════════════════════════════════════════════════════════
function Logo({ size = 24 }) {
  const uid = useId();
  const a = `la${uid}`, b = `lb${uid}`;
  return (
    <svg width={size} height={size} viewBox="0 0 160 160" fill="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id={a} x1="0" y1="0" x2=".7" y2="1">
          <stop offset="0%" stopColor="#F0F0F0" /><stop offset="100%" stopColor="#7A7A7A" />
        </linearGradient>
        <linearGradient id={b} x1="1" y1="0" x2=".2" y2="1">
          <stop offset="0%" stopColor="#C8C8C8" stopOpacity=".85" /><stop offset="100%" stopColor="#4A4A4A" stopOpacity=".6" />
        </linearGradient>
      </defs>
      <path d="M80 14 L42 142 L62 142 L72 104 L88 104 L98 142 L118 142 Z" fill={`url(#${a})`} />
      <path d="M80 14 L118 142 L98 142 L88 104 L80 58 Z" fill={`url(#${b})`} />
      <path d="M80 58 L68 104 L92 104 Z" fill={C.bg} />
    </svg>
  );
}

// ═══════════════════════════════════════════════════════════
// DATABASE
// ═══════════════════════════════════════════════════════════
const DB = {
  async load() {
    try { const raw = localStorage.getItem("aurum-fund"); return raw ? JSON.parse(raw) : DB.init(); }
    catch { return DB.init(); }
  },
  init() {
    return {
      users: {}, trades: DB.genTrades(),
      fund: { totalDeposited: 0, totalWithdrawn: 0, startDate: "2026-03-01" },
      eq: DB.genEq(),
    };
  },
  async save(data) { try { localStorage.setItem("aurum-fund", JSON.stringify(data)); } catch (e) { console.error(e); } },
  async reset() { localStorage.removeItem("aurum-fund"); },
  genEq() {
    const e = [{ d: 0, v: 10000 }]; let b = 10000, p = 10000;
    for (let d = 1; d <= 60; d++) {
      b += (Math.random() < .63 ? 1 : -1) * (Math.random() * 65 + 10) * (Math.random() * 2.5 + 1);
      p = Math.max(p, b);
      e.push({ d, v: Math.round(b * 100) / 100, dd: Math.round((p - b) / p * 10000) / 100 });
    }
    return e;
  },
  genTrades() {
    const sy = ["BTC", "ETH", "SOL", "BNB", "LINK", "INJ", "XRP", "SUI"];
    const sn = ["AZOTH", "HERMES", "MERCURIO"];
    return Array.from({ length: 30 }, (_, i) => {
      const w = Math.random() < .63;
      const d = new Date("2026-03-28"); d.setDate(d.getDate() - i);
      return {
        sym: sy[i % sy.length], s: sn[i % 3],
        pnl: Math.round((w ? Math.random() * 55 + 8 : -(Math.random() * 30 + 5)) * 100) / 100,
        date: d.toISOString().slice(0, 10), ts: Date.now() - i * 3600000,
      };
    });
  },
};

// ═══════════════════════════════════════════════════════════
// SHARED COMPONENTS
// ═══════════════════════════════════════════════════════════
function Fade({ children, delay = 0, y = 20 }) {
  const ref = useRef(null);
  const [v, setV] = useState(false);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const ob = new IntersectionObserver(([e]) => { if (e.isIntersecting) setV(true); }, { threshold: .1 });
    ob.observe(el); return () => ob.disconnect();
  }, []);
  return (
    <div ref={ref} style={{
      transform: v ? "translateY(0)" : `translateY(${y}px)`, opacity: v ? 1 : 0,
      transition: `all 0.8s cubic-bezier(0.16,1,0.3,1) ${delay}s`,
    }}>{children}</div>
  );
}

function ChartTip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: C.bg3, border: `1px solid ${C.brd2}`, borderRadius: 8, padding: "10px 16px" }}>
      <div style={{ fontSize: 10, color: C.t3, marginBottom: 4 }}>Day {label}</div>
      {payload.map((p, i) => (
        <div key={i} style={{ fontSize: 14, fontWeight: 600, color: p.dataKey === "dd" ? C.r : C.gold, fontFamily: "var(--fm)" }}>
          {p.dataKey === "dd" ? "" : "$"}{p.value?.toFixed(2)}{p.dataKey === "dd" ? "%" : ""}
        </div>
      ))}
    </div>
  );
}

function Counter({ to, prefix = "", suffix = "", color = C.t, size = 32 }) {
  const [v, setV] = useState(0);
  const ref = useRef(null);
  const [started, setStarted] = useState(false);
  const num = parseFloat(String(to).replace(/[^0-9.\-]/g, "")) || 0;
  const dec = String(to).includes(".") ? (String(to).split(".")[1]?.length || 0) : 0;

  useEffect(() => {
    const el = ref.current; if (!el) return;
    const ob = new IntersectionObserver(([e]) => { if (e.isIntersecting) setStarted(true); }, { threshold: .1 });
    ob.observe(el); return () => ob.disconnect();
  }, []);

  useEffect(() => {
    if (!started) return;
    let s = 0; const step = num / (1400 / 16);
    const id = setInterval(() => {
      s += step;
      if ((step > 0 && s >= num) || (step < 0 && s <= num)) { setV(num); clearInterval(id); } else setV(s);
    }, 16);
    return () => clearInterval(id);
  }, [started, num]);

  return (
    <span ref={ref} style={{ fontSize: size, fontWeight: 600, fontFamily: "var(--fm)", color, letterSpacing: "-0.02em" }}>
      {prefix}{v.toFixed(dec)}{suffix}
    </span>
  );
}

// ═══════════════════════════════════════════════════════════
// GEOMETRIC VISUALIZER (replaces Globe)
// ═══════════════════════════════════════════════════════════
function HexGrid() {
  return (
    <div style={{ position: "relative", width: "clamp(300px, 36vw, 440px)", aspectRatio: "1", flexShrink: 0 }}>
      {/* Ambient glow */}
      <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: "80%", height: "80%", borderRadius: "50%", background: `radial-gradient(circle, rgba(200,200,200,0.12) 0%, rgba(255,255,255,0.03) 45%, transparent 70%)` }} />

      <svg viewBox="0 0 400 400" style={{ width: "100%", height: "100%", animation: "float 8s ease infinite" }}>
        {/* Outer ring */}
        <circle cx="200" cy="200" r="180" fill="none" stroke={C.gold} strokeWidth="0.5" opacity="0.12" />
        <circle cx="200" cy="200" r="140" fill="none" stroke={C.gold} strokeWidth="0.4" opacity="0.08" strokeDasharray="4 8" />
        <circle cx="200" cy="200" r="100" fill="none" stroke="white" strokeWidth="0.3" opacity="0.06" />

        {/* Hexagon */}
        {[0, 1, 2, 3, 4, 5].map(i => {
          const a = (i * 60 - 90) * Math.PI / 180;
          const x = 200 + 150 * Math.cos(a), y = 200 + 150 * Math.sin(a);
          const nx = 200 + 150 * Math.cos(a + Math.PI / 3), ny = 200 + 150 * Math.sin(a + Math.PI / 3);
          return <g key={i}>
            <line x1={x} y1={y} x2={nx} y2={ny} stroke={C.gold} strokeWidth="0.6" opacity="0.15" />
            <line x1={x} y1={y} x2="200" y2="200" stroke={C.gold} strokeWidth="0.3" opacity="0.08" />
            <circle cx={x} cy={y} r="3" fill={C.gold} opacity="0.2" />
          </g>;
        })}

        {/* Inner triangle */}
        <polygon points="200,60 320,280 80,280" fill="none" stroke={C.gold} strokeWidth="0.5" opacity="0.1" />

        {/* Center */}
        <circle cx="200" cy="200" r="6" fill={C.gold} opacity="0.3" />
        <circle cx="200" cy="200" r="2" fill={C.gold2} opacity="0.8" />

        {/* Orbiting dots */}
        {[0, 120, 240].map((d, i) => {
          const a = (d - 90) * Math.PI / 180;
          return <circle key={i} cx={200 + 100 * Math.cos(a)} cy={200 + 100 * Math.sin(a)} r="2.5" fill={C.gold} opacity="0.4">
            <animate attributeName="opacity" values="0.15;0.5;0.15" dur={`${3 + i}s`} repeatCount="indefinite" />
          </circle>;
        })}

        {/* Data labels */}
        {[
          { x: 200, y: 54, label: "AZOTH" },
          { x: 330, y: 285, label: "HERMES" },
          { x: 70, y: 285, label: "MERCURIO" },
        ].map((l, i) => (
          <text key={i} x={l.x} y={l.y} textAnchor="middle" fill={C.gold} fontSize="9" fontFamily="var(--fm)" opacity="0.35" letterSpacing="2">{l.label}</text>
        ))}
      </svg>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// LANDING PAGE
// ═══════════════════════════════════════════════════════════
function Landing({ onEnter, lang }) {
  const t = lang === "pt";
  const eq = useMemo(() => DB.genEq(), []);
  const stratRef = useRef();
  const perfRef = useRef();
  const gid = useId();

  const engines = [
    { id: "AZOTH", name: "Systematic Momentum", color: "#C8C8C8", desc: t ? "Motor de momentum direcional com regime filter, scoring omega e sizing convexo. Opera em BULL e BEAR com sinais não-correlacionados." : "Directional momentum engine with regime filter, omega scoring and convex sizing. Operates in BULL and BEAR with uncorrelated signals." },
    { id: "HERMES", name: "Statistical Arbitrage", color: "#A8A8A8", desc: t ? "Arbitragem estatística delta-neutral de funding rates em 13 exchanges simultâneas. Captura spread sem exposição direcional." : "Delta-neutral statistical arbitrage of funding rates across 13 simultaneous exchanges. Captures spread without directional exposure." },
    { id: "MERCURIO", name: "Order Flow Analysis", color: "#8A8A8A", desc: t ? "Microestrutura e fluxo de ordens. Detecta divergências CVD, imbalance de volume e liquidações para antecipar movimentos." : "Microstructure and order flow. Detects CVD divergences, volume imbalance and liquidations to anticipate moves." },
  ];

  const stats = [
    { value: "22.1", suffix: "%", label: t ? "Retorno 90d" : "90d Return" },
    { value: "3.58", label: "Sharpe Ratio" },
    { value: "5.1", suffix: "%", label: t ? "Max Drawdown" : "Max Drawdown" },
    { value: "64.2", suffix: "%", label: "Win Rate" },
  ];

  return (
    <div>
      {/* ── HERO ─────────────────────────────── */}
      <section style={{ minHeight: "100vh", display: "flex", alignItems: "center", position: "relative", overflow: "hidden" }}>
        <div className="orb orb-gold" style={{ top: "-10%", right: "-5%" }} />
        <div className="orb orb-white" style={{ bottom: "-20%", left: "-10%" }} />
        <div className="container">
          <div className="hero-flex" style={{ display: "flex", alignItems: "center", gap: "clamp(40px, 6vw, 80px)" }}>
            <div style={{ flex: "1 1 420px" }}>
              <Fade>
                <div className="badge" style={{ marginBottom: 28 }}>
                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: C.g, boxShadow: `0 0 12px ${C.g}` }} />
                  {t ? "OPERANDO 24/7" : "LIVE 24/7"}
                </div>
              </Fade>

              <Fade delay={0.1}>
                <h1 style={{ fontSize: "clamp(36px, 5.5vw, 62px)", fontFamily: "var(--fd)", fontWeight: 400, lineHeight: 1.1, marginBottom: 24, letterSpacing: "-0.02em" }}>
                  {t ? "Capital gerido por " : "Capital managed by "}
                  <span style={{ fontStyle: "italic", color: C.gold }}>{t ? "inteligência quantitativa" : "quantitative intelligence"}</span>
                </h1>
              </Fade>

              <Fade delay={0.2}>
                <p style={{ fontSize: 16, lineHeight: 1.8, color: C.t2, maxWidth: 480, marginBottom: 36 }}>
                  {t
                    ? "Três engines não-correlacionados executam 24/7 em crypto futures. Deposite via crypto, PIX ou Binance."
                    : "Three uncorrelated engines execute 24/7 across crypto futures. Deposit via crypto, PIX or Binance."}
                </p>
              </Fade>

              <Fade delay={0.3}>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 48 }}>
                  <button onClick={onEnter} className="btn-primary">{t ? "Acessar Plataforma" : "Access Platform"} <span style={{ fontSize: 16 }}>&rarr;</span></button>
                  <button onClick={() => stratRef.current?.scrollIntoView({ behavior: "smooth" })} className="btn-secondary">
                    {t ? "Ver Estrategias" : "View Strategies"}
                  </button>
                </div>
              </Fade>

              <Fade delay={0.4}>
                <div className="stats-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 24 }}>
                  {stats.map((s, i) => (
                    <div key={i}>
                      <Counter to={s.value} suffix={s.suffix || ""} color={i === 0 ? C.gold : C.t} size={24} />
                      <div style={{ fontSize: 11, color: C.t3, marginTop: 4, letterSpacing: 0.5 }}>{s.label}</div>
                    </div>
                  ))}
                </div>
              </Fade>
            </div>

            <Fade delay={0.2} y={0}>
              <HexGrid />
            </Fade>
          </div>
        </div>
      </section>

      {/* ── STRATEGIES ─────────────────────────── */}
      <div className="section-line" />
      <section ref={stratRef} className="section">
        <div className="container">
          <Fade>
            <div className="badge" style={{ marginBottom: 12 }}>{t ? "ESTRATEGIAS" : "STRATEGIES"}</div>
            <h2 style={{ fontSize: "clamp(28px, 3.5vw, 42px)", fontFamily: "var(--fd)", fontWeight: 400, marginBottom: 48, lineHeight: 1.2 }}>
              {t ? "Tres engines, " : "Three engines, "}
              <span style={{ fontStyle: "italic", color: C.gold }}>{t ? "zero correlacao" : "zero correlation"}</span>
            </h2>
          </Fade>

          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {engines.map((e, i) => (
              <Fade key={i} delay={i * 0.08}>
                <div className="glass" style={{ padding: "28px 28px", display: "flex", gap: 20, alignItems: "flex-start", transition: "all 0.3s", cursor: "default" }}>
                  <div style={{ width: 3, height: 48, borderRadius: 2, background: e.color, flexShrink: 0, boxShadow: `0 0 16px ${e.color}30` }} />
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
                      <span className="mono" style={{ fontSize: 10, color: e.color, fontWeight: 600, background: `${e.color}10`, padding: "3px 10px", borderRadius: 4, letterSpacing: 1 }}>{e.id}</span>
                      <span style={{ fontSize: 15, fontWeight: 600 }}>{e.name}</span>
                    </div>
                    <p style={{ fontSize: 13, color: C.t2, lineHeight: 1.8 }}>{e.desc}</p>
                  </div>
                </div>
              </Fade>
            ))}
          </div>
        </div>
      </section>

      {/* ── PERFORMANCE ─────────────────────────── */}
      <div className="section-line" />
      <section ref={perfRef} className="section">
        <div className="container">
          <Fade>
            <div className="badge" style={{ marginBottom: 12 }}>PERFORMANCE</div>
            <h2 style={{ fontSize: "clamp(28px, 3.5vw, 42px)", fontFamily: "var(--fd)", fontWeight: 400, marginBottom: 48, lineHeight: 1.2 }}>
              {t ? "Resultados " : "Results "}
              <span style={{ fontStyle: "italic", color: C.gold }}>{t ? "auditados" : "audited"}</span>
            </h2>
          </Fade>

          <Fade delay={0.1}>
            <div className="glass" style={{ padding: 28, position: "relative", overflow: "hidden" }}>
              {/* Glow line effect */}
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, overflow: "hidden" }}>
                <div style={{ position: "absolute", width: "30%", height: "100%", background: `linear-gradient(to right, transparent, ${C.gold}40, transparent)`, animation: "glow-line 4s ease infinite" }} />
              </div>

              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20, flexWrap: "wrap", gap: 16 }}>
                {[
                  { l: t ? "Retorno Total" : "Total Return", v: "+22.1%", c: C.g },
                  { l: "Sharpe", v: "3.58", c: C.t },
                  { l: "Sortino", v: "5.18", c: C.t },
                  { l: "Max DD", v: "-5.1%", c: C.r },
                  { l: "Win Rate", v: "64.2%", c: C.gold },
                ].map((m, i) => (
                  <div key={i} style={{ textAlign: "center" }}>
                    <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: m.c }}>{m.v}</div>
                    <div style={{ fontSize: 10, color: C.t3, marginTop: 2, letterSpacing: 0.5 }}>{m.l}</div>
                  </div>
                ))}
              </div>

              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={eq}>
                  <defs>
                    <linearGradient id={`eg${gid}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={C.gold} stopOpacity={0.12} />
                      <stop offset="100%" stopColor={C.gold} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="d" tick={{ fill: C.t3, fontSize: 10, fontFamily: "var(--fm)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: C.t3, fontSize: 10, fontFamily: "var(--fm)" }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                  <Tooltip content={<ChartTip />} />
                  <Area type="monotone" dataKey="v" stroke={C.gold} strokeWidth={1.5} fill={`url(#eg${gid})`} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </Fade>

          <Fade delay={0.2}>
            <div style={{ textAlign: "center", marginTop: 48 }}>
              <button onClick={onEnter} className="btn-gold" style={{ padding: "16px 48px", fontSize: 14 }}>
                {t ? "Comecar a Investir" : "Start Investing"} <span style={{ fontSize: 18 }}>&rarr;</span>
              </button>
              <p style={{ fontSize: 11, color: C.t3, marginTop: 16 }}>
                {t ? "Performance passada nao garante resultados futuros" : "Past performance does not guarantee future results"}
              </p>
            </div>
          </Fade>
        </div>
      </section>

      {/* ── FOOTER ─────────────────────────── */}
      <div className="section-line" />
      <footer style={{ padding: "40px 0" }}>
        <div className="container" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Logo size={20} />
            <span style={{ fontSize: 12, fontWeight: 600, letterSpacing: 3 }}>AURUM</span>
          </div>
          <div style={{ display: "flex", gap: 28 }}>
            {[t ? "Estrategias" : "Strategies", t ? "Performance" : "Performance", "API", "Docs"].map((l, i) => (
              <span key={i} style={{ fontSize: 12, color: C.t3, cursor: "pointer", transition: "color 0.2s" }}
                onMouseEnter={e => e.target.style.color = C.t} onMouseLeave={e => e.target.style.color = C.t3}>{l}</span>
            ))}
          </div>
          <span style={{ fontSize: 10, color: C.t3 }}>&copy; 2026 AURUM Finance</span>
        </div>
      </footer>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// AUTH
// ═══════════════════════════════════════════════════════════
function Auth({ onAuth, lang }) {
  const t = lang === "pt";
  const [mode, setMode] = useState("email");
  const [email, setEmail] = useState("");
  const [pass, setPass] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [isReg, setIsReg] = useState(false);

  const wallets = [
    { n: "MetaMask", icon: "M", color: "#f6851b" },
    { n: "Rabby", icon: "R", color: "#7c5cfc" },
    { n: "WalletConnect", icon: "W", color: "#3b99fc" },
  ];

  const doLogin = async () => {
    if (!email) return; setLoading(true);
    const db = await DB.load();
    const uid = email.toLowerCase().replace(/[^a-z0-9]/g, "_");
    const isAdmin = email.toLowerCase() === ADMIN_EMAIL;
    if (!db.users[uid] && isReg) {
      db.users[uid] = { email, name: name || email.split("@")[0], balance: 0, deposits: [], withdrawals: [], pnl: 0, joinedAt: new Date().toISOString() };
      await DB.save(db);
    }
    const user = db.users[uid];
    if (!user && !isAdmin) { setLoading(false); setIsReg(true); return; }
    setLoading(false); onAuth({ uid, email, isAdmin, ...(user || { name: "Admin" }) });
  };

  const doWallet = async (w) => {
    setLoading(true);
    setTimeout(async () => {
      const db = await DB.load();
      const uid = "wallet_" + Date.now();
      db.users[uid] = { email: w, name: w + " User", balance: 0, deposits: [], withdrawals: [], pnl: 0, joinedAt: new Date().toISOString() };
      await DB.save(db);
      setLoading(false); onAuth({ uid, email: w, isAdmin: false, ...db.users[uid] });
    }, 1000);
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}>
      <Fade>
        <div style={{ width: "100%", maxWidth: 400 }}>
          <div style={{ textAlign: "center", marginBottom: 32 }}>
            <div style={{ display: "inline-block", marginBottom: 16 }}><Logo size={48} /></div>
            <h2 style={{ fontSize: 24, fontFamily: "var(--fd)", fontWeight: 400 }}>
              {isReg ? (t ? "Criar conta" : "Create account") : (t ? "Entrar" : "Sign in")}
            </h2>
            <p style={{ fontSize: 13, color: C.t3, marginTop: 6 }}>
              {t ? "Acesse sua conta AURUM Finance" : "Access your AURUM Finance account"}
            </p>
          </div>

          {/* Mode toggle */}
          <div style={{ display: "flex", background: C.bg2, borderRadius: 8, padding: 3, marginBottom: 20, border: `1px solid ${C.brd}` }}>
            {[["email", "Email"], ["wallet", "Wallet"]].map(([k, l]) => (
              <button key={k} onClick={() => setMode(k)} style={{
                flex: 1, padding: 10, borderRadius: 6, border: "none", cursor: "pointer",
                fontSize: 12, fontWeight: 600, letterSpacing: 0.5, fontFamily: "var(--f)",
                background: mode === k ? C.bg3 : "transparent", color: mode === k ? C.t : C.t3,
                transition: "all 0.2s",
              }}>{l}</button>
            ))}
          </div>

          {mode === "email" ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {isReg && <input className="input" placeholder={t ? "Nome completo" : "Full name"} value={name} onChange={e => setName(e.target.value)} />}
              <input className="input" type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} />
              <input className="input" type="password" placeholder={t ? "Senha" : "Password"} value={pass} onChange={e => setPass(e.target.value)} />
              <button onClick={doLogin} className="btn-primary" style={{ width: "100%", justifyContent: "center", marginTop: 4 }} disabled={loading}>
                {loading ? "..." : isReg ? (t ? "Criar Conta" : "Create Account") : (t ? "Entrar" : "Sign In")}
              </button>
              <div style={{ textAlign: "center", marginTop: 8, fontSize: 12, color: C.t3 }}>
                {isReg ? (t ? "Ja tem conta? " : "Have an account? ") : (t ? "Nao tem conta? " : "No account? ")}
                <button onClick={() => setIsReg(!isReg)} style={{ background: "none", border: "none", color: C.gold, cursor: "pointer", fontFamily: "var(--f)", fontSize: 12 }}>
                  {isReg ? (t ? "Entrar" : "Sign in") : (t ? "Criar conta" : "Create account")}
                </button>
              </div>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {wallets.map(w => (
                <button key={w.n} onClick={() => doWallet(w.n)} disabled={loading}
                  className="glass" style={{ display: "flex", alignItems: "center", gap: 14, padding: "16px 18px", cursor: "pointer", color: C.t, fontFamily: "var(--f)", fontSize: 14, transition: "all 0.3s" }}>
                  <div style={{ width: 36, height: 36, borderRadius: 8, background: `${w.color}15`, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, color: w.color, fontSize: 14 }}>{w.icon}</div>
                  <span style={{ flex: 1, textAlign: "left", fontWeight: 500 }}>{w.n}</span>
                  <span style={{ color: C.t3, fontSize: 18 }}>&rsaquo;</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </Fade>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// MEMBER DASHBOARD
// ═══════════════════════════════════════════════════════════
function MemberDash({ user, db, setDb, onLogout, lang }) {
  const t = lang === "pt";
  const [tab, setTab] = useState("ov");
  const [dmod, setDmod] = useState(null);
  const [amt, setAmt] = useState("");
  const u = db.users[user.uid] || { balance: 0, deposits: [], withdrawals: [], pnl: 0 };
  const eq = db.eq || []; const trades = db.trades || [];
  const pnlPct = u.balance > 0 ? Math.round(u.pnl / u.balance * 10000) / 100 : 0;
  const gid = useId();

  const doDeposit = async (method) => {
    const a = parseFloat(amt); if (!a || a <= 0) return;
    const ndb = { ...db, users: { ...db.users, [user.uid]: { ...u, balance: u.balance + a, deposits: [...u.deposits, { amount: a, method, date: new Date().toISOString(), status: "confirmed" }] } } };
    await DB.save(ndb); setDb(ndb); setAmt(""); setDmod(null);
  };
  const doWithdraw = async () => {
    const a = parseFloat(amt); if (!a || a <= 0 || a > u.balance) return;
    const ndb = { ...db, users: { ...db.users, [user.uid]: { ...u, balance: u.balance - a, withdrawals: [...u.withdrawals, { amount: a, date: new Date().toISOString(), status: "pending" }] } } };
    await DB.save(ndb); setDb(ndb); setAmt(""); setDmod(null);
  };

  const tabs = t ? ["Portfolio", "Depositar", "Sacar", "Trades"] : ["Portfolio", "Deposit", "Withdraw", "Trades"];
  const tabKeys = ["ov", "dep", "wd", "tr"];

  return (
    <div>
      <div className="tab-bar" style={{ padding: "0 20px" }}>
        {tabs.map((l, i) => <button key={i} onClick={() => setTab(tabKeys[i])} className={`tab ${tab === tabKeys[i] ? "active" : ""}`}>{l}</button>)}
      </div>

      {/* Modal */}
      {dmod && (
        <div style={{ position: "fixed", inset: 0, zIndex: 300, background: "rgba(8,8,8,0.92)", backdropFilter: "blur(24px)", display: "flex", alignItems: "center", justifyContent: "center" }} onClick={e => { if (e.target === e.currentTarget) setDmod(null); }}>
          <div className="glass" style={{ padding: 32, maxWidth: 400, width: "100%", margin: 16, position: "relative" }}>
            <button onClick={() => setDmod(null)} style={{ position: "absolute", top: 14, right: 16, background: "none", border: "none", color: C.t3, cursor: "pointer", fontSize: 18 }}>&times;</button>
            <div className="badge" style={{ marginBottom: 16 }}>{dmod === "withdraw" ? (t ? "SACAR" : "WITHDRAW") : dmod.toUpperCase()}</div>
            <input className="input mono" type="number" placeholder={t ? "Valor em USD" : "Amount in USD"} value={amt} onChange={e => setAmt(e.target.value)} style={{ fontSize: 20, textAlign: "center", marginBottom: 12 }} />
            {dmod === "withdraw" ?
              <button onClick={doWithdraw} className="btn-primary" style={{ width: "100%", justifyContent: "center" }}>{t ? "Confirmar Saque" : "Confirm Withdrawal"}</button>
              : <button onClick={() => doDeposit(dmod)} className="btn-gold" style={{ width: "100%", justifyContent: "center" }}>{t ? "Confirmar Deposito" : "Confirm Deposit"}</button>}
          </div>
        </div>
      )}

      <div style={{ padding: 24, maxWidth: 1000, margin: "0 auto" }}>
        {tab === "ov" && (
          <div>
            {/* Balance card */}
            <div className="glass" style={{ padding: 28, marginBottom: 16, position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", top: 0, right: 0, width: 200, height: 200, background: `radial-gradient(circle, ${C.goldBg}, transparent)`, pointerEvents: "none" }} />
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <div style={{ width: 7, height: 7, borderRadius: "50%", background: C.g, boxShadow: `0 0 10px ${C.g}` }} />
                <span style={{ fontSize: 11, color: C.t3, letterSpacing: 2, fontWeight: 600 }}>LIVE</span>
              </div>
              <div className="mono" style={{ fontSize: 38, fontWeight: 600, letterSpacing: "-0.03em", marginBottom: 6 }}>
                ${u.balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
              <span className="mono" style={{ fontSize: 14, fontWeight: 600, color: u.pnl >= 0 ? C.g : C.r }}>
                {u.pnl >= 0 ? "+" : ""}${u.pnl.toFixed(2)} ({pnlPct}%)
              </span>
            </div>

            {/* Deposit options */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 16 }}>
              {[
                { k: "crypto", label: "Crypto", sub: "USDT / USDC" },
                { k: "pix", label: "PIX", sub: "BRL" },
                { k: "binance", label: "Binance", sub: "Zero fee" },
              ].map(d => (
                <button key={d.k} onClick={() => setDmod(d.k)} className="glass" style={{ padding: "18px 12px", cursor: "pointer", textAlign: "center", color: C.t, fontFamily: "var(--f)", transition: "all 0.3s" }}>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>{d.label}</div>
                  <div style={{ fontSize: 10, color: C.t3 }}>{d.sub}</div>
                </button>
              ))}
            </div>

            <button onClick={() => setDmod("withdraw")} className="glass" style={{ width: "100%", padding: 14, textAlign: "center", cursor: "pointer", color: C.r, fontWeight: 600, fontSize: 12, fontFamily: "var(--f)", marginBottom: 16, transition: "all 0.3s" }}>
              {t ? "Solicitar Saque" : "Request Withdrawal"}
            </button>

            {/* Equity chart */}
            <div className="glass" style={{ padding: 20 }}>
              <div style={{ fontSize: 10, color: C.t3, letterSpacing: 2, fontWeight: 600, marginBottom: 12 }}>EQUITY CURVE</div>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={eq}>
                  <defs><linearGradient id={`me${gid}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={C.gold} stopOpacity={0.1} /><stop offset="100%" stopColor={C.gold} stopOpacity={0} /></linearGradient></defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" />
                  <XAxis dataKey="d" tick={{ fill: C.t3, fontSize: 9, fontFamily: "var(--fm)" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: C.t3, fontSize: 9, fontFamily: "var(--fm)" }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                  <Tooltip content={<ChartTip />} />
                  <Area type="monotone" dataKey="v" stroke={C.gold} strokeWidth={1.5} fill={`url(#me${gid})`} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {tab === "dep" && (
          <div>
            {[
              { k: "crypto", label: "Crypto", desc: "USDT, USDC, BTC, ETH", color: "#3b99fc" },
              { k: "pix", label: "PIX", desc: t ? "Reais via PIX" : "BRL via PIX", color: "#32bcad" },
              { k: "binance", label: "Binance Pay", desc: t ? "Taxa zero" : "Zero fee", color: "#f0b90b" },
            ].map(d => (
              <button key={d.k} onClick={() => setDmod(d.k)} className="glass" style={{ display: "flex", alignItems: "center", gap: 16, padding: 20, cursor: "pointer", color: C.t, fontFamily: "var(--f)", width: "100%", marginBottom: 10, transition: "all 0.3s" }}>
                <div style={{ width: 40, height: 40, borderRadius: 10, background: `${d.color}12`, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, color: d.color, fontSize: 15 }}>{d.label[0]}</div>
                <div style={{ flex: 1, textAlign: "left" }}>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>{d.label}</div>
                  <div style={{ fontSize: 12, color: C.t3 }}>{d.desc}</div>
                </div>
                <span style={{ color: C.t3, fontSize: 20 }}>&rsaquo;</span>
              </button>
            ))}
          </div>
        )}

        {tab === "wd" && (
          <div className="glass" style={{ padding: 28, textAlign: "center" }}>
            <div style={{ fontSize: 11, color: C.t3, letterSpacing: 2, fontWeight: 600, marginBottom: 16 }}>{t ? "SALDO DISPONIVEL" : "AVAILABLE BALANCE"}</div>
            <div className="mono" style={{ fontSize: 36, fontWeight: 600, marginBottom: 20 }}>${u.balance.toFixed(2)}</div>
            <input className="input mono" type="number" placeholder={t ? "Valor" : "Amount"} value={amt} onChange={e => setAmt(e.target.value)} style={{ textAlign: "center", fontSize: 18, marginBottom: 12 }} />
            <button onClick={doWithdraw} className="btn-primary" style={{ width: "100%", justifyContent: "center" }}>{t ? "Sacar" : "Withdraw"}</button>
          </div>
        )}

        {tab === "tr" && (
          <div className="glass" style={{ overflow: "hidden" }}>
            <div style={{ padding: "12px 18px", fontSize: 10, color: C.t3, letterSpacing: 2, fontWeight: 600, borderBottom: `1px solid ${C.brd}` }}>{t ? "HISTORICO" : "HISTORY"}</div>
            {trades.slice(0, 25).map((tr, i) => (
              <div key={i} className="row-hover" style={{ display: "flex", alignItems: "center", padding: "10px 18px", borderBottom: `1px solid ${C.brd}`, fontSize: 12, gap: 8 }}>
                <span className="mono" style={{ flex: "0 0 70px", color: C.t3, fontSize: 10 }}>{tr.date}</span>
                <span className="mono" style={{ flex: "0 0 48px", fontWeight: 600 }}>{tr.sym}</span>
                <span style={{ flex: "0 0 80px" }}>
                  <span className="mono" style={{
                    fontSize: 9, fontWeight: 600, padding: "3px 8px", borderRadius: 4, letterSpacing: 0.5,
                    background: tr.s === "AZOTH" ? "rgba(200,200,200,0.12)" : tr.s === "HERMES" ? "rgba(168,168,168,0.12)" : "rgba(138,138,138,0.12)",
                    color: tr.s === "AZOTH" ? "#C8C8C8" : tr.s === "HERMES" ? "#A8A8A8" : "#8A8A8A",
                  }}>{tr.s}</span>
                </span>
                <span style={{ flex: 1 }} />
                <span className="mono" style={{ fontWeight: 600, color: tr.pnl >= 0 ? C.g : C.r }}>{tr.pnl >= 0 ? "+" : ""}{tr.pnl.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// ADMIN DASHBOARD
// ═══════════════════════════════════════════════════════════
function AdminDash({ db, setDb, onLogout, lang }) {
  const t = lang === "pt";
  const [tab, setTab] = useState("ov");
  const users = Object.entries(db.users || {});
  const totalAUM = users.reduce((a, [, u]) => a + u.balance, 0);
  const totalDeps = users.reduce((a, [, u]) => a + (u.deposits || []).reduce((b, d) => b + d.amount, 0), 0);
  const totalWds = users.reduce((a, [, u]) => a + (u.withdrawals || []).reduce((b, w) => b + w.amount, 0), 0);
  const pending = users.flatMap(([uid, u]) => (u.withdrawals || []).filter(w => w.status === "pending").map(w => ({ ...w, uid, name: u.name })));
  const eq = db.eq || []; const trades = db.trades || [];
  const gid = useId();

  const approveWd = async (uid, idx) => {
    const u = { ...db.users[uid] }; u.withdrawals = [...u.withdrawals]; u.withdrawals[idx] = { ...u.withdrawals[idx], status: "confirmed" };
    const ndb = { ...db, users: { ...db.users, [uid]: u } }; await DB.save(ndb); setDb(ndb);
  };
  const resetAll = async () => { await DB.reset(); setDb(DB.init()); };

  const adminTabs = t ? ["Visao Geral", "Membros", "Trades", "Config"] : ["Overview", "Members", "Trades", "Config"];
  const tabKeys = ["ov", "mb", "tr", "cfg"];

  return (
    <div>
      <div className="tab-bar" style={{ padding: "0 20px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginRight: 12 }}>
          <span style={{ fontSize: 9, color: C.r, background: C.rBg, padding: "3px 10px", borderRadius: 4, fontWeight: 700, letterSpacing: 1 }}>ADMIN</span>
        </div>
        {adminTabs.map((l, i) => <button key={i} onClick={() => setTab(tabKeys[i])} className={`tab ${tab === tabKeys[i] ? "active" : ""}`}>{l}</button>)}
      </div>

      <div style={{ padding: 24, maxWidth: 1000, margin: "0 auto" }}>
        {tab === "ov" && (
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
              {[
                [t ? "AUM Total" : "Total AUM", `$${totalAUM.toFixed(0)}`, C.gold],
                [t ? "Membros" : "Members", users.length, C.t],
                [t ? "Depositos" : "Deposits", `$${totalDeps.toFixed(0)}`, C.g],
                [t ? "Saques" : "Withdrawals", `$${totalWds.toFixed(0)}`, C.r],
              ].map(([l, v, c], i) => (
                <div key={i} className="glass" style={{ padding: 18 }}>
                  <div style={{ fontSize: 10, color: C.t3, letterSpacing: 1.5, marginBottom: 6, fontWeight: 600 }}>{l}</div>
                  <div className="mono" style={{ fontSize: 22, fontWeight: 600, color: c }}>{v}</div>
                </div>
              ))}
            </div>

            {pending.length > 0 && (
              <div className="glass" style={{ marginBottom: 20, overflow: "hidden" }}>
                <div style={{ padding: "12px 18px", fontSize: 10, color: C.r, letterSpacing: 2, fontWeight: 600, borderBottom: `1px solid ${C.brd}` }}>
                  {t ? "SAQUES PENDENTES" : "PENDING WITHDRAWALS"} ({pending.length})
                </div>
                {pending.map((w, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", padding: "12px 18px", borderBottom: `1px solid ${C.brd}`, fontSize: 13, gap: 10 }}>
                    <span style={{ flex: 1, fontWeight: 500 }}>{w.name}</span>
                    <span className="mono" style={{ color: C.r }}>-${w.amount}</span>
                    <button onClick={() => { const uIdx = db.users[w.uid].withdrawals.findIndex(x => x.date === w.date && x.status === "pending"); if (uIdx >= 0) approveWd(w.uid, uIdx); }}
                      style={{ background: C.g, color: C.bg, border: "none", padding: "6px 14px", borderRadius: 6, fontSize: 11, fontWeight: 600, cursor: "pointer" }}>
                      {t ? "Aprovar" : "Approve"}
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="glass" style={{ padding: 20 }}>
              <div style={{ fontSize: 10, color: C.t3, letterSpacing: 2, fontWeight: 600, marginBottom: 12 }}>{t ? "EQUITY DO FUNDO" : "FUND EQUITY"}</div>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={eq}>
                  <defs><linearGradient id={`ae${gid}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={C.gold} stopOpacity={0.1} /><stop offset="100%" stopColor={C.gold} stopOpacity={0} /></linearGradient></defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.03)" />
                  <XAxis dataKey="d" tick={{ fill: C.t3, fontSize: 9 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: C.t3, fontSize: 9 }} axisLine={false} tickLine={false} domain={["auto", "auto"]} />
                  <Tooltip content={<ChartTip />} />
                  <Area type="monotone" dataKey="v" stroke={C.gold} strokeWidth={1.5} fill={`url(#ae${gid})`} dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {tab === "mb" && (
          <div className="glass" style={{ overflow: "hidden" }}>
            <div style={{ padding: "12px 18px", fontSize: 10, color: C.t3, letterSpacing: 2, fontWeight: 600, borderBottom: `1px solid ${C.brd}` }}>{t ? "MEMBROS" : "MEMBERS"} ({users.length})</div>
            {users.length === 0 ? (
              <div style={{ padding: 40, textAlign: "center", color: C.t3 }}>{t ? "Nenhum membro" : "No members"}</div>
            ) : users.map(([uid, u]) => (
              <div key={uid} className="row-hover" style={{ display: "flex", alignItems: "center", padding: "14px 18px", borderBottom: `1px solid ${C.brd}`, gap: 12 }}>
                <div style={{ width: 34, height: 34, borderRadius: "50%", background: C.glass2, border: `1px solid ${C.brd2}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 600, color: C.gold }}>
                  {(u.name || "?")[0].toUpperCase()}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 500, fontSize: 14 }}>{u.name}</div>
                  <div style={{ fontSize: 11, color: C.t3 }}>{u.email}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="mono" style={{ fontWeight: 600, fontSize: 14 }}>${u.balance.toFixed(2)}</div>
                  <div style={{ fontSize: 10, color: C.t3 }}>{(u.deposits || []).length}d / {(u.withdrawals || []).length}w</div>
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === "tr" && (
          <div className="glass" style={{ overflow: "hidden" }}>
            <div style={{ padding: "12px 18px", fontSize: 10, color: C.t3, letterSpacing: 2, fontWeight: 600, borderBottom: `1px solid ${C.brd}` }}>TRADES</div>
            {trades.slice(0, 30).map((tr, i) => (
              <div key={i} className="row-hover" style={{ display: "flex", alignItems: "center", padding: "10px 18px", borderBottom: `1px solid ${C.brd}`, fontSize: 12, gap: 8 }}>
                <span className="mono" style={{ flex: "0 0 70px", color: C.t3, fontSize: 10 }}>{tr.date}</span>
                <span className="mono" style={{ flex: "0 0 48px", fontWeight: 600 }}>{tr.sym}</span>
                <span style={{ flex: "0 0 80px" }}>
                  <span className="mono" style={{
                    fontSize: 9, fontWeight: 600, padding: "3px 8px", borderRadius: 4, letterSpacing: 0.5,
                    background: tr.s === "AZOTH" ? "rgba(200,200,200,0.12)" : tr.s === "HERMES" ? "rgba(168,168,168,0.12)" : "rgba(138,138,138,0.12)",
                    color: tr.s === "AZOTH" ? "#C8C8C8" : tr.s === "HERMES" ? "#A8A8A8" : "#8A8A8A",
                  }}>{tr.s}</span>
                </span>
                <span style={{ flex: 1 }} />
                <span className="mono" style={{ fontWeight: 600, color: tr.pnl >= 0 ? C.g : C.r }}>{tr.pnl >= 0 ? "+" : ""}{tr.pnl.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}

        {tab === "cfg" && (
          <div className="glass" style={{ padding: 28 }}>
            <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 16, fontFamily: "var(--fd)" }}>{t ? "Configuracoes" : "Settings"}</div>
            <button onClick={() => { if (window.confirm(t ? "Tem certeza? Isto apaga todos os dados." : "Are you sure? This will delete all data.")) resetAll(); }}
              style={{ background: C.rBg, color: C.r, border: `1px solid rgba(255,77,79,0.35)`, padding: "12px 24px", borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "var(--f)" }}>
              {t ? "Resetar Banco de Dados" : "Reset Database"}
            </button>
            <p style={{ fontSize: 11, color: C.t3, marginTop: 10 }}>{t ? "Remove todos os dados. Irreversivel." : "Removes all data. Irreversible."}</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════
export default function App() {
  const [page, setPage] = useState("land");
  const [lang, setLang] = useState("pt");
  const [user, setUser] = useState(null);
  const [db, setDb] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => { (async () => { const d = await DB.load(); setDb(d); setLoading(false); })(); }, []);
  useEffect(() => { document.documentElement.lang = lang === "pt" ? "pt-BR" : "en"; }, [lang]);
  useEffect(() => {
    const t = { land: "AURUM Finance", auth: lang === "pt" ? "Entrar — AURUM" : "Sign In — AURUM", member: "Dashboard — AURUM", admin: "Admin — AURUM" };
    document.title = t[page] || "AURUM Finance";
  }, [page, lang]);

  const handleAuth = async (u) => { const d = await DB.load(); setDb(d); setUser(u); setPage(u.isAdmin ? "admin" : "member"); };
  const handleLogout = () => { setUser(null); setPage("land"); };

  if (loading || !db) return (
    <div style={{ background: C.bg, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 20, height: 20, border: `2px solid ${C.brd}`, borderTop: `2px solid ${C.gold}`, borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
    </div>
  );

  return (
    <div style={{ background: C.bg, color: C.t, minHeight: "100vh", position: "relative" }}>
      {/* Grid background */}
      <div className="grid-bg" />

      {/* NAV */}
      <nav style={{
        position: "sticky", top: 0, zIndex: 100,
        background: "rgba(8,8,8,0.88)", backdropFilter: "blur(20px)",
        borderBottom: `1px solid rgba(255,255,255,0.08)`, boxShadow: "0 1px 24px rgba(0,0,0,0.35)", height: 56,
        display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 24px",
      }}>
        <div onClick={() => { if (!user) setPage("land"); }} style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 10 }}>
          <Logo size={24} />
          <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: 4 }}>AURUM</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {user && <span style={{ fontSize: 11, color: C.t3, marginRight: 4 }}>{user.name || user.email}</span>}
          {user ? (
            <button onClick={handleLogout} className="btn-secondary" style={{ padding: "7px 16px", fontSize: 11 }}>{lang === "pt" ? "Sair" : "Logout"}</button>
          ) : page === "land" ? (
            <button onClick={() => setPage("auth")} className="btn-primary" style={{ padding: "8px 20px", fontSize: 11 }}>{lang === "pt" ? "Entrar" : "Sign In"}</button>
          ) : null}
          <button onClick={() => setLang(lang === "en" ? "pt" : "en")} style={{
            background: C.glass2, border: `1px solid ${C.brd}`, color: C.t3, cursor: "pointer",
            padding: "5px 10px", borderRadius: 6, fontSize: 10, fontWeight: 600, fontFamily: "var(--f)", transition: "all 0.2s",
          }}>{lang === "en" ? "PT" : "EN"}</button>
        </div>
      </nav>

      {page === "land" && <Landing onEnter={() => setPage("auth")} lang={lang} />}
      {page === "auth" && <Auth onAuth={handleAuth} lang={lang} />}
      {page === "member" && user && <MemberDash user={user} db={db} setDb={setDb} onLogout={handleLogout} lang={lang} />}
      {page === "admin" && user && <AdminDash db={db} setDb={setDb} onLogout={handleLogout} lang={lang} />}
    </div>
  );
}
