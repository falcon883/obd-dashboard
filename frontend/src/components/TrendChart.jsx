import { fmt } from '../format.js'

const W = 360
const H = 150
const PAD = { l: 42, r: 12, t: 12, b: 24 }

function niceTicks(lo, hi, n = 3) {
  const range = Math.max(hi - lo, 1e-9)
  const raw = range / n
  const mag = 10 ** Math.floor(Math.log10(raw))
  const f = raw / mag
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag
  const out = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) out.push(v)
  return out
}

/**
 * One value per drive, oldest on the left (plain SVG, like the live charts).
 * points: [{ stamp, label, value }]   band: [low, high] normal range, drawn as a soft stripe.
 */
export default function TrendChart({ title, hint, points, unit, decimals = 0, band }) {
  const values = points.map((p) => p.value)
  const latest = points.length ? points[points.length - 1] : null
  const iw = W - PAD.l - PAD.r
  const ih = H - PAD.t - PAD.b

  let lo = values.length ? Math.min(...values) : 0
  let hi = values.length ? Math.max(...values) : 1
  if (band) {
    lo = Math.min(lo, band[0])
    hi = Math.max(hi, band[1])
  }
  const margin = (hi - lo || 1) * 0.12
  lo -= margin
  hi += margin
  const x = (i) => PAD.l + (points.length === 1 ? iw / 2 : (i * iw) / (points.length - 1))
  const y = (v) => PAD.t + ih - ((v - lo) / (hi - lo)) * ih
  const outside = (v) => band && (v < band[0] || v > band[1])
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p.value).toFixed(1)}`).join(' ')

  return (
    <div className="card trend">
      <div className="trend-head">
        <h3>{title}</h3>
        {latest && (
          <span className={`trend-now${outside(latest.value) ? ' warn' : ''}`}>
            {fmt(latest.value, decimals)} {unit}
          </span>
        )}
      </div>
      {points.length === 0 ? (
        <p className="muted small trend-empty">Nothing to show yet.</p>
      ) : (
        <svg
          viewBox={`0 0 ${W} ${H}`}
          role="img"
          aria-label={`${title}: ${points.length} drives, latest ${fmt(latest.value, decimals)} ${unit}`}
        >
          {band && (
            <rect
              className="trend-band"
              x={PAD.l}
              width={iw}
              y={y(band[1])}
              height={Math.max(0, y(band[0]) - y(band[1]))}
            />
          )}
          {niceTicks(lo, hi).map((t) => (
            <g key={t}>
              <line className="trend-grid" x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} />
              <text className="trend-tick" x={PAD.l - 6} y={y(t) + 3} textAnchor="end">
                {fmt(t, decimals)}
              </text>
            </g>
          ))}
          {points.length > 1 && <path className="trend-line" d={path} />}
          {points.map((p, i) => (
            <circle
              key={p.stamp}
              className={`trend-dot${outside(p.value) ? ' warn' : ''}`}
              cx={x(i)}
              cy={y(p.value)}
              r={4}
            >
              <title>{`${p.label}: ${fmt(p.value, decimals)} ${unit}`}</title>
            </circle>
          ))}
          <text
            className="trend-tick"
            x={PAD.l}
            y={H - 6}
            textAnchor={points.length === 1 ? 'middle' : 'start'}
          >
            {points[0].label}
          </text>
          {points.length > 1 && (
            <text className="trend-tick" x={W - PAD.r} y={H - 6} textAnchor="end">
              {latest.label}
            </text>
          )}
        </svg>
      )}
      {points.length === 1 && (
        <p className="muted small trend-note">One drive so far. The line appears after a second.</p>
      )}
      <p className="muted small trend-hint">{hint}</p>
    </div>
  )
}
