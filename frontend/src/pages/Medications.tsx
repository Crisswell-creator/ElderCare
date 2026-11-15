import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pause, Pencil, Play, Plus, Trash2, X } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, p, type InventoryEvent, type Medication } from '../api'
import { usePatient } from '../hooks'
import { Alert, Badge, Button, ConfirmDialog, Empty, ErrorState, Modal, PageHead, SelectField, Skeleton, TextArea, TextField } from '../ui'
import { errorText, fmtDate, fmtDateTime, fmtQty, fmtTime, useForm, useToast } from '../lib'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function scheduleText(m: Medication) {
  if (m.schedule_type === 'as_needed') return 'As needed'
  return m.times.map(t => `${fmtTime(t.local_time)}${t.days.length < 7 ? ` (${t.days.map(d => DAYS[d]).join(', ')})` : ''}`).join(', ')
}

function StatusBadge({ m }: { m: Medication }) {
  if (m.status === 'paused') return <Badge tone="warn">Paused</Badge>
  if (m.status === 'discontinued') return <Badge tone="neutral">Stopped</Badge>
  return <Badge tone="ok">Active</Badge>
}

function StockText({ m }: { m: Medication }) {
  if (m.quantity_on_hand === null) return <span className="muted">Not tracked</span>
  return (
    <span>
      <span className="num">{fmtQty(m.quantity_on_hand)}</span> {m.dose_unit}{m.quantity_on_hand === 1 ? '' : 's'}
      {m.days_remaining !== null && <span className="muted"> (about {Math.floor(m.days_remaining)} days)</span>}
      {m.low_stock && <> <Badge tone="warn">Refill soon</Badge></>}
    </span>
  )
}

