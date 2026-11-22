import { useMemo, useState } from 'react'
import useObdStream from './hooks/useObdStream.js'
import { api } from './api.js'
import { COLORS, carLine, fmt, fmtDuration, makeUnits } from './format.js'
import Gauge from './components/Gauge.jsx'
import LineChart from './components/LineChart.jsx'
import Garage from './components/Garage.jsx'
import StartCard from './components/StartCard.jsx'
import {
  AlertBanner,
  CodesCard,
  EventLog,
  SensorTable,
  StatusIcon,
  Tile,
  Vitals,
  WarmupCard,
  overallStatus,
} from './components/Panels.jsx'

const RUNNING = ['connecting', 'connected', 'lost']
const WINDOWS = [
  [120, '2 min'],
  [300, '5 min'],
  [600, '10 min'],
]

function loadUnits() {
  try {
    return localStorage.getItem('obd-units') || 'us'
  } catch {
    return 'us'
  }
}

function StatusPill({ status, serverUp }) {
  let cls = 'idle'
  let text = 'Idle'
  if (serverUp === false) ((cls = 'bad'), (text = 'Server offline'))
  else if (status.state === 'connecting') ((cls = 'warn pulse'), (text = 'Connecting…'))
  else if (status.state === 'connected') ((cls = 'ok pulse'), (text = 'Live'))
  else if (status.state === 'lost') ((cls = 'warn pulse'), (text = 'Reconnecting…'))
  else if (status.state === 'error') ((cls = 'bad'), (text = 'Error'))
  else if (status.state === 'finished') text = 'Finished'
  return (
    <span className={`pill ${cls}`}>
      <i />
      {text}
    </span>
  )
}

