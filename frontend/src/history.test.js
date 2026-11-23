import { describe, expect, it } from 'vitest'
import { DEFAULT_LIMITS, makeUnits } from './format.js'
import { fmtShortDate, totals, trendDefs, trendPoints } from './history.js'

const drive = (stamp, over = {}) => ({
  stamp,
  in_trends: true,
  distance_km: 10,
  coolant_max_c: 90,
  battery_avg_v: 14.2,
  ...over,
})

describe('trend points', () => {
  it('keeps only drives that count and have a value, in the given order', () => {
    const drives = [
      drive('20261120_080000'),
      drive('20261121_080000', { in_trends: false }),
      drive('20261122_080000', { battery_avg_v: null }),
      drive('20261123_080000', { battery_avg_v: 13.9 }),
    ]
    const pts = trendPoints(drives, 'battery_avg_v')
    expect(pts.map((p) => p.stamp)).toEqual(['20261120_080000', '20261123_080000'])
    expect(pts.map((p) => p.value)).toEqual([14.2, 13.9])
  })

  it('converts for display without touching the data', () => {
    const [p] = trendPoints([drive('20261120_080000')], 'coolant_max_c', makeUnits('us').t)
    expect(p.value).toBe(194)
  })

  it('has nothing to plot for an empty history', () => {
    expect(trendPoints([], 'coolant_max_c')).toEqual([])
  })
})

describe('totals and labels', () => {
  it('adds up distance and finds the first and last drive', () => {
    const t = totals([drive('20261120_080000'), drive('20261123_080000', { distance_km: 5.5 })])
    expect(t).toEqual({ count: 2, km: 15.5, first: '20261120_080000', last: '20261123_080000' })
    expect(totals([])).toEqual({ count: 0, km: 0, first: null, last: null })
  })

  it('shows a short date and leaves odd stamps alone', () => {
    expect(fmtShortDate('20261121_214351')).toMatch(/21/)
    expect(fmtShortDate('weird')).toBe('weird')
  })
})

describe('trend definitions', () => {
  it('uses the live dashboard limits as the normal range, in the chosen units', () => {
    const metric = trendDefs(makeUnits('metric'))
    const us = trendDefs(makeUnits('us'))
    const battery = metric.find((d) => d.key === 'battery_avg_v')
    expect(battery.band).toEqual([
      DEFAULT_LIMITS.battery_low_running_v,
      DEFAULT_LIMITS.battery_high_running_v,
    ])
    expect(metric.find((d) => d.key === 'coolant_max_c').band).toEqual([80, 102])
    expect(us.find((d) => d.key === 'coolant_max_c').band).toEqual([176, 215.6])
    expect(us.find((d) => d.key === 'coolant_max_c').unit).toBe('°F')
  })

  it('follows limits edited on the Settings screen', () => {
    const defs = trendDefs(makeUnits('metric'), { ...DEFAULT_LIMITS, ltft_warn_pct: 5 })
    expect(defs.find((d) => d.key === 'ltft_avg_pct').band).toEqual([-5, 5])
  })
})
