import { fmt, fmtDuration } from './format.js'

const KM_TO_MI = 0.621371

/** How a finished drive is headlined: the pill status (see StatusIcon), a title and one line under it. */
export const HEADLINE = {
  ok: { status: 'ok', title: 'All good', note: 'No alerts came up during this drive.' },
  warn: { status: 'warn', title: 'Some warnings', note: 'Nothing urgent, but worth a look below.' },
  crit: { status: 'bad', title: 'Needs attention', note: 'Something serious came up during this drive.' },
}

/** 'C:\\logs\\VIN\\20261123_141751_report.txt' -> '20261123_141751_report.txt' */
export const fileName = (path) => (path ? String(path).split(/[\\/]/).pop() : null)

/** '[CRIT] Check-engine light is ON' -> { level: 'bad', text: 'Check-engine light is ON' } */
export function parseAlert(line) {
  const m = /^\[(CRIT|WARN)\]\s*(.*)$/.exec(String(line))
  if (!m) return { level: 'warn', text: String(line) }
  return { level: m[1] === 'CRIT' ? 'bad' : 'warn', text: m[2] }
}

/** The warm-up tile: time to reach the highest checkpoint the engine got to, or why there is none. */
export function warmupTile(o, U) {
  for (const t of ['85', '80', '70']) {
    const sec = o.warm_s?.[t]
    if (sec != null)
      return { value: fmt(sec / 60, 1), unit: 'min', sub: `to ${fmt(U.t(Number(t)))} ${U.temp}` }
  }
  const started = o.start_coolant_c
  if (started != null && started >= 70) return { value: 'Warm', unit: '', sub: 'engine started warm' }
  return { value: '—', unit: '', sub: o.coolant_max_c == null ? 'no coolant reading' : 'never reached 70 °C' }
}

/** The number tiles on the finished screen, in the user's units. Blank values stay blank, never zero. */
export function outcomeTiles(o, U) {
  const km = o.distance_km
  const warm = warmupTile(o, U)
  return [
    { key: 'time', label: 'Drive time', value: fmtDuration(o.duration_s), unit: '' },
    {
      key: 'dist',
      label: 'Distance',
      value: km ? fmt(U.us ? km * KM_TO_MI : km, 1) : '—',
      unit: km ? (U.us ? 'mi' : 'km') : '',
    },
    {
      key: 'hot',
      label: 'Hottest coolant',
      value: fmt(U.t(o.coolant_max_c)),
      unit: o.coolant_max_c == null ? '' : U.temp,
      sub: o.start_coolant_c == null ? undefined : `started at ${fmt(U.t(o.start_coolant_c))} ${U.temp}`,
    },
    { key: 'warm', label: 'Warm-up', ...warm },
    {
      key: 'volts',
      label: 'Charging voltage',
      value: fmt(o.battery_avg_v, 1),
      unit: o.battery_avg_v == null ? '' : 'V',
      sub: o.battery_avg_v == null ? 'engine never ran' : 'average, engine running',
    },
    {
      key: 'trim',
      label: 'Long-term fuel trim',
      value: o.ltft_avg_pct == null ? '—' : `${o.ltft_avg_pct > 0 ? '+' : ''}${fmt(o.ltft_avg_pct, 1)}`,
      unit: o.ltft_avg_pct == null ? '' : '%',
      sub: 'average',
    },
  ]
}

/** Readings per second over the most recent rows (the live charts' buffer). */
export function streamRate(rows, n = 30) {
  if (rows.length < 2) return null
  const tail = rows.slice(-n)
  const span = tail[tail.length - 1].t - tail[0].t
  return span > 0 ? (tail.length - 1) / span : null
}

/** '2026-11-23T14:18:02' (the logger's local clock) -> 'Nov 23, 2:18 PM' */
export function fmtStarted(iso) {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}
