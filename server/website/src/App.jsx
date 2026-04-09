import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

// ═══════════════════════════════════════
// DESIGN TOKENS
// ═══════════════════════════════════════
const C={gold:"#BF9B30",goldL:"#DEBD52",goldD:"#7D6522",goldBg:"#BF9B3010",bg:"#050608",c1:"#0B0D12",c2:"#10131A",c3:"#161A22",brd:"#1B1F28",brdL:"#282D3A",t:"#EAE7DE",td:"#585752",tm:"#94918A",g:"#3FA876",gBg:"#3FA87615",r:"#C4524C",rBg:"#C4524C15"};
const M="'JetBrains Mono',monospace";
const ADMIN_EMAIL="admin@aurum.finance";

// ═══════════════════════════════════════
// LOGO
// ═══════════════════════════════════════
function IngotLogo({size=24}){
  return <svg width={size} height={size} viewBox="0 0 160 160" fill="none" style={{display:"block"}}>
    <defs><linearGradient id="iga" x1="0" y1="0" x2=".7" y2="1"><stop offset="0%" stopColor="#E8CC5A"/><stop offset="100%" stopColor="#8A6E1F"/></linearGradient>
    <linearGradient id="igb" x1="1" y1="0" x2=".2" y2="1"><stop offset="0%" stopColor="#BF9B30" stopOpacity=".85"/><stop offset="100%" stopColor="#5C4A15" stopOpacity=".6"/></linearGradient></defs>
    <path d="M80 14 L42 142 L62 142 L72 104 L88 104 L98 142 L118 142 Z" fill="url(#iga)"/>
    <path d="M80 14 L118 142 L98 142 L88 104 L80 58 Z" fill="url(#igb)"/>
    <path d="M80 58 L68 104 L92 104 Z" fill={C.bg}/>
  </svg>;
}

// ═══════════════════════════════════════
// DATABASE (persistent storage)
// ═══════════════════════════════════════
const DB={
  async load(){
    try{const r=await window.storage.get("aurum-fund",true);return r?JSON.parse(r.value):DB.init();}
    catch{return DB.init();}
  },
  init(){return{users:{},trades:DB.genTrades(),fund:{totalDeposited:0,totalWithdrawn:0,startDate:"2026-03-01"},eq:DB.genEq()};},
  async save(data){try{await window.storage.set("aurum-fund",JSON.stringify(data),true);}catch(e){console.error("Save failed",e);}},
  async reset(){try{await window.storage.delete("aurum-fund",true);}catch{}},
  genEq(){const e=[{d:0,v:5000}];let b=5000,p=5000;for(let d=1;d<=45;d++){b+=(Math.random()<.63?1:-1)*(Math.random()*35+5)*(Math.random()*2.5+1);p=Math.max(p,b);e.push({d,v:Math.round(b*100)/100,dd:Math.round((p-b)/p*10000)/100});}return e;},
  genTrades(){const sy=["BTC","ETH","SOL","NATGAS","RED","CL","BEAT"],sn=["SM-1","SV-5D","FRC-13"];
    return Array.from({length:30},(_,i)=>{const w=Math.random()<.63;return{sym:sy[i%sy.length],s:sn[i%3],pnl:Math.round((w?Math.random()*40+5:-(Math.random()*25+3))*100)/100,date:`2026-03-${String(Math.max(1,45-i)).padStart(2,"0")}`,ts:Date.now()-i*3600000};});},
};

// ═══════════════════════════════════════
// SHARED COMPONENTS
// ═══════════════════════════════════════
function Tip({active,payload,label}){if(!active||!payload?.length)return null;
  return <div style={{background:C.c3,border:`1px solid ${C.goldD}40`,borderRadius:6,padding:"8px 14px"}}><div style={{fontSize:10,color:C.td}}>Day {label}</div>
    {payload.map((p,i)=><div key={i} style={{fontSize:13,fontWeight:600,color:p.dataKey==="dd"?C.r:C.gold,fontFamily:M}}>{p.dataKey==="dd"?"":"$"}{p.value?.toFixed(2)}{p.dataKey==="dd"?"%":""}</div>)}</div>;}

function useFadeIn(){const ref=useRef(null);const[v,setV]=useState(false);
  useEffect(()=>{const el=ref.current;if(!el)return;const ob=new IntersectionObserver(([e])=>{if(e.isIntersecting)setV(true);},{threshold:.1});ob.observe(el);return()=>ob.disconnect();},[]);return[ref,v];}
function Fade({children,delay=0,y=24}){const[ref,v]=useFadeIn();
  return <div ref={ref} style={{transform:v?`translateY(0)`:`translateY(${y}px)`,opacity:v?1:0,transition:`all .7s cubic-bezier(.16,1,.3,1) ${delay}s`}}>{children}</div>;}

function Ct({to,prefix="",suffix="",color=C.t,size=28}){
  const[v,setV]=useState(0);const num=parseFloat(String(to).replace(/[^0-9.\-]/g,""))||0;
  const dec=String(to).includes(".")?String(to).split(".")[1]?.length||0:0;
  useEffect(()=>{let s=0;const step=num/(1800/16);const id=setInterval(()=>{s+=step;if((step>0&&s>=num)||(step<0&&s<=num)){setV(num);clearInterval(id);}else setV(s);},16);return()=>clearInterval(id);},[num]);
  return <span style={{fontSize:size,fontWeight:600,fontFamily:M,color}}>{prefix}{v.toFixed(dec)}{suffix}</span>;}

