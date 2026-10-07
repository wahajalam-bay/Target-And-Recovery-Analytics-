import { ChevronRight, ChevronsDownUp, ChevronsUpDown } from 'lucide-react'
import { memo, useEffect, useMemo, useState } from 'react'
import { applyViewTree } from '../lib/aging'
import { count, money, moneyFull } from '../lib/format'
import { AgingBar, EmptyState, StatusBadge } from './ui'

function collectKeys(nodes, depthLimit, depth = 0, out = new Set()) {
  nodes.forEach((n) => {
    if (n.children?.length && depth < depthLimit) {
      out.add(n.key)
      collectKeys(n.children, depthLimit, depth + 1, out)
    }
  })
  return out
}

const DEFAULT_DEPTH = 2 // e.g. Arman Yousaf → Abdul Wahab Mian / Ajlal Haider → their teams

/** `view` = 'target' (achieved vs target) or 'received' (achieved + money received outside targets). */
function HierarchyTable({ data, onSelect, view = 'target' }) {
  const rootKey = data?.map((n) => n.key).join(',')
  const initial = useMemo(() => collectKeys(data || [], DEFAULT_DEPTH), [rootKey]) // eslint-disable-line react-hooks/exhaustive-deps
  const [open, setOpen] = useState(initial)
  useEffect(() => setOpen(initial), [initial]) // only when the visible root changes, not on refresh
  const rows = useMemo(() => applyViewTree(data, view), [data, view])

  if (!rows?.length) return <EmptyState />
  const toggle = (k) => setOpen((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })
  const received = view === 'received'

  return (
    <div>
      <div className="-mt-1 mb-2 flex justify-end gap-1">
        <button onClick={() => setOpen(collectKeys(rows, 99))} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-ink-500 hover:bg-hover hover:text-ink-900">
          <ChevronsUpDown size={12} /> Expand all
        </button>
        <button onClick={() => setOpen(new Set())} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-ink-500 hover:bg-hover hover:text-ink-900">
          <ChevronsDownUp size={12} /> Collapse all
        </button>
      </div>
      <div className="scroll-thin max-h-[620px] overflow-auto rounded-xl border border-line-soft">
        <table className="tbl min-w-[1060px]">
          <colgroup>
            <col /><col className="w-[64px]" /><col className="w-[124px]" /><col className="w-[130px]" /><col className="w-[110px]" />
            <col className="w-[160px]" /><col className="w-[120px]" /><col className="w-[84px]" /><col className="w-[90px]" />
          </colgroup>
          <thead>
            <tr>
              <th>Staff</th><th className="r">Team</th><th className="r">Target assigned</th>
              <th className="r">{received ? 'Received incl. outside' : 'Target achieved'}</th>
              <th className="r">Pending</th><th className="r">Achievement</th><th>Aging</th><th className="r">Bookings</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((n) => <Row key={n.key} node={n} depth={0} open={open} toggle={toggle} onSelect={onSelect} received={received} />)}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Row({ node, depth, open, toggle, onSelect, received }) {
  const hasKids = node.children?.length > 0
  const isOpen = open.has(node.key)
  const sub = hasKids ? 'Manager · team total' : node.has_own_target ? 'Individual target' : 'No target · money received outside targets'
  return (
    <>
      <tr className={`group ${hasKids ? 'font-medium' : ''}`}>
        <td style={hasKids ? { background: depth === 0 ? 'var(--color-primary-50)' : undefined } : undefined}>
          <div className="flex items-center" style={{ paddingLeft: depth * 22 }}>
            {depth > 0 && <span className="mr-2 h-7 w-px shrink-0 bg-line" aria-hidden />}
            <button onClick={() => hasKids && toggle(node.key)} aria-label={isOpen ? 'Collapse' : 'Expand'} aria-expanded={hasKids ? isOpen : undefined}
              className={`mr-1.5 grid h-5 w-5 shrink-0 place-items-center rounded ${hasKids ? 'text-ink-500 hover:bg-white hover:text-ink-900 hover:shadow-[0_0_0_1px_var(--color-line)]' : 'invisible'}`}>
              <ChevronRight size={13} className={`transition-transform duration-150 ${isOpen ? 'rotate-90' : ''}`} />
            </button>
            <div className={`mr-2.5 grid h-7 w-7 shrink-0 place-items-center rounded-full text-[10.5px] font-semibold ${hasKids ? 'bg-primary-700 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.25)]' : 'bg-line-soft text-ink-600'}`}>
              {initials(node.name)}
            </div>
            <div className="min-w-0 leading-tight">
              <p className={`truncate ${hasKids ? 'font-semibold text-ink-900' : 'font-medium text-ink-800'}`}>{node.name}</p>
              <p className="truncate text-[11px] font-normal text-ink-400">
                {sub}{hasKids && node.has_own_target ? ` · own ${money(node.own_assigned)}` : ''}
                {received && node.outside ? ` · incl. ${money(node.outside)} outside target` : ''}
              </p>
            </div>
          </div>
        </td>
        <td className="r num text-ink-500">{hasKids ? count(node.team_size) : '—'}</td>
        <td className="r num text-ink-600" title={moneyFull(node.assigned)}>{money(node.assigned)}</td>
        <td className="r"><span className="money" title={moneyFull(node.achieved)}>{money(node.achieved)}</span></td>
        <td className={`r num ${node.pending < 0 ? 'text-positive-700' : 'text-ink-600'}`} title={moneyFull(node.pending)}>{node.assigned ? money(node.pending) : '—'}</td>
        <td className="r">
          <span className="inline-flex items-center justify-end gap-2.5">
            <span className="bar-track w-16"><span className="bar-fill" style={{ width: `${Math.max(0, Math.min(100, node.rate ?? 0))}%`, background: rateColor(node.rate) }} /></span>
            <StatusBadge rate={node.rate} showLabel={false} />
          </span>
        </td>
        <td><AgingBar aging={node.aging} width={104} /></td>
        <td className="r num text-ink-600">{count(node.bookings)}</td>
        <td className="r">
          <button onClick={() => onSelect?.({ staff_id: node.staff_id, name: node.name })}
            className="inline-flex items-center gap-0.5 rounded-md px-2 py-1 text-xs font-medium text-primary-700 opacity-70 transition hover:bg-primary-50 hover:opacity-100 group-hover:opacity-100">
            Details <ChevronRight size={12} />
          </button>
        </td>
      </tr>
      {hasKids && isOpen && node.children.map((c) => (
        <Row key={c.key} node={c} depth={depth + 1} open={open} toggle={toggle} onSelect={onSelect} received={received} />
      ))}
    </>
  )
}

function rateColor(rate) {
  if (rate === null || rate === undefined) return '#cbd5e1'
  const r = Math.round(rate * 10) / 10
  return r >= 90 ? '#1f8a5b' : r >= 60 ? '#2456a6' : '#c0392b'
}

function initials(name = '') {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
}

export default memo(HierarchyTable)
