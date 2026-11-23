import { api } from '../api.js'
import { COLORS } from '../format.js'
import { HEADLINE, fileName, fmtStarted, outcomeTiles, parseAlert } from '../summary.js'
import LineChart from './LineChart.jsx'
import { StatusIcon, Tile } from './Panels.jsx'

function Finding({ level, children }) {
  return (
    <li className="finding">
      <StatusIcon status={level} />
      <span>{children}</span>
    </li>
  )
}

/** What the car said at the end: alerts raised during the drive, trouble codes and failed self-tests. */
function WhatHappened({ o }) {
  const alerts = o.alerts.map(parseAlert)
  const clean = !alerts.length && !o.monitor_failures.length && !o.stored.length && !o.pending.length
  return (
    <div className="card sum-card">
      <div className="card-title">What happened</div>
      {clean && (
        <ul className="findings">
          <Finding level="ok">Nothing to worry about on this drive.</Finding>
        </ul>
      )}
      {!clean && (
        <ul className="findings">
          {alerts.map((a, i) => (
            <Finding key={i} level={a.level}>
              {a.text}
            </Finding>
          ))}
          {o.monitor_failures.map((f) => (
            <Finding key={f} level="warn">
              Self-test failed: {f}
            </Finding>
          ))}
        </ul>
      )}
      <p className="muted small sum-codes">
        Check-engine light {o.mil ? 'ON' : 'off'} ·{' '}
        {o.stored.length ? `stored: ${o.stored.join(', ')}` : 'no stored codes'}
        {o.pending.length ? ` · pending: ${o.pending.join(', ')}` : ''}
      </p>
      {!o.end_answered && (
        <p className="muted small">
          The car stopped answering at the end, so codes and self-tests are the last ones seen.
        </p>
      )}
    </div>
  )
}

/** Shown in place of the frozen dashboard once a session has ended. */
export default function SessionSummary({ status, info, rows, U, onHistory }) {
  const result = status.result
  const o = result.outcome
  const head = HEADLINE[o.verdict] || HEADLINE.ok
  const vin = info?.car?.vin
  const report = fileName(result.report)
  const csv = fileName(result.csv)
  const when = info?.car ? info.car.display_name : null
  const tiles = outcomeTiles(o, U)
  const span = rows.length > 1 ? Math.max(10, Math.ceil(rows[rows.length - 1].t - rows[0].t)) : 0

  return (
    <section className="summary-screen">
      <div className={`card sum-hero ${head.status}`}>
        <div className="sum-icon">
          <StatusIcon status={head.status} />
        </div>
        <div className="sum-title">
          <h2>{head.title}</h2>
          <p className="muted">{o.demo ? 'Demo drive. Nothing was saved.' : head.note}</p>
          <p className="muted small sum-meta">
            {[when, fmtStarted(info?.started)].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="sum-actions">
          {vin && report && (
            <a className="btn" href={api.fileUrl(vin, report)} target="_blank" rel="noreferrer">
              Full report
            </a>
          )}
          {vin && csv && (
            <a className="btn ghost" href={api.fileUrl(vin, csv)} download>
              CSV
            </a>
          )}
          {!o.demo && (
            <button className="btn ghost" onClick={onHistory}>
              History
            </button>
          )}
        </div>
      </div>

      <div className="tiles sum-tiles">
        {tiles.map((t) => (
          <Tile key={t.key} label={t.label} value={t.value} unit={t.unit} sub={t.sub} />
        ))}
      </div>

      <div className="sum-grid">
        <WhatHappened o={o} />
        {span > 0 && (
          <div className="sum-charts">
            <LineChart
              title="Coolant temperature"
              unit={U.temp}
              rows={rows}
              windowSec={span}
              thresholds={[{ y: U.t(info?.thresholds?.coolant_warn_c ?? 102), color: COLORS.warn }]}
              series={[{ label: 'Coolant', color: COLORS.orange, get: (v) => U.t(v.COOLANT_TEMP) }]}
            />
            <LineChart
              title="Vehicle speed"
              unit={U.speed}
              rows={rows}
              windowSec={span}
              yMin={0}
              series={[{ label: 'Speed', color: COLORS.violet, get: (v) => U.s(v.SPEED) }]}
            />
          </div>
        )}
      </div>

      {result.summary?.length > 0 && !o.demo && (
        <details className="card sum-raw">
          <summary>Full text summary</summary>
          <pre>{result.summary.join('\n')}</pre>
        </details>
      )}
    </section>
  )
}
