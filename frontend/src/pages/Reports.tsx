// Period reports computed from stored records, with permission-checked downloads.
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Download, FileDown } from 'lucide-react'
import { api, p, type Report } from '../api'
import { usePatient } from '../hooks'
import { Empty, ErrorState, PageHead, Skeleton, TextField } from '../ui'
import { fmtDate, fmtDateTime } from '../lib'

const iso = (d: Date) => d.toISOString().slice(0, 10)

export function ReportsPage() {
  const { pid, can } = usePatient()
  const [range, setRange] = useState(() => ({ start: iso(new Date(Date.now() - 29 * 864e5)), end: iso(new Date()) }))
  const q = useQuery({ queryKey: ['report', pid, range], queryFn: () => api.get<Report>(p(pid, `/reports?start=${range.start}&end=${range.end}`)) })
  const qs = `?start=${range.start}&end=${range.end}`
  const r = q.data
  return (
    <div className="page stack-lg">
      <PageHead title="Reports" intro="Totals for a chosen period, calculated from what has been recorded." />
      <div className="panel panel-pad form-grid two" role="group" aria-label="Reporting period">
        <TextField label="From" type="date" value={range.start} max={range.end} onChange={e => setRange(s => ({ ...s, start: e.target.value }))} />
        <TextField label="To" type="date" value={range.end} min={range.start} onChange={e => setRange(s => ({ ...s, end: e.target.value }))} />
      </div>
      <section className="panel panel-pad stack" aria-labelledby="dl-h">
        <h2 id="dl-h">Downloads</h2>
        <div className="row">
          {can('view_profile') && can('view_medications') && <a className="btn btn-secondary" href={p(pid, '/visit-summary.pdf')} target="_blank" rel="noopener"><FileDown aria-hidden="true" />Doctor visit summary (PDF)</a>}
          {can('view_medications') && <a className="btn btn-secondary" href={p(pid, `/reports/doses.csv${qs}`)}><Download aria-hidden="true" />Dose records (CSV)</a>}
          {can('view_appointments') && <a className="btn btn-secondary" href={p(pid, `/reports/appointments.csv${qs}`)}><Download aria-hidden="true" />Appointments (CSV)</a>}
          <a className="btn btn-secondary" href={p(pid, '/reports/tasks.csv')}><Download aria-hidden="true" />Care tasks (CSV)</a>
        </div>
        <p className="muted small">Downloads include only what you're allowed to see, and each one is recorded in the activity history.</p>
      </section>
      {q.isLoading ? <Skeleton lines={6} /> : q.error ? <ErrorState error={q.error} /> : r && (
        <>
          {r.adherence && (
            <section className="panel table-wrap" aria-labelledby="med-h">
              <div className="panel-head"><h2 id="med-h">Medicines by week</h2></div>
              {r.adherence.totals.scheduled === 0 ? <Empty title="No doses in this period" /> : (
                <table className="data">
                  <thead><tr><th scope="col">Week starting</th><th scope="col">Taken</th><th scope="col">Skipped</th><th scope="col">Missed</th><th scope="col">Not confirmed</th><th scope="col">Rate</th></tr></thead>
                  <tbody>
                    {r.adherence.weekly.map(w => <tr key={w.period}><td>{fmtDate(w.period, { day: 'numeric', month: 'short' })}</td><td className="num">{w.taken}</td><td className="num">{w.skipped}</td><td className="num">{w.missed}</td><td className="num">{w.unconfirmed}</td><td className="num">{w.adherence_pct === null ? '—' : `${Math.round(w.adherence_pct)}%`}</td></tr>)}
                    <tr><th scope="row">Whole period</th><td className="num">{r.adherence.totals.taken}</td><td className="num">{r.adherence.totals.skipped}</td><td className="num">{r.adherence.totals.missed}</td><td className="num">{r.adherence.totals.unconfirmed}</td><td className="num">{r.adherence.totals.adherence_pct === null ? '—' : `${Math.round(r.adherence.totals.adherence_pct)}%`}</td></tr>
                  </tbody>
                </table>
              )}
            </section>
          )}
          <div className="grid-dash">
            {r.appointments && (
              <section className="panel panel-pad stack" aria-labelledby="ap-h">
                <h2 id="ap-h">Appointments</h2>
                <dl className="kv">
                  <dt>In the period</dt><dd className="num">{r.appointments.total}</dd>
                  <dt>Attended</dt><dd className="num">{r.appointments.completed}</dd>
                  <dt>Cancelled</dt><dd className="num">{r.appointments.cancelled}</dd>
                  <dt>Still upcoming</dt><dd className="num">{r.appointments.upcoming}</dd>
                  <dt>Past, outcome not recorded</dt><dd className="num">{r.appointments.past_unrecorded}</dd>
                </dl>
              </section>
            )}
            <section className="panel panel-pad stack" aria-labelledby="tk-h">
              <h2 id="tk-h">Care tasks</h2>
              <p className="num">{r.tasks.open} open, {r.tasks.overdue} overdue, {r.tasks.completed_in_period} completed in this period</p>
              {r.tasks.by_person.length > 0 && (
                <table className="data">
                  <thead><tr><th scope="col">Person</th><th scope="col">Open</th><th scope="col">Overdue</th><th scope="col">Completed</th></tr></thead>
                  <tbody>{r.tasks.by_person.map(b => <tr key={b.name}><td>{b.name}</td><td className="num">{b.open ?? 0}</td><td className="num">{b.overdue ?? 0}</td><td className="num">{b.completed_in_period ?? 0}</td></tr>)}</tbody>
                </table>
              )}
            </section>
          </div>
          <div className="grid-dash">
            {r.refills && (
              <section className="panel table-wrap" aria-labelledby="rf-h">
                <div className="panel-head"><h2 id="rf-h">Refills recorded</h2></div>
                {r.refills.length === 0 ? <Empty title="No refills in this period" /> : (
                  <table className="data"><thead><tr><th scope="col">When</th><th scope="col">Medicine</th><th scope="col">Added</th><th scope="col">By</th></tr></thead>
                    <tbody>{r.refills.map((f, i) => <tr key={i}><td>{fmtDateTime(f.recorded_at)}</td><td>{f.medication}</td><td className="num">{f.quantity}</td><td>{f.by}</td></tr>)}</tbody></table>
                )}
              </section>
            )}
            {r.activity_by_person && (
              <section className="panel panel-pad stack" aria-labelledby="ac-h">
                <h2 id="ac-h">Who has been helping</h2>
                <p className="muted small">Number of recorded actions, listed alphabetically.</p>
                <ul className="list list-compact" style={{ margin: '0 calc(-1 * var(--s5))' }}>{r.activity_by_person.map(a => <li key={a.name} className="spread"><span>{a.name}</span><span className="num">{a.actions}</span></li>)}</ul>
              </section>
            )}
          </div>
          <ul className="muted small">{r.notes.map(n => <li key={n}>{n}</li>)}</ul>
        </>
      )}
    </div>
  )
}
