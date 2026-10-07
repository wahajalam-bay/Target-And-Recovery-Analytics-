// One number format for the whole dashboard.
//   131,700,000 -> 131.7M   132,000,000 -> 132M   228,215,952 -> 228.2M
//   2,345,000,000 -> 2.35B  3,000,000,000 -> 3B    585,000 -> 585K
// Billions keep up to two decimals, millions and thousands one; trailing zeros are dropped.
// Exact figures (with commas) are available through moneyFull for tooltips and drill-down.
const full = new Intl.NumberFormat('en-PK', { maximumFractionDigits: 0 })
const UNITS = [
  { base: 1e9, suffix: 'B', decimals: 2 },
  { base: 1e6, suffix: 'M', decimals: 1 },
  { base: 1e3, suffix: 'K', decimals: 1 },
]

function scaled(abs, { base, decimals }) {
  // Thousands: a decimal only helps below 100K (12.3K), not above it (585K).
  if (base === 1e3 && abs >= 1e5) decimals = 0
  // Integer-based rounding avoids binary float surprises (2.345 -> 2.35, not 2.34).
  const step = base / 10 ** decimals
  return Math.round(abs / step) / 10 ** decimals
}

export function money(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  const abs = Math.abs(Number(v))
  const sign = v < 0 ? '−' : ''
  for (let i = 0; i < UNITS.length; i++) {
    const u = UNITS[i]
    if (abs < u.base) continue
    const n = scaled(abs, u)
    if (n >= 1000 && i > 0) { // 999,960 would round to "1000K": show "1M" instead
      const up = UNITS[i - 1]
      return `${sign}${scaled(abs, up)}${up.suffix}`
    }
    return `${sign}${n}${u.suffix}`
  }
  const rounded = Math.round(abs)
  return rounded >= 1000 ? `${sign}1K` : `${sign}${full.format(rounded)}`
}

export const moneyFull = (v) => (v === null || v === undefined ? '—' : `PKR ${full.format(v)}`)
export const exact = (v) => (v === null || v === undefined ? '—' : full.format(v))
export const count = (v) => (v === null || v === undefined ? '—' : full.format(v))

/** Percent with at most one decimal and no trailing .0 (57.7%, 100%, 0%). */
export function pct(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—'
  return `${Math.round(Number(v) * 10) / 10}%`
}

export function monthLabel(iso, short = false) {
  if (!iso) return ''
  const [y, m] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString('en-GB', {
    month: short ? 'short' : 'long', year: short ? '2-digit' : 'numeric', timeZone: 'UTC',
  })
}

export function timePKT(iso, withDate = false) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-GB', {
    timeZone: 'Asia/Karachi', hour: '2-digit', minute: '2-digit',
    ...(withDate ? { day: '2-digit', month: 'short' } : { second: '2-digit' }),
  })
}
