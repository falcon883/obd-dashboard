import { DEFAULT_LIMITS, parseStamp } from './format.js'

/** How a drive's overall verdict is shown: [pill class, label]. Shared by the garage list and the History table. */
export const VERDICT = { ok: ['ok', 'OK'], warn: ['warn', 'Warnings'], crit: ['bad', 'Critical'] }

export function fmtShortDate(stamp) {
  const d = parseStamp(stamp)
  return d ? d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : stamp
}

/**
 * The points for one trend chart: the drives long enough to count that have a value for `key`, oldest first
 * (the server already sorts them). `convert` changes units for display only.
 */
export function trendPoints(drives, key, convert = (v) => v) {
  return drives
    .filter((d) => d.in_trends && d[key] != null)
    .map((d) => ({ stamp: d.stamp, label: fmtShortDate(d.stamp), value: convert(d[key]) }))
}

export function totals(drives) {
  return {
    count: drives.length,
    km: drives.reduce((sum, d) => sum + (d.distance_km || 0), 0),
    first: drives.length ? drives[0].stamp : null,
    last: drives.length ? drives[drives.length - 1].stamp : null,
  }
}

/**
 * The charts on the History screen. `band` is the range the live dashboard treats as normal (limits in force
 * by default); points outside it are drawn in the warning colour.
 */
export function trendDefs(U, limits = DEFAULT_LIMITS) {
  return [
    {
      key: 'warm_80_min',
      title: 'Warm-up time',
      unit: 'min',
      decimals: 1,
      hint: `Minutes to reach ${Math.round(U.t(80))} ${U.temp} on a cold start. A thermostat stuck open takes much longer.`,
    },
    {
      key: 'coolant_max_c',
      title: 'Hottest coolant',
      unit: U.temp,
      decimals: 0,
      convert: U.t,
      band: [U.t(limits.warmed_up_c), U.t(limits.coolant_warn_c)],
      hint: 'The peak of each drive. A slow climb over weeks can point to a cooling problem.',
    },
    {
      key: 'battery_avg_v',
      title: 'Charging voltage',
      unit: 'V',
      decimals: 1,
      band: [limits.battery_low_running_v, limits.battery_high_running_v],
      hint: 'Average battery voltage while the engine ran. A downward drift can mean a tiring alternator or battery.',
    },
    {
      key: 'ltft_avg_pct',
      title: 'Long-term fuel trim',
      unit: '%',
      decimals: 1,
      band: [-limits.ltft_warn_pct, limits.ltft_warn_pct],
      hint: 'How much fuel the engine computer adds or removes on average. Growing values point to a leak or a dirty sensor.',
    },
    {
      key: 'warm_idle_rpm',
      title: 'Warm idle speed',
      unit: 'rpm',
      decimals: 0,
      band: [limits.idle_rpm_min, limits.idle_rpm_max],
      hint: 'Engine speed standing still once warm. A rough or hunting idle shows up here.',
    },
  ]
}
