import { Check, ChevronDown, Search, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

/**
 * Dropdown filter. Single-select by default; `multiple` gives checkboxes and an
 * array value. options: [{value, label, sub?, indent?}]
 */
export default function Combobox({
  label, icon: Icon, value, onChange, options, multiple = false, noun = 'items',
  placeholder = 'All', allLabel = 'All', searchable = true, disabled = false,
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    const esc = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [])
  useEffect(() => { if (open) { setQ(''); setTimeout(() => inputRef.current?.focus(), 30) } }, [open])

  const selected = useMemo(() => new Set((multiple ? value || [] : value == null ? [] : [value]).map(String)), [value, multiple])
  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase()
    const list = s ? options.filter((o) => `${o.label} ${o.sub || ''}`.toLowerCase().includes(s)) : options
    return list.slice(0, 500)
  }, [q, options])

  const toggle = (v) => {
    if (!multiple) { onChange(v); setOpen(false); return }
    const cur = value || []
    onChange(cur.some((x) => String(x) === String(v)) ? cur.filter((x) => String(x) !== String(v)) : [...cur, v])
  }
  const selectShown = () => {
    const cur = new Set((value || []).map(String))
    onChange([...(value || []), ...filtered.map((o) => o.value).filter((v) => !cur.has(String(v)))])
  }

  let text = placeholder
  let hasValue = false
  if (multiple && value?.length) {
    hasValue = true
    text = value.length === 1 ? (options.find((o) => String(o.value) === String(value[0]))?.label ?? '1 selected') : `${value.length} ${noun} selected`
  } else if (!multiple && value != null) {
    hasValue = true
    text = options.find((o) => String(o.value) === String(value))?.label ?? placeholder
  }

  return (
    <div ref={ref} className="relative w-full">
      <p className="label-caps mb-1 flex items-center gap-1.5">{Icon && <Icon size={11} className="text-ink-400" />} {label}</p>
      <button type="button" disabled={disabled} onClick={() => setOpen((o) => !o)}
        className={`flex h-9 w-full items-center justify-between gap-2 rounded-md border bg-white px-3 text-left text-[13px] transition-colors
          ${open ? 'border-primary-600 ring-2 ring-primary-600/10' : hasValue ? 'border-primary-300 hover:border-primary-500' : 'border-line hover:border-ink-400'}
          ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}>
        <span className={`truncate ${hasValue ? 'font-medium text-ink-900' : 'text-ink-500'}`}>{text}</span>
        <span className="flex items-center gap-1 text-ink-400">
          {hasValue && allLabel && (
            <span role="button" aria-label="Clear" className="rounded p-0.5 hover:bg-hover hover:text-ink-700"
              onClick={(e) => { e.stopPropagation(); onChange(multiple ? [] : null) }}><X size={13} /></span>
          )}
          <ChevronDown size={14} className={`transition-transform duration-150 ${open ? 'rotate-180' : ''}`} />
        </span>
      </button>
      {open && (
          <div className="pop-in absolute left-0 z-40 mt-1 w-full min-w-[280px] overflow-hidden rounded-lg border border-line bg-white shadow-[var(--shadow-pop)]">
            {searchable && (
              <div className="flex items-center gap-2 border-b border-line-soft px-3">
                <Search size={14} className="text-ink-400" />
                <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…"
                  className="h-9 w-full bg-transparent text-[13px] outline-none placeholder:text-ink-400" />
              </div>
            )}
            {multiple && (
              <div className="flex items-center justify-between border-b border-line-soft px-3 py-1.5 text-xs">
                <span className="text-ink-500">{selected.size ? `${selected.size} selected` : allLabel}</span>
                <span className="flex gap-3">
                  <button className="font-medium text-primary-600 hover:text-primary-800" onClick={selectShown}>Select {q ? 'matches' : 'all'}</button>
                  <button className="font-medium text-ink-500 hover:text-ink-800" onClick={() => onChange([])}>Clear</button>
                </span>
              </div>
            )}
            <ul className="scroll-thin max-h-80 overflow-auto py-1">
              {!multiple && allLabel && <Item active={value == null} onClick={() => toggle(null)} label={allLabel} />}
              {filtered.map((o) => (
                <Item key={o.value} multiple={multiple} active={selected.has(String(o.value))} onClick={() => toggle(o.value)}
                  label={o.label} sub={o.sub} indent={q ? 0 : o.indent} />
              ))}
              {filtered.length === 0 && <li className="px-3 py-6 text-center text-xs text-ink-500">No matches</li>}
            </ul>
          </div>
      )}
    </div>
  )
}

function Item({ active, onClick, label, sub, indent = 0, multiple }) {
  return (
    <li>
      <button type="button" onClick={onClick}
        className={`flex w-full items-center gap-2.5 py-1.5 pr-3 text-left text-[13px] hover:bg-hover ${active && !multiple ? 'bg-primary-50' : ''}`}
        style={{ paddingLeft: 12 + indent * 14 }}>
        {multiple ? (
          <span className={`grid h-4 w-4 shrink-0 place-items-center rounded border ${active ? 'border-primary-600 bg-primary-600 text-white' : 'border-ink-400/60 bg-white'}`}>
            {active && <Check size={11} strokeWidth={3} />}
          </span>
        ) : (
          <span className="flex h-4 w-4 shrink-0 items-center justify-center text-primary-600">{active && <Check size={14} />}</span>
        )}
        <span className="min-w-0 flex-1">
          <span className={`block truncate text-ink-900 ${active ? 'font-semibold' : ''}`}>{label}</span>
          {sub && <span className="block truncate text-[11px] text-ink-500">{sub}</span>}
        </span>
      </button>
    </li>
  )
}
