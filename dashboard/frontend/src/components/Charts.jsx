import { memo, useMemo, useState } from 'react'
import {
  Area, Bar, CartesianGrid, Cell, ComposedChart, Pie, PieChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { applyView } from '../lib/aging'
import { count, money, moneyFull, monthLabel, pct } from '../lib/format'
import { AXIS, BAR_RADIUS_V, COLORS, CURSOR, SERIES, SHARE_SCALE, rateStatus } from '../lib/theme'
import { AgingBar, EmptyState, Legend, Segmented, StatusBadge, TooltipCard } from './ui'

// All charts are static (no Recharts animation): they render instantly and never restart on refresh.
const short = (s, n = 18) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s)
const moneyRows = (d) => [
  { label: 'Assigned', value: d.assigned, color: SERIES.assigned.color },
  { label: 'Achieved', value: d.achieved, color: SERIES.achieved.color },
  { label: 'Pending', value: d.pending, color: SERIES.pending.color },
  { label: 'Achievement rate', value: d.rate, kind: 'pct' },
]
const Defs = () => (
  <defs>
    <linearGradient id="gAssigned" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#3a6cbb" /><stop offset="100%" stopColor="#1e4b93" /></linearGradient>
    <linearGradient id="gAchieved" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#34a071" /><stop offset="100%" stopColor="#176b47" /></linearGradient>
    <linearGradient id="gRate" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#2f7de1" stopOpacity="0.28" /><stop offset="100%" stopColor="#2f7de1" stopOpacity="0" /></linearGradient>
  </defs>
)

/* ---------- Monthly trend (hero) ----------
   The achievement rate is the story (area + line); assigned/achieved are compact bars on their own
   axis. The selected month is spotlit; other months are dimmed. Same trend rows as before. */
export const TrendChart = memo(function TrendChart({ data, month, height = 300 }) {
  if (!data?.length) return <EmptyState />
  const rows = data.map((d) => ({ ...d, label: monthLabel(d.month, true) }))
  const cur = rows.find((r) => r.month === month)
  const s = cur ? rateStatus(cur.rate) : null
  return (
    <>
      {cur && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <div>
              <p className="label-caps">{monthLabel(cur.month)} · achievement rate</p>
              <p className={`num text-[30px] font-semibold leading-none tracking-[-0.02em] ${s.text}`}>{pct(cur.rate)}</p>
            </div>
            <div className="h-9 w-px bg-line" />
            <div><p className="label-caps">Achieved</p><p className="num text-[20px] font-semibold leading-tight text-ink-900" title={moneyFull(cur.achieved)}>{money(cur.achieved)}</p></div>
            <div><p className="label-caps">of target</p><p className="num text-[20px] font-semibold leading-tight text-ink-700" title={moneyFull(cur.assigned)}>{money(cur.assigned)}</p></div>
          </div>
          <Legend items={[{ label: 'Achievement rate', color: COLORS.accent, line: true }, { label: 'Target assigned', color: SERIES.assigned.color }, { label: 'Target achieved', color: SERIES.achieved.color }]} />
        </div>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 10, right: 0, left: 0, bottom: 0 }} barGap={4}>
          <Defs />
          <CartesianGrid stroke={COLORS.grid} vertical={false} strokeDasharray="2 4" />
          {cur && <ReferenceArea yAxisId="r" x1={cur.label} x2={cur.label} fill="rgba(47,125,225,0.07)" stroke="rgba(47,125,225,0.25)" radius={8} />}
          <XAxis dataKey="label" {...AXIS} tick={{ fill: COLORS.axis, fontSize: 11.5 }} axisLine={{ stroke: '#e2e7ef', strokeWidth: 1 }} />
          <YAxis yAxisId="r" orientation="left" {...AXIS} domain={[0, (max) => Math.max(100, Math.ceil(max / 20) * 20)]} tickFormatter={(v) => `${v}%`} width={44} />
          <YAxis yAxisId="m" orientation="right" {...AXIS} tickFormatter={money} width={54} />
          <Tooltip cursor={CURSOR} isAnimationActive={false} content={({ active, payload }) => {
            if (!active || !payload?.length) return null
            const d = payload[0].payload
            return <TooltipCard title={monthLabel(d.month)} rows={[...moneyRows(d), { label: 'Bookings', value: count(d.bookings), kind: 'count' }]} />
          }} />
          <Area yAxisId="r" type="monotone" dataKey="rate" stroke={COLORS.accent} strokeWidth={2.5} fill="url(#gRate)" isAnimationActive={false}
            dot={{ r: 3.5, strokeWidth: 2, fill: '#fff', stroke: COLORS.accent }} activeDot={{ r: 5 }} />
          <Bar yAxisId="m" dataKey="assigned" radius={BAR_RADIUS_V} maxBarSize={22} isAnimationActive={false}>
            {rows.map((r) => <Cell key={r.month} fill="url(#gAssigned)" fillOpacity={r.month === month ? 1 : 0.28} />)}
          </Bar>
          <Bar yAxisId="m" dataKey="achieved" radius={BAR_RADIUS_V} maxBarSize={22} isAnimationActive={false}>
            {rows.map((r) => <Cell key={r.month} fill="url(#gAchieved)" fillOpacity={r.month === month ? 1 : 0.28} />)}
          </Bar>
        </ComposedChart>
      </ResponsiveContainer>
    </>
  )
})

