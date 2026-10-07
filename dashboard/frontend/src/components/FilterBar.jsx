import { Building2, Calendar, Hourglass, House, MapPin, RotateCcw, Users } from 'lucide-react'
import { memo, useMemo } from 'react'
import { AGING } from '../lib/aging'
import { monthLabel } from '../lib/format'
import { withTeams } from '../lib/hierarchy'
import Combobox from './Combobox'

const AGING_OPTIONS = AGING.map((a) => ({ value: a.key, label: a.label, sub: 'Age of the installment paid, at the start of the month' }))

/**
 * Floating glass toolbar. Lists arrive already cross-filtered by the backend (selecting a
 * project narrows staff, cities and units, and so on). Selecting a manager includes their
 * whole reporting line in the data; the option sub-label says how many that is.
 * Aging keeps every booking but counts only money on installments in the chosen buckets.
 */
function FilterBar({ options, filters, setFilter, reset, loading, disabled = false }) {
  const o = options || {}
  const months = useMemo(() => [...(o.months || [])].reverse().map((m) => ({ value: m, label: monthLabel(m) })), [o.months])
  const staff = useMemo(() => withTeams(o.staff).map((s) => ({
    value: s.id, label: s.name, indent: Math.max(0, s.level - 1),
    sub: s.isManager
      ? `Manager · includes ${s.agents} agent${s.agents === 1 ? '' : 's'}${s.team > s.agents ? ` and ${s.team - s.agents} manager${s.team - s.agents === 1 ? '' : 's'}` : ''} below`
      : 'Agent · individual target',
  })), [o.staff])
  const cities = useMemo(() => (o.cities || []).map((c) => ({ value: c.id, label: c.label, sub: c.projects.join(' · ') })), [o.cities])
  const projects = useMemo(() => (o.projects || [])
    .map((p) => ({ value: p.id, label: p.name, sub: (o.cities || []).find((c) => c.id === p.city_id)?.label })),
  [o.projects, o.cities])
  const units = useMemo(() => (o.units || []).map((u) => ({ value: u.id, label: u.label, sub: u.project })), [o.units])
  const active = ['staff_id', 'city_id', 'project_id', 'unit_id', 'aging'].reduce((n, k) => n + (filters[k]?.length ? 1 : 0), 0)
  const n = (list) => (loading && !list.length ? '…' : list.length.toLocaleString())

  return (
    <div className="glass px-4 py-3">
      <div className="grid grid-cols-2 items-end gap-3 md:grid-cols-3 xl:grid-cols-[1fr_1.4fr_1fr_1.25fr_1.2fr_1.1fr_auto]">
        <Combobox label="Month" disabled={disabled} icon={Calendar} value={filters.month} options={months} allLabel={null}
          searchable={false} placeholder={loading ? 'Loading…' : 'Select month'} onChange={(v) => v && setFilter('month', v)} />
        <Combobox multiple noun="staff" label="Staff · hierarchy" disabled={disabled} icon={Users} value={filters.staff_id} options={staff}
          allLabel="All staff" placeholder={`All staff (${n(staff)})`} onChange={(v) => setFilter('staff_id', v)} />
        <Combobox multiple noun="cities" label="City" disabled={disabled} icon={MapPin} value={filters.city_id} options={cities}
          allLabel="All cities" placeholder={`All cities (${n(cities)})`} searchable={false} onChange={(v) => setFilter('city_id', v)} />
        <Combobox multiple noun="projects" label="Project" disabled={disabled} icon={Building2} value={filters.project_id} options={projects}
          allLabel="All projects" placeholder={`All projects (${n(projects)})`} onChange={(v) => setFilter('project_id', v)} />
        <Combobox multiple noun="units" label="Unit" disabled={disabled} icon={House} value={filters.unit_id} options={units}
          allLabel="All units" placeholder={`All units (${n(units)})`} onChange={(v) => setFilter('unit_id', v)} />
        <Combobox multiple noun="buckets" label="Aging" disabled={disabled} icon={Hourglass} value={filters.aging || []} options={AGING_OPTIONS}
          allLabel="All aging" placeholder="All aging" searchable={false} onChange={(v) => setFilter('aging', v)} />
        {disabled ? (
          <p className="pb-2 text-[11.5px] leading-snug text-ink-500">Snapshot view<br />filters are off</p>
        ) : (
          <button onClick={reset} disabled={!active}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-xs font-medium text-ink-600 transition-colors hover:bg-white hover:text-ink-900 hover:shadow-[0_1px_2px_rgba(11,31,58,0.1)] disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:shadow-none">
            <RotateCcw size={13} /> Reset{active ? ` (${active})` : ''}
          </button>
        )}
      </div>
    </div>
  )
}

export default memo(FilterBar)
