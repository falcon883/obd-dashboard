import { useMemo, useState } from 'react'
import { COLORS, UNIT_LABEL, buildChecks, fmt, fmtDuration } from '../format.js'

const STATUS_COLOR = { ok: COLORS.ok, info: COLORS.info, warn: COLORS.warn, bad: COLORS.bad }

export function StatusIcon({ status }) {
  const c = STATUS_COLOR[status] || '#64748b'
  if (status === 'ok')
    return (
      <svg width="18" height="18" viewBox="0 0 20 20">
        <circle cx="10" cy="10" r="9" fill={c} fillOpacity=".16" />
        <path
          d="M5.8 10.4l2.8 2.8 5.6-6"
          fill="none"
          stroke={c}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  if (status === 'info')
    return (
      <svg width="18" height="18" viewBox="0 0 20 20">
        <circle cx="10" cy="10" r="9" fill={c} fillOpacity=".16" />
        <circle cx="10" cy="10" r="3" fill={c} />
      </svg>
    )
  return (
    <svg width="18" height="18" viewBox="0 0 20 20">
      <circle cx="10" cy="10" r="9" fill={c} fillOpacity=".18" />
      <path d="M10 5.5v5.5M10 14v.1" stroke={c} strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

/** Overall verdict from the backend's currently-active alerts. */
export function overallStatus(last) {
  const a = Object.values(last?.alerts || {})
  if (a.some((x) => x[0] === 'CRIT')) return { status: 'bad', text: 'Critical', count: a.length }
  if (a.length) return { status: 'warn', text: 'Warning', count: a.length }
  return { status: 'ok', text: 'All clear', count: 0 }
}

export function AlertBanner({ last }) {
  const a = Object.entries(last?.alerts || {})
  if (!a.length) return null
  return (
    <div className="alerts">
      {a.map(([k, [lvl, msg]]) => (
        <div key={k} className={`alert ${lvl === 'CRIT' ? 'bad' : 'warn'}`}>
          <StatusIcon status={lvl === 'CRIT' ? 'bad' : 'warn'} />
          <span className="alert-lvl">{lvl === 'CRIT' ? 'Critical' : 'Warning'}</span>
          <span>{msg}</span>
        </div>
      ))}
    </div>
  )
}

export function Tile({ label, value, unit, sub, bar, color }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">
        <span style={color ? { color } : undefined}>{value}</span>
        {unit ? <small>{unit}</small> : null}
      </div>
      {bar != null && (
        <div className="tile-bar">
          <i style={{ width: `${Math.max(0, Math.min(100, bar))}%`, background: color || COLORS.info }} />
        </div>
      )}
      {sub ? <div className="tile-sub">{sub}</div> : null}
    </div>
  )
}

export function Vitals({ last, U }) {
  const checks = useMemo(() => (last ? buildChecks(last.values, last, U) : []), [last, U])
  return (
    <div className="card">
      <div className="card-title">Vitals</div>
      {!checks.length && <div className="muted pad">Waiting for data…</div>}
      <ul className="vitals">
        {checks.map((c) => (
          <li key={c.id}>
            <StatusIcon status={c.status} />
            <div className="v-main">
              <span className="v-label">{c.label}</span>
              <span className="v-note" style={{ color: STATUS_COLOR[c.status] }}>
                {c.note}
              </span>
            </div>
            <span className="v-value">{c.value}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function WarmupCard({ last, U }) {
  const cool = last?.values?.COOLANT_TEMP
  if (cool == null) return null
  const start = last.start_cool ?? cool
  const target = 90
  const pct = Math.max(0, Math.min(100, ((cool - start) / Math.max(target - start, 1)) * 100))
  const done = cool >= 85
  const marks = [70, 80, 85]
  return (
    <div className="card">
      <div className="card-title">Engine warm-up</div>
      <div className="warm-top">
        <span
          className="warm-big"
          style={{ color: done ? COLORS.ok : cool < 70 ? COLORS.cold : COLORS.info }}
        >
          {done ? 'At operating temperature' : cool < 70 ? 'Cold — warming up' : 'Almost there'}
        </span>
      </div>
      <div className="warm-track">
        <i style={{ width: `${pct}%`, background: done ? COLORS.ok : COLORS.info }} />
        {marks.map((m) => {
          const left = ((m - start) / Math.max(target - start, 1)) * 100
          return left > 0 && left < 100 ? <b key={m} style={{ left: `${left}%` }} /> : null
        })}
      </div>
      <div className="warm-marks">
        {marks.map((m) => {
          const t = last.warm?.[String(m)]
          return (
            <span key={m} className={t != null ? 'hit' : ''}>
              {fmt(U.t(m))}
              {U.temp} <em>{t != null ? fmtDuration(t) : '—'}</em>
            </span>
          )
        })}
      </div>
      <p className="muted small">
        If coolant never gets near 90°C (195°F) after a drive, the thermostat may be stuck open.
      </p>
    </div>
  )
}

export function CodesCard({ last }) {
  const c = last?.codes
  const mf = last?.misfire || {}
  const cyl = Object.keys(mf)
    .filter((k) => k.startsWith('cyl'))
    .sort()
  const max = Math.max(5, ...cyl.map((k) => mf[k]))
  return (
    <div className="card">
      <div className="card-title">Codes & misfires</div>
      <div className="mil-row">
        <span className={`mil ${c?.mil ? 'on' : ''}`}>
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M4 10v6h2l2 2h8l2-2h2v-3h-2v-3h-3l-1-2H11l-1 2H7V8H5v2z" />
          </svg>
          Check engine {c?.mil ? 'ON' : 'off'}
        </span>
      </div>
      {c && !c.stored?.length && !c.pending?.length && (
        <div className="codes-none">No stored or pending trouble codes</div>
      )}
      {c?.stored?.map((x) => (
        <div key={x} className="code bad">
          {x}
        </div>
      ))}
      {c?.pending?.map((x) => (
        <div key={x} className="code warn">
          Pending: {x}
        </div>
      ))}
      {cyl.length > 0 && (
        <div className="mf">
          <div className="mf-head">
            <span>Misfires this drive</span>
            <b>{fmt(mf.total)} total</b>
          </div>
          {cyl.map((k) => (
            <div key={k} className="mf-row">
              <span>Cyl {k.slice(3)}</span>
              <div className="mf-bar">
                <i
                  style={{
                    width: `${(mf[k] / max) * 100}%`,
                    background: mf[k] >= 10 ? COLORS.warn : COLORS.info,
                  }}
                />
              </div>
              <em>{fmt(mf[k])}</em>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function EventLog({ events }) {
  const list = [...events].reverse()
  return (
    <div className="card">
      <div className="card-title">Event log</div>
      {!list.length && <div className="muted pad">No alerts yet — that&apos;s good.</div>}
      <ul className="events">
        {list.slice(0, 40).map((e, i) => (
          <li key={i}>
            <i style={{ background: e.level === 'CRIT' ? COLORS.bad : COLORS.warn }} />
            <time>{e.time}</time>
            <span>{e.msg}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function SensorTable({ info, last, U }) {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const sensors = info?.sensors || []
  const units = info?.units || {}
  const v = last?.values || {}
  const rows = sensors
    .filter((s) => !q || `${s.name} ${s.desc}`.toLowerCase().includes(q.toLowerCase()))
    .map((s) => {
      const raw = v[s.name]
      const u = units[s.name]
      let val = raw
      let label = UNIT_LABEL[u] ?? ''
      if (typeof raw === 'number') {
        if (u === 'degree_Celsius') {
          val = U.t(raw)
          label = U.temp
        } else if (u === 'kilometer_per_hour') {
          val = U.s(raw)
          label = U.speed
        }
      }
      return { ...s, val, label }
    })
  return (
    <div className="card">
      <div className="card-head">
        <div className="card-title">
          All sensors <span className="muted">({sensors.length})</span>
        </div>
        <div className="row-gap">
          {open && (
            <input
              className="search"
              placeholder="Filter…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          )}
          <button className="btn ghost" onClick={() => setOpen(!open)}>
            {open ? 'Hide' : 'Show'}
          </button>
        </div>
      </div>
      {open && (
        <div className="table-wrap">
          <table className="sensors">
            <tbody>
              {rows.map((r) => (
                <tr key={r.name}>
                  <td>{r.desc}</td>
                  <td className="num">
                    {typeof r.val === 'number'
                      ? fmt(r.val, Math.abs(r.val) < 100 && !Number.isInteger(r.val) ? 2 : 0)
                      : (r.val ?? '—')}
                  </td>
                  <td className="unit">{r.label}</td>
                  <td className="rate">{r.fast ? 'live' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