/** Month table beside the trend: the same rows, as numbers, with status pills. */
export const TrendTable = memo(function TrendTable({ data, month }) {
  if (!data?.length) return <EmptyState height={160} />
  const rows = [...data].reverse()
  const maxAch = Math.max(1, ...data.map((r) => r.achieved))
  return (
    <table className="tbl">
      <thead><tr><th>Month</th><th className="r">Assigned</th><th className="r">Achieved</th><th className="r">Rate</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.month} className={r.month === month ? 'font-semibold' : ''}>
            <td className={`whitespace-nowrap ${r.month === month ? 'text-ink-900' : 'text-ink-700'}`} title={r.month === month ? 'Selected month' : ''}>
              {r.month === month && <span className="mr-2 inline-block h-2 w-2 rounded-full bg-accent align-middle" />}{monthLabel(r.month, true)}
            </td>
            <td className="r num text-ink-600" title={moneyFull(r.assigned)}>{money(r.assigned)}</td>
            <td className="r">
              <span className="inline-flex items-center justify-end gap-2">
                <span className="bar-track w-12"><span className="bar-fill" style={{ width: `${(r.achieved / maxAch) * 100}%`, background: SERIES.achieved.color }} /></span>
                <span className="money" title={moneyFull(r.achieved)}>{money(r.achieved)}</span>
              </span>
            </td>
            <td className="r"><StatusBadge rate={r.rate} showLabel={false} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
})

/* ---------- Ranked bar-table shared by Project and Staff performance ----------
   Track = the row's own target (always full width); fill = achieved ÷ target from the existing rate,
   capped at 100% with a chip for the excess. `view` = 'received' swaps achieved for achieved + money
   received outside targets (figures come from the API; see lib/aging applyView). */
