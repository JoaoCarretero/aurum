import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { tokens } from "../../lib/tokens";

export function EquityCurve({ data, height = 180, id = "eq" }) {
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={data} margin={{ top: 4, right: 4, left: 4, bottom: 4 }}>
          <defs>
            <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={tokens.amberBright} stopOpacity={0.28} />
              <stop offset="100%" stopColor={tokens.amber} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={tokens.brd} vertical={false} strokeDasharray="1 4" />
          <XAxis dataKey="t" hide />
          <YAxis hide domain={["auto", "auto"]} />
          <Tooltip
            cursor={{ stroke: tokens.brdStrong, strokeDasharray: "2 2" }}
            contentStyle={{
              background: tokens.bg2,
              border: `1px solid ${tokens.brd}`,
              borderRadius: 4,
              fontFamily: "'Geist Mono', monospace",
              fontSize: 11,
              color: tokens.t,
              padding: "6px 10px",
            }}
            labelStyle={{ color: tokens.t3 }}
            formatter={(v) => [Number(v).toFixed(2), "NAV"]}
          />
          <Area
            type="monotone"
            dataKey="v"
            stroke={tokens.amberBright}
            strokeWidth={1.5}
            fill={`url(#${id}-fill)`}
            dot={false}
            isAnimationActive
            animationDuration={1200}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
