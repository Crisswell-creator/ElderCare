import { useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Lightbulb } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { api, p, type Activity, type AdherenceReport, type Counts, type Member } from '../api'
import { usePatient } from '../session'
import { Alert, Button, Empty, ErrorState, PageHead, SelectField, Skeleton, TextField, fmtDate, fmtDateTime } from '../ui'

const iso = (d: Date) => d.toISOString().slice(0, 10)

/** Stacked bars of recorded outcomes per period; a table below carries the same numbers. */
function OutcomeChart({ series, granularity }: { series: AdherenceReport['series']; granularity: string }) {
  if (!series.length) return null
  const W = 720, H = 220, pad = 28, gap = 4
  const max = Math.max(...series.map(s => s.scheduled), 1)
  const bw = Math.max(4, (W - pad * 2) / series.length - gap)
  const colors: [keyof Counts, string, string][] = [['taken', '#256b42', 'Taken'], ['skipped', '#8a99a3', 'Skipped'], ['missed', '#b42318', 'Missed'], ['unconfirmed', '#d29b3a', 'Not confirmed'], ['pending', '#d6ddda', 'Upcoming']]
  const label = (period: string) => granularity === 'month' ? fmtDate(period, { month: 'short' }) : fmtDate(period, { day: 'numeric', month: 'short' })
  const every = Math.ceil(series.length / 8)
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H + 24}`} className="chart" role="img" aria-label="Dose outcomes per period. The same numbers are in the table below.">
        {[0, 0.5, 1].map(t => <line key={t} x1={pad} x2={W - pad} y1={H - t * (H - 10)} y2={H - t * (H - 10)} stroke="#e3e8e6" />)}
        {series.map((s, i) => {
          let y = H
          const x = pad + i * (bw + gap)
          return (
            <g key={s.period}>
              {colors.map(([k, c]) => {
                const v = s[k] as number
                if (!v) return null
                const h = (v / max) * (H - 10)
                y -= h
                return <rect key={k} x={x} y={y} width={bw} height={h} fill={c} />
              })}
              {i % every === 0 && <text x={x + bw / 2} y={H + 16} textAnchor="middle">{label(s.period)}</text>}
            </g>
          )
        })}
      </svg>
      <figcaption className="row small" style={{ gap: 16 }}>
        {colors.map(([k, c, l]) => <span key={k} className="row" style={{ gap: 6 }}><span aria-hidden="true" style={{ width: 12, height: 12, background: c, borderRadius: 2, display: 'inline-block' }} />{l}</span>)}
      </figcaption>
    </figure>
  )
}

const pct = (c: Counts) => (c.adherence_pct === null ? '—' : `${Math.round(c.adherence_pct)}%`)

export function InsightsPage() {
  const { pid, can } = usePatient()
  const today = new Date()
  const [range, setRange] = useState({ start: iso(new Date(today.getTime() - 29 * 864e5)), end: iso(today), granularity: 'day' })
  const q = useQuery({
    queryKey: ['adherence', pid, range],
    queryFn: () => api.get<AdherenceReport>(p(pid, `/adherence?start=${range.start}&end=${range.end}&granularity=${range.granularity}`)),
    enabled: can('view_adherence'),
  })
  if (!can('view_adherence')) return <div className="page"><Alert tone="info">You don't have permission to see adherence reports.</Alert></div>
  const r = q.data
  return (
    <div className="page stack-lg">
      <PageHead title="Adherence" intro="Calculated only from doses recorded in ElderCare." />
      <form className="panel panel-pad form-grid two" onSubmit={e => e.preventDefault()} aria-label="Reporting period">
        <TextField label="From" type="date" value={range.start} max={range.end} onChange={e => setRange(s => ({ ...s, start: e.target.value }))} />
        <TextField label="To" type="date" value={range.end} min={range.start} onChange={e => setRange(s => ({ ...s, end: e.target.value }))} />
        <SelectField label="Group by" value={range.granularity} onChange={e => setRange(s => ({ ...s, granularity: e.target.value }))}>
          <option value="day">Day</option><option value="week">Week</option><option value="month">Month</option>
        </SelectField>
      </form>
      {q.isLoading ? <Skeleton lines={8} /> : q.error ? <ErrorState error={q.error} /> : r && (
        r.totals.scheduled === 0 ? <div className="panel"><Empty title="No doses in this period">Once doses are scheduled and recorded, results appear here.</Empty></div> : (
          <>
            <div className="stats" role="group" aria-label="Totals for the period">
              <div className="stat"><div className="value">{pct(r.totals)}</div><div className="label">Taken, of {r.totals.resolved} recorded</div></div>
              <div className="stat"><div className="value num">{r.totals.taken}</div><div className="label">Taken</div></div>
              <div className="stat"><div className="value num">{r.totals.skipped}</div><div className="label">Skipped</div></div>
              <div className="stat"><div className="value num">{r.totals.missed}</div><div className="label">Missed</div></div>
              <div className="stat"><div className="value num">{r.totals.unconfirmed}</div><div className="label">Not confirmed</div></div>
            </div>
            {r.insights.length > 0 ? (
              <section className="panel" aria-labelledby="ins-h">
                <div className="panel-head"><h2 id="ins-h">Patterns worth discussing</h2><Lightbulb aria-hidden="true" style={{ color: 'var(--muted)' }} /></div>
                <ul className="list">
                  {r.insights.map(i => <li key={i.kind}><p>{i.text}</p><p className="muted small">{i.basis}</p></li>)}
                </ul>
              </section>
            ) : (
              <p className="muted">No patterns shown: there isn't enough recorded data in this period to say anything reliable.</p>
            )}
            <section className="panel panel-pad stack" aria-labelledby="chart-h">
              <h2 id="chart-h">Outcomes by {range.granularity}</h2>
              <OutcomeChart series={r.series} granularity={r.granularity} />
            </section>
            <div className="stack-lg">
              <section className="panel table-wrap" aria-labelledby="med-h">
                <div className="panel-head"><h2 id="med-h">By medicine</h2></div>
                <table className="data">
                  <thead><tr><th scope="col">Medicine</th><th scope="col">Taken</th><th scope="col">Skipped</th><th scope="col">Missed</th><th scope="col">Not confirmed</th><th scope="col">Rate</th></tr></thead>
                  <tbody>{r.by_medication.map(m => <tr key={m.medication_id}><td>{m.name}</td><td className="num">{m.taken}</td><td className="num">{m.skipped}</td><td className="num">{m.missed}</td><td className="num">{m.unconfirmed}</td><td className="num">{pct(m)}</td></tr>)}</tbody>
                </table>
              </section>
              <section className="panel table-wrap" aria-labelledby="tod-h">
                <div className="panel-head"><h2 id="tod-h">By time of day</h2></div>
                <table className="data">
                  <thead><tr><th scope="col">Time</th><th scope="col">Recorded</th><th scope="col">Rate</th></tr></thead>
                  <tbody>{r.by_time_of_day.map(t => <tr key={t.bucket}><td>{t.label}</td><td className="num">{t.resolved}</td><td className="num">{pct(t)}</td></tr>)}</tbody>
                </table>
              </section>
            </div>
            <details className="panel panel-pad">
              <summary style={{ cursor: 'pointer', fontWeight: 600 }}>How these numbers are calculated</summary>
              <ul style={{ marginBottom: 0 }}>{r.rules.map(rule => <li key={rule}>{rule}</li>)}</ul>
              <table className="data" style={{ marginTop: 16 }}>
                <caption className="sr-only">Outcomes per period</caption>
                <thead><tr><th scope="col">Period</th><th scope="col">Taken</th><th scope="col">Skipped</th><th scope="col">Missed</th><th scope="col">Not confirmed</th><th scope="col">Upcoming</th></tr></thead>
                <tbody>{r.series.map(s => <tr key={s.period}><td>{fmtDate(s.period, { day: 'numeric', month: 'short', year: 'numeric' })}</td><td className="num">{s.taken}</td><td className="num">{s.skipped}</td><td className="num">{s.missed}</td><td className="num">{s.unconfirmed}</td><td className="num">{s.pending}</td></tr>)}</tbody>
              </table>
            </details>
          </>
        )
      )}
    </div>
  )
}

const CATEGORIES: [string, string][] = [['', 'Everything'], ['dose', 'Doses'], ['medication', 'Medicines'], ['inventory', 'Stock'], ['appointment', 'Appointments'], ['task', 'Tasks'], ['note', 'Notes'], ['access', 'Access and permissions'], ['profile', 'Profile'], ['document', 'Documents'], ['export', 'Exports'], ['help', 'Help requests']]

const fmtValue = (v: unknown) => (v === null || v === undefined || v === '' ? 'empty' : Array.isArray(v) ? v.join(', ') : String(v))

export function ActivityPage() {
  const { pid, can } = usePatient()
  const [params, setParams] = useSearchParams()
  const filters = { category: params.get('category') ?? '', person: params.get('person') ?? '', start: params.get('start') ?? '', end: params.get('end') ?? '' }
  const setFilter = (k: string, v: string) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }) }
  const members = useQuery({ queryKey: ['members', pid], queryFn: () => api.get<Member[]>(p(pid, '/members')), enabled: can('view_activity') })
  const qs = [filters.category && `category=${filters.category}`, filters.person && `actor_user_id=${filters.person}`, filters.start && `start=${filters.start}`, filters.end && `end=${filters.end}`].filter(Boolean).join('&')
  const q = useInfiniteQuery({
    queryKey: ['activity', pid, qs],
    queryFn: ({ pageParam }) => api.get<{ items: Activity[]; next_before: number | null }>(p(pid, `/activity?limit=30${pageParam ? `&before=${pageParam}` : ''}${qs ? `&${qs}` : ''}`)),
    initialPageParam: 0,
    getNextPageParam: last => last.next_before ?? undefined,
    enabled: can('view_activity'),
  })
  if (!can('view_activity')) return <div className="page"><Alert tone="info">You don't have permission to see the activity history.</Alert></div>
  const items = q.data?.pages.flatMap(pg => pg.items) ?? []
  return (
    <div className="page stack-lg" style={{ maxWidth: '60rem' }}>
      <PageHead title="Activity" intro="Every change, who made it and when. This history can't be edited or deleted." />
      <div className="panel panel-pad form-grid two" role="group" aria-label="Filter activity">
        <SelectField label="Kind" value={filters.category} onChange={e => setFilter('category', e.target.value)}>{CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</SelectField>
        <SelectField label="Person" value={filters.person} onChange={e => setFilter('person', e.target.value)}>
          <option value="">Everyone</option>{(members.data ?? []).map(m => <option key={m.user_id} value={m.user_id}>{m.full_name}</option>)}
        </SelectField>
        <TextField label="From" type="date" value={filters.start} onChange={e => setFilter('start', e.target.value)} />
        <TextField label="To" type="date" value={filters.end} onChange={e => setFilter('end', e.target.value)} />
      </div>
      {q.isLoading ? <Skeleton lines={8} /> : q.error ? <ErrorState error={q.error} /> : items.length === 0 ? (
        <div className="panel"><Empty title="Nothing matches these filters" /></div>
      ) : (
        <div className="panel">
          <ol className="list">
            {items.map(a => (
              <li key={a.id}>
                <div className="spread" style={{ alignItems: 'flex-start' }}>
                  <p>{a.summary}</p>
                  <time className="muted small num" dateTime={a.created_at} style={{ whiteSpace: 'nowrap' }}>{fmtDateTime(a.created_at)}</time>
                </div>
                {a.changes && Object.keys(a.changes).length > 0 && (
                  <details style={{ marginTop: 6 }}>
                    <summary className="small" style={{ cursor: 'pointer', color: 'var(--teal-700)' }}>What changed</summary>
                    <dl className="kv small" style={{ marginTop: 6 }}>
                      {Object.entries(a.changes).map(([field, [before, after]]) => (
                        <div key={field} style={{ display: 'contents' }}><dt>{field.replace(/_/g, ' ')}</dt><dd><span className="muted">{fmtValue(before)}</span> &rarr; {fmtValue(after)}</dd></div>
                      ))}
                    </dl>
                  </details>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
      {q.hasNextPage && <div><Button variant="secondary" loading={q.isFetchingNextPage} onClick={() => q.fetchNextPage()}>Show older activity</Button></div>}
    </div>
  )
}
