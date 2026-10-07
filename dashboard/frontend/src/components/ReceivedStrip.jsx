import { memo } from 'react'
import { AGING, agingTotal } from '../lib/aging'
import { count, money, moneyFull, pct } from '../lib/format'
import { COLORS } from '../lib/theme'
import { AgingBar, Skeleton } from './ui'

const SPLIT = [
  { key: 'installment', label: 'Installment', color: COLORS.primary },
  { key: 'possession', label: 'Possession', color: '#6f93cf' },
]

/**
 * Right under the KPI cards: what the Target achieved figure is made of.
 *   left   Installment vs Possession (the only two categories that count)
 *   middle the same money by aging bucket of the installment it paid
 *   right  total received including money outside targets
 * Every figure is the API's; the strip never computes a new measure.
 */
function ReceivedStrip({ kpis, loading }) {
  if (loading || !kpis) return <Skeleton className="h-[112px] w-full" />
  const total = kpis.achieved || 0
  const split = kpis.split || {}
  const aging = kpis.aging || {}
  const share = (v) => (total ? pct((v / total) * 100) : '0%')
  return (
    <div className="card grid grid-cols-1 gap-5 px-5 py-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1.6fr)_minmax(0,0.8fr)]">
      <div>
        <p className="label-caps">Received against target</p>
        <p className="num mt-1 text-[22px] font-semibold leading-tight text-ink-900" title={moneyFull(total)}>
          {money(total)} <span className="text-xs font-medium text-ink-500">· {count(split.payments)} payments</span>
        </p>
        <div className="mt-2.5 flex h-2.5 overflow-hidden rounded-full bg-line-soft">
          {SPLIT.map((s) => <span key={s.key} style={{ width: `${total ? ((split[s.key] || 0) / total) * 100 : 0}%`, background: s.color }} />)}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[12px]">
          {SPLIT.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5 text-ink-700" title={moneyFull(split[s.key])}>
              <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />{s.label}
              <b className="num font-semibold text-ink-900">{money(split[s.key] || 0)}</b>
              <span className="num text-ink-500">{share(split[s.key] || 0)}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="lg:border-l lg:border-line-soft lg:pl-5">
        <p className="label-caps">By aging of the installment paid</p>
        <div className="mt-2.5"><AgingBar aging={aging} height={10} /></div>
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-4">
          {AGING.map((a) => (
            <div key={a.key} className="min-w-0" title={`${a.label}: ${moneyFull(aging[a.key])}`}>
              <p className="flex items-center gap-1.5 truncate text-[11px] text-ink-500"><span className="h-2 w-2 rounded-[2px]" style={{ background: a.color }} />{a.label}</p>
              <p className="num text-[14px] font-semibold text-ink-900">{money(aging[a.key] || 0)} <span className="text-[11px] font-medium text-ink-500">{share(aging[a.key] || 0)}</span></p>
            </div>
          ))}
        </div>
        {agingTotal(aging) !== total && <p className="mt-1 text-[11px] text-critical-700">Aging buckets do not add up to the total.</p>}
      </div>

      <div className="lg:border-l lg:border-line-soft lg:pl-5">
        <p className="label-caps">Total received incl. outside target</p>
        <p className="num mt-1 text-[22px] font-semibold leading-tight text-ink-900" title={moneyFull(kpis.received_total)}>{money(kpis.received_total || 0)}</p>
        <p className="mt-1.5 text-[12px] text-ink-600">
          <b className="num font-semibold text-ink-800">{money(total)}</b> against target + <b className="num font-semibold text-ink-800">{money(kpis.outside?.target_related || 0)}</b> outside target
        </p>
        <p className="mt-0.5 text-[11px] text-ink-400">Installment + Possession only</p>
      </div>
    </div>
  )
}

export default memo(ReceivedStrip)
