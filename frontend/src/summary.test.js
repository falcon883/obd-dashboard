import { describe, expect, it } from 'vitest'
import { makeUnits } from './format.js'
import {
  HEADLINE,
  fileName,
  fmtStarted,
  outcomeTiles,
  parseAlert,
  streamRate,
  warmupTile,
} from './summary.js'

const outcome = (over = {}) => ({
  verdict: 'ok',
  duration_s: 905,
  distance_km: 10,
  start_coolant_c: 30,
  coolant_max_c: 90,
  warm_s: { 70: 240, 80: 420 },
  battery_avg_v: 14.2,
  ltft_avg_pct: 2.5,
  ...over,
})
const byKey = (tiles) => Object.fromEntries(tiles.map((t) => [t.key, t]))

describe('outcome tiles', () => {
  it('shows the drive in metric', () => {
    const t = byKey(outcomeTiles(outcome(), makeUnits('metric')))
    expect(t.time.value).toBe('15:05')
    expect(t.dist).toMatchObject({ value: '10.0', unit: 'km' })
    expect(t.hot).toMatchObject({ value: '90', unit: '°C', sub: 'started at 30 °C' })
    expect(t.warm).toMatchObject({ value: '7.0', unit: 'min', sub: 'to 80 °C' })
    expect(t.volts).toMatchObject({ value: '14.2', unit: 'V' })
    expect(t.trim).toMatchObject({ value: '+2.5', unit: '%' })
  })

  it('converts to US units', () => {
    const t = byKey(outcomeTiles(outcome(), makeUnits('us')))
    expect(t.dist).toMatchObject({ value: '6.2', unit: 'mi' })
    expect(t.hot).toMatchObject({ value: '194', unit: '°F', sub: 'started at 86 °F' })
    expect(t.warm.sub).toBe('to 176 °F')
  })

  it('keeps missing values blank instead of showing zeros', () => {
    const t = byKey(
      outcomeTiles(
        outcome({
          distance_km: 0,
          coolant_max_c: null,
          start_coolant_c: null,
          battery_avg_v: null,
          ltft_avg_pct: null,
          warm_s: {},
        }),
        makeUnits('metric'),
      ),
    )
    expect(t.dist.value).toBe('—')
    expect(t.hot).toMatchObject({ value: '—', unit: '' })
    expect(t.volts).toMatchObject({ value: '—', unit: '' })
    expect(t.trim.value).toBe('—')
  })

  it('shows a negative trim with its own minus sign', () => {
    const t = byKey(outcomeTiles(outcome({ ltft_avg_pct: -3.1 }), makeUnits('metric')))
    expect(t.trim.value).toBe('-3.1')
  })
})

describe('warm-up tile', () => {
  const U = makeUnits('metric')
  it('uses the highest checkpoint reached', () => {
    expect(warmupTile(outcome({ warm_s: { 70: 100, 80: 200, 85: 300 } }), U).sub).toBe('to 85 °C')
    expect(warmupTile(outcome({ warm_s: { 70: 100 } }), U).sub).toBe('to 70 °C')
  })
  it('says so when the engine started warm or never warmed up', () => {
    expect(warmupTile(outcome({ warm_s: {}, start_coolant_c: 85 }), U).sub).toBe('engine started warm')
    expect(warmupTile(outcome({ warm_s: {}, start_coolant_c: 20, coolant_max_c: 55 }), U).sub).toBe(
      'never reached 70 °C',
    )
  })
})

describe('small helpers', () => {
  it('splits an alert into its level and text', () => {
    expect(parseAlert('[CRIT] Check-engine light is ON')).toEqual({
      level: 'bad',
      text: 'Check-engine light is ON',
    })
    expect(parseAlert('[WARN] Coolant running hot')).toEqual({ level: 'warn', text: 'Coolant running hot' })
    expect(parseAlert('something else')).toEqual({ level: 'warn', text: 'something else' })
  })

  it('takes a file name from a Windows or Linux path', () => {
    expect(fileName('D:\\OBD\\logs\\VIN\\20261123_141751_report.txt')).toBe('20261123_141751_report.txt')
    expect(fileName('/home/x/20261123_data.csv')).toBe('20261123_data.csv')
    expect(fileName(null)).toBeNull()
  })

  it('formats the start time and ignores a missing one', () => {
    expect(fmtStarted('2026-11-23T14:18:02')).toMatch(/23/)
    expect(fmtStarted('')).toBe('')
    expect(fmtStarted('nonsense')).toBe('')
  })

  it('has a headline for each verdict', () => {
    expect(Object.keys(HEADLINE)).toEqual(['ok', 'warn', 'crit'])
    expect(HEADLINE.crit.status).toBe('bad')
  })

  it('works out readings per second', () => {
    const rows = Array.from({ length: 41 }, (_, i) => ({ t: i * 0.25, v: {} }))
    expect(streamRate(rows)).toBeCloseTo(4)
    expect(streamRate([])).toBeNull()
    expect(streamRate([{ t: 1, v: {} }])).toBeNull()
  })
})
