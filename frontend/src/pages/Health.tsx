import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileUp, Pencil, Plus, Trash2 } from 'lucide-react'
import { api, p, type DocumentItem, type Profile } from '../api'
import { usePatient } from '../hooks'
import { Alert, Badge, Button, Checkbox, ConfirmDialog, Empty, ErrorState, Modal, PageHead, SelectField, Skeleton, TextArea, TextField } from '../ui'
import { errorText, fmtDate, useForm, useToast } from '../lib'

type Kind = 'allergies' | 'history' | 'contacts' | 'doctors'
interface FieldDef { key: string; label: string; type?: 'text' | 'date' | 'tel' | 'select' | 'textarea' | 'check'; options?: [string, string][]; required?: boolean; hint?: string }

const DEFS: Record<Kind, { title: string; noun: string; fields: FieldDef[] }> = {
  allergies: { title: 'Allergies', noun: 'allergy', fields: [
    { key: 'substance', label: 'Allergic to', required: true },
    { key: 'reaction', label: 'Reaction' },
    { key: 'severity', label: 'Severity', type: 'select', options: [['unknown', 'Not known'], ['mild', 'Mild'], ['moderate', 'Moderate'], ['severe', 'Severe']] },
  ] },
  history: { title: 'Medical history', noun: 'history entry', fields: [
    { key: 'title', label: 'Condition or event', required: true },
    { key: 'kind', label: 'Type', type: 'select', options: [['condition', 'Condition'], ['procedure', 'Operation or procedure'], ['hospitalization', 'Hospital stay'], ['immunization', 'Vaccination'], ['other', 'Other']] },
    { key: 'status', label: 'Status', type: 'select', options: [['active', 'Current'], ['managed', 'Managed'], ['resolved', 'Resolved'], ['historical', 'In the past']] },
    { key: 'occurred_on', label: 'Date (if known)', type: 'date' },
    { key: 'notes', label: 'Notes', type: 'textarea' },
  ] },
  contacts: { title: 'Emergency contacts', noun: 'emergency contact', fields: [
    { key: 'name', label: 'Name', required: true },
    { key: 'relationship_label', label: 'Relationship' },
    { key: 'phone', label: 'Phone', type: 'tel', required: true },
    { key: 'email', label: 'Email (optional)' },
    { key: 'priority', label: 'Call order', type: 'select', options: [['1', '1st'], ['2', '2nd'], ['3', '3rd'], ['4', '4th'], ['5', '5th']] },
  ] },
  doctors: { title: 'Doctors', noun: 'doctor', fields: [
    { key: 'name', label: 'Name', required: true },
    { key: 'specialty', label: 'Specialty' },
    { key: 'clinic', label: 'Practice or clinic' },
    { key: 'phone', label: 'Phone', type: 'tel' },
    { key: 'is_primary', label: 'Main doctor', type: 'check' },
  ] },
}

