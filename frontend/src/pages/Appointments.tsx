import { useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarPlus, ChevronLeft, ChevronRight, Download, MapPin, Plus, Trash2 } from 'lucide-react'
import { api, p, type Appointment, type Question } from '../api'
import { usePatient } from '../session'
import {
  Alert, Badge, Button, Checkbox, ConfirmDialog, Empty, ErrorState, Modal, PageHead, Skeleton,
  TextArea, TextField, errorText, fmtDate, fmtTime, useForm, useNow, useToast,
} from '../ui'

const REMINDERS: [number, string][] = [[10080, '1 week before'], [2880, '2 days before'], [1440, '1 day before'], [240, '4 hours before'], [120, '2 hours before'], [60, '1 hour before']]

function MonthCalendar({ appts, month, setMonth, onPick, now }: { appts: Appointment[]; month: Date; setMonth: (d: Date) => void; onPick: (iso: string) => void; now: number }) {
  const first = new Date(month.getFullYear(), month.getMonth(), 1)
  const offset = (first.getDay() + 6) % 7
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  const byDay = new Map<string, Appointment[]>()
  for (const a of appts) byDay.set(a.local_date, [...(byDay.get(a.local_date) ?? []), a])
  const cells: (number | null)[] = [...Array(offset).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)]
  while (cells.length % 7) cells.push(null)
  const iso = (d: number) => `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
  const todayIso = new Date(now).toISOString().slice(0, 10)
  const label = month.toLocaleDateString([], { month: 'long', year: 'numeric' })
  return (
    <section className="panel" aria-labelledby="cal-h">
      <div className="panel-head">
        <h2 id="cal-h">{label}</h2>
        <div className="row" style={{ gap: 4 }}>
          <button type="button" className="icon-btn" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft aria-hidden="true" /></button>
          <button type="button" className="icon-btn" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight aria-hidden="true" /></button>
        </div>
      </div>
      <table className="cal" style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
        <caption className="sr-only">Appointments in {label}</caption>
        <thead><tr>{['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => <th key={i} scope="col" className="muted small" style={{ padding: 6, fontWeight: 600 }}><abbr title={['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'][i]} style={{ textDecoration: 'none' }}>{d}</abbr></th>)}</tr></thead>
        <tbody>
          {Array.from({ length: cells.length / 7 }, (_, w) => (
            <tr key={w}>
              {cells.slice(w * 7, w * 7 + 7).map((d, i) => {
                if (!d) return <td key={i} />
                const list = byDay.get(iso(d)) ?? []
                const isToday = iso(d) === todayIso
                return (
                  <td key={i} style={{ padding: 2, textAlign: 'center' }}>
                    {list.length ? (
                      <button type="button" onClick={() => onPick(iso(d))} className="btn btn-primary" style={{ minHeight: 40, width: '100%', padding: 0 }}
                        aria-label={`${fmtDate(iso(d), { weekday: 'long', day: 'numeric', month: 'long' })}: ${list.map(a => `${fmtTime(a.local_time)} ${a.doctor_name}`).join(', ')}`}>
                        {d}
                      </button>
                    ) : (
                      <span className="num" style={{ display: 'grid', placeItems: 'center', minHeight: 40, borderRadius: 6, fontWeight: isToday ? 700 : 400, outline: isToday ? '2px solid var(--teal-700)' : undefined, outlineOffset: -2 }}>
                        {d}{isToday && <span className="sr-only"> (today)</span>}
                      </span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

export function AppointmentsPage() {
  const { pid, can } = usePatient()
  const qc = useQueryClient()
  const toast = useToast()
  const [scope, setScope] = useState<'upcoming' | 'past'>('upcoming')
  const [editing, setEditing] = useState<Appointment | 'new' | null>(null)
  const [cancelling, setCancelling] = useState<Appointment | null>(null)
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1))
  const [highlight, setHighlight] = useState('')
  const now = useNow(60_000)
  const list = useQuery({ queryKey: ['appointments', pid, scope], queryFn: () => api.get<Appointment[]>(p(pid, `/appointments?scope=${scope}`)) })
  const all = useQuery({ queryKey: ['appointments', pid, 'all'], queryFn: () => api.get<Appointment[]>(p(pid, '/appointments?scope=all')) })
  const refresh = () => { qc.invalidateQueries({ queryKey: ['appointments', pid] }); qc.invalidateQueries({ queryKey: ['overview', pid] }) }
  const complete = useMutation({ mutationFn: (a: Appointment) => api.post(p(pid, `/appointments/${a.id}/complete`)), onSuccess: () => { toast('Marked as attended.'); refresh() }, onError: e => toast(errorText(e), 'error') })
  const cancel = useMutation({ mutationFn: (a: Appointment) => api.post(p(pid, `/appointments/${a.id}/cancel`), {}), onSuccess: () => { toast('Appointment cancelled.'); setCancelling(null); refresh() }, onError: e => toast(errorText(e), 'error') })
  const scheduled = useMemo(() => (all.data ?? []).filter(a => a.status === 'scheduled'), [all.data])

  return (
    <div className="page stack-lg">
      <PageHead title="Appointments" intro="Doctor visits, with reminders for everyone who follows them."
        actions={can('manage_appointments') && <Button icon={<Plus aria-hidden="true" />} onClick={() => setEditing('new')}>Add appointment</Button>} />
      <div className="grid-dash">
        <section className="stack" aria-labelledby="list-h">
          <div className="spread">
            <h2 id="list-h" className="sr-only">Appointment list</h2>
            <div className="chips" role="tablist" aria-label="Which appointments">
              {(['upcoming', 'past'] as const).map(s => (
                <button key={s} type="button" role="tab" aria-selected={scope === s} className={`btn ${scope === s ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setScope(s)}>
                  {s === 'upcoming' ? 'Upcoming' : 'Past and cancelled'}
                </button>
              ))}
            </div>
          </div>
          {list.isLoading ? <Skeleton lines={5} /> : list.error ? <ErrorState error={list.error} /> : !list.data!.length ? (
            <div className="panel"><Empty title={scope === 'upcoming' ? 'No upcoming appointments' : 'Nothing here yet'}
              action={scope === 'upcoming' && can('manage_appointments') && <Button onClick={() => setEditing('new')}>Add appointment</Button>} /></div>
          ) : (
            <div className="panel">
              <ul className="list">
                {list.data!.map(a => (
                  <li key={a.id} id={`appt-${a.id}`} style={highlight === a.local_date ? { background: 'var(--teal-50)' } : undefined}>
                    <div className="spread" style={{ alignItems: 'flex-start' }}>
                      <div className="stack" style={{ gap: 4 }}>
                        <p style={{ fontSize: 'var(--fs-lg)', fontWeight: 700, color: 'var(--navy-800)' }}>
                          {fmtDate(a.local_date, { weekday: 'long', day: 'numeric', month: 'long' })}, <span className="num">{fmtTime(a.local_time)}</span>
                        </p>
                        <p>{a.doctor_name}{a.specialty && <span className="muted">, {a.specialty}</span>}</p>
                        {a.location && <p className="muted row" style={{ gap: 6 }}><MapPin size={16} aria-hidden="true" />{a.location}</p>}
                        {a.purpose && <p className="small">Purpose: {a.purpose}</p>}
                        {a.notes && <p className="small muted" style={{ whiteSpace: 'pre-line' }}>{a.notes}</p>}
                      </div>
                      {a.status !== 'scheduled' && <Badge tone={a.status === 'completed' ? 'ok' : 'neutral'}>{a.status === 'completed' ? 'Attended' : 'Cancelled'}</Badge>}
                    </div>
                    <div className="row" style={{ marginTop: 12 }}>
                      <a className="btn btn-quiet" href={p(pid, `/appointments/${a.id}/calendar.ics`)}><Download aria-hidden="true" />Add to calendar</a>
                      {can('manage_appointments') && a.status === 'scheduled' && (
                        <>
                          <Button variant="secondary" onClick={() => setEditing(a)}>Change</Button>
                          {new Date(a.starts_at).getTime() < now && <Button variant="secondary" loading={complete.isPending} onClick={() => complete.mutate(a)}>Mark attended</Button>}
                          <Button variant="danger" onClick={() => setCancelling(a)}>Cancel</Button>
                        </>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
        <div className="stack-lg">
          <MonthCalendar now={now} appts={scheduled} month={month} setMonth={setMonth} onPick={d => { setScope('upcoming'); setHighlight(d); setTimeout(() => document.querySelector(`[id^="appt-"]`)?.scrollIntoView({ block: 'nearest' }), 50) }} />
          <QuestionsPanel pid={pid} />
        </div>
      </div>
      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'Add appointment' : 'Change appointment'}>
        {editing && <AppointmentForm pid={pid} appt={editing === 'new' ? undefined : editing} onDone={() => { setEditing(null); refresh() }} />}
      </Modal>
      <ConfirmDialog open={!!cancelling} onClose={() => setCancelling(null)} danger busy={cancel.isPending} title="Cancel this appointment?"
        confirmLabel="Cancel appointment" onConfirm={() => cancelling && cancel.mutate(cancelling)}
        body={<p>{cancelling && `${cancelling.doctor_name} on ${fmtDate(cancelling.local_date, { weekday: 'long', day: 'numeric', month: 'long' })}.`} Reminders will stop. It stays in the past list.</p>} />
    </div>
  )
}

function AppointmentForm({ pid, appt, onDone }: { pid: number; appt?: Appointment; onDone: () => void }) {
  const toast = useToast()
  const f = useForm({
    doctor_name: appt?.doctor_name ?? '', specialty: appt?.specialty ?? '', date: appt?.local_date ?? '',
    time: appt?.local_time ?? '10:00', location: appt?.location ?? '', purpose: appt?.purpose ?? '', notes: appt?.notes ?? '',
  })
  const [offsets, setOffsets] = useState<number[]>(appt?.reminder_offsets ?? [1440, 120])
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    f.submit(async () => {
      const body = { ...f.values, reminder_offsets: offsets }
      if (appt) await api.put(p(pid, `/appointments/${appt.id}`), body)
      else await api.post(p(pid, '/appointments'), body)
      toast(appt ? 'Appointment updated.' : 'Appointment added.')
      onDone()
    })
  }
  return (
    <form className="form-grid" onSubmit={onSubmit} noValidate>
      {f.formError && <Alert tone="danger">{f.formError}</Alert>}
      <div className="form-grid two">
        <TextField label="Doctor or clinic" required {...f.bind('doctor_name')} />
        <TextField label="Specialty" placeholder="For example, cardiology" {...f.bind('specialty')} />
        <TextField label="Date" type="date" required {...f.bind('date')} />
        <TextField label="Time" type="time" required {...f.bind('time')} />
      </div>
      <TextField label="Location" {...f.bind('location')} />
      <TextField label="Purpose" placeholder="For example, blood pressure review" {...f.bind('purpose')} />
      <TextArea label="Notes" rows={2} {...f.bind('notes')} />
      <fieldset>
        <legend>Reminders</legend>
        <div className="form-grid two" style={{ gap: 0 }}>
          {REMINDERS.map(([v, label]) => (
            <Checkbox key={v} label={label} checked={offsets.includes(v)} onChange={() => setOffsets(o => (o.includes(v) ? o.filter(x => x !== v) : [...o, v]))} />
          ))}
        </div>
      </fieldset>
      <div className="form-actions"><Button type="submit" icon={<CalendarPlus aria-hidden="true" />} loading={f.busy}>{appt ? 'Save changes' : 'Add appointment'}</Button></div>
    </form>
  )
}

function QuestionsPanel({ pid }: { pid: number }) {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['questions', pid], queryFn: () => api.get<Question[]>(p(pid, '/questions')) })
  const [text, setText] = useState('')
  const refresh = () => qc.invalidateQueries({ queryKey: ['questions', pid] })
  const add = useMutation({ mutationFn: () => api.post(p(pid, '/questions'), { text }), onSuccess: () => { setText(''); refresh() }, onError: e => toast(errorText(e), 'error') })
  const toggle = useMutation({ mutationFn: (id: number) => api.post(p(pid, `/questions/${id}/resolve`)), onSuccess: refresh })
  const remove = useMutation({ mutationFn: (id: number) => api.del(p(pid, `/questions/${id}`)), onSuccess: refresh })
  return (
    <section className="panel" aria-labelledby="q-h">
      <div className="panel-head"><h2 id="q-h">Questions for the doctor</h2></div>
      <div className="panel-body stack">
        <p className="muted small">They appear on the printable visit summary until ticked off.</p>
        <form className="row" style={{ alignItems: 'flex-end', flexWrap: 'nowrap' }} onSubmit={e => { e.preventDefault(); if (text.trim()) add.mutate() }}>
          <div style={{ flex: 1 }}><TextField label="New question" value={text} onChange={e => setText(e.target.value)} maxLength={500} /></div>
          <Button type="submit" variant="secondary" loading={add.isPending}>Add</Button>
        </form>
        {q.data?.length === 0 && <p className="muted small">No questions yet.</p>}
        <ul className="list" style={{ margin: '0 calc(-1 * var(--s5))' }}>
          {q.data?.map(item => (
            <li key={item.id} className="spread" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
              <label className="check" style={{ flex: 1, padding: 0 }}>
                <input type="checkbox" checked={item.resolved} disabled={!item.is_mine && toggle.isPending} onChange={() => toggle.mutate(item.id)} />
                <span><span style={{ textDecoration: item.resolved ? 'line-through' : undefined }}>{item.text}</span>
                  <span className="muted small" style={{ display: 'block' }}>{item.author_name}</span></span>
              </label>
              {item.is_mine && <button type="button" className="icon-btn" aria-label={`Delete question: ${item.text}`} onClick={() => remove.mutate(item.id)}><Trash2 aria-hidden="true" /></button>}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
