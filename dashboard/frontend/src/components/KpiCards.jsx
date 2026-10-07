import { CircleCheck, CircleDollarSign, Gauge, Hourglass, Layers, Target } from 'lucide-react'
import { memo } from 'react'
import { count, money, moneyFull, monthLabel, pct } from '../lib/format'
import { COLORS, rateStatus } from '../lib/theme'
import { DeltaChip, Skeleton, StatusBadge } from './ui'

/**
 * One KPI tile: 3D icon coin + small label, large value, optional comparison chip, supporting lines.
 * Values are exactly the API figures. Target achieved = Installment + Possession deposited in the
 * month on bookings with a target (Propone's stored figure is shown underneath); Target bookings
 * counts only bookings with a target; Outside targets = the same money on bookings with no target.
 */
function Kpi({ label, icon: Icon, coin, accent, value, unit, valueClass = 'text-ink-900', title, chip, children }) {
  return (
    <div className="kpi card card-hover flex h-[142px] flex-col px-4 pb-3.5 pt-3.5" title={title}>
      <span className="kpi-accent" style={{ background: accent }} />
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="label-caps truncate">{label}</p>
          <p className={`num mt-2 truncate text-[27px] font-semibold leading-none tracking-[-0.02em] ${valueClass}`}>
            {unit && <span className="mr-1 align-[4px] text-[11px] font-medium tracking-normal text-ink-400">{unit}</span>}
            {value}
          </p>
        </div>
        <span className="coin shrink-0" style={{ '--coin-a': coin[0], '--coin-b': coin[1], '--coin-shadow': coin[2] }}>
          <Icon size={15} strokeWidth={2.2} />
        </span>
      </div>
      <div className="mt-2 min-h-[20px]">{chip}</div>
      <div className="mt-auto text-xs leading-[17px] text-ink-500">{children}</div>
    </div>
  )
}

const COIN = {
  blue: ['#3b86e6', '#183f80', 'rgba(36,86,166,0.5)'],
  green: ['#3fb27f', '#176b47', 'rgba(31,138,91,0.5)'],
  slate: ['#9aa7b8', '#5b6778', 'rgba(91,103,120,0.45)'],
  red: ['#e06b5f', '#9b2d22', 'rgba(192,57,43,0.45)'],
}
const B = ({ children }) => <b className="num font-semibold text-ink-700">{children}</b>

function KpiCards({ kpis, compare, loading }) {
  const grid = 'grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6'
  if (loading || !kpis) {
    return (
      <div className={grid}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="card h-[142px] px-4 py-3.5">
            <Skeleton className="h-2.5 w-24" /><Skeleton className="mt-4 h-7 w-28" /><Skeleton className="mt-3 h-4 w-20" /><Skeleton className="mt-4 h-2.5 w-32" />
          </div>
        ))}
      </div>
    )
  }
  const status = rateStatus(kpis.rate)
  const statusCoin = status.key === 'high' ? COIN.green : status.key === 'low' ? COIN.red : COIN.blue
  const exceeded = kpis.pending < 0
  const o = kpis.outside || {}
  const prev = compare?.previous
  const vs = prev ? `vs ${monthLabel(prev.month, true)}` : null

  return (
    <div className={grid}>
      <Kpi label="Target assigned" icon={Target} coin={COIN.blue} accent={COLORS.primary} unit="PKR" value={money(kpis.assigned)} title={moneyFull(kpis.assigned)}>
        <B>{count(kpis.staff)}</B> staff · <B>{count(kpis.projects)}</B> projects
      </Kpi>

      <Kpi label="Target achieved" icon={CircleCheck} coin={COIN.green} accent={COLORS.positive} unit="PKR" value={money(kpis.achieved)}
        title={`${moneyFull(kpis.achieved)} Installment + Possession deposited this month on bookings with an assigned target. Propone's stored achieved amount: ${moneyFull(kpis.propone_achieved)}`}
        chip={<DeltaChip current={kpis.achieved} previous={prev?.achieved} label={vs} />}>
        <span className="block truncate">Inst. + Possession on targeted bookings</span>
        <span className="block truncate">Propone shows <B>{money(kpis.propone_achieved)}</B></span>
      </Kpi>

      <Kpi label="Pending target" icon={Hourglass} coin={COIN.slate} accent={COLORS.pending} unit="PKR" value={money(kpis.pending)} title={moneyFull(kpis.pending)}
        chip={exceeded ? <span className="delta delta-up">Target exceeded by {money(-kpis.pending)}</span> : null}>
        Assigned − achieved
      </Kpi>

      <Kpi label="Achievement rate" icon={Gauge} coin={statusCoin} accent={status.color} value={pct(kpis.rate)} valueClass={status.text}
        title={`${pct(kpis.rate)} · status ${status.label}`}
        chip={<DeltaChip current={kpis.rate} previous={prev?.rate} kind="pts" label={vs} />}>
        <div className="mb-1.5 bar-track"><div className="bar-fill transition-[width] duration-300" style={{ width: `${Math.min(100, kpis.rate ?? 0)}%`, background: status.color }} /></div>
        <StatusBadge rate={kpis.rate} />
      </Kpi>

      <Kpi label="Target bookings" icon={Layers} coin={COIN.slate} accent={COLORS.neutral} value={count(kpis.bookings_with_target)}
        title={`${count(kpis.bookings_with_target)} bookings with a target this month · ${count(kpis.bookings_with_achievement)} of them received Installment or Possession money against the target`}
        chip={kpis.bookings_with_target ? <span className="delta delta-flat whitespace-nowrap">{pct((100 * kpis.bookings_with_achievement) / kpis.bookings_with_target)} achieved</span> : null}>
        <span className="block truncate"><B>{count(kpis.bookings_with_achievement)}</B> achieved against target</span>
      </Kpi>

      <Kpi label="Outside targets" icon={CircleDollarSign} coin={COIN.slate} accent={COLORS.neutral} unit="PKR" value={money(o.target_related ?? 0)}
        title={`${moneyFull(o.target_related)} Installment + Possession received this month on ${count(o.bookings)} bookings with no target. Not part of Target achieved; detailed in the last section.`}
        chip={<span className="delta delta-flat whitespace-nowrap">{count(o.bookings ?? 0)} bookings</span>}>
        <span className="block truncate">Received with no target</span>
        <span className="block truncate">Installment + Possession</span>
      </Kpi>
    </div>
  )
}

export default memo(KpiCards)
