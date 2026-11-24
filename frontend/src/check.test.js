import { describe, expect, it } from 'vitest'
import { VERDICT, carHeading, checkFileUrl, groupFindings, secondsLeft } from './check.js'

describe('groupFindings', () => {
  it('puts bad and warn together, keeps the server order inside each block', () => {
    const f = [
      { id: 'a', level: 'bad' },
      { id: 'b', level: 'warn' },
      { id: 'c', level: 'info' },
      { id: 'd', level: 'ok' },
      { id: 'e', level: 'ok' },
    ]
    const g = groupFindings(f)
    expect(g.attention.map((x) => x.id)).toEqual(['a', 'b'])
    expect(g.notes.map((x) => x.id)).toEqual(['c'])
    expect(g.fine.map((x) => x.id)).toEqual(['d', 'e'])
  })

  it('copes with nothing at all', () => {
    expect(groupFindings(undefined)).toEqual({ attention: [], notes: [], fine: [] })
  })
})

describe('VERDICT', () => {
  it('maps every server verdict to a pill status the icons know', () => {
    expect(Object.keys(VERDICT)).toEqual(['clear', 'look', 'flags'])
    expect(Object.values(VERDICT).map((v) => v.status)).toEqual(['ok', 'warn', 'bad'])
  })
})

describe('helpers', () => {
  it('builds a safe download url', () => {
    expect(checkFileUrl('20260102_030405_check.txt')).toBe('/api/checks/20260102_030405_check.txt')
    expect(checkFileUrl('a b/c')).toBe('/api/checks/a%20b%2Fc')
  })

  it('names the car, or says it is not identified', () => {
    expect(carHeading({ car: '2016 Hyundai Sonata', vin: 'X' })).toEqual({
      name: '2016 Hyundai Sonata',
      vin: 'X',
    })
    expect(carHeading({})).toEqual({ name: 'Car not identified', vin: null })
    expect(carHeading(null).name).toBe('Car not identified')
  })

  it('reads the countdown out of the status message', () => {
    expect(secondsLeft('Listening to the engine... 12 s left')).toBe(12)
    expect(secondsLeft('Reading the car’s records...')).toBeNull()
    expect(secondsLeft(undefined)).toBeNull()
  })
})
