import { ArrowLeft, Building2, ChevronRight, Receipt, UserRound, X } from 'lucide-react'
import { memo, useEffect, useState } from 'react'
import { AGING } from '../lib/aging'
import { useApi } from '../lib/api'
import { count, money, moneyFull, monthLabel, pct } from '../lib/format'
import { rateStatus } from '../lib/theme'
import { AgingBar, EmptyState, ErrorState, RateBar, Skeleton, StatusBadge } from './ui'

/** Staff → Project → Booking / Unit → Installment + Possession payment lines (aging filter applied). */
function DrillDrawer({ person, filters, tick, onClose }) {
  const [project, setProject] = useState(null)
  const [booking, setBooking] = useState(null)
  useEffect(() => { setProject(null); setBooking(null) }, [person?.staff_id, filters.month])

  const base = { month: filters.month, city_id: filters.city_id, unit_id: filters.unit_id, aging: filters.aging }
  const projects = useApi('/drill/projects', { ...base, staff_id: person?.staff_id, project_id: filters.project_id }, tick, !!person)
  const bookings = useApi('/drill/bookings', { ...base, staff_id: person?.staff_id, project_id: project?.project_id }, tick, !!person && !!project)
  const payments = useApi('/drill/payments', { month: filters.month, booking_id: booking?.booking_id, aging: filters.aging }, tick, !!booking)

  useEffect(() => {
    if (!person) return undefined
    const esc = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [person, onClose])

  const level = booking ? 3 : project ? 2 : 1
  const back = () => (booking ? setBooking(null) : setProject(null))

  return (
    <>
      {person && (
        <>
          <div className="fade-in fixed inset-0 z-40 bg-ink-900/20" onClick={onClose} />
          <aside className="drawer-in fixed inset-y-0 right-0 z-50 flex w-full max-w-[1100px] flex-col border-l border-line bg-canvas shadow-[var(--shadow-pop)]">
            <header className="border-b border-line bg-white px-6 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  {level > 1 && (
                    <button onClick={back} aria-label="Back" className="grid h-8 w-8 place-items-center rounded-lg border border-line text-ink-700 hover:bg-hover">
                      <ArrowLeft size={15} />
                    </button>
                  )}
                  <div>
                    <p className="label-caps">Target detail · {monthLabel(filters.month)}{filters.aging?.length ? ` · aging: ${filters.aging.map((k) => AGING.find((a) => a.key === k)?.short).join(', ')}` : ''}</p>
                    <h2 className="text-[17px] font-semibold text-ink-900">{person.name}</h2>
                  </div>
                </div>
                <button onClick={onClose} aria-label="Close" className="grid h-8 w-8 place-items-center rounded-lg text-ink-500 hover:bg-hover hover:text-ink-900"><X size={17} /></button>
              </div>
              <nav className="mt-3 flex flex-wrap items-center gap-1 text-xs">
                <Crumb icon={UserRound} active={level === 1} onClick={() => { setProject(null); setBooking(null) }}>{person.name}</Crumb>
                {project && <><ChevronRight size={13} className="text-ink-400" />
                  <Crumb icon={Building2} active={level === 2} onClick={() => setBooking(null)}>{project.name}</Crumb></>}
                {booking && <><ChevronRight size={13} className="text-ink-400" />
                  <Crumb icon={Receipt} active>{booking.booking_number}{booking.unit ? ` · Unit ${booking.unit}` : ''}</Crumb></>}
              </nav>
            </header>

            <div className="scroll-thin flex-1 overflow-auto p-6">
              {level === 1 && <ProjectsLevel state={projects} onPick={setProject} />}
              {level === 2 && <BookingsLevel state={bookings} onPick={setBooking} />}
              {level === 3 && <PaymentsLevel state={payments} booking={booking} />}
            </div>
          </aside>
        </>
      )}
    </>
  )
}

