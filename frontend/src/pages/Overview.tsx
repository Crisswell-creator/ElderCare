// Family and caregiver home for one person. Family members get the monitoring view (trends,
// visits, history); caregivers get the task view (what needs doing now). Same data, different
// emphasis; every number comes from the overview endpoint.
import { AlertTriangle, CalendarDays, FileDown, Pill } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Counts, Dose } from '../api'
import { usePatient } from '../hooks'
import { Alert, Badge, DoseBadge, Empty, PageHead, Skeleton } from '../ui'
import { doseView, fmtDate, fmtRelative, fmtTime, useNow } from '../lib'

function pct(c: Counts | null) {
  return c && c.adherence_pct !== null ? `${Math.round(c.adherence_pct)}%` : 'No data yet'
}

function AttentionList({ doses, pid, now }: { doses: Dose[]; pid: number; now: number }) {
  const items = doses.filter(d => ['overdue', 'unconfirmed', 'missed', 'due'].includes(doseView(d.status, d.scheduled_at, now)))
  if (!items.length) return <p className="muted">Nothing needs attention right now.</p>
  return (
    <ul className="list list-compact" style={{ margin: '0 calc(-1 * var(--s5))' }}>
      {items.map(d => (
        <li key={d.id} className="spread">
          <span><strong className="num">{fmtTime(d.local_time)}</strong> &nbsp;{d.medication_name} {d.strength}</span>
          <DoseBadge view={doseView(d.status, d.scheduled_at, now)} />
        </li>
      ))}
      <li><Link to={`/p/${pid}/today`}>Open today's doses</Link></li>
    </ul>
  )
}