function Globe(){
  const cx=50,cy=50,r1=42,vr=26;
  const hx=n=>[0,1,2,3,4,5].map(i=>{const a=(i*60-90)*Math.PI/180;return`${cx+n*Math.cos(a)},${cy+n*Math.sin(a)}`;});
  const vx=hx(r1);
  return <div style={{position:"relative",width:"clamp(280px,38vw,400px)",height:"clamp(280px,38vw,400px)",flexShrink:0}}>
    <style>{`@keyframes sp{from{transform:rotate(0)}to{transform:rotate(360deg)}}@keyframes gl{0%,100%{opacity:.25}50%{opacity:1}}@keyframes br{0%,100%{transform:scale(1);opacity:.8}50%{transform:scale(1.01);opacity:1}}.vo{position:absolute;border-radius:50%;top:50%;left:50%;transform:translate(-50%,-50%)}.vs1{animation:sp 50s linear infinite}.vs2{animation:sp 70s linear infinite reverse}.vd{position:absolute;width:5px;height:5px;border-radius:50%;background:${C.gold};animation:gl 4s ease infinite;box-shadow:0 0 10px ${C.gold}60}`}</style>
    <svg viewBox="0 0 100 100" style={{position:"absolute",inset:0,width:"100%",height:"100%",animation:"br 10s ease infinite"}}>
      <circle cx={cx} cy={cy} r="47" fill="none" stroke={C.gold} strokeWidth=".5" opacity=".22"/>
      <circle cx={cx} cy={cy} r="30" fill="none" stroke={C.gold} strokeWidth=".4" opacity=".16"/>
      <polygon points={`${vx[0]} ${vx[2]} ${vx[4]}`} fill="none" stroke={C.gold} strokeWidth=".7" opacity=".22"/>
      <polygon points={`${vx[1]} ${vx[3]} ${vx[5]}`} fill="none" stroke={C.gold} strokeWidth=".7" opacity=".22"/>
      <circle cx={cx} cy={cy-vr*.72} r="3" fill="none" stroke={C.gold} strokeWidth=".5" opacity=".2"/>
      <line x1={cx} y1={cy-vr*.56} x2={cx} y2={cy+vr*.18} stroke={C.gold} strokeWidth=".5" opacity=".16"/>
      <line x1={cx-vr*.72} y1={cy-vr*.18} x2={cx+vr*.72} y2={cy-vr*.18} stroke={C.gold} strokeWidth=".45" opacity=".15"/>
      <line x1={cx} y1={cy+vr*.18} x2={cx-vr*.44} y2={cy+vr*.78} stroke={C.gold} strokeWidth=".45" opacity=".15"/>
      <line x1={cx} y1={cy+vr*.18} x2={cx+vr*.44} y2={cy+vr*.78} stroke={C.gold} strokeWidth=".45" opacity=".15"/>
      {vx.map((p,i)=>{const[x,y]=p.split(",");return <circle key={i} cx={x} cy={y} r="1.5" fill={C.gold} opacity=".25"/>;})}
    </svg>
    <div className="vo vs1" style={{width:"94%",height:"94%"}}>{[0,45,90,135,180,225,270,315].map((d,i)=> <div key={i} className="vd" style={{top:`${50-47*Math.cos(d*Math.PI/180)}%`,left:`${50+47*Math.sin(d*Math.PI/180)}%`,animationDelay:`${i*.3}s`}}/>)}</div>
    <div className="vo vs2" style={{width:"60%",height:"60%"}}>{[30,150,270].map((d,i)=> <div key={i} className="vd" style={{top:`${50-47*Math.cos(d*Math.PI/180)}%`,left:`${50+47*Math.sin(d*Math.PI/180)}%`,width:4,height:4,background:C.goldD,animationDelay:`${i*.6}s`}}/>)}</div>
    <div style={{position:"absolute",top:"50%",left:"50%",transform:"translate(-50%,-50%)",width:8,height:8,borderRadius:"50%",background:C.gold,boxShadow:`0 0 24px ${C.gold}40, 0 0 60px ${C.gold}15`}}/>
  </div>;
}

