export const COLORS = {
  ok: '#34d399',
  info: '#38bdf8',
  warn: '#fbbf24',
  bad: '#f87171',
  cold: '#60a5fa',
  violet: '#a78bfa',
  pink: '#f472b6',
  orange: '#fb923c',
}

const C2F = (c) => (c * 9) / 5 + 32
const KPH2MPH = (k) => k * 0.621371

/** Unit helpers. Everything arrives from the car in metric; convert only for display. */
export function makeUnits(sys) {
  const us = sys === 'us'
  return {
    us,
    temp: us ? '°F' : '°C',
    speed: us ? 'mph' : 'km/h',
    t: (c) => (c == null ? null : us ? C2F(c) : c),
    s: (k) => (k == null ? null : us ? KPH2MPH(k) : k),
  }
}

export function fmt(v, d = 0) {
  if (v == null || Number.isNaN(v)) return '—'
  const n = Number(v)
  return (Object.is(n, -0) || (n < 0 && Math.abs(n) < 0.5 * 10 ** -d) ? 0 : n).toLocaleString('en-US', {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  })
}

export function fmtDuration(sec) {
  if (sec == null || Number.isNaN(sec)) return '—'
  const s = Math.max(0, Math.round(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = s % 60
  const pad = (n) => String(n).padStart(2, '0')
  return h ? `${h}:${pad(m)}:${pad(r)}` : `${m}:${pad(r)}`
}

export const UNIT_LABEL = {
  degree_Celsius: '°C',
  kilometer_per_hour: 'km/h',
  percent: '%',
  volt: 'V',
  kilopascal: 'kPa',
  pascal: 'Pa',
  revolutions_per_minute: 'rpm',
  degree: '°',
  second: 's',
  minute: 'min',
  kilometer: 'km',
  count: '',
  ratio: '',
  milliampere: 'mA',
  gram_per_second: 'g/s',
}

const ok = (note) => ({ status: 'ok', note })
const info = (note) => ({ status: 'info', note })
const warn = (note) => ({ status: 'warn', note })
const bad = (note) => ({ status: 'bad', note })

// Fallback only: a running session reports the limits it really uses (info.thresholds), which can be
// edited on the Settings screen. The names and values match src/obd_dashboard/userconfig.py (a test checks it).
export const DEFAULT_LIMITS = {
  running_rpm: 400,
  coolant_cold_c: 70,
  warmed_up_c: 80,
  coolant_warn_c: 102,
  coolant_crit_c: 108,
  warmup_check_after_min: 20,
  battery_low_running_v: 13,
  battery_high_running_v: 15,
  battery_low_off_v: 12,
  ltft_warn_pct: 10,
  ltft_crit_pct: 20,
  stft_warn_pct: 15,
  stft_window: 30,
  idle_rpm_min: 500,
  idle_rpm_max: 1100,
  catalyst_warn_c: 950,
  catalyst_crit_c: 1000,
  fuel_low_pct: 10,
  misfire_rise: 10,
}

/** The limits in force for this session: the car's own report, over the built-in defaults. */
export const limitsOf = (info) => ({ ...DEFAULT_LIMITS, ...(info?.thresholds || {}) })

const rateCoolant = (c, L) => {
  if (c < L.coolant_cold_c) return info('Warming up')
  if (c >= L.coolant_crit_c) return bad('Overheating')
  if (c >= L.coolant_warn_c) return warn('Running hot')
  return ok('Normal')
}

const rateBattery = (volts, running, L) => {
  if (running && volts < L.battery_low_running_v) return warn('Charging low')
  if (running && volts > L.battery_high_running_v) return warn('Overcharging')
  if (!running && volts < L.battery_low_off_v) return warn('Weak battery')
  return ok(running ? 'Charging OK' : 'Battery OK')
}

const rateTrim = (lt, L) => {
  const a = Math.abs(lt)
  if (a >= L.ltft_crit_pct) return bad(lt > 0 ? 'Very lean' : 'Very rich')
  if (a >= L.ltft_warn_pct) return warn(lt > 0 ? 'Running lean' : 'Running rich')
  return ok('Balanced')
}

const rateCatalyst = (m, L) => {
  if (m >= L.catalyst_crit_c) return bad('Too hot')
  if (m >= L.catalyst_warn_c) return warn('Very hot')
  return ok('Normal')
}

const rateMisfires = (rise, L) => {
  if (rise >= L.misfire_rise) return warn(`Rising (+${fmt(rise)})`)
  return ok(rise > 0 ? `+${fmt(rise)} this session` : 'Quiet')
}

const rateCodes = (codes) => {
  const stored = codes.stored?.length || 0
  const pending = codes.pending?.length || 0
  const value = String(stored + pending)
  if (codes.mil) return { value, ...bad('Check-engine light ON') }
  if (stored) return { value, ...bad('Codes stored') }
  if (pending) return { value, ...warn('Pending code') }
  return { value: '0', ...ok('No codes') }
}

const CATALYST_KEYS = ['CATALYST_TEMP_B1S1', 'CATALYST_TEMP_B1S2', 'CATALYST_TEMP_B2S1', 'CATALYST_TEMP_B2S2']

/**
 * Health rules shown in the "Vitals" panel.
 * v = latest sensor values (metric), last = latest row payload, U = unit helpers from makeUnits(),
 * limits = the session's alert limits (see limitsOf). Returns [{ id, label, value, status: 'ok' | 'warn' | 'bad' | 'info', note }].
 */
export function buildChecks(v, last, U, limits) {
  const L = { ...DEFAULT_LIMITS, ...limits }
  const out = []
  const running = v.RPM != null && v.RPM > L.running_rpm

  if (v.COOLANT_TEMP != null) {
    const c = v.COOLANT_TEMP
    out.push({ id: 'coolant', label: 'Coolant', value: `${fmt(U.t(c))}${U.temp}`, ...rateCoolant(c, L) })
  }

  if (v.battery_v != null) {
    out.push({
      id: 'battery',
      label: 'Battery',
      value: `${fmt(v.battery_v, 1)} V`,
      ...rateBattery(v.battery_v, running, L),
    })
  }

  const lt = v.LONG_FUEL_TRIM_1
  if (lt != null) {
    out.push({
      id: 'trim',
      label: 'Fuel trim',
      value: `${lt > 0 ? '+' : ''}${fmt(lt, 1)}%`,
      ...rateTrim(lt, L),
    })
  }

  const cats = CATALYST_KEYS.map((k) => v[k]).filter((x) => typeof x === 'number')
  if (cats.length) {
    const hottest = Math.max(...cats)
    out.push({
      id: 'cat',
      label: 'Catalyst',
      value: `${fmt(U.t(hottest))}${U.temp}`,
      ...rateCatalyst(hottest, L),
    })
  }

  const misfires = last?.misfire?.total
  if (misfires != null) {
    const rise = misfires - (last.misfire0 ?? misfires)
    out.push({ id: 'misfire', label: 'Misfires', value: fmt(misfires), ...rateMisfires(rise, L) })
  }

  if (last?.codes) {
    out.push({ id: 'codes', label: 'Trouble codes', ...rateCodes(last.codes) })
  }

  if (v.FUEL_LEVEL != null) {
    const low = v.FUEL_LEVEL < L.fuel_low_pct
    out.push({
      id: 'fuel',
      label: 'Fuel',
      value: `${fmt(v.FUEL_LEVEL)}%`,
      status: low ? 'warn' : 'ok',
      note: low ? 'Low' : 'OK',
    })
  }
  return out
}

/** '20261121_214351' -> a local Date (the stamp is the logger's local clock). */
export function parseStamp(stamp) {
  const m = /^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(stamp || '')
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : null
}

export function fmtStamp(stamp) {
  const d = parseStamp(stamp)
  if (!d) return stamp
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

/** The one-line car description used in the header: nickname or "2016 Hyundai Sonata", plus engine. */
export function carLine(car) {
  if (!car) return ''
  const name = car.display_name || car.title || 'Unknown car'
  return car.engine ? `${name} · ${car.engine}` : name
}