const GRID = 'grid-cols-[minmax(0,1.15fr)_minmax(0,1.6fr)_78px_84px_92px_100px]'
function BarTable({ rows, idKey, name, sub, onSelect, selected = new Set(), footLabel, received = false }) {
  return (
    <>
      <div className="rowlist rounded-xl overflow-hidden">
        {rows.map((r) => {
          const isSel = selected.has(r[idKey])
          return (
            <button key={r[idKey]} onClick={() => onSelect?.(r)} disabled={!onSelect}
              className={`row-hover grid w-full ${GRID} items-center gap-4 px-3 text-left ${isSel ? '!bg-primary-50' : ''}`}
              style={{ minHeight: 44 }}
              title={`${name(r)}: ${moneyFull(r.achieved)} ${received ? 'received (incl. outside target)' : 'achieved'} of ${moneyFull(r.assigned)} target${received && r.outside ? ` · ${moneyFull(r.outside)} outside target` : ''} · ${count(r.bookings)} bookings${onSelect ? ' · click for detail' : ''}`}>
              <span className="min-w-0">
                <span className={`block truncate text-[13px] ${isSel ? 'font-semibold text-ink-900' : 'font-medium text-ink-800'}`}>{name(r)}</span>
                {sub?.(r) && <span className="block truncate text-[11px] text-ink-500">{sub(r)}</span>}
              </span>
              <span className="flex items-center gap-2">
                <span className="bar-track flex-1" style={{ background: '#d5deee' }}>
                  <span className="bar-achieved" style={{ width: `${Math.min(100, r.rate ?? 0)}%`, background: r.rate >= 100 ? `linear-gradient(90deg, ${SERIES.achieved.color}, ${COLORS.accent})` : undefined }} />
                </span>
                {r.rate > 100 && <span className="delta delta-neutral shrink-0" title={`${pct(r.rate)} of target · ${moneyFull(r.achieved - r.assigned)} above target`}>+{pct(r.rate - 100)}</span>}
              </span>
              <span className="num text-right text-[12.5px] text-ink-500" title={moneyFull(r.assigned)}>{r.assigned ? money(r.assigned) : '—'}</span>
              <span className="money text-right text-[13px]" title={moneyFull(r.achieved)}>{money(r.achieved)}</span>
              <span className="flex justify-end"><AgingBar aging={r.aging} width={88} /></span>
              <span className="flex justify-end"><StatusBadge rate={r.rate} showLabel={false} /></span>
            </button>
          )
        })}
      </div>
      <div className={`mt-2 grid ${GRID} gap-4 px-3 text-[10.5px] uppercase tracking-wide text-ink-400`}>
        <span>{footLabel}</span><span>{received ? 'Received as % of target' : 'Achieved as % of target'}</span><span className="text-right">Assigned</span>
        <span className="text-right">{received ? 'Received' : 'Achieved'}</span><span className="text-right">Aging</span><span className="text-right">Rate</span>
      </div>
    </>
  )
}
const barLegend = (received) => [{ label: 'Target (100%)', color: '#d5deee' }, { label: received ? 'Received vs target' : 'Achieved vs target', color: SERIES.achieved.color }, { label: 'Above target', color: COLORS.accent }]
const SORTS = [{ value: 'assigned', label: 'By target' }, { value: 'achieved', label: 'By achieved' }, { value: 'rate', label: 'By %' }]
function useSorted(data, sort) {
  return useMemo(() => {
    const src = [...(data || [])]
    if (sort === 'rate') src.sort((a, b) => (b.rate ?? -1) - (a.rate ?? -1))
    else src.sort((a, b) => b[sort] - a[sort])
    return src
  }, [data, sort])
}

export const ProjectTable = memo(function ProjectTable({ data, onSelect, selected = [], view = 'target' }) {
  const [sort, setSort] = useState('assigned')
  const received = view === 'received'
  const src = useMemo(() => applyView((data || []).filter((r) => received || r.assigned > 0), view), [data, view, received])
  const rows = useSorted(src, sort)
  if (!rows.length) return <EmptyState />
  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3"><Legend items={barLegend(received)} /><Segmented value={sort} onChange={setSort} options={SORTS} /></div>
      <BarTable rows={rows} idKey="project_id" name={(r) => r.name} onSelect={onSelect} selected={new Set(selected)} footLabel="Project" received={received} />
    </>
  )
})

