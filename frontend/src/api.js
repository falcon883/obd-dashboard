const post = (url, body) =>
  fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  }).then((r) => r.json())

const json = (r) => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export const api = {
  garage: () => fetch('/api/garage').then(json),
  rename: (vin, nickname) => post(`/api/garage/${encodeURIComponent(vin)}`, { nickname }),
  fileUrl: (vin, name) => `/api/garage/${encodeURIComponent(vin)}/${encodeURIComponent(name)}`,
  ports: () => fetch('/api/ports').then((r) => r.json()),
  start: (body) => post('/api/start', body),
  stop: () => post('/api/stop'),
}
