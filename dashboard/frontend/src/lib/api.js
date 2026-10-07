import { useEffect, useRef, useState } from 'react'

/** Arrays become repeated parameters: {staff_id: [1, 2]} -> ?staff_id=1&staff_id=2 */
export function buildQuery(params) {
  const q = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => {
    if (Array.isArray(v)) v.forEach((x) => q.append(k, x))
    else if (v !== null && v !== undefined && v !== '') q.set(k, v)
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}

/**
 * Snapshot mode: a self-contained HTML export embeds API responses in
 * window.__DASHBOARD_SNAPSHOT__ = { taken_at, responses: { "<path>?<sorted params>": body } }.
 * The live dashboard never sets it, so it keeps calling the API as before.
 */
export const SNAPSHOT = typeof window !== 'undefined' ? window.__DASHBOARD_SNAPSHOT__ || null : null

export function snapshotKey(path, params) {
  const pairs = [...new URLSearchParams(buildQuery(params).slice(1)).entries()]
    .sort((x, y) => (x[0] === y[0] ? x[1].localeCompare(y[1]) : x[0].localeCompare(y[0])))
  return path + (pairs.length ? `?${pairs.map(([k, v]) => `${k}=${v}`).join('&')}` : '')
}

function fromSnapshot(path, params) {
  const hit = SNAPSHOT.responses[snapshotKey(path, params)]
  if (hit) return hit
  if (path === '/drill/payments') {  // bookings with no payment this month
    return { lines: [], payments_total: 0, target_payments: 0, other_payments: 0 }
  }
  throw new Error('This view is not included in this snapshot.')
}

export async function getJSON(path, params, signal) {
  if (SNAPSHOT) return fromSnapshot(path, params)
  const res = await fetch(`/api${path}${buildQuery(params)}`, { signal })
  let body = null
  try { body = await res.json() } catch { /* non-JSON error page */ }
  if (!res.ok) throw new Error(body?.detail || `Request failed (${res.status})`)
  return body
}

/**
 * Fetch `path` with `params`, re-fetching whenever they change or `tick` changes
 * (the 60-second auto refresh). Previous data stays on screen while refreshing.
 */
export function useApi(path, params, tick = 0, enabled = true, debounceMs = 220) {
  const [state, setState] = useState({ data: null, error: null, loading: enabled, refreshing: false, changing: false })
  const key = JSON.stringify([path, params])
  const lastKey = useRef(null)

  useEffect(() => {
    if (!enabled) return undefined
    const ctrl = new AbortController()
    const filtersChanged = lastKey.current !== null && lastKey.current !== key
    lastKey.current = key
    setState((s) => ({ ...s, loading: !s.data, refreshing: true, changing: filtersChanged, error: null }))
    // Ticking several boxes in a multi-select fires one request, not one per click.
    const timer = setTimeout(() => {
      getJSON(path, params, ctrl.signal)
        .then((data) => setState({ data, error: null, loading: false, refreshing: false, changing: false }))
        .catch((err) => {
          if (err.name === 'AbortError') return
          setState((s) => ({ ...s, error: err.message, loading: false, refreshing: false, changing: false }))
        })
    }, filtersChanged ? debounceMs : 0)
    return () => { clearTimeout(timer); ctrl.abort() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tick, enabled])

  return state
}

/**
 * Returns the previous object when the new one has identical content, so a
 * background refresh that brings the same numbers does not re-render (or
 * re-animate) the charts that receive it.
 */
export function useStable(value) {
  const ref = useRef({ json: undefined, value })
  const json = value === undefined ? undefined : JSON.stringify(value)
  if (json !== ref.current.json) ref.current = { json, value }
  return ref.current.value
}
