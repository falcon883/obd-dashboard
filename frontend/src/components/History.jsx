import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { fmt, fmtDuration, fmtStamp, limitsOf } from '../format.js'
import { VERDICT, totals, trendDefs, trendPoints } from '../history.js'
import TrendChart from './TrendChart.jsx'

function Row({ vin, d, U }) {
  const [cls, label] = VERDICT[d.verdict] || ['idle', d.complete ? '—' : 'Incomplete']
  const dist = d.distance_km == null ? null : U.us ? d.distance_km * 0.621371 : d.distance_km
  return (
    <tr className={d.in_trends ? '' : 'dim'}>
      <td>{fmtStamp(d.stamp)}</td>
      <td>{fmtDuration(d.duration_s)}</td>
      <td>{fmt(dist, 1)}</td>
      <td>{fmt(U.t(d.start_coolant_c))}</td>
      <td>{fmt(U.t(d.coolant_max_c))}</td>
      <td>{fmt(d.warm_80_min, 1)}</td>
      <td>{fmt(d.battery_avg_v, 1)}</td>
      <td>
        <span className={`pill ${cls}`}>
          <i />
          {label}
        </span>
      </td>
      <td className="sess-links">
        {d.files.report && (
          <a href={api.fileUrl(vin, d.files.report)} target="_blank" rel="noreferrer">
            Report
          </a>
        )}
        <a href={api.fileUrl(vin, d.files.csv)} download>
          CSV
        </a>
      </td>
    </tr>
  )
}

/** How each car has been doing over time: one point per drive, plus a table of every drive. */
export default function History({ U, info, onClose }) {
  const [cars, setCars] = useState(null)
  const [vin, setVin] = useState(null)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    api
      .garage()
      .then((g) => {
        if (!alive) return
        setCars(g.cars)
        setVin((g.cars.find((c) => c.session_count > 0) || g.cars[0])?.vin ?? null)
      })
      .catch(() => alive && setError('Could not load your cars. Is the server still running?'))
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (!vin) return undefined
    let alive = true
    api
      .history(vin)
      .then((h) => {
        if (!alive) return
        setData(h)
        setError('')
      })
      .catch(() => alive && setError('Could not load the history for this car.'))
    return () => {
      alive = false
    }
  }, [vin])

  const drives = useMemo(() => (data && data.car.vin === vin ? data.drives : []), [data, vin])
  const sum = totals(drives)
  const defs = useMemo(() => trendDefs(U, limitsOf(info)), [U, info])
  const loading = vin && !error && !(data && data.car.vin === vin)
  const distUnit = U.us ? 'mi' : 'km'
  const shownKm = U.us ? sum.km * 0.621371 : sum.km

  return (
    <div className="settings history">
      <div className="set-head">
        <div>
          <h2>History</h2>
          <p className="muted small">
            One point per drive. Short logs under a minute are listed but left out of the charts.
          </p>
        </div>
        <button className="btn ghost" onClick={onClose}>
          Done
        </button>
      </div>

      {error && <div className="banner bad">{error}</div>}
      {cars && cars.length === 0 && (
        <div className="card">
          <p className="muted">No drives logged yet. Start a session, then come back here.</p>
        </div>
      )}

      {cars && cars.length > 0 && (
        <div className="card set-scope">
          <label htmlFor="hist-car">Car</label>
          <select id="hist-car" value={vin || ''} onChange={(e) => setVin(e.target.value)}>
            {cars.map((c) => (
              <option key={c.vin} value={c.vin}>
                {c.display_name}
                {c.vin.startsWith('unknown') ? '' : ` · ${c.vin.slice(-6)}`} · {c.session_count} drive
                {c.session_count === 1 ? '' : 's'}
              </option>
            ))}
          </select>
          {sum.count > 0 && (
            <p className="muted small">
              {sum.count} drive{sum.count === 1 ? '' : 's'} · {fmt(shownKm)} {distUnit} driven · since{' '}
              {fmtStamp(sum.first)}
            </p>
          )}
        </div>
      )}

      {loading && <p className="muted">Loading…</p>}

      {drives.length > 0 && (
        <>
          <div className="trend-grid-wrap">
            {defs.map((def) => (
              <TrendChart
                key={def.key}
                title={def.title}
                hint={def.hint}
                unit={def.unit}
                decimals={def.decimals}
                band={def.band}
                points={trendPoints(drives, def.key, def.convert)}
              />
            ))}
          </div>

          <div className="card hist-table">
            <h3>All drives</h3>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Length</th>
                    <th>{distUnit}</th>
                    <th>Start {U.temp}</th>
                    <th>Max {U.temp}</th>
                    <th>Warm-up min</th>
                    <th>Volts</th>
                    <th>Result</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {[...drives].reverse().map((d) => (
                    <Row key={d.stamp} vin={vin} d={d} U={U} />
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted small">
              The warm-up column is only filled for cold starts. Volts is the average while the engine ran.
            </p>
          </div>
        </>
      )}
    </div>
  )
}
