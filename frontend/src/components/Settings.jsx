import { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'

const round1 = (x) => Math.round(x * 10) / 10

/** Everything is stored in the car's units (Celsius); temperature fields are shown in the user's unit. */
const toShown = (f, v, U) => (f.kind === 'temp' && U.us ? round1((v * 9) / 5 + 32) : v)
const fromShown = (f, x, U) => (f.kind === 'temp' && U.us ? Math.round(((x - 32) * 5 * 100) / 9) / 100 : x)
const unitOf = (f, U) => (f.kind === 'temp' ? U.temp : f.unit || '')

function rangeHint(f, U) {
  if (f.min == null || f.max == null) return ''
  return `${toShown(f, f.min, U)}–${toShown(f, f.max, U)} ${unitOf(f, U)}`.trim()
}

function groups(fields) {
  const out = []
  for (const f of fields) {
    let g = out.find((x) => x.title === f.group)
    if (!g) out.push((g = { title: f.group, fields: [] }))
    g.fields.push(f)
  }
  return out
}

/**
 * One editable list of settings. `current` is what is in force for this scope, `base` is what it falls back to
 * when reset (the built-in defaults, or the all-cars values when editing a single car).
 */
function Form({ fields, current, base, U, onSave, onReset, resetLabel, busy }) {
  const initial = useMemo(() => {
    const out = {}
    for (const f of fields)
      out[f.key] = f.kind === 'bool' ? current[f.key] : String(toShown(f, current[f.key], U))
    return out
  }, [fields, current, U])
  const [draft, setDraft] = useState(initial)
  const [localError, setLocalError] = useState('')

  const edited = (f) => draft[f.key] !== initial[f.key]
  const dirty = fields.some(edited)
  const differsFromBase = (f) =>
    f.kind === 'bool'
      ? draft[f.key] !== base[f.key]
      : Math.abs(Number(draft[f.key]) - toShown(f, base[f.key], U)) > 0.049

  const save = () => {
    const values = {}
    for (const f of fields) {
      if (!edited(f)) {
        values[f.key] = current[f.key] // untouched: send the exact stored value, no unit round-trip
      } else if (f.kind === 'bool') {
        values[f.key] = draft[f.key]
      } else {
        const x = Number(draft[f.key])
        if (draft[f.key].trim() === '' || Number.isNaN(x)) return setLocalError(`${f.label}: enter a number`)
        const lo = toShown(f, f.min, U)
        const hi = toShown(f, f.max, U)
        if (x < lo - 0.05 || x > hi + 0.05) {
          return setLocalError(`${f.label}: must be between ${lo} and ${hi} ${unitOf(f, U)}`.trim())
        }
        values[f.key] = fromShown(f, x, U)
      }
    }
    setLocalError('')
    onSave(values)
  }

  return (
    <>
      {groups(fields).map((g) => (
        <section className="card set-group" key={g.title}>
          <div className="card-title">{g.title}</div>
          {g.fields.map((f) => (
            <div className={`set-row${differsFromBase(f) ? ' changed' : ''}`} key={f.key}>
              <div className="set-text">
                <label htmlFor={`s-${f.key}`}>{f.label}</label>
                <span className="set-help">
                  {f.help}
                  {f.help && f.kind !== 'bool' && ' '}
                  {f.kind !== 'bool' && <em>Allowed: {rangeHint(f, U)}</em>}
                </span>
              </div>
              <div className="set-input">
                {f.kind === 'bool' ? (
                  <input
                    id={`s-${f.key}`}
                    type="checkbox"
                    checked={!!draft[f.key]}
                    onChange={(e) => setDraft({ ...draft, [f.key]: e.target.checked })}
                  />
                ) : (
                  <>
                    <input
                      id={`s-${f.key}`}
                      type="number"
                      step="any"
                      inputMode="decimal"
                      value={draft[f.key]}
                      onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                    />
                    <span className="set-unit">{unitOf(f, U)}</span>
                  </>
                )}
                <span className="set-reset-slot">
                  {differsFromBase(f) && (
                    <button
                      type="button"
                      className="link-btn"
                      title="Put back the default"
                      onClick={() =>
                        setDraft({
                          ...draft,
                          [f.key]: f.kind === 'bool' ? base[f.key] : String(toShown(f, base[f.key], U)),
                        })
                      }
                    >
                      ↺ {f.kind === 'bool' ? (base[f.key] ? 'on' : 'off') : toShown(f, base[f.key], U)}
                    </button>
                  )}
                </span>
              </div>
            </div>
          ))}
        </section>
      ))}
      {localError && <div className="banner warn">{localError}</div>}
      <div className="set-actions">
        <button className="btn primary" disabled={busy || !dirty} onClick={save}>
          Save
        </button>
        <button className="btn ghost" disabled={busy || !dirty} onClick={() => setDraft(initial)}>
          Undo edits
        </button>
        <span className="grow" />
        <button
          className="btn ghost"
          disabled={busy}
          onClick={() => window.confirm(`${resetLabel}?`) && onReset()}
        >
          {resetLabel}
        </button>
      </div>
    </>
  )
}

export default function Settings({ U, running, onClose }) {
  const [data, setData] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [tab, setTab] = useState('limits')
  const [scope, setScope] = useState('all') // 'all' or a VIN
  const [notice, setNotice] = useState(null) // { ok, lines }
  const [rev, setRev] = useState(0) // bumps after a save so the form restarts from the stored values
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    api
      .settings()
      .then((d) => alive && setData(d))
      .catch(() => alive && setLoadError('Could not load settings from the dashboard server.'))
    return () => {
      alive = false
    }
  }, [])

  const car = data?.cars.find((c) => c.vin === scope)
  const limits = useMemo(() => {
    if (!data) return null
    return car
      ? { current: { ...data.thresholds, ...car.overrides }, base: data.thresholds }
      : { current: data.thresholds, base: data.defaults }
  }, [data, car])

  const run = async (call, okText) => {
    setBusy(true)
    setNotice(null)
    try {
      const r = await call()
      if (r.ok) {
        setData(r.data)
        setRev((n) => n + 1)
        setNotice({ ok: true, lines: [okText] })
      } else {
        setNotice({ ok: false, lines: r.problems })
      }
    } catch {
      setNotice({ ok: false, lines: ['Could not reach the dashboard server.'] })
    }
    setBusy(false)
  }

  const switchTab = (t) => {
    setTab(t)
    setNotice(null)
  }

  return (
    <div className="settings">
      <div className="set-head">
        <div>
          <h2>Settings</h2>
          <p className="muted small">
            Changes apply from the next session{running ? ' (the current one keeps its limits)' : ''}.
          </p>
        </div>
        <button className="btn ghost" onClick={onClose}>
          Done
        </button>
      </div>

      <div className="seg" role="tablist" aria-label="Settings sections">
        <button className={tab === 'limits' ? 'on' : ''} onClick={() => switchTab('limits')}>
          Alert limits
        </button>
        <button className={tab === 'advanced' ? 'on' : ''} onClick={() => switchTab('advanced')}>
          Advanced
        </button>
      </div>

      {loadError && <div className="banner bad">{loadError}</div>}
      {!data && !loadError && <p className="muted">Loading…</p>}

      {notice && (
        <div className={`banner ${notice.ok ? 'info' : 'bad'}`} role="status">
          {notice.lines.length > 1 ? (
            <ul>
              {notice.lines.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          ) : (
            notice.lines[0]
          )}
        </div>
      )}

      {data && tab === 'limits' && (
        <>
          <div className="card set-scope">
            <label htmlFor="scope">Applies to</label>
            <select
              id="scope"
              value={scope}
              onChange={(e) => {
                setScope(e.target.value)
                setNotice(null)
              }}
            >
              <option value="all">All cars (the defaults)</option>
              {data.cars.map((c) => (
                <option key={c.vin} value={c.vin}>
                  {c.name} · {c.vin.slice(-6)}
                  {Object.keys(c.overrides).length ? ' · custom' : ''}
                </option>
              ))}
            </select>
            <p className="muted small">
              {car
                ? 'Only this car uses these. Everything you leave alone keeps following the all-cars values.'
                : 'Used by every car without its own limits. Different engine? Pick the car above to give it its own.'}
            </p>
          </div>
          <Form
            key={`${scope}-${rev}-${U.us}`}
            fields={data.schema.thresholds}
            current={limits.current}
            base={limits.base}
            U={U}
            busy={busy}
            resetLabel={car ? 'Use the all-cars limits' : 'Reset all limits to defaults'}
            onSave={(values) => run(() => api.saveLimits(values, car?.vin), 'Saved.')}
            onReset={() =>
              run(
                () => api.resetSettings('thresholds', car?.vin),
                car ? 'This car now follows all cars.' : 'Reset.',
              )
            }
          />
        </>
      )}

      {data && tab === 'advanced' && (
        <>
          <Form
            key={`adv-${rev}`}
            fields={data.schema.advanced}
            current={data.advanced}
            base={data.advanced_defaults}
            U={U}
            busy={busy}
            resetLabel="Reset advanced options"
            onSave={(values) => run(() => api.saveAdvanced(values), 'Saved.')}
            onReset={() => run(() => api.resetSettings('advanced'), 'Reset.')}
          />
          <p className="muted small">
            The port, baud rate and log folder are chosen on the Start card or with command-line options (
            <code>obd-dashboard --help</code>).
          </p>
        </>
      )}
    </div>
  )
}
