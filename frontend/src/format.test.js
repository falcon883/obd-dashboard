import { describe, expect, it } from 'vitest'
import {
  DEFAULT_LIMITS,
  buildChecks,
  carLine,
  fmt,
  fmtDuration,
  fmtStamp,
  limitsOf,
  makeUnits,
  parseStamp,
} from './format.js'

const U = makeUnits('metric')
const byId = (checks, id) => checks.find((c) => c.id === id)

describe('formatting', () => {
  it('formats numbers and gaps', () => {
    expect(fmt(1234.5, 1)).toBe('1,234.5')
    expect(fmt(null)).toBe('—')
    expect(fmt(NaN)).toBe('—')
  })

  it('formats durations', () => {
    expect(fmtDuration(65)).toBe('1:05')
    expect(fmtDuration(3725)).toBe('1:02:05')
    expect(fmtDuration(undefined)).toBe('—')
  })

  it('converts units only for display', () => {
    const us = makeUnits('us')
    expect(us.t(100)).toBeCloseTo(212)
    expect(us.s(100)).toBeCloseTo(62.1371)
    expect(us.temp).toBe('°F')
    expect(makeUnits('metric').t(100)).toBe(100)
    expect(us.t(null)).toBeNull()
  })
})

describe('buildChecks (must agree with the backend thresholds)', () => {
  it.each([
    [60, 'info'],
    [90, 'ok'],
    [102, 'warn'],
    [108, 'bad'],
  ])('coolant %i°C -> %s', (temp, status) => {
    expect(byId(buildChecks({ COOLANT_TEMP: temp }, null, U), 'coolant').status).toBe(status)
  })

  it('battery depends on whether the engine is running', () => {
    expect(byId(buildChecks({ RPM: 800, battery_v: 12.5 }, null, U), 'battery').note).toBe('Charging low')
    expect(byId(buildChecks({ RPM: 0, battery_v: 12.5 }, null, U), 'battery').status).toBe('ok')
    expect(byId(buildChecks({ RPM: 0, battery_v: 11.5 }, null, U), 'battery').note).toBe('Weak battery')
  })

  it('fuel trim direction and severity', () => {
    expect(byId(buildChecks({ LONG_FUEL_TRIM_1: 12 }, null, U), 'trim')).toMatchObject({
      status: 'warn',
      note: 'Running lean',
    })
    expect(byId(buildChecks({ LONG_FUEL_TRIM_1: -25 }, null, U), 'trim')).toMatchObject({
      status: 'bad',
      note: 'Very rich',
    })
  })

  it('codes: MIL and stored are bad, pending is a warning, none is ok', () => {
    const codes = (c) => byId(buildChecks({}, { codes: c }, U), 'codes')
    expect(codes({ mil: true, stored: [], pending: [] }).status).toBe('bad')
    expect(codes({ mil: false, stored: ['P0300'], pending: [] })).toMatchObject({ status: 'bad', value: '1' })
    expect(codes({ mil: false, stored: [], pending: ['P0171'] }).status).toBe('warn')
    expect(codes({ mil: false, stored: [], pending: [] })).toMatchObject({ status: 'ok', value: '0' })
  })

  it('misfires are measured from the session start', () => {
    const m = (total) => byId(buildChecks({}, { misfire: { total }, misfire0: 3 }, U), 'misfire')
    expect(m(3).note).toBe('Quiet')
    expect(m(5).note).toBe('+2 this session')
    expect(m(13).status).toBe('warn')
  })

  it('skips checks it has no data for', () => {
    expect(buildChecks({}, null, U)).toEqual([])
  })
})

describe('car + session helpers', () => {
  it('parses the logger stamp as local time', () => {
    const d = parseStamp('20261121_214351')
    expect([d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes()]).toEqual([
      2026, 10, 21, 21, 43,
    ])
    expect(parseStamp('nonsense')).toBeNull()
    expect(fmtStamp('nonsense')).toBe('nonsense')
  })

  it('describes the car in one line', () => {
    expect(carLine({ display_name: '2016 Hyundai Sonata', engine: '2.4 L 4-cyl' })).toBe(
      '2016 Hyundai Sonata · 2.4 L 4-cyl',
    )
    expect(carLine({ display_name: 'Daily', title: '2016 Hyundai Sonata' })).toBe('Daily')
    expect(carLine({})).toBe('Unknown car')
    expect(carLine(null)).toBe('')
  })
})

describe('limits come from the session, not from constants', () => {
  it('limitsOf layers the session report over the defaults', () => {
    expect(limitsOf(null)).toEqual(DEFAULT_LIMITS)
    expect(limitsOf({ thresholds: { coolant_warn_c: 95 } })).toEqual({
      ...DEFAULT_LIMITS,
      coolant_warn_c: 95,
    })
  })

  it('a stricter coolant limit changes the verdict for the same reading', () => {
    const reading = { COOLANT_TEMP: 97 }
    expect(byId(buildChecks(reading, null, U), 'coolant').status).toBe('ok')
    const strict = limitsOf({ thresholds: { coolant_warn_c: 95, coolant_crit_c: 100 } })
    expect(byId(buildChecks(reading, null, U, strict), 'coolant').status).toBe('warn')
  })

  it('catalyst, fuel and misfire limits are all honoured', () => {
    const loose = limitsOf({ thresholds: { catalyst_warn_c: 1100, catalyst_crit_c: 1200, fuel_low_pct: 40 } })
    const v = { CATALYST_TEMP_B1S1: 1010, FUEL_LEVEL: 30 }
    expect(byId(buildChecks(v, null, U), 'cat').status).toBe('bad')
    expect(byId(buildChecks(v, null, U, loose), 'cat').status).toBe('ok')
    expect(byId(buildChecks(v, null, U, loose), 'fuel').status).toBe('warn')
    const strictMisfire = limitsOf({ thresholds: { misfire_rise: 2 } })
    const last = { misfire: { total: 6 }, misfire0: 3 }
    expect(byId(buildChecks({}, last, U, strictMisfire), 'misfire').status).toBe('warn')
  })
})
