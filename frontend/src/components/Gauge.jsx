import { fmt } from '../format.js'

// 270-degree dial. 0deg is 3 o'clock and angles grow clockwise (SVG), so START=135 is bottom-left.
const START = 135
const SWEEP = 270
const CX = 100
const CY = 100
const R = 76

const clamp = (v, a, b) => Math.min(b, Math.max(a, v))
const polar = (r, deg) => {
  const a = (deg * Math.PI) / 180
  return [CX + r * Math.cos(a), CY + r * Math.sin(a)]
}
const arcPath = (r, a0, a1) => {
  const [x0, y0] = polar(r, a0)
  const [x1, y1] = polar(r, a1)
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`
}

export default function Gauge({
  label,
  value,
  min,
  max,
  unit,
  decimals = 0,
  zones = [],
  accent = '#38bdf8',
  ticks = 6,
  sub,
  minLabel,
  maxLabel,
}) {
  const has = value != null && !Number.isNaN(value)
  const frac = has ? clamp((value - min) / (max - min), 0, 1) : 0
  const zone = has
    ? zones.find((z) => value >= z.from && value < z.to) || (value >= max ? zones[zones.length - 1] : null)
    : null
  const color = zone ? zone.color : accent
  const ang = (v) => START + clamp((v - min) / (max - min), 0, 1) * SWEEP
  const full = arcPath(R, START, START + SWEEP)

  const tickMarks = Array.from({ length: ticks + 1 }, (_, i) => {
    const a = START + (i / ticks) * SWEEP
    const [x0, y0] = polar(R - 13, a)
    const [x1, y1] = polar(R - 8, a)
    return <line key={i} x1={x0} y1={y0} x2={x1} y2={y1} className="g-tick" />
  })

  return (
    <div className="card gauge">
      <div className="card-title">{label}</div>
      <svg
        viewBox="0 0 200 184"
        className="gauge-svg"
        role="img"
        aria-label={`${label}: ${has ? fmt(value, decimals) : 'no data'} ${unit}`}
      >
        {zones.map((z, i) => (
          <path
            key={i}
            d={arcPath(R + 12, ang(Math.max(z.from, min)), ang(Math.min(z.to, max)))}
            className="g-zone"
            style={{ stroke: z.color }}
          />
        ))}
        <path d={full} className="g-track" />
        <path
          d={full}
          pathLength="100"
          className="g-fill"
          style={{ stroke: color, strokeDasharray: `${Math.max(frac * 100, 0.01)} 100` }}
        />
        <g
          className="g-dot"
          style={{ transform: `rotate(${START + frac * SWEEP}deg)`, transformOrigin: '100px 100px' }}
        >
          <circle cx={CX + R} cy={CY} r="7.5" fill={color} />
          <circle cx={CX + R} cy={CY} r="3" fill="#0a0e16" />
        </g>
        {tickMarks}
        <text x="100" y="106" className="g-value" style={{ fill: has ? '#f1f5f9' : '#475569' }}>
          {has ? fmt(value, decimals) : '—'}
        </text>
        <text x="100" y="127" className="g-unit">
          {unit}
        </text>
        <text x="46" y="178" className="g-end">
          {minLabel ?? fmt(min)}
        </text>
        <text x="154" y="178" className="g-end">
          {maxLabel ?? fmt(max)}
        </text>
      </svg>
      {sub ? (
        <div className="g-sub" style={{ color }}>
          {sub}
        </div>
      ) : (
        <div className="g-sub">&nbsp;</div>
      )}
    </div>
  )
}
