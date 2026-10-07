import { ArrowDownRight, ArrowUpRight, Inbox, Minus, RotateCcw, TriangleAlert } from 'lucide-react'
import { memo } from 'react'
import { AGING, agingTotal } from '../lib/aging'
import { money, moneyFull, pct } from '../lib/format'
import { RATE_BANDS, rateStatus } from '../lib/theme'

const ACCENTS = {
  blue: 'linear-gradient(180deg, #2f7de1, #183f80)',
  green: 'linear-gradient(180deg, #34a071, #176b47)',
  slate: 'linear-gradient(180deg, #94a3b8, #475569)',
}

/** Page section: heading, one-line description, an optional at-a-glance figure, then its cards. */
export function Section({ title, description, accent = 'blue', stat, children }) {
  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between gap-6 px-0.5">
        <div className="min-w-0">
          <h2 className="section-title" style={{ '--section-accent': ACCENTS[accent] }}>{title}</h2>
          {description && <p className="section-desc mt-1">{description}</p>}
        </div>
        {stat && (
          <div className="shrink-0 text-right leading-tight">
            <p className="num text-[20px] font-semibold tracking-[-0.01em] text-ink-900">{stat.value}</p>
            <p className="text-[11.5px] text-ink-500">{stat.label}</p>
          </div>
        )}
      </div>
      <div className="section-rule" />
      {children}
    </section>
  )
}

/**
 * Content card in one of three tiers: `hero` (raised), default, or `flat` (no box — tables sit
 * directly on the canvas). `dim` fades while new filters load; children never re-mount on refresh.
 */
export const Panel = memo(function Panel({ title, subtitle, icon: Icon, actions, children, className = '', dim = false, flush = false, variant = 'standard' }) {
  const tier = variant === 'hero' ? 'card card-hero' : variant === 'flat' ? 'flat' : 'card'
  const pad = variant === 'flat' ? 'px-1 pb-2 pt-3' : 'px-5 pb-5 pt-4'
  return (
    <div className={`${tier} ${className}`}>
      {(title || actions) && (
        <div className={`flex items-start justify-between gap-4 ${variant === 'flat' ? 'px-1 pt-1' : 'px-5 pt-4'}`}>
          <div className="flex min-w-0 items-start gap-2.5">
            {Icon && <span className="panel-icon mt-px"><Icon size={14} strokeWidth={2.2} /></span>}
            <div className="min-w-0">
              {title && <h3 className="card-title">{title}</h3>}
              {subtitle && <p className="card-desc mt-0.5">{subtitle}</p>}
            </div>
          </div>
          {actions && <div className="shrink-0">{actions}</div>}
        </div>
      )}
      <div className={`${flush ? '' : pad} transition-opacity duration-200 ${dim ? 'opacity-55' : 'opacity-100'}`}>{children}</div>
    </div>
  )
})

export function Skeleton({ className = '', style }) {
  return <div className={`skeleton ${className}`} style={style} />
}

export function ChartSkeleton({ height = 260 }) {
  return (
    <div className="flex items-end gap-3" style={{ height }}>
      {[62, 88, 45, 72, 95, 58, 80, 40].map((h, i) => <Skeleton key={i} className="flex-1" style={{ height: `${h}%` }} />)}
    </div>
  )
}

export function EmptyState({ title = 'No data for the selected filters', hint = 'Widen the month, staff, city or project selection.', height = 200 }) {
  return (
    <div className="grid place-items-center text-center" style={{ minHeight: height }}>
      <div>
        <Inbox size={20} className="mx-auto text-ink-400" />
        <p className="mt-2 text-[13px] font-medium text-ink-700">{title}</p>
        {hint && <p className="mt-0.5 text-xs text-ink-500">{hint}</p>}
      </div>
    </div>
  )
}

export function ErrorState({ message, onRetry, compact = false }) {
  return (
    <div className={`flex items-start gap-3 rounded-xl border border-critical-600/20 bg-critical-100/60 text-critical-700 ${compact ? 'px-3 py-2' : 'p-4'}`}>
      <TriangleAlert size={15} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-semibold">Couldn’t load data</p>
        <p className="mt-0.5 break-words text-xs">{message}</p>
      </div>
      {onRetry && (
        <button onClick={onRetry} className="inline-flex items-center gap-1.5 rounded-md bg-white px-2.5 py-1 text-xs font-medium text-critical-700 ring-1 ring-critical-600/20 hover:bg-critical-100">
          <RotateCcw size={12} /> Retry
        </button>
      )}
    </div>
  )
}

/** Progress bar + rate, coloured by the shared status system. */
export function RateBar({ rate, width = 'w-16' }) {
  const s = rateStatus(rate)
  const w = Math.max(0, Math.min(100, rate ?? 0))
  return (
    <div className="flex items-center justify-end gap-2.5" title={`Status: ${s.label}`}>
      <div className={`bar-track ${width}`}>
        <div className="bar-fill transition-[width] duration-300" style={{ width: `${w}%`, background: s.color }} />
      </div>
      <span className={`num w-12 text-right text-[13px] font-semibold ${s.text}`}>{pct(rate)}</span>
    </div>
  )
}

