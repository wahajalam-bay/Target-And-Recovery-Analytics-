import { RefreshCw, Target } from 'lucide-react'
import { memo, useEffect, useState } from 'react'
import { monthLabel, timePKT } from '../lib/format'

/**
 * Dark header band: title, selected month, freshness and refresh. The filter toolbar is
 * rendered by the page and overlaps the bottom of this band (see App).
 * Keeps its own 1-second countdown so the rest of the dashboard doesn't re-render every second.
 */
function Header({ meta, refreshing, onRefresh, nextRefreshAt, error, snapshot, dataSource, month }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  const secondsLeft = Math.max(0, Math.round((nextRefreshAt - now) / 1000))
  const saved = dataSource === 'saved'
  // The backend only reports an error once data could not be confirmed current for 5 minutes,
  // so a single slow refresh never shows here.
  const delayed = !saved && !!error

  return (
    <header className="band">
      <div className="mx-auto flex max-w-[1680px] items-center justify-between gap-6 px-5 pb-12 pt-4 lg:px-8">
        <div className="flex min-w-0 items-center gap-3.5">
          <div className="coin shrink-0" style={{ '--coin-a': '#3b86e6', '--coin-b': '#183f80', '--coin-shadow': 'rgba(47,125,225,0.55)' }}>
            <Target size={17} strokeWidth={2.2} />
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-[17px] font-semibold leading-tight tracking-[-0.01em] text-white">Target &amp; Recovery Analytics</h1>
            <p className="band-sub truncate text-[12px]">
              Propone · Booking Management › Targets · Zameen Development
              {month && <> · <span className="text-white/90">{monthLabel(month)}</span></>}
            </p>
          </div>
        </div>

        {snapshot ? (
          <div className="text-right leading-tight">
            <p className="flex items-center justify-end gap-1.5 text-xs text-white/90">
              <span className="rounded-full bg-white/15 px-2 py-px text-[11px] font-semibold text-white">Snapshot</span>
              Data as of <span className="num font-medium">{timePKT(snapshot.taken_at, true)}</span>
              <span className="band-sub">PKT</span>
            </p>
            <p className="band-sub mt-0.5 text-[11px]">Static export · figures do not update</p>
          </div>
        ) : (
          <div className="flex items-center gap-4">
            <div className="hidden text-right leading-tight sm:block" title={`Data loaded into Redshift ${timePKT(meta?.data_last_loaded, true)}`}>
              <p className="flex items-center justify-end gap-1.5 text-xs text-white/90">
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${saved ? 'bg-[#ff8a80]' : delayed ? 'bg-[#fbbf24]' : 'bg-[#4ade80] shadow-[0_0_0_3px_rgba(74,222,128,0.18)]'}`} />
                {saved ? 'Showing saved data from' : delayed ? 'Data delayed · last confirmed' : 'Live · updated'}
                <span className="num font-medium text-white">{timePKT(meta?.refreshed_at)}</span>
                <span className="band-sub">PKT</span>
              </p>
              <p className="band-sub mt-0.5 text-[11px]">
                {saved || delayed
                  ? <><span title={error || ''}>{error || 'Waiting for Redshift'}</span> · retrying automatically</>
                  : <>Source loaded <span className="num">{timePKT(meta?.data_last_loaded, true)}</span> · next refresh <span className="num inline-block w-6 text-left">{secondsLeft}s</span></>}
              </p>
            </div>
            <button onClick={onRefresh} title="Refresh now"
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/15 bg-white/10 px-3 text-xs font-medium text-white transition-colors hover:bg-white/20">
              <RefreshCw size={12} className={refreshing ? 'animate-spin' : ''} />
              Refresh
            </button>
          </div>
        )}
      </div>
    </header>
  )
}

export default memo(Header)
