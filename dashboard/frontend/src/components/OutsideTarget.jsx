import { ChevronRight } from 'lucide-react'
import { memo, useMemo, useState } from 'react'
import { count, exact, money, moneyFull } from '../lib/format'
import { COLORS } from '../lib/theme'
import { AgingBar, EmptyState } from './ui'

/**
 * Installment + Possession received this month on bookings with no assigned target.
 * One figure, exactly the "Outside targets" KPI. The API still reports the two record kinds
 * (0-target bookings in the list, bookings in no list) separately; the page shows them as one.
 */
function combine(data) {
  const u = data.untagged || {}, z = data.zero_target || {}
  const rows = [
    ...(z.rows || []).map((r) => ({ ...r, kind: 'zero' })),
    ...(u.rows || []).map((r) => ({ ...r, kind: 'untagged' })),
  ].sort((a, b) => b.target_related - a.target_related)
  return { rows, staff: data.by_staff || [], total: data.target_related || 0, bookings: data.bookings || 0, payments: data.payments || 0, aging: data.aging || {} }
}

/** One bar per staff member: length = their amount against the largest one. */
const StaffChart = memo(function StaffChart({ data }) {
  if (!data?.length) return <EmptyState height={200} />
  const max = Math.max(1, ...data.map((d) => d.total))
  return (
    <div className="rowlist overflow-hidden rounded-xl">
      {data.map((d) => (
        <div key={d.name} className="grid grid-cols-[130px_minmax(0,1fr)_84px] items-center gap-3 px-3 py-[9px]"
          title={`${d.name}: ${moneyFull(d.total)} received with no target`}>
          <span className={`truncate text-[13px] ${d.name === 'Unassigned' ? 'italic text-ink-500' : 'font-medium text-ink-800'}`}>{d.name}</span>
          <span className="flex h-[10px] overflow-hidden rounded-full bg-line-soft shadow-[inset_0_1px_1px_rgba(11,31,58,0.08)]">
            <span className="h-full rounded-full" style={{ width: `${(d.total / max) * 100}%`, background: COLORS.primary }} />
          </span>
          <span className="money text-right text-[13px]" title={moneyFull(d.total)}>{money(d.total)}</span>
        </div>
      ))}
    </div>
  )
})

function Lines({ lines }) {
  return (
    <div className="rounded-lg bg-canvas px-3 py-2">
      <div className="grid grid-cols-[88px_1fr_110px_100px_120px_80px_110px] gap-3 pb-1 text-[10px] uppercase tracking-wide text-ink-400">
        <span>Deposited</span><span>Installment (Propone name)</span><span>Category</span><span>Due</span><span>Aging</span><span>Status</span><span className="text-right">Amount</span>
      </div>
      {lines.map((l, i) => (
        <div key={i} className="grid grid-cols-[88px_1fr_110px_100px_120px_80px_110px] items-center gap-3 py-1 text-xs">
          <span className="num text-ink-500">{l.deposit_date || '—'}</span>
          <span className="truncate text-ink-800" title={l.raw_value}>{l.raw_value}</span>
          <span className="text-ink-700">{l.category}</span>
          <span className="num text-ink-500">{l.installment_due_date || '—'}</span>
          <span className="text-ink-700">{l.aging_label || '—'}</span>
          <span className="text-ink-500">{l.status}</span>
          <span className="num text-right font-semibold text-ink-900">{exact(l.amount)}</span>
        </div>
      ))}
    </div>
  )
}

function Row({ r, open, toggle }) {
  return (
    <>
      <tr onClick={toggle} className="cursor-pointer">
        <td>
          <span className="inline-flex items-center gap-1.5 whitespace-nowrap font-medium text-ink-900">
            <ChevronRight size={13} className={`text-ink-400 transition-transform duration-150 ${open ? 'rotate-90' : ''}`} />{r.unit || '—'}
          </span>
        </td>
        <td className="whitespace-nowrap text-ink-700">{r.booking_number}</td>
        <td className="max-w-[160px] truncate text-ink-800" title={r.customer || ''}>{r.customer || <span className="text-ink-400">—</span>}</td>
        <td className="whitespace-nowrap text-ink-700">{r.project}</td>
        <td className={`whitespace-nowrap ${r.staff === 'Unassigned' ? 'italic text-ink-400' : 'text-ink-700'}`}>{r.staff}</td>
        <td><AgingBar aging={r.aging} width={88} /></td>
        <td className="r"><span className="money" title={moneyFull(r.target_related)}>{money(r.target_related)}</span></td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} className="!h-auto !bg-white py-2">
            {r.lines?.length ? <Lines lines={r.lines} /> : <p className="px-2 py-2 text-xs text-ink-500">No Installment or Possession payment deposited this month.</p>}
          </td>
        </tr>
      )}
    </>
  )
}

function OutsideTarget({ data }) {
  const [open, setOpen] = useState(null)
  const c = useMemo(() => (data && !data.error ? combine(data) : null), [data])
  if (data?.error) return <EmptyState title="This section is unavailable" hint={data.error} />
  if (!c) return null
  if (!c.bookings) return <EmptyState title="No money received without a target for these filters" hint="" />

  return (
    <div className="space-y-6">
      <div className="rounded-xl bg-gradient-to-br from-primary-50 to-white px-5 py-4 shadow-[inset_0_1px_0_#fff,0_0_0_1px_var(--color-line)]">
        <div className="grid grid-cols-1 items-end gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
          <div>
            <p className="label-caps">Received with no target</p>
            <p className="num mt-1.5 text-[30px] font-semibold leading-none tracking-[-0.02em] text-ink-900" title={moneyFull(c.total)}>
              <span className="mr-1 align-[5px] text-[12px] font-medium tracking-normal text-ink-400">PKR</span>{money(c.total)}
            </p>
            <p className="mt-2 text-xs text-ink-500">
              <b className="num font-semibold text-ink-700">{count(c.bookings)}</b> bookings · <b className="num font-semibold text-ink-700">{count(c.payments)}</b> payments · Installment + Possession
            </p>
          </div>
          <div>
            <p className="label-caps mb-2">By aging of the installment paid</p>
            <AgingBar aging={c.aging} height={10} legend />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 2xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <div>
          <p className="label-caps mb-2">By staff</p>
          <StaffChart data={c.staff} />
        </div>
        <div>
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="label-caps">By unit</p>
            <p className="text-[11.5px] text-ink-500"><b className="num font-semibold text-ink-700">{count(c.rows.length)}</b> bookings</p>
          </div>
          <div className="scroll-thin max-h-[460px] overflow-auto rounded-xl border border-line-soft">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Unit</th><th>Booking</th><th>Customer</th><th>Project</th><th>Staff</th><th>Aging</th>
                  <th className="r whitespace-nowrap">Received</th>
                </tr>
              </thead>
              <tbody>
                {c.rows.map((r) => <Row key={`${r.kind}-${r.booking_id}`} r={r} open={open === `${r.kind}-${r.booking_id}`} toggle={() => setOpen(open === `${r.kind}-${r.booking_id}` ? null : `${r.kind}-${r.booking_id}`)} />)}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

export default memo(OutsideTarget)
