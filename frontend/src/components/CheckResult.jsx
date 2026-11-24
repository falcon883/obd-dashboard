import { carHeading, checkFileUrl, groupFindings, VERDICT } from '../check.js'
import { StatusIcon } from './Panels.jsx'

function Findings({ items }) {
  return (
    <ul className="findings">
      {items.map((f) => (
        <li key={f.id} className="finding">
          <StatusIcon status={f.level} />
          <span>
            <b>{f.title}</b>
            {f.detail && <span className="finding-detail">{f.detail}</span>}
          </span>
        </li>
      ))}
    </ul>
  )
}

/** The finished used-car check: verdict, what to ask about, what looked fine, and the honest limits. */
export default function CheckResult({ status, onAgain }) {
  const check = status.result.check
  const head = VERDICT[check.verdict] || VERDICT.look
  const { name, vin } = carHeading(check.snapshot)
  const { attention, notes, fine } = groupFindings(check.findings)
  const report = check.files?.report

  return (
    <section className="summary-screen">
      <div className={`card sum-hero ${head.status}`}>
        <div className="sum-icon">
          <StatusIcon status={head.status} />
        </div>
        <div className="sum-title">
          <h2>{head.title}</h2>
          <p className="muted">
            {check.demo ? 'Demo check on a simulated car. Nothing was saved.' : head.note}
          </p>
          <p className="muted small sum-meta">
            {name}
            {vin ? ` · VIN ${vin}` : ''}
          </p>
        </div>
        <div className="sum-actions">
          {report && (
            <a className="btn" href={checkFileUrl(report)} target="_blank" rel="noreferrer">
              Report
            </a>
          )}
          <button className="btn ghost" onClick={onAgain}>
            Check another car
          </button>
        </div>
      </div>

      {attention.length > 0 && (
        <div className="card sum-card">
          <div className="card-title">Ask the seller about</div>
          <Findings items={attention} />
        </div>
      )}
      {notes.length > 0 && (
        <div className="card sum-card">
          <div className="card-title">Good to know</div>
          <Findings items={notes} />
        </div>
      )}
      {fine.length > 0 && (
        <div className="card sum-card">
          <div className="card-title">Looks fine</div>
          <Findings items={fine} />
        </div>
      )}

      <p className="muted small check-caveat">{check.caveat}</p>
    </section>
  )
}