// ═══════════════════════════════════════
// LANDING
// ═══════════════════════════════════════
function Landing({onEnter,lang}){
  const t=lang==="pt",eq=useMemo(()=>DB.genEq(),[]);
  const refs={s:useRef(),p:useRef()};

  return <div>
    <section style={{minHeight:"100vh",display:"flex",alignItems:"center",justifyContent:"center",padding:"60px 20px",position:"relative",overflow:"hidden"}}>
      <div style={{position:"absolute",top:"30%",left:"60%",width:600,height:600,background:`radial-gradient(circle,${C.gold}06 0%,transparent 70%)`,pointerEvents:"none"}}/>
      <div className="hf" style={{display:"flex",alignItems:"center",gap:"clamp(24px,5vw,64px)",maxWidth:1000,position:"relative",zIndex:1}}>
        <div style={{flex:"1 1 360px"}}>
          <Fade><div style={{display:"inline-flex",alignItems:"center",gap:8,background:C.goldBg,border:`1px solid ${C.gold}20`,borderRadius:20,padding:"6px 14px",marginBottom:20}}>
            <div style={{width:6,height:6,borderRadius:"50%",background:C.g,boxShadow:`0 0 8px ${C.g}`}}/>
            <span style={{fontSize:10,color:C.gold,fontWeight:600,letterSpacing:1.5}}>{t?"OPERANDO 24/7":"LIVE 24/7"}</span>
          </div></Fade>
          <Fade delay={.1}><h1 style={{fontSize:"clamp(28px,5vw,46px)",fontWeight:300,lineHeight:1.15,marginBottom:20}}>
            {t?"Seu capital operado por ":"Your capital managed by "}<br/>
            <span style={{fontWeight:500,background:`linear-gradient(135deg,${C.gold},${C.goldL})`,WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent"}}>{t?"inteligência quantitativa":"quantitative intelligence"}</span>
          </h1></Fade>
          <Fade delay={.2}><p style={{fontSize:14,lineHeight:1.9,color:C.tm,maxWidth:440,marginBottom:28}}>
            {t?"Deposite via crypto, PIX ou Binance. Três algoritmos não-correlacionados executam 24/7 em 13 exchanges globais.":"Deposit via crypto, PIX or Binance. Three uncorrelated algorithms execute 24/7 across 13 global exchanges."}
          </p></Fade>
          <Fade delay={.3}><div style={{display:"flex",gap:10,flexWrap:"wrap",marginBottom:32}}>
            <button onClick={onEnter} className="bp">{t?"ACESSAR PLATAFORMA":"ACCESS PLATFORM"}</button>
            <button onClick={()=>refs.s.current?.scrollIntoView({behavior:"smooth"})} className="bo">{t?"ESTRATÉGIAS":"STRATEGIES"}</button>
          </div></Fade>
          <Fade delay={.4}><div className="hs" style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:20}}>
            {(t?[["13","Exchanges"],["4.9k+","Pares"],["3","Engines"],["24/7","Live"]]:[["13","Exchanges"],["4.9k+","Pairs"],["3","Engines"],["24/7","Live"]]).map(([v,l],i)=>
              <div key={i}><Ct to={v} color={i===0?C.gold:C.t} size={20}/><br/><span style={{fontSize:9,color:C.td,letterSpacing:1}}>{l}</span></div>)}
          </div></Fade>
        </div>
        <Fade delay={.2} y={0}><Globe/></Fade>
      </div>
    </section>

    {/* STRATEGIES */}
    <section ref={refs.s} className="sec"><div className="wrap">
      <Fade><div className="tag">{t?"ESTRATÉGIAS":"STRATEGIES"}</div>
      <h2 className="h2">{t?"Três engines, ":"Three engines, "}<span>{t?"zero correlação":"zero correlation"}</span></h2></Fade>
      <div style={{display:"flex",flexDirection:"column",gap:10,marginTop:20}}>
        {[{id:"SM-1",n:"Systematic Momentum",c:"#7577D1",d:t?"Momentum direcional adaptativo com regime filter e sizing convexo.":"Adaptive directional momentum with regime filter and convex sizing."},
          {id:"SV-5D",n:"State Vector Model",c:"#C9A048",d:t?"Modelo de estado 5D com decomposição de forças e atualização Bayesiana.":"5D state model with force decomposition and Bayesian updating."},
          {id:"FRC-13",n:"Funding Rate Capture",c:"#5AAF7A",d:t?"Arbitragem delta-neutral de funding em 13 exchanges simultâneas.":"Delta-neutral funding arbitrage across 13 simultaneous exchanges."}
        ].map((e,i)=> <Fade key={i} delay={i*.08}><div className="hov-card card" style={{padding:20,display:"flex",gap:14,alignItems:"start"}}>
          <div style={{width:4,height:36,borderRadius:2,background:e.c,flexShrink:0,boxShadow:`0 0 10px ${e.c}40`}}/>
          <div><div style={{display:"flex",alignItems:"center",gap:8,marginBottom:4}}>
            <span style={{fontSize:9,fontFamily:M,color:e.c,fontWeight:600,background:`${e.c}12`,padding:"2px 7px",borderRadius:3}}>{e.id}</span>
            <span style={{fontSize:13,fontWeight:600}}>{e.n}</span></div>
            <p style={{fontSize:12,color:C.td,lineHeight:1.7}}>{e.d}</p></div>
        </div></Fade>)}
      </div>
    </div></section>

    {/* PERFORMANCE */}
    <section ref={refs.p} className="sec"><div className="wrap">
      <Fade><div className="tag">PERFORMANCE</div></Fade>
      <Fade delay={.1}><div className="card glow-card" style={{padding:20}}>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={eq}><defs><linearGradient id="gG" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={C.gold} stopOpacity={.15}/><stop offset="100%" stopColor={C.gold} stopOpacity={0}/></linearGradient></defs>
            <CartesianGrid strokeDasharray="3 3" stroke={C.brd}/><XAxis dataKey="d" tick={{fill:C.td,fontSize:9}} axisLine={false} tickLine={false}/>
            <YAxis tick={{fill:C.td,fontSize:9}} axisLine={false} tickLine={false} domain={["auto","auto"]}/>
            <Tooltip content={<Tip/>}/><Area type="monotone" dataKey="v" stroke={C.gold} strokeWidth={2} fill="url(#gG)" dot={false}/></AreaChart>
        </ResponsiveContainer>
      </div></Fade>
      <Fade delay={.2}><div style={{textAlign:"center",marginTop:28}}>
        <button onClick={onEnter} className="bp" style={{padding:"14px 40px"}}>{t?"COMEÇAR A INVESTIR":"START INVESTING"}</button>
      </div></Fade>
    </div></section>

    <footer style={{borderTop:`1px solid ${C.brd}`,padding:"24px 20px",marginTop:40}}>
      <div className="wrap" style={{display:"flex",justifyContent:"space-between",flexWrap:"wrap",gap:10}}>
        <span style={{fontSize:11,fontWeight:600,letterSpacing:3}}>AURUM</span>
        <span style={{fontSize:8,color:C.td}}>{t?"Performance passada não garante resultados futuros.":"Past performance does not guarantee future results."} © 2026</span>
      </div>
    </footer>
  </div>;
}

