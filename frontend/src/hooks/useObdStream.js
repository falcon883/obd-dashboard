import { useEffect, useState } from 'react'

const MAX_SECONDS = 900 // the live charts keep the last 15 minutes
const MAX_ROWS = 6000 // ...and never more than this many rows, however fast the car answers

/** Subscribes to the FastAPI Server-Sent-Events stream and keeps the live session in React state. */
export default function useObdStream() {
  const [serverUp, setServerUp] = useState(null) // null = not known yet
  const [status, setStatus] = useState({ state: 'idle', message: 'Not started' })
  const [info, setInfo] = useState(null)
  const [rows, setRows] = useState([]) // [{ t, v }]
  const [last, setLast] = useState(null)
  const [events, setEvents] = useState([])

  useEffect(() => {
    const es = new EventSource('/api/stream')
    es.onopen = () => setServerUp(true)
    es.onerror = () => setServerUp(false) // EventSource reconnects by itself
    es.addEventListener('snapshot', (e) => {
      const s = JSON.parse(e.data)
      setServerUp(true)
      setStatus(s.status)
      setInfo(s.info)
      setRows(s.history || [])
      setLast(s.last)
      setEvents(s.events || [])
    })
    es.addEventListener('row', (e) => {
      const r = JSON.parse(e.data)
      setLast(r)
      setRows((prev) => {
        const next = prev.slice()
        next.push({ t: r.t, v: r.values })
        let cut = 0
        while (cut < next.length - 1 && r.t - next[cut].t > MAX_SECONDS) cut += 1
        cut = Math.max(cut, next.length - MAX_ROWS)
        return cut > 0 ? next.slice(cut) : next
      })
    })
    es.addEventListener('alert', (e) => setEvents((prev) => [...prev.slice(-299), JSON.parse(e.data)]))
    es.addEventListener('info', (e) => setInfo(JSON.parse(e.data)))
    es.addEventListener('status', (e) => {
      const s = JSON.parse(e.data)
      setStatus(s)
      if (s.state === 'connecting') {
        // a fresh session: wipe the previous one
        setRows([])
        setLast(null)
        setEvents([])
        setInfo(null)
      }
    })
    return () => es.close()
  }, [])

  return { serverUp, status, info, rows, last, events }
}
