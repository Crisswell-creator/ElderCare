import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlarmClock, CalendarDays, Check, Phone, RotateCcw, SkipForward, Volume2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, p, type Dose } from '../api'
import { usePatient, useSession } from '../hooks'
import { Alert, Button, DoseBadge, Empty, ErrorState, Modal, PageHead, Skeleton, TextArea } from '../ui'
import { doseView, errorText, fmtDate, fmtQty, fmtTime, useNow, useToast, type DoseView } from '../lib'

const SOURCE_LABEL: Record<string, string> = { elder: 'the elder', caregiver: 'a caregiver', family: 'a family member' }

function greeting(): string {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

function useDoseActions(pid: number) {
  const qc = useQueryClient()
  const toast = useToast()
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['doses', pid] })
    qc.invalidateQueries({ queryKey: ['overview', pid] })
    qc.invalidateQueries({ queryKey: ['medications', pid] })
  }
  return useMutation({
    mutationFn: ({ dose, action, body }: { dose: Dose; action: 'take' | 'skip' | 'snooze' | 'undo'; body?: object }) =>
      api.post<Dose>(p(pid, `/doses/${dose.id}/${action}`), body ?? {}),
    onSuccess: (_d, v) => {
      const name = v.dose.medication_name
      toast({ take: `${name} recorded as taken.`, skip: `${name} recorded as skipped.`, snooze: `Reminder snoozed.`, undo: `Record removed for ${name}.` }[v.action])
      invalidate()
    },
    onError: err => { toast(errorText(err), 'error'); invalidate() },
  })
}