// ═══════════════════════════════════════
// AUTH
// ═══════════════════════════════════════
function Auth({onAuth,lang}){
  const t=lang==="pt";const[mode,setMode]=useState("email");const[email,setEmail]=useState("");const[pass,setPass]=useState("");const[loading,setLoading]=useState(false);const[name,setName]=useState("");const[isReg,setIsReg]=useState(false);
  const wallets=[{n:"MetaMask",i:"🦊"},{n:"Rabby",i:"🐰"},{n:"WalletConnect",i:"🔗"}];
  const doLogin=async()=>{if(!email)return;setLoading(true);const db=await DB.load();
    const uid=email.toLowerCase().replace(/[^a-z0-9]/g,"_");
    const isAdmin=email.toLowerCase()===ADMIN_EMAIL;
    if(!db.users[uid]&&isReg){db.users[uid]={email,name:name||email.split("@")[0],balance:0,deposits:[],withdrawals:[],pnl:0,joinedAt:new Date().toISOString()};await DB.save(db);}
    const user=db.users[uid];
    if(!user&&!isAdmin){setLoading(false);setIsReg(true);return;}
    setLoading(false);onAuth({uid,email,isAdmin,...(user||{name:"Admin"})});};
  const doWallet=async(w)=>{setLoading(true);setTimeout(async()=>{
    const db=await DB.load();const uid="wallet_"+Date.now();
    if(!db.users[uid]){db.users[uid]={email:w,name:w+" User",balance:0,deposits:[],withdrawals:[],pnl:0,joinedAt:new Date().toISOString()};await DB.save(db);}
    setLoading(false);onAuth({uid,email:w,isAdmin:false,...db.users[uid]});},1000);};

  return <div style={{minHeight:"100vh",display:"flex",alignItems:"center",justifyContent:"center",padding:20}}>
    <Fade><div style={{width:"100%",maxWidth:380}}>
      <div style={{textAlign:"center",marginBottom:24}}>
        <div style={{display:"inline-block",marginBottom:12}}><IngotLogo size={48}/></div>
        <h2 style={{fontSize:20,fontWeight:400}}>{isReg?(t?"Criar conta":"Create account"):(t?"Entrar":"Sign in")}</h2>
      </div>
      <div style={{display:"flex",background:C.c1,borderRadius:6,padding:3,marginBottom:16,border:`1px solid ${C.brd}`}}>
        {[["email","Email"],["wallet","Wallet"]].map(([k,l])=> <button key={k} onClick={()=>setMode(k)} style={{flex:1,padding:"9px",borderRadius:4,border:"none",cursor:"pointer",fontSize:11,fontWeight:600,letterSpacing:1,fontFamily:"var(--s)",background:mode===k?C.c3:"transparent",color:mode===k?C.t:C.td}}>{l}</button>)}
      </div>
      {mode==="email"?<div>
        {isReg&&<input className="inp" placeholder={t?"Nome completo":"Full name"} value={name} onChange={e=>setName(e.target.value)}/>}
        <input className="inp" type="email" placeholder="Email" value={email} onChange={e=>setEmail(e.target.value)}/>
        <input className="inp" type="password" placeholder={t?"Senha":"Password"} value={pass} onChange={e=>setPass(e.target.value)}/>
        <button onClick={doLogin} className="bp" style={{width:"100%",textAlign:"center"}} disabled={loading}>{loading?"...":(isReg?(t?"CRIAR CONTA":"CREATE ACCOUNT"):(t?"ENTRAR":"SIGN IN"))}</button>
        <div style={{textAlign:"center",marginTop:14,fontSize:11,color:C.td}}>
          {isReg?(t?"Já tem conta? ":"Have an account? "):(t?"Não tem conta? ":"No account? ")}
          <span onClick={()=>setIsReg(!isReg)} style={{color:C.gold,cursor:"pointer"}}>{isReg?(t?"Entrar":"Sign in"):(t?"Criar conta":"Create account")}</span>
        </div>

      </div>
      :<div style={{display:"flex",flexDirection:"column",gap:8}}>
        {wallets.map(w=> <button key={w.n} onClick={()=>doWallet(w.n)} disabled={loading} className="hov-card" style={{display:"flex",alignItems:"center",gap:12,padding:"14px 16px",background:C.c1,border:`1px solid ${C.brd}`,borderRadius:8,cursor:"pointer",color:C.t,fontSize:13,fontFamily:"var(--s)"}}>
          <span style={{fontSize:22}}>{w.i}</span><span style={{flex:1,textAlign:"left",fontWeight:500}}>{w.n}</span><span style={{color:C.td}}>›</span>
        </button>)}
      </div>}
    </div></Fade>
  </div>;
}

