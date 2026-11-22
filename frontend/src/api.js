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

/** Settings writes return { ok, data } or { ok: false, problems: [text, ...] } so the form can list every reason. */
const write = async (method, url, body) => {
  const r = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json().catch(() => ({}))
  if (r.ok) return { ok: true, data }
  const detail = data.detail
  const problems = Array.isArray(detail)
    ? detail.map((d) => d.msg || String(d))
    : [String(detail || `HTTP ${r.status}`)]
  return { ok: false, problems }
}

export const api = {
  garage: () => fetch('/api/garage').then(json),
  rename: (vin, nickname) => post(`/api/garage/${encodeURIComponent(vin)}`, { nickname }),
  fileUrl: (vin, name) => `/api/garage/${encodeURIComponent(vin)}/${encodeURIComponent(name)}`,
  settings: () => fetch('/api/settings').then(json),
  saveLimits: (values, vin) => write('PUT', '/api/settings/thresholds', { values, vin: vin || null }),
  saveAdvanced: (values) => write('PUT', '/api/settings/advanced', { values }),
  resetSettings: (scope, vin) => write('POST', '/api/settings/reset', { scope, vin: vin || null }),
  ports: () => fetch('/api/ports').then((r) => r.json()),
  start: (body) => post('/api/start', body),
  stop: () => post('/api/stop'),
}
