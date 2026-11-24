/** Used-car check: how the verdict is headlined and how findings are grouped on screen. */

/** `status` is a StatusIcon / pill status. */
export const VERDICT = {
  clear: {
    status: 'ok',
    title: 'Nothing worrying found',
    note: 'The engine computer has nothing to complain about.',
  },
  look: {
    status: 'warn',
    title: 'Worth a closer look',
    note: 'A few things are worth asking the seller about before you decide.',
  },
  flags: {
    status: 'bad',
    title: 'Serious flags',
    note: 'The computer shows problems that could be expensive. Be careful with this one.',
  },
}

/** Findings come worst-first from the server; this splits them into the three blocks the screen shows. */
export function groupFindings(findings) {
  const list = findings || []
  return {
    attention: list.filter((f) => f.level === 'bad' || f.level === 'warn'),
    notes: list.filter((f) => f.level === 'info'),
    fine: list.filter((f) => f.level === 'ok'),
  }
}

/** Download link for a saved check file (the server only serves the exact names a check writes). */
export const checkFileUrl = (name) => `/api/checks/${encodeURIComponent(name)}`

/** 'Heading for the car being checked: its name, else a plain fallback, and the VIN to compare with the listing. */
export function carHeading(snapshot) {
  const name = snapshot?.car || 'Car not identified'
  return { name, vin: snapshot?.vin || null }
}

/** Seconds left in "Listening to the engine... 12 s left", for a progress bar; null when the text has none. */
export function secondsLeft(message) {
  const m = /(\d+)\s*s left/.exec(String(message || ''))
  return m ? Number(m[1]) : null
}