// ═══════════════════════════════════════
// MEMBER DASHBOARD
// ═══════════════════════════════════════
function MemberDash({user,db,setDb,onLogout,lang}){
  const t=lang==="pt";const[tab,setTab]=useState("ov");const[dmod,setDmod]=useState(null);const[amt,setAmt]=useState("");
  const u=db.users[user.uid]||{balance:0,deposits:[],withdrawals:[],pnl:0};
  const eq=db.eq||[];const trades=db.trades||[];
  const pnlPct=u.balance>0?Math.round(u.pnl/u.balance*10000)/100:0;

  const doDeposit=async(method)=>{const a=parseFloat(amt);if(!a||a<=0)return;
    const ndb={...db,users:{...db.users,[user.uid]:{...u,balance:u.balance+a,deposits:[...u.deposits,{amount:a,method,date:new Date().toISOString(),status:"confirmed"}]}}};
    await DB.save(ndb);setDb(ndb);setAmt("");setDmod(null);};
  const doWithdraw=async()=>{const a=parseFloat(amt);if(!a||a<=0||a>u.balance)return;
    const ndb={...db,users:{...db.users,[user.uid]:{...u,balance:u.balance-a,withdrawals:[...u.withdrawals,{amount:a,date:new Date().toISOString(),status:"pending"}]}}};
    await DB.save(ndb);setDb(ndb);setAmt("");setDmod(null);};

  const tabs=t?["Portfólio","Depositar","Sacar","Operações"]:["Portfolio","Deposit","Withdraw","Trades"];
  const tabKeys=["ov","dep","wd","tr"];

  return <div>
    <div style={{borderBottom:`1px solid ${C.brd}`,padding:"0 20px",display:"flex",overflowX:"auto"}}>
      {tabs.map((l,i)=> <button key={i} onClick={()=>setTab(tabKeys[i])} style={{background:"none",border:"none",padding:"13px 14px",fontSize:11,fontWeight:500,cursor:"pointer",fontFamily:"var(--s)",whiteSpace:"nowrap",color:tab===tabKeys[i]?C.gold:C.td,borderBottom:tab===tabKeys[i]?`2px solid ${C.gold}`:"2px solid transparent"}}>{l}</button>)}
    </div>

    {/* DEPOSIT/WITHDRAW MODAL */}
    {dmod&&<div style={{position:"fixed",inset:0,zIndex:300,background:`${C.bg}EE`,backdropFilter:"blur(20px)",display:"flex",alignItems:"center",justifyContent:"center"}} onClick={e=>{if(e.target===e.currentTarget)setDmod(null);}}>
      <div className="card glow-card" style={{padding:28,maxWidth:380,width:"100%",margin:16,position:"relative"}}>
        <button onClick={()=>setDmod(null)} style={{position:"absolute",top:10,right:12,background:"none",border:"none",color:C.td,cursor:"pointer",fontSize:16}}>✕</button>
        <div className="tag" style={{textAlign:"center"}}>{dmod==="withdraw"?(t?"SACAR":"WITHDRAW"):dmod.toUpperCase()}</div>
        <div style={{marginTop:16}}>
          <input className="inp" type="number" placeholder={t?"Valor em USD":"Amount in USD"} value={amt} onChange={e=>setAmt(e.target.value)} style={{fontSize:18,textAlign:"center",fontFamily:M}}/>
          {dmod==="withdraw"?
            <button onClick={doWithdraw} className="bp" style={{width:"100%",textAlign:"center"}}>{t?"CONFIRMAR SAQUE":"CONFIRM WITHDRAWAL"}</button>
          :<button onClick={()=>doDeposit(dmod)} className="bp" style={{width:"100%",textAlign:"center"}}>{t?"CONFIRMAR DEPÓSITO":"CONFIRM DEPOSIT"}</button>}
          {dmod==="pix"&&<div style={{background:C.c3,borderRadius:6,padding:12,textAlign:"center",border:`1px solid ${C.brd}`,marginTop:12}}>
            <div style={{fontSize:9,color:C.td,letterSpacing:2}}>CHAVE PIX</div><div style={{fontSize:11,fontFamily:M,color:C.gold,marginTop:4}}>aurum@finance.com.br</div></div>}
          {dmod==="binance"&&<div style={{background:C.c3,borderRadius:6,padding:12,textAlign:"center",border:`1px solid ${C.brd}`,marginTop:12}}>
            <div style={{fontSize:9,color:C.td,letterSpacing:2}}>BINANCE ID</div><div style={{fontSize:16,fontFamily:M,color:C.gold,fontWeight:600,marginTop:4}}>847 291 053</div></div>}
          {dmod==="crypto"&&<div style={{background:C.c3,borderRadius:6,padding:12,textAlign:"center",border:`1px solid ${C.brd}`,marginTop:12}}>
            <div style={{fontSize:9,color:C.td,letterSpacing:2}}>USDT TRC-20</div><div style={{fontSize:10,fontFamily:M,color:C.gold,marginTop:4,wordBreak:"break-all"}}>TJx8Kv3R9qn7f4Bk2GYpMz...</div></div>}
        </div>
      </div>
    </div>}

    <div style={{padding:"20px",maxWidth:960,margin:"0 auto"}}>
      {tab==="ov"&&<div>
        <div className="card" style={{padding:22,marginBottom:14,background:`linear-gradient(135deg,${C.c1},${C.c2})`}}>
          <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:8}}>
            <div style={{width:6,height:6,borderRadius:"50%",background:C.g,boxShadow:`0 0 8px ${C.g}`}}/><span style={{fontSize:10,color:C.td,letterSpacing:2}}>LIVE</span></div>
          <div style={{fontSize:32,fontWeight:600,fontFamily:M,marginBottom:4}}>${u.balance.toLocaleString(undefined,{minimumFractionDigits:2})}</div>
          <span style={{fontSize:13,fontFamily:M,fontWeight:600,color:u.pnl>=0?C.g:C.r}}>{u.pnl>=0?"+":""}${u.pnl.toFixed(2)} ({pnlPct}%)</span>
        </div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:8,marginBottom:14}}>
          {[["🔗","Crypto","crypto"],["🇧🇷","PIX","pix"],["⬡","Binance","binance"]].map(([ic,l,k])=>
            <button key={k} onClick={()=>setDmod(k)} className="hov-card card" style={{padding:"14px 8px",cursor:"pointer",textAlign:"center",color:C.t,fontFamily:"var(--s)"}}>
              <div style={{fontSize:18,marginBottom:3}}>{ic}</div><div style={{fontSize:10}}>{t?"Depositar":"Deposit"} {l}</div></button>)}
        </div>
        <button onClick={()=>setDmod("withdraw")} className="card hov-card" style={{width:"100%",padding:12,textAlign:"center",cursor:"pointer",color:C.r,fontWeight:600,fontSize:12,fontFamily:"var(--s)",marginBottom:14,border:`1px solid ${C.brd}`}}>
          {t?"SOLICITAR SAQUE":"REQUEST WITHDRAWAL"}
        </button>
        <div className="card" style={{padding:16}}>
          <div style={{fontSize:10,color:C.td,letterSpacing:2,marginBottom:8}}>EQUITY</div>
          <ResponsiveContainer width="100%" height={160}>
            <AreaChart data={eq}><defs><linearGradient id="dG" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={C.gold} stopOpacity={.12}/><stop offset="100%" stopColor={C.gold} stopOpacity={0}/></linearGradient></defs>
              <CartesianGrid strokeDasharray="3 3" stroke={C.brd}/><XAxis dataKey="d" tick={{fill:C.td,fontSize:9}} axisLine={false} tickLine={false}/>
              <YAxis tick={{fill:C.td,fontSize:9}} axisLine={false} tickLine={false} domain={["auto","auto"]}/><Tooltip content={<Tip/>}/>
              <Area type="monotone" dataKey="v" stroke={C.gold} strokeWidth={1.5} fill="url(#dG)" dot={false}/></AreaChart>
          </ResponsiveContainer>
        </div>
      </div>}
      {tab==="dep"&&<div>{[{k:"crypto",i:"🔗",l:"Crypto",d:"USDT, USDC, BTC, ETH"},{k:"pix",i:"🇧🇷",l:"PIX",d:t?"Reais via PIX":"BRL via PIX"},{k:"binance",i:"⬡",l:"Binance Pay",d:t?"Taxa zero":"Zero fee"}].map(d=>
        <button key={d.k} onClick={()=>setDmod(d.k)} className="hov-card card" style={{display:"flex",alignItems:"center",gap:14,padding:18,cursor:"pointer",color:C.t,fontFamily:"var(--s)",width:"100%",marginBottom:10,textAlign:"left"}}>
          <span style={{fontSize:24}}>{d.i}</span><div style={{flex:1}}><div style={{fontSize:14,fontWeight:600}}>{d.l}</div><div style={{fontSize:11,color:C.td}}>{d.d}</div></div><span style={{color:C.td}}>›</span>
        </button>)}
        {u.deposits.length>0&&<div className="card" style={{marginTop:16,overflow:"hidden"}}>
          <div style={{padding:"10px 14px",fontSize:10,color:C.td,letterSpacing:2,borderBottom:`1px solid ${C.brd}`}}>{t?"HISTÓRICO":"HISTORY"}</div>
          {u.deposits.map((d,i)=><div key={i} style={{display:"flex",padding:"8px 14px",borderBottom:`1px solid ${C.brd}06`,fontSize:11}}>
            <span style={{flex:1,color:C.tm}}>{d.method}</span><span style={{fontFamily:M,color:C.g}}>+${d.amount}</span>
            <span style={{fontSize:9,color:C.g,background:C.gBg,padding:"1px 6px",borderRadius:3,marginLeft:8}}>{d.status}</span>
          </div>)}</div>}
      </div>}
      {tab==="wd"&&<div>
        <div className="card" style={{padding:20,textAlign:"center"}}>
          <div style={{fontSize:10,color:C.td,letterSpacing:2,marginBottom:12}}>{t?"SALDO DISPONÍVEL":"AVAILABLE BALANCE"}</div>
          <div style={{fontSize:28,fontFamily:M,fontWeight:600,marginBottom:16}}>${u.balance.toFixed(2)}</div>
          <input className="inp" type="number" placeholder={t?"Valor":"Amount"} value={amt} onChange={e=>setAmt(e.target.value)} style={{textAlign:"center",fontFamily:M,fontSize:16}}/>
          <button onClick={doWithdraw} className="bp" style={{width:"100%",textAlign:"center"}}>{t?"SACAR":"WITHDRAW"}</button>
        </div>
        {u.withdrawals.length>0&&<div className="card" style={{marginTop:16,overflow:"hidden"}}>
          <div style={{padding:"10px 14px",fontSize:10,color:C.td,letterSpacing:2,borderBottom:`1px solid ${C.brd}`}}>{t?"SAQUES":"WITHDRAWALS"}</div>
          {u.withdrawals.map((w,i)=><div key={i} style={{display:"flex",padding:"8px 14px",borderBottom:`1px solid ${C.brd}06`,fontSize:11}}>
            <span style={{flex:1,color:C.tm}}>{new Date(w.date).toLocaleDateString()}</span><span style={{fontFamily:M,color:C.r}}>-${w.amount}</span>
            <span style={{fontSize:9,color:w.status==="confirmed"?C.g:C.gold,background:w.status==="confirmed"?C.gBg:C.goldBg,padding:"1px 6px",borderRadius:3,marginLeft:8}}>{w.status}</span>
          </div>)}</div>}
      </div>}
      {tab==="tr"&&<div className="card" style={{overflow:"hidden"}}>
        {trades.slice(0,25).map((tr,i)=> <div key={i} className="hov-row" style={{display:"flex",alignItems:"center",padding:"8px 14px",borderBottom:`1px solid ${C.brd}06`,fontSize:11,gap:6}}>
          <span style={{flex:"0 0 52px",color:C.td,fontFamily:M,fontSize:10}}>{tr.date}</span>
          <span style={{flex:"0 0 44px",fontWeight:600,fontFamily:M}}>{tr.sym}</span>
          <span style={{flex:"0 0 50px"}}><span style={{fontSize:9,fontWeight:600,padding:"1px 6px",borderRadius:3,background:tr.s==="SM-1"?"#7577D112":tr.s==="SV-5D"?"#C9A04812":"#5AAF7A12",color:tr.s==="SM-1"?"#7577D1":tr.s==="SV-5D"?"#C9A048":"#5AAF7A"}}>{tr.s}</span></span>
          <span style={{flex:1}}/><span style={{fontWeight:600,fontFamily:M,color:tr.pnl>=0?C.g:C.r}}>{tr.pnl>=0?"+":""}{tr.pnl.toFixed(2)}</span></div>)}
      </div>}
    </div>
  </div>;
}