function Crumb({ icon: Icon, active, onClick, children }) {
  return (
    <button onClick={onClick} disabled={active}
      className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 ${active ? 'bg-primary-100 font-semibold text-primary-800' : 'text-ink-600 hover:bg-hover hover:text-ink-900'}`}>
      <Icon size={12} /> {children}
    </button>
  )
}

function Loading() {
  return <div className="space-y-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-11 w-full" />)}</div>
}

function Summary({ items }) {
  return (
    <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-5">
      {items.map((it) => (
        <div key={it.label} className="card px-4 py-3">
          <p className="label-caps">{it.label}</p>
          <p className={`num mt-1.5 text-lg font-semibold ${it.tone || 'text-ink-900'}`} title={it.title}>{it.value}</p>
          {it.sub && <div className="mt-1 text-[11px] text-ink-500">{it.sub}</div>}
        </div>
      ))}
    </div>
  )
}

const TH = ({ children, left }) => <th className={`label-caps whitespace-nowrap py-2.5 pl-4 ${left ? 'text-left' : 'text-right'} last:pr-4`}>{children}</th>
const sum = (rows, k) => rows.reduce((a, r) => a + (r[k] || 0), 0)
const rate = (a, t) => (t ? (100 * a) / t : null)
const sumAging = (rows) => AGING.reduce((o, a) => ({ ...o, [a.key]: sum(rows.map((r) => r.aging || {}), a.key) }), {})

function Table({ head, children }) {
  return (
    <div className="card overflow-hidden">
      <table className="w-full text-[13px]">
        <thead className="border-b border-line"><tr>{head}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

/** Receivables by age (Propone) or deposits by age, as four small figures. */
function Buckets({ values, prefix }) {
  if (!values) return null
  return (
    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-500">
      {AGING.map((a) => (
        <span key={a.key} title={`${prefix} ${a.label}: ${moneyFull(values[a.key])}`}>
          {a.short}: <b className="num font-medium text-ink-700">{money(values[a.key] || 0)}</b>
        </span>
      ))}
    </div>
  )
}

function ProjectsLevel({ state, onPick }) {
  if (state.loading) return <Loading />
  if (state.error) return <ErrorState message={state.error} />
  const rows = state.data?.rows || []
  if (!rows.length) return <EmptyState />
  const A = sum(rows, 'assigned'), H = sum(rows, 'achieved'), O = sum(rows, 'outside')
  return (
    <>
      <Summary items={[
        { label: 'Target assigned', value: money(A), title: moneyFull(A) },
        { label: 'Target achieved', value: money(H), title: moneyFull(H), tone: 'text-positive-700', sub: 'Inst. + Possession on targeted bookings' },
        { label: 'Pending', value: money(A - H), title: moneyFull(A - H) },
        { label: 'Achievement', value: pct(rate(H, A)), tone: rateStatus(rate(H, A)).text, sub: <StatusBadge rate={rate(H, A)} /> },
        { label: 'Outside target', value: money(O), title: moneyFull(O), sub: `Total received ${money(H + O)}` }]} />
      <div className="card mb-4 px-4 py-3">
        <p className="label-caps mb-2">Target achieved by aging of the installment paid</p>
        <AgingBar aging={sumAging(rows)} height={10} legend />
      </div>
      <Table head={<><TH left>Project</TH><TH>Receivables</TH><TH>Assigned</TH><TH>Achieved</TH><TH>Pending</TH><TH>Achievement</TH><TH left>Aging</TH><TH>Outside target</TH><TH>Bookings</TH></>}>
        {rows.map((r) => (
          <tr key={r.project_id} onClick={() => onPick(r)} className="cursor-pointer border-b border-line-soft last:border-0 hover:bg-hover">
            <td className="py-3 pl-4">
              <p className="font-medium text-ink-900">{r.name}</p>
              <Buckets values={r.receivable_buckets} prefix="Receivable" />
            </td>
            <td className="num whitespace-nowrap py-3 pl-4 text-right text-ink-500" title={moneyFull(r.receivables)}>{money(r.receivables)}</td>
            <td className="num whitespace-nowrap py-3 pl-4 text-right text-ink-800" title={moneyFull(r.assigned)}>{money(r.assigned)}</td>
            <td className="num whitespace-nowrap py-3 pl-4 text-right font-semibold text-ink-900" title={moneyFull(r.achieved)}>{money(r.achieved)}</td>
            <td className={`num whitespace-nowrap py-3 pl-4 text-right ${r.pending < 0 ? 'text-positive-700' : 'text-ink-800'}`}>{r.assigned ? money(r.pending) : '—'}</td>
            <td className="py-3 pl-4"><RateBar rate={r.rate} width="w-14" /></td>
            <td className="py-3 pl-4"><AgingBar aging={r.aging} width={110} /></td>
            <td className="num whitespace-nowrap py-3 pl-4 text-right text-ink-600" title={moneyFull(r.outside)}>{money(r.outside)}</td>
            <td className="num whitespace-nowrap py-3 pl-4 pr-4 text-right text-ink-800">
              <span className="inline-flex items-center gap-1">{count(r.bookings)} <ChevronRight size={14} className="text-ink-400" /></span>
            </td>
          </tr>
        ))}
      </Table>
    </>
  )
}

function BookingsLevel({ state, onPick }) {
  if (state.loading) return <Loading />
  if (state.error) return <ErrorState message={state.error} />
  const rows = state.data?.rows || []
  if (!rows.length) return <EmptyState />
  const A = sum(rows, 'assigned'), H = sum(rows, 'achieved'), O = sum(rows, 'outside')
  const targeted = new Set(rows.filter((r) => r.targeted).map((r) => r.booking_id)).size
  return (
    <>
      <Summary items={[
        { label: 'Bookings with target', value: count(targeted), sub: `${count(rows.filter((r) => r.targeted && r.achieved > 0).length)} achieved against target` },
        { label: 'Target assigned', value: money(A), title: moneyFull(A) },
        { label: 'Target achieved', value: money(H), title: moneyFull(H), tone: 'text-positive-700' },
        { label: 'Achievement', value: pct(rate(H, A)), tone: rateStatus(rate(H, A)).text, sub: <StatusBadge rate={rate(H, A)} /> },
        { label: 'Outside target', value: money(O), title: moneyFull(O), sub: 'Received with no target' }]} />
      <Table head={<><TH left>Booking</TH><TH left>Unit</TH><TH left>Customer</TH><TH left>Staff</TH><TH left>Remarks</TH><TH>Assigned</TH><TH>Inst. + Possession</TH><TH>Pending</TH><TH>Overdue</TH><TH left>Aging</TH></>}>
        {rows.map((r) => (
          <tr key={r.booking_target_id} onClick={() => onPick(r)} className="cursor-pointer border-b border-line-soft last:border-0 hover:bg-hover">
            <td className="py-2.5 pl-4 font-medium text-ink-900">{r.booking_number}</td>
            <td className="py-2.5 pl-4 text-ink-700">{r.unit || '—'}</td>
            <td className="max-w-[160px] truncate py-2.5 pl-4 text-ink-800" title={r.customer || ''}>{r.customer || <span className="text-ink-400">—</span>}</td>
            <td className="py-2.5 pl-4 text-ink-500">{r.staff}</td>
            <td className="py-2.5 pl-4">
              {r.targeted
                ? (r.credited_row ? <span className="pill pill-soft-good">Targeted</span> : <span className="pill pill-soft-neutral" title="This booking is also in another staff member's target; its money is counted on that row">Shared · counted elsewhere</span>)
                : <span className="pill pill-soft-neutral" title="No target: money shown under Outside targets">No target</span>}
            </td>
            <td className="num whitespace-nowrap py-2.5 pl-4 text-right text-ink-800" title={moneyFull(r.assigned)}>{money(r.assigned)}</td>
            <td className="num whitespace-nowrap py-2.5 pl-4 text-right font-semibold text-ink-900" title={moneyFull(r.received)}>{money(r.received)}</td>
            <td className={`num whitespace-nowrap py-2.5 pl-4 text-right ${r.pending < 0 ? 'text-positive-700' : 'text-ink-800'}`}>{r.assigned ? money(r.pending) : '—'}</td>
            <td className="num whitespace-nowrap py-2.5 pl-4 text-right text-ink-500" title={moneyFull(r.overdue_amount)}>{money(r.overdue_amount)}</td>
            <td className="py-2.5 pl-4 pr-4"><span className="inline-flex items-center gap-2"><AgingBar aging={r.aging} width={96} /><ChevronRight size={14} className="text-ink-400" /></span></td>
          </tr>
        ))}
      </Table>
    </>
  )
}

function PaymentsLevel({ state, booking }) {
  if (state.loading) return <Loading />
  if (state.error) return <ErrorState message={state.error} />
  const d = state.data
  const lines = d?.lines || []
  return (
    <>
      <Summary items={[
        { label: 'Target assigned', value: money(booking.assigned), title: moneyFull(booking.assigned) },
        { label: booking.targeted ? 'Target achieved' : 'Received · no target', value: money(d?.received ?? booking.received), title: moneyFull(d?.received ?? booking.received), tone: 'text-positive-700', sub: 'Installment + Possession this month' },
        { label: 'Pending', value: booking.assigned ? money(booking.pending) : '—', title: moneyFull(booking.pending) },
        { label: 'Propone shows', value: money(booking.propone_achieved), title: moneyFull(booking.propone_achieved), sub: 'Propone stored achieved amount' },
        { label: 'Payments', value: count(new Set(lines.map((l) => l.payment_id)).size), sub: `${count(lines.length)} allocation lines` }]} />
      <div className="mb-4 grid grid-cols-2 gap-3 text-xs md:grid-cols-5">
        <Info label="Project" value={booking.project} /><Info label="Unit" value={booking.unit || '—'} />
        <Info label="Customer" value={booking.customer || '—'} />
        <Info label="Due this month" value={moneyFull(booking.due_amount)} /><Info label="Overdue" value={moneyFull(booking.overdue_amount)} />
      </div>
      <div className="card mb-4 px-4 py-3">
        <p className="label-caps mb-2">Received by aging of the installment paid</p>
        <AgingBar aging={d?.aging} height={10} legend />
      </div>
      {!lines.length ? (
        <div className="card"><EmptyState title="No Installment or Possession payment deposited this month" hint="Only Verified or Received payments deposited in the selected month count." /></div>
      ) : (
        <Table head={<><TH left>Deposited</TH><TH left>Payment ref</TH><TH left>Installment (Propone name)</TH><TH left>Category</TH><TH left>Installment due</TH><TH left>Aging</TH><TH left>Status</TH><TH>Amount</TH></>}>
          {lines.map((l, i) => (
            <tr key={i} className="border-b border-line-soft last:border-0">
              <td className="num py-2.5 pl-4 text-ink-700">{l.deposit_date || '—'}</td>
              <td className="num py-2.5 pl-4 text-ink-500">{l.payment_reference || l.payment_id}</td>
              <td className="py-2.5 pl-4 text-ink-900">{l.raw_value}</td>
              <td className="py-2.5 pl-4 text-ink-800">{l.category}</td>
              <td className="num py-2.5 pl-4 text-ink-500">{l.installment_due_date || '—'}</td>
              <td className="py-2.5 pl-4 text-ink-700">{l.aging_label || '—'}</td>
              <td className="py-2.5 pl-4 text-ink-500">{l.status}</td>
              <td className="num py-2.5 pl-4 pr-4 text-right font-semibold text-ink-900" title={moneyFull(l.amount)}>{moneyFull(l.amount).replace('PKR ', '')}</td>
            </tr>
          ))}
        </Table>
      )}
    </>
  )
}

function Info({ label, value }) {
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">{label}</p>
      <p className="num mt-0.5 truncate font-medium text-ink-900">{value}</p>
    </div>
  )
}

export default memo(DrillDrawer)