export function OverviewPage() {
  const { pid, overview: o, can, name } = usePatient()
  const now = useNow()
  if (!o) return <div className="page"><Skeleton lines={8} /></div>
  const caregiver = o.my_role === 'caregiver'
  const doses = o.today_doses ?? []
  const done = doses.filter(d => d.status === 'taken').length
  const attention = doses.filter(d => ['overdue', 'unconfirmed', 'missed'].includes(doseView(d.status, d.scheduled_at, now))).length

  return (
    <div className="page stack-lg">
      <PageHead
        title={caregiver ? `Today's care for ${name}` : name ? `${o.patient_name}` : 'Overview'}
        intro={`${fmtDate(o.local_date, { weekday: 'long', day: 'numeric', month: 'long' })} in ${o.timezone.replace(/_/g, ' ')}`}
        actions={can('view_profile') && can('view_medications') && (
          <a className="btn btn-secondary" href={`/api/patients/${pid}/visit-summary.pdf`} target="_blank" rel="noopener">
            <FileDown aria-hidden="true" />Visit summary (PDF)
          </a>
        )}
      />

      {o.pending_requests > 0 && (
        <Alert tone="info" title={`${o.pending_requests} access request${o.pending_requests > 1 ? 's' : ''} waiting`}>
          <Link to={`/p/${pid}/care-team`}>Review requests</Link>
        </Alert>
      )}

      {o.today_doses && (
        <div className="stats" role="group" aria-label="Today's numbers">
          <div className="stat"><div className="value">{done}<span className="muted" style={{ fontSize: 'var(--fs-lg)' }}> / {doses.filter(d => !d.as_needed).length}</span></div><div className="label">Doses taken today</div></div>
          <div className="stat"><div className="value" style={{ color: attention ? 'var(--warn)' : undefined }}>{attention}</div><div className="label">Need attention</div></div>
          {o.adherence_7d && <div className="stat"><div className="value">{pct(o.adherence_7d)}</div><div className="label">Taken, last 7 days ({o.adherence_7d.resolved} recorded)</div></div>}
          {o.upcoming_appointments && <div className="stat"><div className="value">{o.upcoming_appointments.length}</div><div className="label">Upcoming visits</div></div>}
        </div>
      )}

      <div className="grid-dash">
        <div className="stack-lg">
          {o.today_doses && (
            <section className="panel" aria-labelledby="attention-h">
              <div className="panel-head"><h2 id="attention-h">{caregiver ? 'To do now' : 'Needs attention'}</h2>{attention > 0 && <AlertTriangle aria-hidden="true" style={{ color: 'var(--warn)' }} />}</div>
              <div className="panel-body"><AttentionList doses={doses} pid={pid} now={now} /></div>
            </section>
          )}
          {o.today_doses && (
            <section className="panel" aria-labelledby="sched-h">
              <div className="panel-head"><h2 id="sched-h">Today's schedule</h2><Link to={`/p/${pid}/today`} className="small">{can('confirm_doses') ? 'Record doses' : 'View doses'}</Link></div>
              {doses.length === 0 ? <Empty title="No doses today" /> : (
                <div className="table-wrap">
                  <table className="data">
                    <caption className="sr-only">Today's doses</caption>
                    <thead><tr><th scope="col">Time</th><th scope="col">Medicine</th><th scope="col">Status</th><th scope="col" className="hide-mobile">Recorded by</th></tr></thead>
                    <tbody>
                      {doses.map(d => (
                        <tr key={d.id}>
                          <td className="num">{d.as_needed ? 'As needed' : fmtTime(d.local_time)}</td>
                          <td>{d.medication_name} <span className="muted">{d.strength}</span></td>
                          <td><DoseBadge view={doseView(d.status, d.scheduled_at, now)} /></td>
                          <td className="hide-mobile muted">{d.confirmed_by ?? ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}
          {!caregiver && o.recent_activity && (
            <section className="panel" aria-labelledby="act-h">
              <div className="panel-head"><h2 id="act-h">Recent activity</h2><Link to={`/p/${pid}/activity`} className="small">Full history</Link></div>
              {o.recent_activity.length === 0 ? <Empty title="No activity yet" /> : (
                <ul className="list list-compact">
                  {o.recent_activity.map(a => <li key={a.id}><p>{a.summary}</p><p className="muted small">{fmtRelative(a.created_at)}</p></li>)}
                </ul>
              )}
            </section>
          )}
        </div>
        <div className="stack-lg">
          {o.upcoming_appointments && (
            <section className="panel" aria-labelledby="appts-h">
              <div className="panel-head"><h2 id="appts-h">Upcoming appointments</h2><CalendarDays aria-hidden="true" style={{ color: 'var(--muted)' }} /></div>
              {o.upcoming_appointments.length === 0 ? <Empty title="None scheduled" action={can('manage_appointments') && <Link className="btn btn-secondary" to={`/p/${pid}/appointments`}>Add appointment</Link>} /> : (
                <ul className="list list-compact">
                  {o.upcoming_appointments.map(a => (
                    <li key={a.id}>
                      <p><strong>{fmtDate(a.local_date)}</strong> at <span className="num">{fmtTime(a.local_time)}</span></p>
                      <p className="muted small">{a.doctor_name}{a.specialty && `, ${a.specialty}`}{a.location && ` | ${a.location}`}</p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
          {o.low_stock && o.low_stock.length > 0 && (
            <section className="panel" aria-labelledby="stock-h">
              <div className="panel-head"><h2 id="stock-h">Refills needed soon</h2><Pill aria-hidden="true" style={{ color: 'var(--muted)' }} /></div>
              <ul className="list list-compact">
                {o.low_stock.map(m => (
                  <li key={m.id} className="spread">
                    <Link to={`/p/${pid}/medications/${m.id}`}>{m.name} {m.strength}</Link>
                    <Badge tone="warn">~{Math.floor(m.days_remaining)} days left</Badge>
                  </li>
                ))}
              </ul>
              <p className="panel-body muted small">Estimates from recorded stock and the schedule.</p>
            </section>
          )}
          {o.adherence_30d && (
            <section className="panel panel-pad stack" aria-labelledby="adh-h">
              <h2 id="adh-h">Last 30 days</h2>
              {o.adherence_30d.resolved === 0 ? <p className="muted">No recorded doses yet.</p> : (
                <>
                  <p><span style={{ fontSize: 'var(--fs-2xl)', fontWeight: 700 }} className="num">{pct(o.adherence_30d)}</span> of recorded doses taken</p>
                  <div className="meter" aria-hidden="true"><span style={{ width: `${o.adherence_30d.adherence_pct ?? 0}%` }} /></div>
                  <p className="muted small num">{o.adherence_30d.taken} taken, {o.adherence_30d.skipped} skipped, {o.adherence_30d.missed} missed, {o.adherence_30d.unconfirmed} not confirmed</p>
                  <Link to={`/p/${pid}/insights`} className="small">See trends</Link>
                </>
              )}
            </section>
          )}
          <section className="panel" aria-labelledby="contacts-h">
            <div className="panel-head"><h2 id="contacts-h">Emergency contacts</h2></div>
            <div className="panel-body stack gap-2">
              {o.emergency_contacts.length === 0 ? <p className="muted small">None recorded.</p> : o.emergency_contacts.map(c => (
                <p key={c.name + c.phone}>{c.name}{c.relationship_label && <span className="muted"> ({c.relationship_label})</span>}<br /><a href={`tel:${c.phone.replace(/[^\d+]/g, '')}`}>{c.phone}</a></p>
              ))}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
