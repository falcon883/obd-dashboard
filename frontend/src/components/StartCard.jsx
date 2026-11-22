import { useEffect, useState } from 'react'
import { api } from '../api.js'

/** Shown when no session is running: pick the port, start the car (or the demo). */
export default function StartCard({ status, serverUp }) {
  const [ports, setPorts] = useState([])
  const [port, setPort] = useState('')
  const [baud, setBaud] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const refresh = () =>
    api
      .ports()
      .then((p) => {
        setPorts(p)
        const ch = p.find((x) => /CH340/i.test(x.description))
        setPort((cur) => cur || (ch ? ch.device : ''))
      })
      .catch(() => {})

  useEffect(() => {
    if (serverUp) refresh()
  }, [serverUp])

  const start = async (demo) => {
    setBusy(true)
    setErr('')
    try {
      const r = await api.start({ port: port || null, baud: baud ? Number(baud) : 0, demo })
      if (!r.ok) setErr(r.message || 'Could not start')
    } catch {
      setErr('Could not reach the dashboard server')
    }
    setBusy(false)
  }

  const finished = status.state === 'finished'
  const failed = status.state === 'error'

  return (
    <div className="card start">
      <h2>{finished ? 'Session finished' : 'Ready to monitor your car'}</h2>
      <p className="muted">
        Plug the adapter into the OBD port (MS/HS switch on <b>HS</b>), start the engine, then press Start.
      </p>

      {failed && (
        <div className="alert bad">
          <span>{status.message}</span>
        </div>
      )}

      {finished && status.result && (
        <div className="summary">
          {status.result.csv && (
            <p className="muted small">
              Saved <code>{status.result.csv}</code> and <code>{status.result.report}</code>
            </p>
          )}
          <pre>{(status.result.summary || []).join('\n')}</pre>
        </div>
      )}

      <div className="start-form">
        <label>
          Port
          <select value={port} onChange={(e) => setPort(e.target.value)}>
            <option value="">Auto-detect (CH340)</option>
            {ports.map((p) => (
              <option key={p.device} value={p.device}>
                {p.device} — {p.description}
              </option>
            ))}
          </select>
        </label>
        <label>
          Baud
          <input type="number" placeholder="Auto" value={baud} onChange={(e) => setBaud(e.target.value)} />
        </label>
        <button className="btn ghost" onClick={refresh} title="Rescan ports">
          Rescan
        </button>
      </div>
      {err && (
        <div className="alert warn">
          <span>{err}</span>
        </div>
      )}
      <div className="start-actions">
        <button className="btn primary" disabled={busy || !serverUp} onClick={() => start(false)}>
          Start monitoring
        </button>
        <button className="btn" disabled={busy || !serverUp} onClick={() => start(true)}>
          Try the demo
        </button>
      </div>
    </div>
  )
}
