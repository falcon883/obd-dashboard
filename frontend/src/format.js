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
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
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

// Thresholds mirror the backend rules (src/obd_dashboard/rules.py) so alerts and vitals agree.
export const LIMITS = {
  runningRpm: 400,
  coolantWarn: 102,
  coolantCrit: 108,
  coolantCold: 70,
  chargingLow: 13,
  chargingHigh: 15,
  batteryOff: 12,
  trimWarn: 10,
  trimCrit: 20,
  catWarn: 950,
  catCrit: 1000,
  misfireRise: 10,
  fuelLow: 10,
}

const rateCoolant = (c) => {
  if (c < LIMITS.coolantCold) return info('Warming up')
  if (c >= LIMITS.coolantCrit) return bad('Overheating')
  if (c >= LIMITS.coolantWarn) return warn('Running hot')
  return ok('Normal')
}

const rateBattery = (volts, running) => {
  if (running && volts < LIMITS.chargingLow) return warn('Charging low')
  if (running && volts > LIMITS.chargingHigh) return warn('Overcharging')
  if (!running && volts < LIMITS.batteryOff) return warn('Weak battery')
  return ok(running ? 'Charging OK' : 'Battery OK')
}

const rateTrim = (lt) => {
  const a = Math.abs(lt)
  if (a >= LIMITS.trimCrit) return bad(lt > 0 ? 'Very lean' : 'Very rich')
  if (a >= LIMITS.trimWarn) return warn(lt > 0 ? 'Running lean' : 'Running rich')
  return ok('Balanced')
}

const rateCatalyst = (m) => {
  if (m >= LIMITS.catCrit) return bad('Too hot')
  if (m >= LIMITS.catWarn) return warn('Very hot')
  return ok('Normal')
}

const rateMisfires = (rise) => {
  if (rise >= LIMITS.misfireRise) return warn(`Rising (+${fmt(rise)})`)
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
 * v = latest sensor values (metric), last = latest row payload, U = unit helpers from makeUnits().
 * Returns [{ id, label, value, status: 'ok' | 'warn' | 'bad' | 'info', note }].
 */
export function buildChecks(v, last, U) {
  const out = []
  const running = v.RPM != null && v.RPM > LIMITS.runningRpm

  if (v.COOLANT_TEMP != null) {
    const c = v.COOLANT_TEMP
    out.push({ id: 'coolant', label: 'Coolant', value: `${fmt(U.t(c))}${U.temp}`, ...rateCoolant(c) })
  }

  if (v.battery_v != null) {
    out.push({
      id: 'battery',
      label: 'Battery',
      value: `${fmt(v.battery_v, 1)} V`,
      ...rateBattery(v.battery_v, running),
    })
  }

  const lt = v.LONG_FUEL_TRIM_1
  if (lt != null) {
    out.push({ id: 'trim', label: 'Fuel trim', value: `${lt > 0 ? '+' : ''}${fmt(lt, 1)}%`, ...rateTrim(lt) })
  }

  const cats = CATALYST_KEYS.map((k) => v[k]).filter((x) => typeof x === 'number')
  if (cats.length) {
    const hottest = Math.max(...cats)
    out.push({
      id: 'cat',
      label: 'Catalyst',
      value: `${fmt(U.t(hottest))}${U.temp}`,
      ...rateCatalyst(hottest),
    })
  }

  const misfires = last?.misfire?.total
  if (misfires != null) {
    const rise = misfires - (last.misfire0 ?? misfires)
    out.push({ id: 'misfire', label: 'Misfires', value: fmt(misfires), ...rateMisfires(rise) })
  }

  if (last?.codes) {
    out.push({ id: 'codes', label: 'Trouble codes', ...rateCodes(last.codes) })
  }

  if (v.FUEL_LEVEL != null) {
    const low = v.FUEL_LEVEL < LIMITS.fuelLow
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
