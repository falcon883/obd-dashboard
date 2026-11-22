import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { fmt, fmtDuration } from '../format.js'

function useSize() {
  const ref = useRef(null)
  const [w, setW] = useState(320)
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    setW(el.clientWidth || 320)
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

function niceStep(range, n) {
  const raw = Math.max(range, 1e-9) / n
  const mag = 10 ** Math.floor(Math.log10(raw))
  const f = raw / mag
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag
}

/**
 * Small live line chart (plain SVG, no chart library).
 * rows: [{ t, v }]  series: [{ label, color, get: (v) => number | null }]
 */
export default function LineChart({
  title,
  rows,
  series,
  windowSec,
  yMin,
  yMax,
  decimals = 0,
  unit = '',
  thresholds = [],
  height = 170,
}) {
  const [ref, width] = useSize()
  const [hover, setHover] = useState(null)
  const gid = useId().replace(/:/g, '')
  const pad = { l: 44, r: 10, t: 8, b: 20 }
  const w = Math.max(width, 120)
  const iw = w - pad.l - pad.r
  const ih = height - pad.t - pad.b

  const view = useMemo(() => {
    const tmax = rows.length ? rows[rows.length - 1].t : 0
    const x0 = rows.length ? Math.max(rows[0].t, tmax - windowSec) : 0
    const x1 = Math.max(x0 + windowSec, tmax)
    const vis = rows.filter((r) => r.t >= x0)
    const vals = series.map((s) => vis.map((r) => s.get(r.v)))
    let lo = yMin
    let hi = yMax
    if (lo == null || hi == null) {
      const all = vals.flat().filter((x) => typeof x === 'number')
      const mn = all.length ? Math.min(...all) : 0
      const mx = all.length ? Math.max(...all) : 1
      const span = mx - mn || Math.max(1, Math.abs(mx) * 0.1)
      if (lo == null) lo = mn - span * 0.1
      if (hi == null) hi = mx + span * 0.1
    }
    // round the axis to "nice" numbers (1, 2, 5 x 10^n) so the tick labels are readable
    const step = niceStep(hi - lo, 4)
    if (yMin == null) lo = Math.floor(lo / step) * step
    if (yMax == null) hi = Math.ceil(hi / step) * step
    const ticks = []
    for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9; v += step) ticks.push(v)
    return { x0, x1, vis, vals, lo, hi, ticks, step }
  }, [rows, series, windowSec, yMin, yMax])

  const { x0, x1, vis, vals, lo, hi, ticks: yTicks, step } = view
  const X = (t) => pad.l + ((t - x0) / (x1 - x0 || 1)) * iw
  const Y = (v) => pad.t + (1 - (v - lo) / (hi - lo || 1)) * ih

  const paths = series.map((s, si) => {
    let d = ''
    let pen = false
    vis.forEach((r, i) => {
      const v = vals[si][i]
      if (typeof v !== 'number') {
        pen = false
        return
      }
      d += `${pen ? 'L' : 'M'}${X(r.t).toFixed(1)} ${Y(v).toFixed(1)} `
      pen = true
    })
    return d
  })

  const tickDecimals = step < 1 ? (step < 0.1 ? 2 : 1) : decimals
  const xTicks = [0, 1, 2, 3, 4].map((i) => x0 + ((x1 - x0) * i) / 4)
  const idx = hover != null && hover < vis.length ? hover : null
  const shown = idx != null ? vis[idx] : vis[vis.length - 1]

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const t = x0 + ((e.clientX - rect.left - pad.l) / (iw || 1)) * (x1 - x0)
    let best = 0
    let bd = Infinity
    vis.forEach((r, i) => {
      const d = Math.abs(r.t - t)
      if (d < bd) {
        bd = d
        best = i
      }
    })
    setHover(best)
  }

  const firstPath = paths[0]
  const areaD =
    firstPath && vis.length > 1 && series.length === 1
      ? `${firstPath} L${X(vis[vis.length - 1].t).toFixed(1)} ${Y(lo).toFixed(1)} L${X(vis[0].t).toFixed(1)} ${Y(lo).toFixed(1)} Z`
      : null

  return (
    <div className="card chart">
      <div className="chart-head">
        <div className="card-title">{title}</div>
        <div className="legend">
          {series.map((s) => {
            const v = shown ? s.get(shown.v) : null
            return (
              <span key={s.label} className="legend-item">
                <i style={{ background: s.color }} />
                {series.length > 1 && <em>{s.label}</em>}
                <b>{fmt(v, decimals)}</b>
                <small>{unit}</small>
              </span>
            )
          })}
        </div>
      </div>
      <div ref={ref} className="chart-body">
        <svg
          width={w}
          height={height}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          role="img"
          aria-label={title}
        >
          <defs>
            <linearGradient id={`g${gid}`} x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stopColor={series[0]?.color} stopOpacity="0.28" />
              <stop offset="100%" stopColor={series[0]?.color} stopOpacity="0" />
            </linearGradient>
          </defs>
          {yTicks.map((v, i) => (
            <g key={i}>
              <line x1={pad.l} x2={w - pad.r} y1={Y(v)} y2={Y(v)} className="c-grid" />
              <text x={pad.l - 6} y={Y(v) + 3.5} className="c-label" textAnchor="end">
                {fmt(v, tickDecimals)}
              </text>
            </g>
          ))}
          {xTicks.map((t, i) => (
            <text
              key={i}
              x={X(t)}
              y={height - 5}
              className="c-label"
              textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}
            >
              {fmtDuration(t)}
            </text>
          ))}
          {thresholds
            .filter((th) => th.y >= lo && th.y <= hi)
            .map((th, i) => (
              <line
                key={i}
                x1={pad.l}
                x2={w - pad.r}
                y1={Y(th.y)}
                y2={Y(th.y)}
                className="c-thresh"
                style={{ stroke: th.color }}
              />
            ))}
          {areaD && <path d={areaD} fill={`url(#g${gid})`} />}
          {paths.map((d, i) => (
            <path key={i} d={d} className="c-line" style={{ stroke: series[i].color }} />
          ))}
          {idx != null && shown && (
            <g>
              <line x1={X(shown.t)} x2={X(shown.t)} y1={pad.t} y2={pad.t + ih} className="c-cursor" />
              {series.map((s, i) => {
                const v = s.get(shown.v)
                return typeof v === 'number' ? (
                  <circle
                    key={i}
                    cx={X(shown.t)}
                    cy={Y(v)}
                    r="3.5"
                    fill={s.color}
                    stroke="#0a0e16"
                    strokeWidth="1.5"
                  />
                ) : null
              })}
            </g>
          )}
          {!vis.length && (
            <text x={w / 2} y={height / 2} className="c-empty" textAnchor="middle">
              Waiting for data…
            </text>
          )}
        </svg>
      </div>
    </div>
  )
}