export function MedicationsPage() {
  const { pid, can, isElder } = usePatient()
  const [showStopped, setShowStopped] = useState(false)
  const q = useQuery({ queryKey: ['medications', pid, showStopped], queryFn: () => api.get<Medication[]>(p(pid, `/medications?include_inactive=${showStopped}`)) })
  return (
    <div className="page stack-lg">
      <PageHead title={isElder ? 'My medicines' : 'Medicines'}
        intro="Doses and instructions are shown exactly as recorded. ElderCare never changes a prescription."
        actions={can('manage_medications') && <Link className="btn btn-primary" to={`/p/${pid}/medications/new`}><Plus aria-hidden="true" />Add medicine</Link>} />
      {q.isLoading ? <Skeleton lines={6} /> : q.error ? <ErrorState error={q.error} retry={() => q.refetch()} /> : (
        <div className="panel">
          {q.data!.length === 0 ? (
            <Empty title="No medicines yet" action={can('manage_medications') && <Link className="btn btn-primary" to={`/p/${pid}/medications/new`}>Add the first medicine</Link>}>
              Add each medicine with its dose and times. Reminders start from the next scheduled time.
            </Empty>
          ) : (
            <ul className="list">
              {q.data!.map(m => (
                <li key={m.id} className="spread" style={{ alignItems: 'flex-start' }}>
                  <div className="stack" style={{ gap: 4, minWidth: 0 }}>
                    <h2><Link to={`/p/${pid}/medications/${m.id}`}>{m.name}</Link> <span className="muted" style={{ fontWeight: 600 }}>{m.strength}</span></h2>
                    <p>{fmtQty(m.dose_amount)} {m.dose_unit} &nbsp;|&nbsp; <span className="num">{scheduleText(m)}</span></p>
                    {m.instructions && <p className="muted small">{m.instructions}</p>}
                  </div>
                  <div className="stack" style={{ gap: 6, justifyItems: 'end', textAlign: 'right' }}>
                    <StatusBadge m={m} />
                    <span className="small"><StockText m={m} /></span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div><Button variant="quiet" onClick={() => setShowStopped(s => !s)}>{showStopped ? 'Hide stopped medicines' : 'Show stopped medicines'}</Button></div>
    </div>
  )
}

const KIND_LABEL: Record<string, string> = { initial: 'Starting count', refill: 'Refill', correction: 'Count corrected', dose_taken: 'Dose taken', dose_reverted: 'Dose record undone' }

export function MedicationDetailPage() {
  const { mid } = useParams()
  const { pid, can } = usePatient()
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const q = useQuery({ queryKey: ['medication', pid, mid], queryFn: () => api.get<{ medication: Medication; inventory: InventoryEvent[] }>(p(pid, `/medications/${mid}`)) })
  const [stock, setStock] = useState<'refill' | 'correction' | null>(null)
  const [statusTo, setStatusTo] = useState<'paused' | 'discontinued' | null>(null)
  const [removing, setRemoving] = useState(false)
  const stockForm = useForm({ quantity: '', note: '' })
  const [reason, setReason] = useState('')
  const refresh = () => { qc.invalidateQueries({ queryKey: ['medication', pid, mid] }); qc.invalidateQueries({ queryKey: ['medications', pid] }); qc.invalidateQueries({ queryKey: ['overview', pid] }) }
  const setStatus = useMutation({
    mutationFn: (status: string) => api.post<Medication>(p(pid, `/medications/${mid}/status`), { status, reason }),
    onSuccess: m => { toast(`${m.name} is now ${m.status === 'active' ? 'active' : m.status === 'paused' ? 'paused' : 'stopped'}.`); setStatusTo(null); setReason(''); refresh() },
    onError: e => toast(errorText(e), 'error'),
  })
  const remove = useMutation({
    mutationFn: () => api.del(p(pid, `/medications/${mid}`)),
    onSuccess: () => { toast('Medicine removed. Its history is kept.'); refresh(); navigate(`/p/${pid}/medications`) },
    onError: e => toast(errorText(e), 'error'),
  })
  if (q.isLoading) return <div className="page"><Skeleton lines={8} /></div>
  if (q.error || !q.data) return <div className="page"><ErrorState error={q.error} /></div>
  const m = q.data.medication
  const canStock = can('confirm_doses') || can('manage_medications')
  return (
    <div className="page stack-lg">
      <PageHead title={`${m.name} ${m.strength}`.trim()} crumbs={[{ to: `/p/${pid}/medications`, label: 'Medicines' }]}
        actions={can('manage_medications') && !m.archived && (
          <>
            <Link className="btn btn-secondary" to={`/p/${pid}/medications/${m.id}/edit`}><Pencil aria-hidden="true" />Edit</Link>
            {m.status === 'active'
              ? <Button variant="secondary" icon={<Pause aria-hidden="true" />} onClick={() => setStatusTo('paused')}>Pause</Button>
              : <Button variant="secondary" icon={<Play aria-hidden="true" />} loading={setStatus.isPending} onClick={() => setStatus.mutate('active')}>Resume</Button>}
          </>
        )} />
      {m.status !== 'active' && <Alert tone="warn" title={m.status === 'paused' ? 'Paused' : 'Stopped'}>{m.status_reason || 'No reason recorded.'} No reminders are sent while it is not active.</Alert>}
      <div className="grid-dash">
        <section className="panel panel-pad" aria-labelledby="details-h">
          <h2 id="details-h" style={{ marginBottom: 16 }}>Details as recorded</h2>
          <dl className="kv">
            <dt>Dose</dt><dd>{fmtQty(m.dose_amount)} {m.dose_unit} ({m.form})</dd>
            <dt>When</dt><dd className="num">{scheduleText(m)}</dd>
            <dt>Instructions</dt><dd>{m.instructions || <span className="muted">None recorded</span>}</dd>
            <dt>Prescribed by</dt><dd>{m.prescriber || <span className="muted">Not recorded</span>}</dd>
            <dt>Started</dt><dd>{fmtDate(m.start_date, { day: 'numeric', month: 'long', year: 'numeric' })}{m.end_date && <>, ends {fmtDate(m.end_date, { day: 'numeric', month: 'long', year: 'numeric' })}</>}</dd>
            <dt>Status</dt><dd><StatusBadge m={m} /></dd>
          </dl>
        </section>
        <section className="panel panel-pad stack" aria-labelledby="stock-h">
          <h2 id="stock-h">Stock</h2>
          <p style={{ fontSize: 'var(--fs-lg)' }}><StockText m={m} /></p>
          {m.estimated_run_out && <p className="muted small">Estimated to run out around {fmtDate(m.estimated_run_out, { day: 'numeric', month: 'long' })}. This estimate assumes doses are taken as scheduled.</p>}
          {canStock && !m.archived && (
            <div className="row">
              <Button icon={<Plus aria-hidden="true" />} onClick={() => setStock('refill')}>Record refill</Button>
              {can('manage_medications') && <Button variant="secondary" onClick={() => setStock('correction')}>Correct count</Button>}
            </div>
          )}
        </section>
      </div>
      <section className="panel" aria-labelledby="ledger-h">
        <div className="panel-head"><h2 id="ledger-h">Stock history</h2></div>
        {q.data.inventory.length === 0 ? <Empty title="No stock recorded">Record a refill to start tracking how much is left.</Empty> : (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th scope="col">When</th><th scope="col">Change</th><th scope="col">Count after</th><th scope="col">By</th><th scope="col" className="hide-mobile">Note</th></tr></thead>
              <tbody>
                {q.data.inventory.map(e => (
                  <tr key={e.id}>
                    <td>{fmtDateTime(e.created_at)}</td>
                    <td>{KIND_LABEL[e.kind] ?? e.kind} <span className="num muted">({e.quantity_delta > 0 ? '+' : ''}{fmtQty(e.quantity_delta)})</span></td>
                    <td className="num">{fmtQty(e.quantity_after)}</td>
                    <td>{e.actor_name ?? 'ElderCare'}</td>
                    <td className="hide-mobile muted">{e.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {can('manage_medications') && !m.archived && (
        <section className="panel panel-pad stack" aria-labelledby="stop-h">
          <h2 id="stop-h">Stop or remove</h2>
          <p className="muted">Only change this when the prescriber has said so. Stopping keeps the medicine on record; removing hides it while keeping its full history.</p>
          <div className="row">
            {m.status !== 'discontinued' && <Button variant="secondary" icon={<X aria-hidden="true" />} onClick={() => setStatusTo('discontinued')}>Mark as stopped</Button>}
            <Button variant="danger" icon={<Trash2 aria-hidden="true" />} onClick={() => setRemoving(true)}>Remove medicine</Button>
          </div>
        </section>
      )}

      <Modal open={!!stock} onClose={() => setStock(null)} title={stock === 'refill' ? 'Record a refill' : 'Correct the count'}>
        <form className="form-grid" noValidate onSubmit={(e: FormEvent) => {
          e.preventDefault()
          stockForm.submit(async () => {
            await api.post(p(pid, `/medications/${mid}/inventory`), { kind: stock, quantity: Number(stockForm.values.quantity), note: stockForm.values.note })
            toast(stock === 'refill' ? 'Refill recorded.' : 'Count corrected.'); setStock(null); stockForm.setValues({ quantity: '', note: '' }); refresh()
          })
        }}>
          {stockForm.formError && <Alert tone="danger">{stockForm.formError}</Alert>}
          <TextField label={stock === 'refill' ? `How many ${m.dose_unit}s were added?` : `How many ${m.dose_unit}s are there now?`} type="number" inputMode="decimal" min={0} step="any" required {...stockForm.bind('quantity')} />
          <TextField label="Note (optional)" placeholder={stock === 'refill' ? 'For example, collected from pharmacy' : 'For example, counted the pack'} {...stockForm.bind('note')} />
          <div className="form-actions"><Button variant="secondary" onClick={() => setStock(null)}>Cancel</Button><Button type="submit" loading={stockForm.busy}>{stock === 'refill' ? 'Record refill' : 'Save count'}</Button></div>
        </form>
      </Modal>
      <Modal open={!!statusTo} onClose={() => setStatusTo(null)} title={statusTo === 'paused' ? `Pause ${m.name}?` : `Mark ${m.name} as stopped?`}>
        <form className="form-grid" onSubmit={e => { e.preventDefault(); if (statusTo) setStatus.mutate(statusTo) }}>
          <p>Future doses will be cancelled and no reminders sent. {statusTo === 'paused' ? 'You can resume it later.' : 'The record and history are kept.'}</p>
          <TextArea label="Reason" rows={2} hint="For example: advised by Dr Okafor on 10 March." value={reason} onChange={e => setReason(e.target.value)} />
          <div className="form-actions"><Button variant="secondary" onClick={() => setStatusTo(null)}>Cancel</Button><Button type="submit" loading={setStatus.isPending}>{statusTo === 'paused' ? 'Pause medicine' : 'Mark as stopped'}</Button></div>
        </form>
      </Modal>
      <ConfirmDialog open={removing} onClose={() => setRemoving(false)} danger busy={remove.isPending} title={`Remove ${m.name}?`}
        confirmLabel="Remove medicine" onConfirm={() => remove.mutate()}
        body={<p>It will disappear from the medicine list and no more doses will be scheduled. Past doses, stock history and the activity record are kept.</p>} />
    </div>
  )
}

interface TimeRow { local_time: string; days: number[] }

export function MedicationFormPage() {
  const { mid } = useParams()
  const { pid } = usePatient()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const editing = !!mid
  const existing = useQuery({ queryKey: ['medication', pid, mid], queryFn: () => api.get<{ medication: Medication }>(p(pid, `/medications/${mid}`)), enabled: editing })
  if (editing && existing.isLoading) return <div className="page"><Skeleton lines={8} /></div>
  const m = existing.data?.medication
  return <MedicationForm key={m?.id ?? 'new'} pid={pid} med={m} onDone={async id => {
    await qc.invalidateQueries({ queryKey: ['medications', pid] })
    await qc.invalidateQueries({ queryKey: ['medication', pid] })
    await qc.invalidateQueries({ queryKey: ['doses', pid] })
    await qc.invalidateQueries({ queryKey: ['overview', pid] })
    navigate(`/p/${pid}/medications/${id}`)
  }} />
}

function MedicationForm({ pid, med, onDone }: { pid: number; med?: Medication; onDone: (id: number) => void }) {
  const toast = useToast()
  const [today] = useState(() => new Date().toISOString().slice(0, 10))
  const f = useForm({
    name: med?.name ?? '', strength: med?.strength ?? '', form: med?.form ?? 'tablet',
    dose_amount: med ? String(med.dose_amount) : '1', dose_unit: med?.dose_unit ?? 'tablet',
    instructions: med?.instructions ?? '', schedule_type: med?.schedule_type ?? 'scheduled',
    start_date: med?.start_date ?? today, end_date: med?.end_date ?? '', prescriber: med?.prescriber ?? '',
    refill_threshold_days: String(med?.refill_threshold_days ?? 7), initial_quantity: '',
  })
  const [times, setTimes] = useState<TimeRow[]>(med?.times.length ? med.times : [{ local_time: '08:00', days: [0, 1, 2, 3, 4, 5, 6] }])
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    f.submit(async () => {
      const v = f.values
      const body = {
        ...v, dose_amount: Number(v.dose_amount), refill_threshold_days: Number(v.refill_threshold_days),
        end_date: v.end_date || null, times: v.schedule_type === 'scheduled' ? times : [],
        ...(med ? {} : { initial_quantity: v.initial_quantity === '' ? null : Number(v.initial_quantity) }),
      }
      if (med) delete (body as Record<string, unknown>).initial_quantity
      const res = med ? await api.put<Medication>(p(pid, `/medications/${med.id}`), body) : await api.post<Medication>(p(pid, '/medications'), body)
      toast(med ? 'Changes saved. Future doses follow the new schedule.' : `${res.name} added.`)
      onDone(res.id)
    })
  }
  const setTime = (i: number, patch: Partial<TimeRow>) => setTimes(ts => ts.map((t, j) => (j === i ? { ...t, ...patch } : t)))
  const toggleDay = (i: number, d: number) => setTime(i, { days: times[i].days.includes(d) ? times[i].days.filter(x => x !== d) : [...times[i].days, d].sort() })
  return (
    <div className="page" style={{ maxWidth: '50rem' }}>
      <PageHead title={med ? `Edit ${med.name}` : 'Add a medicine'} crumbs={[{ to: `/p/${pid}/medications`, label: 'Medicines' }]}
        intro="Copy the details from the prescription label. ElderCare records them; it doesn't check or change them." />
      <form className="stack-lg" onSubmit={onSubmit} noValidate>
        {f.formError && <Alert tone="danger">{f.formError}</Alert>}
        <section className="panel panel-pad form-grid" aria-labelledby="what-h">
          <h2 id="what-h">The medicine</h2>
          <div className="form-grid two">
            <TextField label="Name" required placeholder="For example, Metformin" {...f.bind('name')} />
            <TextField label="Strength" placeholder="For example, 500 mg" {...f.bind('strength')} />
            <SelectField label="Form" {...f.bind('form')}>
              {['tablet', 'capsule', 'liquid', 'injection', 'inhaler', 'drops', 'patch', 'cream', 'other'].map(x => <option key={x} value={x}>{x[0].toUpperCase() + x.slice(1)}</option>)}
            </SelectField>
            <TextField label="Prescribed by" {...f.bind('prescriber')} />
          </div>
          <div className="form-grid two">
            <TextField label="Amount per dose" type="number" inputMode="decimal" min={0} step="any" required {...f.bind('dose_amount')} />
            <TextField label="Unit" placeholder="tablet, ml, puff" required {...f.bind('dose_unit')} />
          </div>
          <TextArea label="Instructions" rows={2} placeholder="For example, take with food" hint="Shown with every reminder exactly as written." {...f.bind('instructions')} />
        </section>

        <section className="panel panel-pad form-grid" aria-labelledby="when-h">
          <h2 id="when-h">When it's taken</h2>
          <fieldset>
            <legend className="sr-only">Schedule type</legend>
            <div className="chips">
              <label className="chip"><input type="radio" name="schedule_type" checked={f.values.schedule_type === 'scheduled'} onChange={() => f.set('schedule_type', 'scheduled')} /><span>At set times</span></label>
              <label className="chip"><input type="radio" name="schedule_type" checked={f.values.schedule_type === 'as_needed'} onChange={() => f.set('schedule_type', 'as_needed')} /><span>Only when needed</span></label>
            </div>
          </fieldset>
          {f.values.schedule_type === 'scheduled' && (
            <div className="stack">
              {times.map((t, i) => (
                <fieldset key={i} className="panel" style={{ padding: 'var(--s4)', background: 'var(--surface-sunk)' }}>
                  <legend className="sr-only">Dose time {i + 1}</legend>
                  <div className="spread" style={{ alignItems: 'flex-end' }}>
                    <div style={{ maxWidth: '12rem' }}><TextField label={`Time ${times.length > 1 ? i + 1 : ''}`.trim()} type="time" required value={t.local_time} onChange={e => setTime(i, { local_time: e.target.value })} /></div>
                    {times.length > 1 && <Button variant="quiet" icon={<X aria-hidden="true" />} onClick={() => setTimes(ts => ts.filter((_, j) => j !== i))}>Remove time</Button>}
                  </div>
                  <div className="chips" style={{ marginTop: 12 }} role="group" aria-label={`Days for time ${i + 1}`}>
                    {DAYS.map((d, di) => (
                      <label key={d} className="chip"><input type="checkbox" checked={t.days.includes(di)} onChange={() => toggleDay(i, di)} /><span>{d}</span></label>
                    ))}
                  </div>
                </fieldset>
              ))}
              {times.length < 8 && <div><Button variant="secondary" icon={<Plus aria-hidden="true" />} onClick={() => setTimes(ts => [...ts, { local_time: '20:00', days: [0, 1, 2, 3, 4, 5, 6] }])}>Add another time</Button></div>}
              {f.errors.times && <p className="error" role="alert">{f.errors.times}</p>}
            </div>
          )}
          <div className="form-grid two">
            <TextField label="Start date" type="date" required {...f.bind('start_date')} />
            <TextField label="End date (optional)" type="date" hint="Leave empty for ongoing medicines." {...f.bind('end_date')} />
          </div>
        </section>

        <section className="panel panel-pad form-grid" aria-labelledby="stock-form-h">
          <h2 id="stock-form-h">Stock</h2>
          <div className="form-grid two">
            {!med && <TextField label={`How many ${f.values.dose_unit || 'unit'}s are there now? (optional)`} type="number" inputMode="decimal" min={0} step="any" hint="Leave empty to skip stock tracking." {...f.bind('initial_quantity')} />}
            <TextField label="Warn when this many days are left" type="number" min={0} max={90} {...f.bind('refill_threshold_days')} />
          </div>
        </section>
        <div className="form-actions">
          <Link className="btn btn-secondary" to={med ? `/p/${pid}/medications/${med.id}` : `/p/${pid}/medications`}>Cancel</Link>
          <Button type="submit" loading={f.busy}>{med ? 'Save changes' : 'Add medicine'}</Button>
        </div>
      </form>
    </div>
  )
}