export const StaffTable = memo(function StaffTable({ data, onSelect, view = 'target' }) {
  const [sort, setSort] = useState('assigned')
  const received = view === 'received'
  const src = useMemo(() => applyView((data || []).filter((r) => received || r.has_target !== false), view), [data, view, received])
  const rows = useSorted(src, sort)
  if (!rows.length) return <EmptyState />
  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-3"><Legend items={barLegend(received)} /><Segmented value={sort} onChange={setSort} options={SORTS} /></div>
      <BarTable rows={rows} idKey="staff_id" name={(r) => r.name} sub={(r) => (r.manager ? `Reports to ${r.manager}` : null)} onSelect={onSelect} footLabel="Staff" received={received} />
    </>
  )
})

/* ---------- Regions: the verified project figures grouped by the project's city ----------
   Sum of assigned / achieved over a region's projects (rows are disjoint, nothing counted twice);
   rate = achieved ÷ assigned. Same grouping the City filter applies. */
export function groupByCity(byProject, options) {
  if (!byProject?.length || !options?.projects || !options?.cities) return []
  const cityOf = new Map(options.projects.map((p) => [p.id, p.city_id]))
  const label = new Map(options.cities.map((c) => [c.id, c.label]))
  const acc = new Map()
  byProject.forEach((p) => {
    const cid = cityOf.get(p.project_id)
    const k = cid ?? 'other'
    const cur = acc.get(k) || { city_id: k, name: label.get(cid) || 'Other city', assigned: 0, achieved: 0, bookings: 0, projects: 0 }
    cur.assigned += p.assigned; cur.achieved += p.achieved; cur.bookings += p.bookings; cur.projects += 1
    acc.set(k, cur)
  })
  return [...acc.values()].map((c) => ({ ...c, pending: c.assigned - c.achieved, rate: c.assigned ? Math.round((c.achieved / c.assigned) * 10000) / 100 : null }))
    .sort((a, b) => b.assigned - a.assigned)
}

/** One ranked strip per region: name, filled progress bar, achieved / assigned, status. */
export const CityChart = memo(function CityChart({ data }) {
  if (!data?.length) return <EmptyState hint="Region names come from the projects in scope." />
  const max = Math.max(1, ...data.map((c) => c.assigned))
  return (
    <div className="rowlist overflow-hidden rounded-xl">
      {data.map((c) => {
        const s = rateStatus(c.rate)
        return (
          <div key={c.city_id} className="grid grid-cols-[130px_minmax(0,1fr)_auto] items-center gap-4 px-3 py-3">
            <div className="min-w-0">
              <p className="truncate text-[13.5px] font-semibold text-ink-900">{c.name}</p>
              <p className="text-[11px] text-ink-500">{count(c.projects)} project{c.projects === 1 ? '' : 's'} · {count(c.bookings)} bookings</p>
            </div>
            <div>
              <div className="bar-track" style={{ height: 10 }}>
                <span className="bar-fill" style={{ width: `${(c.assigned / max) * 100}%`, background: '#d5deee' }} />
                <span className="bar-fill" style={{ width: `${(Math.min(c.achieved, c.assigned) / max) * 100}%`, background: `linear-gradient(90deg, ${s.color}cc, ${s.color})` }} />
              </div>
              <p className="mt-1.5 text-[11.5px] text-ink-500">
                <span className="money" title={moneyFull(c.achieved)}>{money(c.achieved)}</span> achieved of <span className="num font-medium text-ink-700" title={moneyFull(c.assigned)}>{money(c.assigned)}</span>
              </p>
            </div>
            <div className="text-right">
              <p className={`num text-[20px] font-semibold leading-none ${s.text}`}>{pct(c.rate)}</p>
              <div className="mt-1.5"><StatusBadge rate={c.rate} /></div>
            </div>
          </div>
        )
      })}
    </div>
  )
})

