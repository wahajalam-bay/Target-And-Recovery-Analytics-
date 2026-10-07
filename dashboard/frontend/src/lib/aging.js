// Aging buckets: age of the installment an Installment / Possession payment was allocated to,
// measured at the first day of the target month (Pakistan time). Same boundaries as Propone's
// receivable buckets. Keys match the API (`aging` filter and `aging` breakdowns).
export const AGING = [
  { key: 'current', label: 'Current (0–30 days)', short: 'Current', color: '#12325f' },
  { key: 'd30_60', label: '30–60 days', short: '30–60', color: '#2f7de1' },
  { key: 'd60_90', label: '60–90 days', short: '60–90', color: '#8fb6ec' },
  { key: 'd90_plus', label: '90+ days', short: '90+', color: '#cfdcf0' },
]
export const AGING_KEYS = AGING.map((a) => a.key)
export const agingTotal = (a) => AGING.reduce((s, b) => s + (a?.[b.key] || 0), 0)

/** Dashboard view: achieved against the target only, or achieved plus money received outside targets. */
export const VIEWS = [
  { value: 'target', label: 'Target only' },
  { value: 'received', label: '+ Outside target' },
]

/** Rows with achieved/pending/rate swapped for the received figures when the view asks for it. */
export function applyView(rows, view) {
  if (!rows || view !== 'received') return rows
  return rows.map(viewRow)
}
export function viewRow(r) {
  const received = r.received ?? r.achieved
  return { ...r, achieved: received, pending: r.assigned - received, rate: r.rate_received ?? (r.assigned ? Math.round((received / r.assigned) * 10000) / 100 : null) }
}
export function applyViewTree(nodes, view) {
  if (!nodes || view !== 'received') return nodes
  return nodes.map((n) => ({ ...viewRow(n), children: applyViewTree(n.children, view) }))
}