// ═══════════════════════════════════════
// ADMIN DASHBOARD
// ═══════════════════════════════════════
function AdminDash({db,setDb,onLogout,lang}){
  const t=lang==="pt";const[tab,setTab]=useState("ov");
  const users=Object.entries(db.users||{});
  const totalAUM=users.reduce((a,[,u])=>a+u.balance,0);
  const totalDeps=users.reduce((a,[,u])=>a+(u.deposits||[]).reduce((b,d)=>b+d.amount,0),0);
  const totalWds=users.reduce((a,[,u])=>a+(u.withdrawals||[]).reduce((b,w)=>b+w.amount,0),0);
  const pending=users.flatMap(([uid,u])=>(u.withdrawals||[]).filter(w=>w.status==="pending").map(w=>({...w,uid,name:u.name})));
  const eq=db.eq||[];const trades=db.trades||[];

  const approveWd=async(uid,idx)=>{const u={...db.users[uid]};u.withdrawals=[...u.withdrawals];u.withdrawals[idx]={...u.withdrawals[idx],status:"confirmed"};
    const ndb={...db,users:{...db.users,[uid]:u}};await DB.save(ndb);setDb(ndb);};
  const resetAll=async()=>{await DB.reset();setDb(DB.init());};

  const tabs=t?["Visão Geral","Membros","Operações","Config"]:["Overview","Members","Trades","Config"];
  const tabKeys=["ov","mb","tr","cfg"];

  return <div>
    <div style={{borderBottom:`1px solid ${C.brd}`,padding:"0 20px",display:"flex",overflowX:"auto"}}>
      <div style={{display:"flex",alignItems:"center",gap:6,marginRight:12}}><div style={{fontSize:9,color:C.r,background:C.rBg,padding:"2px 8px",borderRadius:3,fontWeight:600}}>ADMIN</div></div>
      {tabs.map((l,i)=> <button key={i} onClick={()=>setTab(tabKeys[i])} style={{background:"none",border:"none",padding:"13px 14px",fontSize:11,fontWeight:500,cursor:"pointer",fontFamily:"var(--s)",whiteSpace:"nowrap",color:tab===tabKeys[i]?C.gold:C.td,borderBottom:tab===tabKeys[i]?`2px solid ${C.gold}`:"2px solid transparent"}}>{l}</button>)}
    </div>
    <div style={{padding:"20px",maxWidth:960,margin:"0 auto"}}>
      {tab==="ov"&&<div>
        <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:10,marginBottom:16}}>
          {[[t?"AUM Total":"Total AUM",`$${totalAUM.toFixed(0)}`,C.gold],[t?"Membros":"Members",users.length,C.t],[t?"Depósitos":"Deposits",`$${totalDeps.toFixed(0)}`,C.g],[t?"Saques":"Withdrawals",`$${totalWds.toFixed(0)}`,C.r]].map(([l,v,c],i)=>
            <div key={i} className="card" style={{padding:16}}><div style={{fontSize:9,color:C.td,letterSpacing:1.5,marginBottom:4}}>{l}</div>
              <div style={{fontSize:22,fontWeight:600,fontFamily:M,color:c}}>{v}</div></div>)}
        </div>
        {pending.length>0&&<div className="card" style={{marginBottom:16,overflow:"hidden"}}>
          <div style={{padding:"10px 14px",fontSize:10,color:C.r,letterSpacing:2,borderBottom:`1px solid ${C.brd}`}}>{t?"SAQUES PENDENTES":"PENDING WITHDRAWALS"} ({pending.length})</div>
          {pending.map((w,i)=><div key={i} style={{display:"flex",alignItems:"center",padding:"10px 14px",borderBottom:`1px solid ${C.brd}06`,fontSize:12,gap:8}}>
            <span style={{flex:1,fontWeight:500}}>{w.name}</span><span style={{fontFamily:M,color:C.r}}>-${w.amount}</span>
            <button onClick={()=>{const uIdx=db.users[w.uid].withdrawals.findIndex(x=>x.date===w.date&&x.status==="pending");if(uIdx>=0)approveWd(w.uid,uIdx);}}
              style={{background:C.g,color:C.bg,border:"none",padding:"4px 12px",borderRadius:4,fontSize:10,fontWeight:600,cursor:"pointer"}}>{t?"Aprovar":"Approve"}</button>
          </div>)}</div>}
        <div className="card" style={{padding:16}}>
          <div style={{fontSize:10,color:C.td,letterSpacing:2,marginBottom:8}}>{t?"EQUITY DO FUNDO":"FUND EQUITY"}</div>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={eq}><defs><linearGradient id="aG" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={C.gold} stopOpacity={.12}/><stop offset="100%" stopColor={C.gold} stopOpacity={0}/></linearGradient></defs>
              <CartesianGrid strokeDasharray="3 3" stroke={C.brd}/><XAxis dataKey="d" tick={{fill:C.td,fontSize:9}} axisLine={false} tickLine={false}/>
              <YAxis tick={{fill:C.td,fontSize:9}} axisLine={false} tickLine={false} domain={["auto","auto"]}/><Tooltip content={<Tip/>}/>
              <Area type="monotone" dataKey="v" stroke={C.gold} strokeWidth={1.5} fill="url(#aG)" dot={false}/></AreaChart>
          </ResponsiveContainer>
        </div>
      </div>}
      {tab==="mb"&&<div>
        {users.length===0?<div className="card" style={{padding:32,textAlign:"center",color:C.td}}>{t?"Nenhum membro registrado":"No members registered"}</div>
        :<div className="card" style={{overflow:"hidden"}}>
          <div style={{padding:"10px 14px",fontSize:10,color:C.td,letterSpacing:2,borderBottom:`1px solid ${C.brd}`}}>{t?"MEMBROS":"MEMBERS"} ({users.length})</div>
          {users.map(([uid,u])=><div key={uid} style={{display:"flex",alignItems:"center",padding:"10px 14px",borderBottom:`1px solid ${C.brd}06`,fontSize:12,gap:8}}>
            <div style={{width:28,height:28,borderRadius:"50%",background:C.c3,display:"flex",alignItems:"center",justifyContent:"center",fontSize:11,fontWeight:600,color:C.gold}}>{(u.name||"?")[0].toUpperCase()}</div>
            <div style={{flex:1}}><div style={{fontWeight:500}}>{u.name}</div><div style={{fontSize:10,color:C.td}}>{u.email}</div></div>
            <div style={{textAlign:"right"}}><div style={{fontFamily:M,fontWeight:600}}>${u.balance.toFixed(2)}</div>
              <div style={{fontSize:9,color:C.td}}>{(u.deposits||[]).length}d / {(u.withdrawals||[]).length}w</div></div>
          </div>)}</div>}
      </div>}
      {tab==="tr"&&<div className="card" style={{overflow:"hidden"}}>
        {trades.slice(0,30).map((tr,i)=> <div key={i} className="hov-row" style={{display:"flex",alignItems:"center",padding:"8px 14px",borderBottom:`1px solid ${C.brd}06`,fontSize:11,gap:6}}>
          <span style={{flex:"0 0 52px",color:C.td,fontFamily:M,fontSize:10}}>{tr.date}</span>
          <span style={{flex:"0 0 44px",fontWeight:600,fontFamily:M}}>{tr.sym}</span>
          <span style={{flex:"0 0 50px"}}><span style={{fontSize:9,fontWeight:600,padding:"1px 6px",borderRadius:3,background:tr.s==="SM-1"?"#7577D112":tr.s==="SV-5D"?"#C9A04812":"#5AAF7A12",color:tr.s==="SM-1"?"#7577D1":tr.s==="SV-5D"?"#C9A048":"#5AAF7A"}}>{tr.s}</span></span>
          <span style={{flex:1}}/><span style={{fontWeight:600,fontFamily:M,color:tr.pnl>=0?C.g:C.r}}>{tr.pnl>=0?"+":""}{tr.pnl.toFixed(2)}</span></div>)}
      </div>}
      {tab==="cfg"&&<div>
        <div className="card" style={{padding:20}}>
          <div style={{fontSize:12,fontWeight:600,marginBottom:12}}>{t?"Configurações":"Settings"}</div>
          <button onClick={resetAll} style={{background:C.r,color:"#fff",border:"none",padding:"10px 20px",borderRadius:4,fontSize:11,fontWeight:600,cursor:"pointer"}}>{t?"RESETAR BANCO DE DADOS":"RESET DATABASE"}</button>
          <p style={{fontSize:10,color:C.td,marginTop:8}}>{t?"Remove todos os usuários e dados. Irreversível.":"Removes all users and data. Irreversible."}</p>
        </div>
      </div>}
    </div>
  </div>;
}

