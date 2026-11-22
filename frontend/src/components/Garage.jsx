import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDuration, fmtStamp } from '../format.js'

const VERDICT = { ok: ['ok', 'OK'], warn: ['warn', 'Warnings'], crit: ['bad', 'Critical'] }
const SHOWN = 5

function Session({ vin, s }) {
  const [cls, label] = VERDICT[s.verdict] || ['idle', s.complete ? '—' : 'Incomplete']
  return (
    <li className="sess">
      <span className="sess-when">{fmtStamp(s.stamp)}</span>
      <span className="sess-dur muted">{s.duration_s != null ? fmtDuration(s.duration_s) : '—'}</span>
      <span className={`pill ${cls}`}>
        <i />
        {label}
      </span>
      <span className="sess-links">
        {s.files.report && (
          <a href={api.fileUrl(vin, s.files.report)} target="_blank" rel="noreferrer">
            Report
          </a>
        )}
        <a href={api.fileUrl(vin, s.files.csv)} download>
          CSV
        </a>
      </span>
    </li>
  )
}

function CarRow({ car, onRename }) {
  const [all, setAll] = useState(false)
  const list = all ? car.sessions : car.sessions.slice(0, SHOWN)
  const rename = () => {
    const name = window.prompt('Nickname for this car (leave empty to remove):', car.nickname || '')
    if (name !== null) onRename(car.vin, name)
  }
  const details = [
    car.nickname ? car.title : null,
    car.engine,
    car.vin.startsWith('unknown') ? null : `VIN ${car.vin}`,
  ]
  return (
    <div className="car-row">
      <div className="car-head">
        <div>
          <div className="car-name">{car.display_name}</div>
          <div className="muted small">{details.filter(Boolean).join(' · ')}</div>
        </div>
        <button className="btn ghost small-btn" onClick={rename}>
          Rename
        </button>
      </div>
      {car.sessions.length === 0 ? (
        <div className="muted small pad">No sessions yet.</div>
      ) : (
        <ul className="sessions">
          {list.map((s) => (
            <Session key={s.stamp} vin={car.vin} s={s} />
          ))}
        </ul>
      )}
      {car.sessions.length > SHOWN && (
        <button className="link-btn" onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${car.sessions.length} sessions`}
        </button>
      )}
    </div>
  )
}

/** Every car you have logged, with its sessions and download links. Shown when no session is running. */
export default function Garage({ serverUp, status }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(false)

  const load = useCallback(() => {
    api
      .garage()
      .then((d) => {
        setData(d)
        setErr(false)
      })
      .catch(() => setErr(true))
  }, [])

  useEffect(() => {
    if (serverUp) load()
  }, [serverUp, status.state, load])

  const rename = async (vin, name) => {
    await api.rename(vin, name)
    load()
  }

  if (err || !data || (data.cars.length === 0 && data.unsorted.length === 0)) return null
  return (
    <div className="card garage">
      <h2>Your cars</h2>
      {data.cars.map((c) => (
        <CarRow key={c.vin} car={c} onRename={rename} />
      ))}
      <p className="muted small foot">
        Logs are saved per car in <code>{data.folder}</code>
        {data.unsorted.length > 0 &&
          ` · ${data.unsorted.length} older loose log file(s) are in that folder too`}
      </p>
    </div>
  )
}