/* ---------- Contribution to target achieved — every project ---------- */
const mix = (a, b, t) => {
  const p = (h) => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)]
  const [r1, g1, b1] = p(a), [r2, g2, b2] = p(b)
  const c = (x, y) => Math.round(x + (y - x) * t).toString(16).padStart(2, '0')
  return `#${c(r1, r2)}${c(g1, g2)}${c(b1, b2)}`
}
function Donut({ parts, size = 230, inner = 74, outer = 108, hover, setHover, center }) {
  return (
    <div className="relative mx-auto" style={{ width: size, height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={parts} dataKey="value" nameKey="name" innerRadius={inner} outerRadius={outer} paddingAngle={1.2} stroke="#fff" strokeWidth={2} cornerRadius={3}
            isAnimationActive={false} onMouseEnter={(_, i) => setHover(i)} onMouseLeave={() => setHover(null)}>
            {parts.map((p, i) => <Cell key={p.name} fill={p.color} opacity={hover === null || hover === i ? 1 : 0.3} />)}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
        <div className="rounded-full bg-white/70 px-3 py-2 backdrop-blur-[2px]">{center}</div>
      </div>
    </div>
  )
}

export const Contribution = memo(function Contribution({ rows, nameKey = 'name' }) {
  const [hover, setHover] = useState(null)
  const parts = useMemo(() => {
    const src = (rows || []).filter((r) => r.achieved > 0).sort((a, b) => b.achieved - a.achieved)
    const total = src.reduce((s, r) => s + r.achieved, 0)
    const n = Math.max(1, src.length - 1)
    const out = src.map((r, i) => ({ name: r[nameKey], value: r.achieved, color: mix(SHARE_SCALE[0], SHARE_SCALE[6], i / n) }))
    const zero = (rows || []).filter((r) => !(r.achieved > 0)).map((r) => r[nameKey])
    return { out, total, zero }
  }, [rows, nameKey])
  if (!parts.total) return <EmptyState height={160} />
  const active = hover !== null ? parts.out[hover] : null
  const top = parts.out[0]
  const center = active
    ? <><p className="label-caps">{short(active.name, 14)}</p><p className="num mt-0.5 text-[20px] font-semibold text-ink-900">{pct((active.value / parts.total) * 100)}</p><p className="num text-[11px] text-ink-500">{money(active.value)}</p></>
    : <><p className="label-caps">Largest share</p><p className="num mt-0.5 text-[20px] font-semibold text-ink-900">{pct((top.value / parts.total) * 100)}</p><p className="truncate text-[11px] text-ink-500" style={{ maxWidth: 120 }}>{top.name}</p></>
  return (
    <div className="grid grid-cols-1 items-start gap-6 sm:grid-cols-[230px_1fr]">
      <div className="sm:sticky sm:top-4">
        <Donut parts={parts.out} hover={hover} setHover={setHover} center={center} />
        <p className="mt-1 text-center text-[11.5px] text-ink-500">Total achieved <span className="money">{money(parts.total)}</span> · {count(parts.out.length)} projects</p>
      </div>
      <div>
        <ul className="rowlist overflow-hidden rounded-xl">
          {parts.out.map((p, i) => (
            <li key={p.name} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}
              className={`row-hover flex items-center gap-3 px-3 py-[6px] ${hover === i ? '!bg-hover' : ''}`}>
              <span className="h-2.5 w-2.5 shrink-0 rounded-[3px]" style={{ background: p.color }} />
              <span className="w-[38%] truncate text-[12.5px] text-ink-800">{p.name}</span>
              <span className="bar-track flex-1" style={{ height: 6 }}><span className="bar-fill" style={{ width: `${(p.value / parts.out[0].value) * 100}%`, background: p.color }} /></span>
              <span className="num w-12 text-right text-[11.5px] text-ink-500">{pct((p.value / parts.total) * 100)}</span>
              <span className="money w-16 text-right text-[12.5px]" title={moneyFull(p.value)}>{money(p.value)}</span>
            </li>
          ))}
        </ul>
        {parts.zero.length > 0 && <p className="mt-2 px-3 text-[11px] text-ink-400">No achievement yet: {parts.zero.join(', ')}</p>}
      </div>
    </div>
  )
})