export default function App() {
  const { serverUp, status, info, rows, last, events } = useObdStream()
  const [sys, setSys] = useState(loadUnits)
  const [win, setWin] = useState(120)
  const U = useMemo(() => makeUnits(sys), [sys])
  const running = RUNNING.includes(status.state)
  const v = last?.values || {}
  const overall = overallStatus(last)

  const setUnits = (s) => {
    setSys(s)
    try {
      localStorage.setItem('obd-units', s)
    } catch {
      /* private mode etc. */
    }
  }

  const engineOn = v.RPM != null && v.RPM > 400
  const cool = v.COOLANT_TEMP
  const coolSub =
    cool == null
      ? ''
      : cool < 70
        ? 'Warming up'
        : cool >= 108
          ? 'Overheating'
          : cool >= 102
            ? 'Running hot'
            : 'Normal'
  const battZones = engineOn
    ? [
        { from: 10, to: 12, color: COLORS.bad },
        { from: 12, to: 13, color: COLORS.warn },
        { from: 13, to: 15, color: COLORS.ok },
        { from: 15, to: 16.1, color: COLORS.warn },
      ]
    : [
        { from: 10, to: 11.8, color: COLORS.bad },
        { from: 11.8, to: 12.4, color: COLORS.warn },
        { from: 12.4, to: 15, color: COLORS.ok },
        { from: 15, to: 16.1, color: COLORS.warn },
      ]

  const showStart = !running
  const hasData = !!last

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <svg width="34" height="34" viewBox="0 0 32 32" aria-hidden="true">
            <circle
              cx="16"
              cy="16"
              r="13"
              fill="none"
              stroke={COLORS.ok}
              strokeWidth="2.6"
              strokeOpacity=".35"
            />
            <path
              d="M5.2 21a11.5 11.5 0 1 1 21.6 0"
              fill="none"
              stroke={COLORS.ok}
              strokeWidth="2.6"
              strokeLinecap="round"
            />
            <path d="M16 18l5.5-6.5" stroke="#f1f5f9" strokeWidth="2.6" strokeLinecap="round" />
          </svg>
          <div>
            <h1>OBD Live</h1>
            <span className="sub" title={info?.car?.vin ? `VIN ${info.car.vin}` : undefined}>
              {info?.car
                ? carLine(info.car)
                : info
                  ? `${info.protocol}${info.port ? ` · ${info.port}` : ''}`
                  : 'Engine & emissions monitor'}
            </span>
          </div>
        </div>
        <div className="top-right">
          {info?.demo && <span className="pill demo">DEMO DATA</span>}
          <StatusPill status={status} serverUp={serverUp} />
          {hasData && (
            <span className={`pill health ${overall.status}`}>
              <StatusIcon status={overall.status} />
              {overall.text}
              {overall.count > 1 ? ` · ${overall.count}` : ''}
            </span>
          )}
          {hasData && (
            <span className="clock" title="Session time">
              {fmtDuration(last.t)}
            </span>
          )}
          <div className="seg" role="group" aria-label="Units">
            <button className={sys === 'us' ? 'on' : ''} onClick={() => setUnits('us')}>
              °F · mph
            </button>
            <button className={sys === 'metric' ? 'on' : ''} onClick={() => setUnits('metric')}>
              °C · km/h
            </button>
          </div>
          {running && (
            <button className="btn danger" onClick={() => api.stop()}>
              Stop
            </button>
          )}
        </div>
      </header>

      {serverUp === false && (
        <div className="banner bad">
          Can&apos;t reach the dashboard server. Start it with <code>obd-dashboard</code> and keep that window
          open.
        </div>
      )}
      {status.state === 'lost' && <div className="banner warn">{status.message}</div>}
      {status.state === 'connecting' && (
        <div className="banner info">
          <span className="spin" /> {status.message}
        </div>
      )}

      {showStart && <StartCard status={status} serverUp={serverUp} />}
      {showStart && <Garage serverUp={serverUp} status={status} />}
      {hasData && <AlertBanner last={last} />}

      {(running || hasData) && (
        <div className="layout">
          <main>
            <section className="gauges">
              <Gauge
                label="Engine speed"
                value={v.RPM}
                min={0}
                max={7000}
                unit="rpm"
                ticks={7}
                maxLabel="7,000"
                zones={[
                  { from: 0, to: 5500, color: COLORS.info },
                  { from: 5500, to: 6500, color: COLORS.warn },
                  { from: 6500, to: 7001, color: COLORS.bad },
                ]}
                sub={v.RPM == null ? '' : v.RPM < 400 ? 'Engine off' : v.SPEED === 0 ? 'Idling' : 'Running'}
              />
              <Gauge
                label="Speed"
                value={U.s(v.SPEED)}
                min={0}
                max={U.us ? 120 : 200}
                unit={U.speed}
                ticks={6}
                accent={COLORS.violet}
                sub={v.SPEED == null ? '' : v.SPEED > 0 ? 'Moving' : 'Stopped'}
              />
              <Gauge
                label="Coolant temperature"
                value={U.t(cool)}
                min={U.t(40)}
                max={U.t(120)}
                unit={U.temp}
                ticks={8}
                zones={[
                  { from: U.t(40), to: U.t(70), color: COLORS.cold },
                  { from: U.t(70), to: U.t(102), color: COLORS.ok },
                  { from: U.t(102), to: U.t(108), color: COLORS.warn },
                  { from: U.t(108), to: U.t(121), color: COLORS.bad },
                ]}
                sub={coolSub}
              />
              <Gauge
                label="Battery"
                value={v.battery_v}
                min={10}
                max={16}
                unit="volts"
                decimals={1}
                ticks={6}
                zones={battZones}
                sub={v.battery_v == null ? '' : engineOn ? 'Charging' : 'Engine off'}
              />
            </section>

            <section>
              <div className="section-head">
                <h3>Live charts</h3>
                <div className="seg small" role="group" aria-label="Chart window">
                  {WINDOWS.map(([s, label]) => (
                    <button key={s} className={win === s ? 'on' : ''} onClick={() => setWin(s)}>
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="charts">
                <LineChart
                  title="Engine speed"
                  unit="rpm"
                  rows={rows}
                  windowSec={win}
                  yMin={0}
                  series={[{ label: 'RPM', color: COLORS.info, get: (x) => x.RPM }]}
                />
                <LineChart
                  title="Vehicle speed"
                  unit={U.speed}
                  rows={rows}
                  windowSec={win}
                  yMin={0}
                  series={[{ label: 'Speed', color: COLORS.violet, get: (x) => U.s(x.SPEED) }]}
                />
                <LineChart
                  title="Coolant temperature"
                  unit={U.temp}
                  rows={rows}
                  windowSec={win}
                  thresholds={[{ y: U.t(102), color: COLORS.warn }]}
                  series={[{ label: 'Coolant', color: COLORS.orange, get: (x) => U.t(x.COOLANT_TEMP) }]}
                />
                <LineChart
                  title="Fuel trims"
                  unit="%"
                  decimals={1}
                  rows={rows}
                  windowSec={win}
                  yMin={-15}
                  yMax={15}
                  thresholds={[
                    { y: 10, color: COLORS.warn },
                    { y: -10, color: COLORS.warn },
                  ]}
                  series={[
                    { label: 'Short', color: COLORS.violet, get: (x) => x.SHORT_FUEL_TRIM_1 },
                    { label: 'Long', color: COLORS.ok, get: (x) => x.LONG_FUEL_TRIM_1 },
                  ]}
                />
                <LineChart
                  title="Engine load & throttle"
                  unit="%"
                  rows={rows}
                  windowSec={win}
                  yMin={0}
                  yMax={100}
                  series={[
                    { label: 'Load', color: COLORS.info, get: (x) => x.ENGINE_LOAD },
                    { label: 'Throttle', color: COLORS.pink, get: (x) => x.THROTTLE_POS },
                  ]}
                />
                <LineChart
                  title="Battery voltage"
                  unit="V"
                  decimals={1}
                  rows={rows}
                  windowSec={win}
                  yMin={11}
                  yMax={16}
                  thresholds={[{ y: 13, color: COLORS.warn }]}
                  series={[{ label: 'Volts', color: COLORS.ok, get: (x) => x.battery_v }]}
                />
              </div>
            </section>

            <section className="card">
              <div className="card-title">Live readings</div>
              <div className="tiles">
                {v.ENGINE_LOAD != null && (
                  <Tile
                    label="Engine load"
                    value={fmt(v.ENGINE_LOAD)}
                    unit="%"
                    bar={v.ENGINE_LOAD}
                    color={COLORS.info}
                  />
                )}
                {v.THROTTLE_POS != null && (
                  <Tile
                    label="Throttle"
                    value={fmt(v.THROTTLE_POS)}
                    unit="%"
                    bar={v.THROTTLE_POS}
                    color={COLORS.pink}
                  />
                )}
                {v.INTAKE_PRESSURE != null && (
                  <Tile label="Manifold pressure" value={fmt(v.INTAKE_PRESSURE)} unit="kPa" />
                )}
                {v.TIMING_ADVANCE != null && (
                  <Tile label="Timing advance" value={fmt(v.TIMING_ADVANCE, 1)} unit="°" />
                )}
                {v.INTAKE_TEMP != null && (
                  <Tile label="Intake air" value={fmt(U.t(v.INTAKE_TEMP))} unit={U.temp} />
                )}
                {v.AMBIANT_AIR_TEMP != null && (
                  <Tile label="Outside air" value={fmt(U.t(v.AMBIANT_AIR_TEMP))} unit={U.temp} />
                )}
                {v.FUEL_LEVEL != null && (
                  <Tile
                    label="Fuel level"
                    value={fmt(v.FUEL_LEVEL)}
                    unit="%"
                    bar={v.FUEL_LEVEL}
                    color={v.FUEL_LEVEL < 10 ? COLORS.warn : COLORS.ok}
                  />
                )}
                {v.FUEL_RAIL_PRESSURE_ABS != null && (
                  <Tile label="Fuel rail pressure" value={fmt(v.FUEL_RAIL_PRESSURE_ABS)} unit="kPa" />
                )}
                {v.CATALYST_TEMP_B1S1 != null && (
                  <Tile label="Catalyst in" value={fmt(U.t(v.CATALYST_TEMP_B1S1))} unit={U.temp} />
                )}
                {v.CATALYST_TEMP_B1S2 != null && (
                  <Tile label="Catalyst out" value={fmt(U.t(v.CATALYST_TEMP_B1S2))} unit={U.temp} />
                )}
                {v.O2_B1S2 != null && (
                  <Tile label="O₂ sensor (after cat)" value={fmt(v.O2_B1S2, 2)} unit="V" />
                )}
                {v.FUEL_STATUS != null && (
                  <Tile
                    label="Fuel loop"
                    value={String(v.FUEL_STATUS).startsWith('closed') ? 'Closed loop' : 'Open loop'}
                    sub={
                      String(v.FUEL_STATUS).startsWith('closed') ? 'Using O₂ feedback' : 'Engine still cold'
                    }
                    color={String(v.FUEL_STATUS).startsWith('closed') ? COLORS.ok : COLORS.cold}
                  />
                )}
                {v.RUN_TIME != null && <Tile label="Engine run time" value={fmtDuration(v.RUN_TIME)} />}
                {v.BAROMETRIC_PRESSURE != null && (
                  <Tile label="Barometer" value={fmt(v.BAROMETRIC_PRESSURE)} unit="kPa" />
                )}
              </div>
            </section>

            <SensorTable info={info} last={last} U={U} />

            {info && (
              <footer className="foot">
                {info.static?.VIN && <span>VIN {info.static.VIN}</span>}
                {info.csv && (
                  <span>
                    Logging to <code>{info.csv}</code> + <code>{info.report}</code>
                  </span>
                )}
                {info.demo && <span>Simulated data — nothing is being saved.</span>}
              </footer>
            )}
          </main>

          <aside>
            <Vitals last={last} U={U} />
            <WarmupCard last={last} U={U} />
            <CodesCard last={last} />
            <EventLog events={events} />
          </aside>
        </div>
      )}
    </div>
  )
}
