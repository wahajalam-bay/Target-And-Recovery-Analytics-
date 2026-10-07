// Single source of colour for charts, tables and cards. Small, strict system:
//   navy/blue  target / assigned, target-related collections, 60–90% status
//   green      achieved / positive, ≥ 90% status
//   red        < 60% status only
//   blue-grey  pending
//   warm slate other collections, neutrals
export const COLORS = {
  navy: '#0b1f3a',
  primary: '#2456a6',
  primaryDark: '#183f80',
  accent: '#2f7de1',
  muted: '#8fa8d2',
  mutedLight: '#d3deef',
  pending: '#b9c6dc',
  positive: '#1f8a5b',
  positiveLight: '#34a071',
  positiveMuted: '#9ccbb5',
  critical: '#c0392b',
  neutral: '#9a9ea8',
  ink: '#1e293b',
  axis: '#6b7a90',
  grid: '#eaeef4',
  track: '#e8edf4',
}

export const SERIES = {
  assigned: { label: 'Target assigned', color: COLORS.primary },
  achieved: { label: 'Target achieved', color: COLORS.positive },
  pending: { label: 'Pending', color: COLORS.pending },
}

export const AXIS = { tick: { fill: COLORS.axis, fontSize: 11 }, axisLine: false, tickLine: false }
export const CATEGORY_AXIS_TICK = { fill: '#334155', fontSize: 12 }
export const BAR_RADIUS_H = [0, 4, 4, 0]
export const BAR_RADIUS_V = [4, 4, 0, 0]
export const CURSOR = { fill: 'rgba(36, 86, 166, 0.05)' }

/**
 * Achievement status — the only three status colours, used identically everywhere.
 *   >= 90%  green  ·  60% to < 90%  blue  ·  < 60%  red
 * The rate is rounded to one decimal first, so the colour always agrees with the number shown.
 */
export const RATE_BANDS = [
  { min: 90, key: 'high', color: COLORS.positive, text: 'text-positive-700', soft: 'bg-positive-100', pill: 'pill-good', label: '≥ 90%' },
  { min: 60, key: 'mid', color: COLORS.primary, text: 'text-primary-700', soft: 'bg-primary-100', pill: 'pill-mid', label: '60% to < 90%' },
  { min: -Infinity, key: 'low', color: COLORS.critical, text: 'text-critical-700', soft: 'bg-critical-100', pill: 'pill-low', label: '< 60%' },
]
export function rateStatus(rate) {
  if (rate === null || rate === undefined) return { key: 'none', color: '#cbd5e1', text: 'text-ink-400', soft: 'bg-line-soft', pill: 'pill-none', label: 'No target' }
  const r = Math.round(rate * 10) / 10
  return RATE_BANDS.find((b) => r >= b.min)
}

// Payments by category: target-related in the blue family, other collections in warm slate.
const CATEGORY_COLORS = { Installment: COLORS.primary, Possession: '#6f93cf' }
const OTHER_SHADES = ['#5f6672', '#767d89', '#8d949f', '#a4aab4', '#b9bec7', '#cbcfd6', '#d9dce2', '#e4e6ea']
const OTHER_ORDER = ['Down Payment', 'Escalation', 'Adjustment Cost', 'Late Payment', '236K Tax', 'PRA Tax',
  'Other Tax', 'Transfer Fee', 'Cancellation Fee', 'Refund', 'Unallocated', 'Other']
export function categoryColor(category) {
  if (CATEGORY_COLORS[category]) return CATEGORY_COLORS[category]
  const i = OTHER_ORDER.indexOf(category)
  return OTHER_SHADES[(i < 0 ? OTHER_ORDER.length : i) % OTHER_SHADES.length]
}

// Ordered blues for share charts (dark to light).
export const SHARE_SCALE = ['#12325f', '#2456a6', '#2f7de1', '#5a98e6', '#8fb6ec', '#b9d1f3', '#d9e5f8']
