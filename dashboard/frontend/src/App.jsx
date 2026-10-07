import { Banknote, Building2, CalendarRange, MapPin, Network, PieChart, TableProperties, Users } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CityChart, Contribution, ProjectTable, StaffTable, TrendChart, TrendTable, groupByCity } from './components/Charts'
import DrillDrawer from './components/DrillDrawer'
import FilterBar from './components/FilterBar'
import Header from './components/Header'
import HierarchyTable from './components/HierarchyTable'
import KpiCards from './components/KpiCards'
import OutsideTarget from './components/OutsideTarget'
import ReceivedStrip from './components/ReceivedStrip'
import { ChartSkeleton, ErrorState, Panel, Section, Segmented, Skeleton } from './components/ui'
import { AGING, VIEWS, applyView } from './lib/aging'
import { SNAPSHOT, useApi, useStable } from './lib/api'
import { count, money, monthLabel, pct } from './lib/format'
import { withTeams } from './lib/hierarchy'

const EMPTY = { month: null, staff_id: [], city_id: [], project_id: [], unit_id: [], aging: [] }
const REFRESH_MS = 60_000

function listLabel(names) {
  if (!names.length) return null
  return names.length <= 2 ? names.join(', ') : `${names.slice(0, 2).join(', ')} +${names.length - 2}`
}