/** Filled status pill — the same three band colours everywhere; text only, no icon. */
export function StatusBadge({ rate, className = '', showLabel = true }) {
  const s = rateStatus(rate)
  return (
    <span className={`pill ${s.pill} ${className}`} title={`Status: ${s.label}`}>{showLabel ? s.label : pct(rate)}</span>
  )
}

/**
 * Comparison chip: change of a value against a reference (previous month).
 * `kind`: 'pct' relative change; 'pts' difference in percentage points. `tone`: 'good-up' | 'neutral'.
 */
export function DeltaChip({ current, previous, kind = 'pct', tone = 'good-up', label }) {
  if (previous === null || previous === undefined || current === null || current === undefined) return null
  let text, dir
  if (kind === 'pts') {
    const diff = Math.round((current - previous) * 10) / 10
    dir = diff > 0 ? 1 : diff < 0 ? -1 : 0
    text = `${diff > 0 ? '+' : ''}${diff} pts`
  } else {
    if (!previous) return null
    const rel = Math.round(((current - previous) / Math.abs(previous)) * 1000) / 10
    dir = rel > 0 ? 1 : rel < 0 ? -1 : 0
    text = `${rel > 0 ? '+' : ''}${rel}%`
  }
  const cls = tone === 'neutral' ? 'delta-neutral' : dir > 0 ? 'delta-up' : dir < 0 ? 'delta-down' : 'delta-flat'
  const Icon = dir > 0 ? ArrowUpRight : dir < 0 ? ArrowDownRight : Minus
  return (
    <span className={`delta ${cls}`} title={label}>
      <Icon size={11} strokeWidth={2.5} />{text}{label ? <span className="font-normal opacity-80"> {label}</span> : null}
    </span>
  )
}

export function StatusLegend() {
  return <Legend items={RATE_BANDS.map((b) => ({ label: b.label, color: b.color }))} />
}

export function Legend({ items }) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-x-3.5 gap-y-1">
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1.5 text-[11.5px] text-ink-600">
          <span className={`inline-block ${it.line ? 'h-[2px] w-3.5' : 'h-2.5 w-2.5 rounded-[3px]'}`} style={{ background: it.color }} />
          {it.label}
        </span>
      ))}
    </div>
  )
}

/** Tooltip body shared by all charts. rows: [{label, value, color, kind: 'money'|'pct'|'count'}] */
export function TooltipCard({ title, rows, footer }) {
  return (
    <div className="min-w-[210px] rounded-xl border border-line bg-white/95 px-3.5 py-3 text-xs shadow-[var(--shadow-pop)] backdrop-blur">
      <p className="mb-2 text-[13px] font-semibold text-ink-900">{title}</p>
      <div className="space-y-1.5">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between gap-6">
            <span className="inline-flex items-center gap-1.5 text-ink-500">
              {r.kind === 'pct'
                ? <span className="h-2 w-2 rounded-full" style={{ background: rateStatus(r.value).color }} />
                : r.color && <span className="h-2 w-2 rounded-[2px]" style={{ background: r.color }} />}
              {r.label}
            </span>
            <span className="num font-semibold text-ink-900">
              {r.kind === 'pct' ? pct(r.value) : r.kind === 'count' ? r.value : moneyFull(r.value)}
            </span>
          </div>
        ))}
      </div>
      {footer && <p className="mt-2 border-t border-line-soft pt-2 text-[11px] text-ink-500">{footer}</p>}
    </div>
  )
}

export function Segmented({ value, onChange, options }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-canvas p-0.5 shadow-[inset_0_1px_2px_rgba(11,31,58,0.06)]">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${value === o.value ? 'bg-white text-ink-900 shadow-[0_1px_2px_rgba(11,31,58,0.10)]' : 'text-ink-500 hover:text-ink-800'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Big number with a muted unit, for tables. */
export function Money({ value, unit, className = '' }) {
  return <span className={`money ${className}`} title={moneyFull(value)}>{value}{unit && <span className="money-unit">{unit}</span>}</span>
}

/**
 * Stacked aging bar: Installment + Possession money by age of the installment it paid
 * (Current / 30–60 / 60–90 / 90+). Full width = the row's own total; hover for exact amounts.
 */
export function AgingBar({ aging, width, height = 8, legend = false }) {
  const total = agingTotal(aging)
  const title = AGING.map((a) => `${a.label}: ${moneyFull(aging?.[a.key] || 0)}`).join(' · ')
  return (
    <div style={width ? { width } : undefined} title={title}>
      <div className="flex overflow-hidden rounded-full bg-line-soft" style={{ height }}>
        {total > 0 && AGING.map((a) => <span key={a.key} style={{ width: `${((aging?.[a.key] || 0) / total) * 100}%`, background: a.color }} />)}
      </div>
      {legend && (
        <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink-600">
          {AGING.map((a) => (
            <span key={a.key} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-[2px]" style={{ background: a.color }} />{a.short}
              <b className="num font-semibold text-ink-800">{money(aging?.[a.key] || 0)}</b>
              {total > 0 && <span className="num text-ink-500">{pct(((aging?.[a.key] || 0) / total) * 100)}</span>}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