// ═══════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════
export default function App(){
  const[page,setPage]=useState("land");const[lang,setLang]=useState("pt");const[user,setUser]=useState(null);const[db,setDb]=useState(null);const[loading,setLoading]=useState(true);

  useEffect(()=>{(async()=>{const d=await DB.load();setDb(d);setLoading(false);})();},[]);

  const handleAuth=async(u)=>{const d=await DB.load();setDb(d);setUser(u);setPage(u.isAdmin?"admin":"member");};
  const handleLogout=()=>{setUser(null);setPage("land");};

  if(loading||!db)return <div style={{background:C.bg,minHeight:"100vh",display:"flex",alignItems:"center",justifyContent:"center"}}>
    <div style={{width:24,height:24,border:`2px solid ${C.brd}`,borderTop:`2px solid ${C.gold}`,borderRadius:"50%",animation:"sp .8s linear infinite"}}/>
    <style>{`@keyframes sp{from{transform:rotate(0)}to{transform:rotate(360deg)}}`}</style></div>;

  return <div style={{background:C.bg,color:C.t,minHeight:"100vh"}}>
    <style>{`
      @import url('https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600;9..40,700&family=JetBrains+Mono:wght@300;400;500;600;700&display=swap');
      :root{--s:'DM Sans',system-ui,sans-serif}*{box-sizing:border-box;margin:0;padding:0}body{background:${C.bg};font-family:var(--s);-webkit-font-smoothing:antialiased}html{scroll-behavior:smooth}
      ::-webkit-scrollbar{width:3px}::-webkit-scrollbar-thumb{background:${C.goldD};border-radius:3px}
      .wrap{max-width:940px;margin:0 auto;padding:0 24px}@media(max-width:600px){.wrap{padding:0 16px}}
      .sec{padding:72px 0;border-top:1px solid ${C.brd}}
      .card{background:${C.c1};border:1px solid ${C.brd};border-radius:8px}.glow-card{box-shadow:0 0 40px ${C.gold}06}
      .tag{font-size:10px;font-weight:600;letter-spacing:2.5px;color:${C.goldD};text-transform:uppercase;margin-bottom:8px}
      .h2{font-size:20px;font-weight:400;margin-top:4px}.h2 span{color:${C.gold}}
      .inp{width:100%;padding:11px 14px;background:${C.c2};border:1px solid ${C.brd};border-radius:6px;color:${C.t};font-size:13px;font-family:var(--s);outline:none;margin-bottom:10px}.inp:focus{border-color:${C.gold}50}
      .bp{background:linear-gradient(135deg,${C.gold},${C.goldD});color:${C.bg};border:none;padding:12px 28px;border-radius:6px;font-size:11px;font-weight:600;letter-spacing:2px;cursor:pointer;font-family:var(--s);box-shadow:0 4px 16px ${C.gold}25;transition:all .3s}.bp:hover{box-shadow:0 6px 24px ${C.gold}35;transform:translateY(-1px)}
      .bo{background:transparent;color:${C.gold};border:1px solid ${C.goldD};padding:12px 28px;border-radius:6px;font-size:11px;font-weight:600;letter-spacing:2px;cursor:pointer;font-family:var(--s);transition:all .3s}.bo:hover{background:${C.goldBg}}
      .hov-card{transition:all .3s}.hov-card:hover{border-color:${C.gold}30;box-shadow:0 0 20px ${C.gold}08;transform:translateY(-1px)}
      .hov-row{transition:background .2s}.hov-row:hover{background:${C.c2}}
      @media(max-width:768px){.hf{flex-direction:column!important;text-align:center!important}.hf>div:first-child{align-items:center!important}.hs{grid-template-columns:repeat(2,1fr)!important}}
      @keyframes sp{from{transform:rotate(0)}to{transform:rotate(360deg)}}
    `}</style>

    {/* NAV */}
    <nav style={{position:"sticky",top:0,zIndex:100,background:`${C.bg}DD`,backdropFilter:"blur(16px)",borderBottom:`1px solid ${C.brd}`,height:50,display:"flex",alignItems:"center",justifyContent:"space-between",padding:"0 20px"}}>
      <div onClick={()=>{if(!user)setPage("land");}} style={{cursor:"pointer",display:"flex",alignItems:"center",gap:8}}>
        <IngotLogo size={26}/>
        <span style={{fontSize:13,fontWeight:600,letterSpacing:3}}>AURUM</span>
      </div>
      <div style={{display:"flex",alignItems:"center",gap:6}}>
        {user&&<span style={{fontSize:10,color:C.td,marginRight:4}}>{user.name||user.email}</span>}
        {user?<button onClick={handleLogout} className="bo" style={{padding:"6px 14px",fontSize:10}}>{lang==="pt"?"Sair":"Logout"}</button>
          :page==="land"?<button onClick={()=>setPage("auth")} className="bo" style={{padding:"6px 14px",fontSize:10}}>{lang==="pt"?"Entrar":"Sign In"}</button>:null}
        <button onClick={()=>setLang(lang==="en"?"pt":"en")} style={{background:C.c2,border:`1px solid ${C.brd}`,color:C.td,cursor:"pointer",padding:"4px 8px",borderRadius:4,fontSize:9,fontWeight:600,fontFamily:"var(--s)"}}>{lang==="en"?"PT":"EN"}</button>
      </div>
    </nav>

    {page==="land"&&<Landing onEnter={()=>setPage("auth")} lang={lang}/>}
    {page==="auth"&&<Auth onAuth={handleAuth} lang={lang}/>}
    {page==="member"&&user&&<MemberDash user={user} db={db} setDb={setDb} onLogout={handleLogout} lang={lang}/>}
    {page==="admin"&&user&&<AdminDash db={db} setDb={setDb} onLogout={handleLogout} lang={lang}/>}
  </div>;
}