function DoseCard({ dose, view, canConfirm, isElder, onSkip, act, busyId }: {
  dose: Dose; view: DoseView; canConfirm: boolean; isElder: boolean; busyId: number | null
  onSkip: (d: Dose) => void; act: (d: Dose, a: 'take' | 'snooze' | 'undo', body?: object) => void
}) {
  const open = ['upcoming', 'due', 'overdue', 'unconfirmed', 'missed'].includes(view)
  const recorded = dose.status === 'taken' || dose.status === 'skipped'
  const busy = busyId === dose.id
  const headingId = `dose-${dose.id}`
  return (
    <article className="dose" aria-labelledby={headingId}>
      <div className="spread" style={{ alignItems: 'flex-start' }}>
        <div>
          <h3 id={headingId} className="dose-name">{dose.medication_name}{dose.strength && <span className="muted" style={{ fontWeight: 600 }}> {dose.strength}</span>}</h3>
          <p className="dose-meta">{fmtQty(dose.dose_amount)} {dose.dose_unit}{dose.instructions && <> &mdash; {dose.instructions}</>}</p>
        </div>
        <DoseBadge view={view} />
      </div>
      {recorded && (
        <p className="muted small">
          {dose.status === 'taken' ? 'Taken' : 'Skipped'} at {new Date(dose.confirmed_at!).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          {dose.confirmed_by && <> by {dose.confirmed_by}{!isElder && dose.confirmation_source && ` (${SOURCE_LABEL[dose.confirmation_source] ?? dose.confirmation_source})`}</>}
          {dose.skip_reason && <> &mdash; &ldquo;{dose.skip_reason}&rdquo;</>}
        </p>
      )}
      {view === 'unconfirmed' && <p className="small" style={{ color: 'var(--warn)' }}>Nobody has recorded this dose yet. If it was taken, you can still record it.</p>}
      {canConfirm && (open || recorded) && (
        <div className="dose-actions">
          {open && view !== 'upcoming' && (
            <>
              <Button icon={<Check aria-hidden="true" />} loading={busy} onClick={() => act(dose, 'take')}>
                Taken<span className="sr-only">: {dose.medication_name}</span>
              </Button>
              <Button variant="secondary" icon={<SkipForward aria-hidden="true" />} disabled={busy} onClick={() => onSkip(dose)}>
                Skip<span className="sr-only">: {dose.medication_name}</span>
              </Button>
              {view === 'due' && dose.status === 'scheduled' && (
                <Button variant="quiet" icon={<AlarmClock aria-hidden="true" />} disabled={busy} onClick={() => act(dose, 'snooze', { minutes: 15 })}>
                  Remind me in 15 min
                </Button>
              )}
            </>
          )}
          {view === 'upcoming' && (
            <Button variant="secondary" icon={<Check aria-hidden="true" />} loading={busy} onClick={() => act(dose, 'take')}>
              Taken early<span className="sr-only">: {dose.medication_name}</span>
            </Button>
          )}
          {recorded && !dose.as_needed && (
            <Button variant="quiet" icon={<RotateCcw aria-hidden="true" />} loading={busy} onClick={() => act(dose, 'undo')}>
              Undo<span className="sr-only"> record for {dose.medication_name}</span>
            </Button>
          )}
        </div>
      )}
    </article>
  )
}

export function TodayPage() {
  const { pid, overview, can, isElder, name } = usePatient()
  const [date, setDate] = useState('')
  const day = date || overview?.local_date || ''
  const dosesQ = useQuery({
    queryKey: ['doses', pid, day],
    queryFn: () => api.get<Dose[]>(p(pid, `/doses?start=${day}&end=${day}`)),
    enabled: !!day && can('view_medications'),
    refetchInterval: 60_000,
  })
  const actions = useDoseActions(pid)
  const [skipping, setSkipping] = useState<Dose | null>(null)
  const [reason, setReason] = useState('')
  const now = useNow()
  const doses = useMemo(() => (dosesQ.data ?? []).filter(d => !d.as_needed || d.status === 'taken'), [dosesQ.data])
  const slots = useMemo(() => {
    const map = new Map<string, Dose[]>()
    for (const d of doses) map.set(d.local_time, [...(map.get(d.local_time) ?? []), d])
    return [...map.entries()]
  }, [doses])
  const isToday = day === overview?.local_date
  const next = isToday ? doses.find(d => d.status === 'scheduled') : undefined
  const nextGroup = next ? doses.filter(d => d.status === 'scheduled' && d.local_time === next.local_time) : []

  const { user } = useSession()
  const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window && user?.preferences?.read_aloud !== false
  function readAloud() {
    const parts = slots.map(([time, group]) => `At ${fmtTime(time)}: ${group.map(d => `${d.medication_name}, ${d.status === 'taken' ? 'taken' : d.status === 'skipped' ? 'skipped' : 'not yet taken'}`).join('; ')}.`)
    const next = overview?.upcoming_appointments?.[0]
    const text = [parts.length ? `Today's medicines. ${parts.join(' ')}` : 'No medicines are scheduled today.',
      next ? `Next appointment: ${fmtDate(next.local_date, { weekday: 'long', day: 'numeric', month: 'long' })} at ${fmtTime(next.local_time)} with ${next.doctor_name}.` : ''].join(' ')
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    u.rate = 0.9
    window.speechSynthesis.speak(u) // reads only; it never records or changes anything
  }
  if (!overview) return <div className="page"><Skeleton lines={6} /></div>
  const act = (dose: Dose, action: 'take' | 'snooze' | 'undo', body?: object) => actions.mutate({ dose, action, body })
  const busyId = actions.isPending ? actions.variables?.dose.id ?? null : null
  const appt = overview.upcoming_appointments?.[0]
  const counts = { taken: doses.filter(d => d.status === 'taken').length, total: doses.filter(d => !d.as_needed).length }

  return (
    <div className="page stack-lg">
      <PageHead
        title={isElder ? `${greeting()}, ${name}` : `Doses for ${name}`}
        intro={<>{fmtDate(day, { weekday: 'long', day: 'numeric', month: 'long' })}{counts.total > 0 && <> &nbsp;|&nbsp; <span className="num">{counts.taken} of {counts.total}</span> doses taken</>}</>}
        actions={isElder ? (canSpeak && slots.length > 0 && <Button variant="secondary" icon={<Volume2 aria-hidden="true" />} onClick={readAloud}>Read my day aloud</Button>) : (
          <div className="field" style={{ minWidth: '11rem' }}>
            <label htmlFor="dose-day" className="sr-only">Show doses for date</label>
            <input id="dose-day" type="date" className="input" value={day} max={overview.local_date} onChange={e => setDate(e.target.value)} />
          </div>
        )}
      />

      {isElder && next && (
        <section className="next-up" aria-labelledby="next-heading">
          <h2 id="next-heading">Next</h2>
          <p className="when">{fmtTime(next.local_time)}</p>
          <p className="what">{nextGroup.map(d => `${d.medication_name} ${d.strength}`.trim()).join(', ')}</p>
        </section>
      )}

      <div className={isElder ? 'stack-lg' : 'grid-dash'}>
        <section aria-labelledby="schedule-heading" className="stack">
          <h2 id="schedule-heading" className={isElder ? 'sr-only' : ''}>Schedule</h2>
          {!can('view_medications') ? (
            <Alert tone="info">You don't have permission to see medicines for {name}.</Alert>
          ) : dosesQ.isLoading ? <Skeleton lines={5} /> : dosesQ.error ? <ErrorState error={dosesQ.error} retry={() => dosesQ.refetch()} /> : slots.length === 0 ? (
            <div className="panel"><Empty title="No doses scheduled for this day"
              action={can('manage_medications') && <Link className="btn btn-primary" to={`/p/${pid}/medications/new`}>Add a medicine</Link>}>
              {can('manage_medications') ? 'Add a medicine with its times, and its doses will appear here.' : 'Scheduled doses will appear here.'}
            </Empty></div>
          ) : (
            <ol className="day" aria-label="Doses by time">
              {slots.map(([time, group]) => {
                const views = group.map(d => doseView(d.status, d.scheduled_at, now))
                const state = views.includes('overdue') || views.includes('unconfirmed') ? 'overdue' : views.includes('due') ? 'due'
                  : views.every(v => v === 'taken') ? 'taken' : views.includes('missed') ? 'missed' : views.every(v => v === 'skipped') ? 'skipped' : 'upcoming'
                return (
                  <li key={time} className="slot" data-state={state}>
                    <div className="slot-time">{fmtTime(time).replace(/\s?[AP]M$/i, '')}<small>{/PM/i.test(fmtTime(time)) ? 'pm' : /AM/i.test(fmtTime(time)) ? 'am' : ''}</small></div>
                    <div className="slot-node" aria-hidden="true" />
                    <div className="slot-body">
                      {group.map((d, i) => (
                        <DoseCard key={d.id} dose={d} view={views[i]} isElder={isElder} canConfirm={can('confirm_doses') && (views[i] !== 'upcoming' || new Date(d.scheduled_at).getTime() - now <= 3 * 3600_000)}
                          onSkip={setSkipping} act={act} busyId={busyId} />
                      ))}
                    </div>
                  </li>
                )
              })}
            </ol>
          )}
        </section>

        <aside className="stack" aria-label="Today's other information">
          {appt && (
            <section className="panel" aria-labelledby="appt-heading">
              <div className="panel-head"><h2 id="appt-heading">Next appointment</h2><CalendarDays aria-hidden="true" style={{ color: 'var(--muted)' }} /></div>
              <div className="panel-body stack" style={{ gap: 4 }}>
                <p style={{ fontSize: 'var(--fs-lg)', fontWeight: 700 }}>{fmtDate(appt.local_date, { weekday: 'long', day: 'numeric', month: 'long' })}, {fmtTime(appt.local_time)}</p>
                <p>{appt.doctor_name}{appt.specialty && ` (${appt.specialty})`}</p>
                {appt.location && <p className="muted">{appt.location}</p>}
                <Link to={`/p/${pid}/appointments`} className="small" style={{ marginTop: 8 }}>All appointments</Link>
              </div>
            </section>
          )}
          {overview.unread_notifications > 0 && (
            <Alert tone="info" title={`${overview.unread_notifications} unread notification${overview.unread_notifications > 1 ? 's' : ''}`}>
              <Link to="/notifications">Read notifications</Link>
            </Alert>
          )}
          {(overview.low_stock?.length ?? 0) > 0 && (
            <Alert tone="warn" title="Running low (estimate)">
              {overview.low_stock!.map(m => <p key={m.id}><Link to={`/p/${pid}/medications/${m.id}`}>{m.name}</Link>: about {Math.floor(m.days_remaining)} days left</p>)}
            </Alert>
          )}
          <section className="panel" aria-labelledby="sos-heading">
            <div className="panel-head"><h2 id="sos-heading">If you need help</h2></div>
            <div className="panel-body stack">
              <p className="small muted">In an emergency, call your local emergency number. ElderCare does not contact emergency services.</p>
              <Link className="btn btn-danger" to={`/p/${pid}/emergency`}>Emergency help</Link>
              {overview.emergency_contacts.length === 0 ? (
                <p className="small">No emergency contacts yet. {can('edit_profile') && <Link to={`/p/${pid}/health`}>Add one</Link>}</p>
              ) : overview.emergency_contacts.slice(0, 3).map(c => (
                <a key={c.phone + c.name} href={`tel:${c.phone.replace(/[^\d+]/g, '')}`} className="btn btn-secondary btn-block" style={{ justifyContent: 'space-between' }}>
                  <span>{c.name}{c.relationship_label && <span className="muted"> ({c.relationship_label})</span>}</span>
                  <span className="row" style={{ gap: 6 }}><Phone aria-hidden="true" /> Call</span>
                </a>
              ))}
            </div>
          </section>
        </aside>
      </div>

      <Modal open={!!skipping} onClose={() => { setSkipping(null); setReason('') }} title={`Skip ${skipping?.medication_name ?? ''}?`}>
        <form className="form-grid" onSubmit={e => {
          e.preventDefault()
          if (skipping) actions.mutate({ dose: skipping, action: 'skip', body: { reason } }, { onSettled: () => { setSkipping(null); setReason('') } })
        }}>
          <p>This records that the dose was deliberately not taken. It does not change the prescription.</p>
          <TextArea label="Reason (optional)" rows={3} value={reason} onChange={e => setReason(e.target.value)} hint="For example: felt unwell, will ask the doctor." />
          <div className="form-actions">
            <Button variant="secondary" onClick={() => { setSkipping(null); setReason('') }}>Cancel</Button>
            <Button type="submit" loading={actions.isPending}>Record as skipped</Button>
          </div>
        </form>
      </Modal>
    </div>
  )
}
