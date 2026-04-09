import { C } from '../theme';

export default function Globe() {
  const cx = 50, cy = 50, r1 = 42, vr = 26;
  const hx = n => [0,1,2,3,4,5].map(i => {
    const a = (i * 60 - 90) * Math.PI / 180;
    return `${cx + n * Math.cos(a)},${cy + n * Math.sin(a)}`;
  });
  const vx = hx(r1);

  return (
    <div style={{ position: "relative", width: "clamp(300px,42vw,440px)", height: "clamp(300px,42vw,440px)", flexShrink: 0 }}>
      <svg viewBox="0 0 100 100" style={{ position: "absolute", inset: 0, width: "100%", height: "100%", animation: "breathe 10s ease infinite" }}>
        <circle cx={cx} cy={cy} r="47" fill="none" stroke={C.gold} strokeWidth=".5" opacity=".22" />
        <circle cx={cx} cy={cy} r="30" fill="none" stroke={C.gold} strokeWidth=".4" opacity=".16" />
        <circle cx={cx} cy={cy} r="15" fill="none" stroke={C.gold} strokeWidth=".3" opacity=".11" />
        <polygon points={`${vx[0]} ${vx[2]} ${vx[4]}`} fill="none" stroke={C.gold} strokeWidth=".7" opacity=".22" />
        <polygon points={`${vx[1]} ${vx[3]} ${vx[5]}`} fill="none" stroke={C.gold} strokeWidth=".7" opacity=".22" />
        <circle cx={cx} cy={cy - vr * .72} r="3.2" fill="none" stroke={C.gold} strokeWidth=".55" opacity=".22" />
        <line x1={cx} y1={cy - vr * .56} x2={cx} y2={cy + vr * .18} stroke={C.gold} strokeWidth=".5" opacity=".18" />
        <line x1={cx - vr * .72} y1={cy - vr * .18} x2={cx + vr * .72} y2={cy - vr * .18} stroke={C.gold} strokeWidth=".5" opacity=".17" />
        <line x1={cx} y1={cy - vr * .36} x2={cx - vr * .6} y2={cy - vr * .56} stroke={C.gold} strokeWidth=".4" opacity=".13" />
        <line x1={cx} y1={cy - vr * .36} x2={cx + vr * .6} y2={cy - vr * .56} stroke={C.gold} strokeWidth=".4" opacity=".13" />
        <line x1={cx} y1={cy + vr * .18} x2={cx - vr * .44} y2={cy + vr * .78} stroke={C.gold} strokeWidth=".5" opacity=".17" />
        <line x1={cx} y1={cy + vr * .18} x2={cx + vr * .44} y2={cy + vr * .78} stroke={C.gold} strokeWidth=".5" opacity=".17" />
        <line x1={cx} y1={cy + vr * .18} x2={cx - vr * .1} y2={cy + vr * .85} stroke={C.gold} strokeWidth=".3" opacity=".11" />
        <line x1={cx} y1={cy + vr * .18} x2={cx + vr * .1} y2={cy + vr * .85} stroke={C.gold} strokeWidth=".3" opacity=".11" />
        {vx.map((p, i) => { const [x, y] = p.split(","); return <circle key={i} cx={x} cy={y} r="1.5" fill={C.gold} opacity=".3" />; })}
      </svg>
      <div className="vorb vspin" style={{ position: "absolute", borderRadius: "50%", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: "94%", height: "94%", animation: "spin 50s linear infinite" }}>
        {[0, 45, 90, 135, 180, 225, 270, 315].map((d, i) =>
          <div key={i} style={{ position: "absolute", width: 5, height: 5, borderRadius: "50%", background: C.gold, animation: `glow 4s ease infinite ${i * .3}s`, boxShadow: `0 0 10px ${C.gold}60`, top: `${50 - 47 * Math.cos(d * Math.PI / 180)}%`, left: `${50 + 47 * Math.sin(d * Math.PI / 180)}%` }} />
        )}
      </div>
      <div style={{ position: "absolute", borderRadius: "50%", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: "60%", height: "60%", animation: "spin 70s linear infinite reverse" }}>
        {[30, 150, 270].map((d, i) =>
          <div key={i} style={{ position: "absolute", width: 4, height: 4, borderRadius: "50%", background: C.goldD, animation: `glow 4s ease infinite ${i * .6}s`, boxShadow: `0 0 10px ${C.gold}40`, top: `${50 - 47 * Math.cos(d * Math.PI / 180)}%`, left: `${50 + 47 * Math.sin(d * Math.PI / 180)}%` }} />
        )}
      </div>
      <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)", width: 8, height: 8, borderRadius: "50%", background: C.gold, boxShadow: `0 0 24px ${C.gold}40, 0 0 60px ${C.gold}15` }} />
    </div>
  );
}