function RecordForm({ pid, kind, item, onDone }: { pid: number; kind: Kind; item?: Record<string, unknown>; onDone: () => void }) {
  const def = DEFS[kind]
  const toast = useToast()
  const init: Record<string, unknown> = {}
  for (const fd of def.fields) init[fd.key] = item?.[fd.key] !== undefined ? (fd.key === 'priority' ? String(item[fd.key]) : item[fd.key]) : (fd.type === 'check' ? false : fd.options ? fd.options[0][0] : '')
  const f = useForm(init)
  return (
    <form className="form-grid" noValidate onSubmit={e => {
      e.preventDefault()
      f.submit(async () => {
        const body: Record<string, unknown> = { ...f.values, occurred_on: f.values.occurred_on || null }
        if (kind === 'contacts') body.priority = Number(f.values.priority)
        if (kind !== 'history') delete (body as Record<string, unknown>).occurred_on
        if (item) await api.put(p(pid, `/${kind}/${item.id}`), body)
        else await api.post(p(pid, `/${kind}`), body)
        toast(item ? 'Saved.' : `${def.noun[0].toUpperCase() + def.noun.slice(1)} added.`)
        onDone()
      })
    }}>
      {f.formError && <Alert tone="danger">{f.formError}</Alert>}
      {def.fields.map(fd => {
        const b = f.bind(fd.key)
        if (fd.type === 'select') return <SelectField key={fd.key} label={fd.label} {...b}>{fd.options!.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</SelectField>
        if (fd.type === 'textarea') return <TextArea key={fd.key} label={fd.label} rows={2} {...b} />
        if (fd.type === 'check') return <Checkbox key={fd.key} label={fd.label} checked={!!f.values[fd.key]} onChange={e => f.set(fd.key, e.target.checked)} />
        return <TextField key={fd.key} label={fd.label} type={fd.type ?? 'text'} required={fd.required} {...b} />
      })}
      <div className="form-actions"><Button type="submit" loading={f.busy}>{item ? 'Save' : 'Add'}</Button></div>
    </form>
  )
}

function RecordSection({ pid, kind, items, canEdit, render }: { pid: number; kind: Kind; items: Record<string, unknown>[]; canEdit: boolean; render: (i: Record<string, unknown>) => ReactNode }) {
  const def = DEFS[kind]
  const qc = useQueryClient()
  const toast = useToast()
  const [editing, setEditing] = useState<Record<string, unknown> | 'new' | null>(null)
  const [removing, setRemoving] = useState<Record<string, unknown> | null>(null)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['profile', pid] }); qc.invalidateQueries({ queryKey: ['overview', pid] }) }
  const remove = useMutation({ mutationFn: (id: unknown) => api.del(p(pid, `/${kind}/${id}`)), onSuccess: () => { toast('Removed.'); setRemoving(null); refresh() }, onError: e => toast(errorText(e), 'error') })
  const hid = `${kind}-h`
  return (
    <section className="panel" aria-labelledby={hid}>
      <div className="panel-head">
        <h2 id={hid}>{def.title}</h2>
        {canEdit && <Button variant="quiet" icon={<Plus aria-hidden="true" />} onClick={() => setEditing('new')}>Add<span className="sr-only"> {def.noun}</span></Button>}
      </div>
      {items.length === 0 ? <p className="panel-body muted">None recorded.</p> : (
        <ul className="list list-compact">
          {items.map(i => (
            <li key={String(i.id)} className="spread" style={{ flexWrap: 'nowrap', alignItems: 'flex-start' }}>
              <div style={{ minWidth: 0 }}>{render(i)}</div>
              {canEdit && (
                <div className="row" style={{ gap: 0, flexWrap: 'nowrap' }}>
                  <button type="button" className="icon-btn" aria-label={`Edit ${def.noun}`} onClick={() => setEditing(i)}><Pencil aria-hidden="true" /></button>
                  <button type="button" className="icon-btn" aria-label={`Remove ${def.noun}`} onClick={() => setRemoving(i)}><Trash2 aria-hidden="true" /></button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? `Add ${def.noun}` : `Edit ${def.noun}`}>
        {editing && <RecordForm pid={pid} kind={kind} item={editing === 'new' ? undefined : editing} onDone={() => { setEditing(null); refresh() }} />}
      </Modal>
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} danger busy={remove.isPending} title={`Remove this ${def.noun}?`}
        confirmLabel="Remove" onConfirm={() => removing && remove.mutate(removing.id)} body={<p>The change is recorded in the activity history.</p>} />
    </section>
  )
}

const age = (dob: string) => {
  const d = new Date(dob), n = new Date()
  return n.getFullYear() - d.getFullYear() - (n < new Date(n.getFullYear(), d.getMonth(), d.getDate()) ? 1 : 0)
}

export function HealthPage() {
  const { pid, can, isElder } = usePatient()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['profile', pid], queryFn: () => api.get<Profile>(p(pid)), enabled: can('view_profile') })
  const [editing, setEditing] = useState(false)
  const [rules, setRules] = useState(false)
  if (!can('view_profile')) return <div className="page"><Alert tone="info">You don't have permission to see the health profile.</Alert></div>
  if (q.isLoading) return <div className="page"><Skeleton lines={8} /></div>
  if (q.error || !q.data) return <div className="page"><ErrorState error={q.error} /></div>
  const { patient: pt } = q.data
  const canEdit = can('edit_profile')
  const asRecords = <T,>(x: T[]) => x as unknown as Record<string, unknown>[]
  return (
    <div className="page stack-lg">
      <PageHead title={isElder ? 'My health' : 'Health profile'} intro="Kept by the people you've allowed. Changes are recorded in the activity history."
        actions={canEdit && <Button variant="secondary" icon={<Pencil aria-hidden="true" />} onClick={() => setEditing(true)}>Edit details</Button>} />
      {pt.managed_by_representative && <Alert tone="info" title="Managed by a trusted representative">This profile was set up on the person's behalf. They can take it over by joining with an elder invitation code.</Alert>}
      <section className="panel panel-pad" aria-labelledby="about-h">
        <h2 id="about-h" style={{ marginBottom: 16 }}>About</h2>
        <dl className="kv">
          <dt>Name</dt><dd>{pt.full_name}{pt.preferred_name && <span className="muted"> (likes to be called {pt.preferred_name})</span>}</dd>
          <dt>Date of birth</dt><dd>{pt.date_of_birth ? `${fmtDate(pt.date_of_birth, { day: 'numeric', month: 'long', year: 'numeric' })} (age ${age(pt.date_of_birth)})` : <span className="muted">Not recorded</span>}</dd>
          <dt>Phone</dt><dd>{pt.phone || <span className="muted">Not recorded</span>}</dd>
          <dt>Address</dt><dd>{pt.address || <span className="muted">Not recorded</span>}</dd>
          <dt>Time zone</dt><dd>{pt.timezone.replace(/_/g, ' ')}</dd>
          {pt.notes && <><dt>Notes</dt><dd style={{ whiteSpace: 'pre-line' }}>{pt.notes}</dd></>}
          <dt>Reminder timing</dt>
          <dd>Unconfirmed after {pt.dose_grace_minutes} min, counted as missed after {Math.round(pt.missed_after_minutes / 60 * 10) / 10} h
            {can('manage_medications') && <> &nbsp;<Button variant="quiet" onClick={() => setRules(true)}>Change</Button></>}</dd>
        </dl>
      </section>
      <div className="grid-dash">
        <div className="stack-lg">
          <RecordSection pid={pid} kind="allergies" items={asRecords(q.data.allergies)} canEdit={canEdit} render={a => (
            <p><strong>{String(a.substance)}</strong>{a.reaction ? ` — ${String(a.reaction)}` : ''} {a.severity !== 'unknown' && <Badge tone={a.severity === 'severe' ? 'danger' : 'warn'}>{String(a.severity)}</Badge>}</p>
          )} />
          <RecordSection pid={pid} kind="history" items={asRecords(q.data.history)} canEdit={canEdit} render={h => (
            <><p><strong>{String(h.title)}</strong> <Badge>{({ active: 'Current', managed: 'Managed', resolved: 'Resolved', historical: 'Past' } as Record<string, string>)[String(h.status)]}</Badge></p>
              <p className="muted small">{String(h.kind).replace('hospitalization', 'hospital stay')}{h.occurred_on ? `, ${fmtDate(String(h.occurred_on), { month: 'short', year: 'numeric' })}` : ''}{h.notes ? ` | ${String(h.notes)}` : ''}</p></>
          )} />
        </div>
        <div className="stack-lg">
          <RecordSection pid={pid} kind="contacts" items={asRecords(q.data.contacts)} canEdit={canEdit} render={c => (
            <><p><strong>{String(c.name)}</strong>{c.relationship_label ? <span className="muted"> ({String(c.relationship_label)})</span> : ''} <Badge tone={Number(c.priority) === 1 ? 'info' : 'neutral'}>{`Call ${['', '1st', '2nd', '3rd', '4th', '5th'][Number(c.priority)] ?? ''}`}</Badge></p>
              <a href={`tel:${String(c.phone).replace(/[^\d+]/g, '')}`}>{String(c.phone)}</a></>
          )} />
          <RecordSection pid={pid} kind="doctors" items={asRecords(q.data.doctors)} canEdit={canEdit} render={d => (
            <><p><strong>{String(d.name)}</strong> {!!d.is_primary && <Badge tone="info">Main doctor</Badge>}</p>
              <p className="muted small">{[d.specialty, d.clinic, d.phone].filter(Boolean).join(' | ')}</p></>
          )} />
        </div>
      </div>
      <Modal open={editing} onClose={() => setEditing(false)} title="Edit details">
        {editing && <ProfileForm profile={q.data} onDone={() => { setEditing(false); qc.invalidateQueries({ queryKey: ['profile', pid] }); qc.invalidateQueries({ queryKey: ['overview', pid] }); toast('Details saved.') }} />}
      </Modal>
      <Modal open={rules} onClose={() => setRules(false)} title="Reminder timing">
        {rules && <RulesForm profile={q.data} onDone={() => { setRules(false); qc.invalidateQueries({ queryKey: ['profile', pid] }); toast('Reminder timing saved.') }} />}
      </Modal>
    </div>
  )
}

function ProfileForm({ profile, onDone }: { profile: Profile; onDone: () => void }) {
  const pt = profile.patient
  const f = useForm({ full_name: pt.full_name, preferred_name: pt.preferred_name, date_of_birth: pt.date_of_birth ?? '', phone: pt.phone, address: pt.address, notes: pt.notes })
  return (
    <form className="form-grid" noValidate onSubmit={e => { e.preventDefault(); f.submit(async () => { await api.patch(p(pt.id), { ...f.values, date_of_birth: f.values.date_of_birth || null }); onDone() }) }}>
      {f.formError && <Alert tone="danger">{f.formError}</Alert>}
      <div className="form-grid two">
        <TextField label="Full name" required {...f.bind('full_name')} />
        <TextField label="Preferred name" {...f.bind('preferred_name')} />
        <TextField label="Date of birth" type="date" {...f.bind('date_of_birth')} />
        <TextField label="Phone" type="tel" {...f.bind('phone')} />
      </div>
      <TextField label="Address" {...f.bind('address')} />
      <TextArea label="Notes" rows={3} hint="Anything carers should know, for example mobility or hearing." {...f.bind('notes')} />
      <div className="form-actions"><Button type="submit" loading={f.busy}>Save details</Button></div>
    </form>
  )
}

function RulesForm({ profile, onDone }: { profile: Profile; onDone: () => void }) {
  const pt = profile.patient
  const f = useForm({ dose_grace_minutes: String(pt.dose_grace_minutes), missed_after_minutes: String(pt.missed_after_minutes) })
  return (
    <form className="form-grid" noValidate onSubmit={e => { e.preventDefault(); f.submit(async () => { await api.put(p(pt.id, '/reminder-rules'), { dose_grace_minutes: Number(f.values.dose_grace_minutes), missed_after_minutes: Number(f.values.missed_after_minutes) }); onDone() }) }}>
      {f.formError && <Alert tone="danger">{f.formError}</Alert>}
      <SelectField label="Ask carers to check after" hint="If a dose isn't recorded within this time, people who follow medicines get a check-in message." {...f.bind('dose_grace_minutes')}>
        {[15, 30, 45, 60, 90, 120, 180, 240].map(m => <option key={m} value={m}>{m} minutes</option>)}
      </SelectField>
      <SelectField label="Count as missed after" {...f.bind('missed_after_minutes')}>
        {[60, 120, 180, 240, 360, 480, 720].map(m => <option key={m} value={m}>{m / 60} hours</option>)}
      </SelectField>
      <div className="form-actions"><Button type="submit" loading={f.busy}>Save timing</Button></div>
    </form>
  )
}

const CATEGORY: Record<string, string> = { lab_result: 'Test result', prescription: 'Prescription', discharge_summary: 'Discharge summary', imaging: 'Scan or X-ray report', insurance: 'Insurance', letter: 'Letter', other: 'Other' }

export function DocumentsPage() {
  const { pid, can } = usePatient()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['documents', pid], queryFn: () => api.get<DocumentItem[]>(p(pid, '/documents')), enabled: can('view_documents') })
  const [uploading, setUploading] = useState(false)
  const [removing, setRemoving] = useState<DocumentItem | null>(null)
  const f = useForm({ title: '', category: 'lab_result' })
  const [file, setFile] = useState<File | null>(null)
  const remove = useMutation({ mutationFn: (d: DocumentItem) => api.del(p(pid, `/documents/${d.id}`)), onSuccess: () => { toast('Document removed.'); setRemoving(null); qc.invalidateQueries({ queryKey: ['documents', pid] }) }, onError: e => toast(errorText(e), 'error') })
  if (!can('view_documents')) return <div className="page"><Alert tone="info">You don't have permission to see documents.</Alert></div>
  return (
    <div className="page stack-lg">
      <PageHead title="Documents" intro="Private to people allowed to see documents. Files are never publicly linked."
        actions={can('upload_documents') && <Button icon={<FileUp aria-hidden="true" />} onClick={() => setUploading(true)}>Upload document</Button>} />
      {q.isLoading ? <Skeleton /> : q.error ? <ErrorState error={q.error} /> : !q.data!.length ? (
        <div className="panel"><Empty title="No documents yet" action={can('upload_documents') && <Button onClick={() => setUploading(true)}>Upload the first document</Button>}>Keep test results, letters and prescriptions together. PDF, PNG or JPEG, up to 10 MB.</Empty></div>
      ) : (
        <div className="panel table-wrap">
          <table className="data">
            <thead><tr><th scope="col">Document</th><th scope="col">Type</th><th scope="col" className="hide-mobile">Added</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>
              {q.data!.map(d => (
                <tr key={d.id}>
                  <td><a href={p(pid, `/documents/${d.id}/download`)}>{d.title}</a><div className="muted small">{d.filename} | {(d.size_bytes / 1024).toFixed(0)} KB</div></td>
                  <td>{CATEGORY[d.category] ?? d.category}</td>
                  <td className="hide-mobile">{fmtDate(d.created_at, { day: 'numeric', month: 'short', year: 'numeric' })}<div className="muted small">{d.uploaded_by}</div></td>
                  <td style={{ textAlign: 'right' }}>{d.can_delete && <button type="button" className="icon-btn" aria-label={`Remove ${d.title}`} onClick={() => setRemoving(d)}><Trash2 aria-hidden="true" /></button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Modal open={uploading} onClose={() => setUploading(false)} title="Upload a document">
        <form className="form-grid" noValidate onSubmit={e => {
          e.preventDefault()
          if (!file) { f.setErrors({ file: 'Choose a file' }); return }
          f.submit(async () => {
            const body = new FormData()
            body.append('title', f.values.title); body.append('category', f.values.category); body.append('file', file)
            await api.post(p(pid, '/documents'), body)
            toast('Document uploaded.'); setUploading(false); setFile(null); f.setValues({ title: '', category: 'lab_result' })
            qc.invalidateQueries({ queryKey: ['documents', pid] })
          })
        }}>
          {f.formError && <Alert tone="danger">{f.formError}</Alert>}
          <TextField label="Title" required placeholder="For example, blood test March" {...f.bind('title')} />
          <SelectField label="Type" {...f.bind('category')}>{Object.entries(CATEGORY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}</SelectField>
          <TextField label="File" type="file" accept="application/pdf,image/png,image/jpeg" hint="PDF, PNG or JPEG, up to 10 MB." error={f.errors.file}
            onChange={e => { setFile((e.target as HTMLInputElement).files?.[0] ?? null); f.setErrors({}) }} />
          <div className="form-actions"><Button type="submit" loading={f.busy}>Upload</Button></div>
        </form>
      </Modal>
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} danger busy={remove.isPending} title={`Remove ${removing?.title ?? ''}?`} confirmLabel="Remove document"
        onConfirm={() => removing && remove.mutate(removing)} body={<p>It will no longer be visible to the care circle. The removal is recorded.</p>} />
    </div>
  )
}