export default function App() {
  const [filters, setFilters] = useState(EMPTY)
  const [tick, setTick] = useState(0)
  const [nextRefreshAt, setNextRefreshAt] = useState(() => Date.now() + REFRESH_MS)
  const nextRef = useRef(nextRefreshAt)
  const [person, setPerson] = useState(null)
  // 'target': achieved vs target. 'received': achieved + money received outside targets (the "more" view).
  const [view, setView] = useState('target')

  // Background refresh every 60s. The 1s check does not set state, so nothing re-renders in between.
  useEffect(() => {
    if (SNAPSHOT) return undefined // static export: no refresh
    const id = setInterval(() => {
      if (document.hidden || Date.now() < nextRef.current) return
      nextRef.current = Date.now() + REFRESH_MS
      setNextRefreshAt(nextRef.current)
      setTick((t) => t + 1)
    }, 1000)
    return () => clearInterval(id)
  }, [])
  const refreshNow = useCallback(() => {
    nextRef.current = Date.now() + REFRESH_MS
    setNextRefreshAt(nextRef.current)
    setTick((t) => t + 1)
  }, [])

  // Every selected dimension is sent, so each option list is narrowed by the others.
  const options = useApi('/filters', filters, tick)
  const dash = useApi('/dashboard', filters, tick)

  // Adopt the backend's default month on first load.
  useEffect(() => {
    if (!filters.month && dash.data?.meta?.month) setFilters((f) => ({ ...f, month: dash.data.meta.month }))
  }, [dash.data, filters.month])

  // Drop selected units that are no longer offered for the chosen cities/projects.
  useEffect(() => {
    const allowed = options.data?.units
    if (!allowed || !filters.unit_id.length) return
    const ok = new Set(allowed.map((u) => u.id))
    if (filters.unit_id.some((u) => !ok.has(u))) setFilters((f) => ({ ...f, unit_id: f.unit_id.filter((u) => ok.has(u)) }))
  }, [options.data, filters.unit_id])

  const projectsRef = useRef([])
  projectsRef.current = options.data?.projects || []
  const setFilter = useCallback((key, value) => {
    setFilters((f) => {
      const next = { ...f, [key]: value }
      if (key === 'city_id' && value.length) {
        const inCity = new Set(projectsRef.current.filter((p) => value.includes(p.city_id)).map((p) => p.id))
        next.project_id = f.project_id.filter((p) => inCity.has(p))
      }
      if (key === 'month') next.unit_id = []
      return next
    })
  }, [])
  const reset = useCallback(() => setFilters((f) => ({ ...EMPTY, month: f.month })), [])

  const d = dash.data
  // Each section keeps its previous object when a refresh returns identical numbers.
  const kpis = useStable(d?.kpis)
  const trend = useStable(d?.trend)
  const hierarchy = useStable(d?.hierarchy)
  const byStaff = useStable(d?.by_staff)
  const byProject = useStable(d?.by_project)
  const outside = useStable(d?.outside_target)
  const meta = d?.meta
  const o = options.data

  // Previous month (same filters) for the comparison chips — taken from the trend series.
  const compare = useMemo(() => {
    if (!trend?.length || !filters.month) return null
    const i = trend.findIndex((t) => t.month === filters.month)
    return i > 0 ? { previous: trend[i - 1] } : null
  }, [trend, filters.month])
  // Regions follow the view too: the same project rows, achieved or received.
  const byCity = useMemo(() => groupByCity(applyView(byProject, view), o), [byProject, o, view])
  const staffTeams = useMemo(() => withTeams(o?.staff), [o?.staff])

  const selectPerson = useCallback((s) => setPerson({ staff_id: s.staff_id, name: s.name }), [])
  const toggleProject = useCallback((p) => setFilters((f) => ({
    ...f, project_id: f.project_id.includes(p.project_id) ? f.project_id.filter((x) => x !== p.project_id) : [...f.project_id, p.project_id],
  })), [])
  const closeDrawer = useCallback(() => setPerson(null), [])

  const loading = dash.loading && !d
  const dim = dash.changing
  const names = (ids, list, key = 'name') => ids.map((id) => list?.find((x) => x.id === id)?.[key]).filter(Boolean)
  const staffScope = filters.staff_id.map((id) => staffTeams.find((s) => s.id === id)).filter(Boolean)
    .map((s) => (s.isManager ? `${s.name} & team (${s.agents} agent${s.agents === 1 ? '' : 's'})` : s.name))
  const scope = [
    listLabel(staffScope),
    listLabel(names(filters.city_id, o?.cities, 'label')),
    listLabel(names(filters.project_id, o?.projects)),
    filters.unit_id.length ? `${filters.unit_id.length} unit${filters.unit_id.length > 1 ? 's' : ''}` : null,
    filters.aging.length ? `Aging ${filters.aging.map((k) => AGING.find((a) => a.key === k)?.short).join(', ')}` : null,
  ].filter(Boolean)

  const viewToggle = SNAPSHOT ? null : <Segmented value={view} onChange={setView} options={VIEWS} />
  const received = view === 'received'
  // At-a-glance figures for section headers (all from data already on the page).
  const stats = {
    trend: kpis ? { value: pct(kpis.rate), label: `${filters.month ? monthLabel(filters.month, true) : ''} achievement rate` } : null,
    breakdown: byProject && byStaff ? { value: `${count(byProject.filter((p) => p.assigned > 0).length)} · ${count(byCity.length)} · ${count(byStaff.filter((s) => s.has_target !== false).length)}`, label: 'projects · regions · agents' } : null,
    detail: kpis ? { value: money(received ? kpis.received_total : kpis.achieved), label: received ? 'received incl. outside target' : 'target achieved' } : null,
    collections: kpis ? { value: money(kpis.outside?.target_related || 0), label: 'received without a target' } : null,
  }

  return (
    <div className="min-h-full">
      {/* 1. Header band */}
      <Header meta={meta} refreshing={dash.refreshing} onRefresh={refreshNow} nextRefreshAt={nextRefreshAt} snapshot={SNAPSHOT}
        error={dash.error && d ? dash.error : meta?.refresh_error} dataSource={meta?.data_source} month={filters.month} />

      <main className="mx-auto -mt-8 max-w-[1680px] space-y-10 px-5 pb-10 lg:px-8">
        {/* Filters: floating glass toolbar, stays at the top while scrolling */}
        <div className="sticky-tools">
          <FilterBar options={o} filters={filters} setFilter={setFilter} reset={reset} loading={options.loading} disabled={!!SNAPSHOT} />
        </div>
        <div className="!mt-2 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2 px-1">
            <p className="text-xs text-ink-600">
              <b className="font-semibold text-ink-900">{filters.month ? monthLabel(filters.month) : '…'}</b>
              {scope.length ? <> · {scope.join(' · ')}</> : <> · All staff, regions and projects</>}
            </p>
            {d && <p className="text-[11.5px] text-ink-400">
              {o ? `${count(o.staff.length)} staff · ${count(o.projects.length)} projects · ${count(o.units.length)} units in scope · ` : ''}
              Amounts in PKR · Installment + Possession only · hover any value for the exact figure
            </p>}
          </div>
          {dash.error && !d && <ErrorState message={dash.error} onRetry={refreshNow} />}
          {dash.error && d && <ErrorState compact message={`Latest refresh failed; showing the previous data. ${dash.error}`} onRetry={refreshNow} />}
        </div>

        {/* Row 1 — KPI cards, then what Target achieved is made of */}
        <div className="space-y-4">
          <KpiCards kpis={kpis} compare={compare} loading={loading} />
          <ReceivedStrip kpis={kpis} loading={loading} />
        </div>

        {/* Row 2 — Main trend analysis */}
        <Section title="Trend" description="Monthly target vs achievement · current filters applied to every month" stat={stats.trend}>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-12">
            <Panel className="xl:col-span-8" variant="hero" title="Monthly target vs achievement" icon={CalendarRange} dim={dim}
              subtitle="Achievement rate over the months, with target and achieved amounts · selected month highlighted">
              {loading ? <ChartSkeleton height={300} /> : <TrendChart data={trend} month={filters.month} height={300} />}
            </Panel>
            <Panel className="xl:col-span-4" title="Month by month" subtitle="Same figures as the chart" icon={TableProperties} dim={dim}>
              {loading ? <Skeleton className="h-[300px] w-full" /> : <TrendTable data={trend} month={filters.month} />}
            </Panel>
          </div>
        </Section>

        {/* Row 3 — Business breakdown */}
        <Section title="Business breakdown" description="Project, region and staff performance · click a project to filter, click a staff row for detail" stat={stats.breakdown}>
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-2 xl:items-start">
            <Panel variant="hero" title="Project performance" icon={Building2} dim={dim} actions={viewToggle}
              subtitle={received ? 'Target as the full bar, achieved + money received outside target filled against it' : 'Target as the full bar, achieved filled against it · click a row to filter the dashboard'}>
              {loading ? <ChartSkeleton /> : <ProjectTable data={byProject} onSelect={SNAPSHOT ? undefined : toggleProject} selected={filters.project_id} view={view} />}
            </Panel>
            <div className="grid grid-cols-1 gap-5">
              <Panel title="Region performance" subtitle="Project figures grouped by the project’s region" icon={MapPin} dim={dim}>
                {loading ? <Skeleton className="h-[180px] w-full" /> : <CityChart data={byCity} />}
              </Panel>
              <Panel title="Staff performance" icon={Users} dim={dim} actions={viewToggle}
                subtitle={byStaff ? `${count(byStaff.filter((s) => s.has_target !== false).length)} agents with individual targets · ${received ? 'achieved + outside target' : 'achieved'} against the target bar · click a row for detail` : ' '}>
                {loading ? <ChartSkeleton /> : <StaffTable data={byStaff} onSelect={selectPerson} view={view} />}
              </Panel>
            </div>
          </div>
        </Section>

        {/* Row 4 — Detailed analysis */}
        <Section title="Detailed analysis" description="Contribution to achievement and the staff hierarchy" stat={stats.detail}>
          <Panel title="Contribution to target achieved" subtitle="Share of the achieved amount, every project" icon={PieChart} dim={dim}>
            {loading ? <Skeleton className="h-[260px] w-full" /> : <Contribution rows={byProject} />}
          </Panel>

          <Panel variant="flat" title="Staff hierarchy" icon={Network} dim={dim} actions={viewToggle}
            subtitle={received
              ? 'Manager rows are the total of everyone below them · received = achieved + Installment/Possession money on bookings without a target'
              : 'Manager rows are the total of everyone below them · Details opens the project, booking and payment drill-down'}>
            {loading ? <div className="space-y-2">{Array.from({ length: 7 }).map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}</div>
              : <HierarchyTable data={hierarchy} onSelect={selectPerson} view={view} />}
            {received && kpis?.outside?.unplaced ? (
              <p className="mt-2 px-1 text-[11px] text-ink-500">
                {money(kpis.outside.unplaced)} of the money received outside targets belongs to bookings with no assignee or an assignee outside this hierarchy, so it appears in the KPI but on no staff row.
              </p>
            ) : null}
          </Panel>
        </Section>

        {/* Row 5 — Money received without a target */}
        <Section title="Money received without a target" accent="green" stat={stats.collections}
          description="Installment + Possession deposited this month on bookings with no target · the same figure as the Outside targets KPI">
          <Panel title="Outside targets" icon={Banknote} dim={dim}
            subtitle="Installment + Possession received on bookings with no target · click a unit for its payments">
            {loading ? <Skeleton className="h-[320px] w-full" /> : <OutsideTarget data={outside} />}
          </Panel>
        </Section>

        <footer className="border-t border-line pt-4 text-[11px] text-ink-400">
          Read-only view of Propone data in Amazon Redshift. Targets come from Propone’s target tables. Target achieved is the Installment + Possession money actually deposited in the month (Verified or Received) on bookings that carry an assigned target; money on bookings without a target is shown separately as Outside targets. Manager rows sum their whole team.
          {SNAPSHOT ? ' Static snapshot; figures do not update.' : ''}
        </footer>
      </main>

      {/* Drill-down (staff → project → booking → payments) */}
      <DrillDrawer person={person} filters={filters} tick={tick} onClose={closeDrawer} />
    </div>
  )
}
