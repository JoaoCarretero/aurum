import { useState, useEffect } from 'react';
import { MONO } from '../theme';

export default function Counter({ to, prefix = "", suffix = "", duration = 1800, color = "#EAE7DE", size = 28 }) {
  const [v, setV] = useState(0);
  const num = parseFloat(String(to).replace(/[^0-9.\-]/g, "")) || 0;
  const dec = String(to).includes(".") ? (String(to).split(".")[1]?.length || 0) : 0;

  useEffect(() => {
    let s = 0;
    const step = num / (duration / 16);
    const id = setInterval(() => {
      s += step;
      if ((step > 0 && s >= num) || (step < 0 && s <= num)) {
        setV(num); clearInterval(id);
      } else setV(s);
    }, 16);
    return () => clearInterval(id);
  }, [num]);

  return (
    <span style={{ fontSize: size, fontWeight: 600, fontFamily: MONO, color }}>
      {prefix}{v.toFixed(dec)}{suffix}
    </span>
  );
}
