// Care tasks and shared notes for one care circle.
import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Pencil, Pin, Plus, Trash2 } from 'lucide-react'
import { api, p, type Member, type Note, type Task } from '../api'
import { usePatient } from '../hooks'
import { Alert, Badge, Button, Checkbox, ConfirmDialog, Empty, ErrorState, Modal, PageHead, SelectField, Skeleton, TextArea, TextField } from '../ui'
import { errorText, fmtDate, fmtRelative, useForm, useToast } from '../lib'

const PRIORITY_TONE = { low: 'neutral', normal: 'info', high: 'warn' } as const
const STATUS_LABEL: Record<Task['status'], string> = { open: 'To do', in_progress: 'In progress', done: 'Done', cancelled: 'Cancelled' }

export function TasksPage() {
  const { pid, overview, can } = usePatient()
  const qc = useQueryClient()
  const toast = useToast()
  const [scope, setScope] = useState<'open' | 'mine' | 'done'>('open')
  const [editing, setEditing] = useState<Task | 'new' | null>(null)
  const [completing, setCompleting] = useState<Task | null>(null)
  const [note, setNote] = useState('')
  const q = useQuery({ queryKey: ['tasks', pid, scope], queryFn: () => api.get<Task[]>(p(pid, `/tasks?scope=${scope}`)) })
  const members = useQuery({ queryKey: ['members', pid], queryFn: () => api.get<Member[]>(p(pid, '/members')) })
  const canManage = can('manage_tasks') || !!overview?.can_decide_access
  const refresh = () => qc.invalidateQueries({ queryKey: ['tasks', pid] })
  const setStatus = useMutation({
    mutationFn: ({ t, status, n }: { t: Task; status: Task['status']; n?: string }) => api.post<Task>(p(pid, `/tasks/${t.id}/status`), { status, note: n ?? '' }),
    onSuccess: t => { toast(`“${t.title}” marked ${STATUS_LABEL[t.status].toLowerCase()}.`); setCompleting(null); setNote(''); refresh() },
    onError: e => toast(errorText(e), 'error'),
  })
  return (
    <div className="page stack-lg">
      <PageHead title="Care tasks" intro="Shared jobs for the care circle, with who is doing what and by when."
        actions={canManage && <Button icon={<Plus aria-hidden="true" />} onClick={() => setEditing('new')}>New task</Button>} />
      <div className="chips" role="tablist" aria-label="Which tasks">
        {([['open', 'Open'], ['mine', 'Assigned to me'], ['done', 'Finished']] as const).map(([v, l]) => (
          <button key={v} type="button" role="tab" aria-selected={scope === v} className={`btn ${scope === v ? 'btn-primary' : 'btn-secondary'}`} onClick={() => setScope(v)}>{l}</button>
        ))}
      </div>
      {q.isLoading ? <Skeleton lines={5} /> : q.error ? <ErrorState error={q.error} /> : !q.data!.length ? (
        <div className="panel"><Empty title={scope === 'done' ? 'No finished tasks yet' : 'Nothing to do here'}
          action={canManage && scope !== 'done' && <Button onClick={() => setEditing('new')}>Create a task</Button>}>
          {scope === 'mine' ? 'Tasks assigned to you will appear here.' : 'For example: collect a repeat prescription, or prepare questions for a visit.'}
        </Empty></div>
      ) : (
        <div className="panel">
          <ul className="list">
            {q.data!.map(t => (
              <li key={t.id}>
                <div className="spread" style={{ alignItems: 'flex-start' }}>
                  <div className="stack" style={{ gap: 4 }}>
                    <h2 style={{ fontSize: 'var(--fs-md)' }}>{t.title}</h2>
                    {t.description && <p className="muted small" style={{ whiteSpace: 'pre-line' }}>{t.description}</p>}
                    <p className="small">
                      {t.assignee_name ? <>For <strong>{t.assignee_name}</strong></> : <span className="muted">Unassigned</span>}
                      {t.due_date && <> &nbsp;|&nbsp; Due {fmtDate(t.due_date)}</>}
                      {t.completed_at && <> &nbsp;|&nbsp; Done {fmtRelative(t.completed_at)}</>}
                    </p>
                    {t.completion_note && <p className="small muted">Note: {t.completion_note}</p>}
                  </div>
                  <div className="row" style={{ gap: 6 }}>
                    {t.overdue && <Badge tone="warn">Overdue</Badge>}
                    <Badge tone={PRIORITY_TONE[t.priority]}>{t.priority === 'normal' ? 'Normal priority' : t.priority === 'high' ? 'High priority' : 'Low priority'}</Badge>
                    {(t.status === 'done' || t.status === 'cancelled') && <Badge tone={t.status === 'done' ? 'ok' : 'neutral'}>{STATUS_LABEL[t.status]}</Badge>}
                  </div>
                </div>
                <div className="row" style={{ marginTop: 12 }}>
                  {t.can_update_status && (t.status === 'open' || t.status === 'in_progress') && (
                    <>
                      <Button icon={<CheckCircle2 aria-hidden="true" />} onClick={() => setCompleting(t)}>Mark done<span className="sr-only">: {t.title}</span></Button>
                      {t.status === 'open' && <Button variant="secondary" loading={setStatus.isPending} onClick={() => setStatus.mutate({ t, status: 'in_progress' })}>Start</Button>}
                    </>
                  )}
                  {t.can_update_status && (t.status === 'done' || t.status === 'cancelled') && <Button variant="secondary" onClick={() => setStatus.mutate({ t, status: 'open' })}>Reopen</Button>}
                  {t.can_edit && t.status !== 'done' && <Button variant="quiet" icon={<Pencil aria-hidden="true" />} onClick={() => setEditing(t)}>Edit</Button>}
                  {t.can_edit && t.status === 'open' && <Button variant="quiet" onClick={() => setStatus.mutate({ t, status: 'cancelled' })}>Cancel task</Button>}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div><a className="btn btn-quiet" href={p(pid, '/reports/tasks.csv')}>Download all tasks (CSV)</a></div>
      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New task' : 'Edit task'}>
        {editing && <TaskForm pid={pid} task={editing === 'new' ? undefined : editing} members={members.data ?? []} onDone={() => { setEditing(null); refresh() }} />}
      </Modal>
      <Modal open={!!completing} onClose={() => setCompleting(null)} title="Mark task as done">
        <form className="form-grid" onSubmit={e => { e.preventDefault(); if (completing) setStatus.mutate({ t: completing, status: 'done', n: note }) }}>
          <p>{completing?.title}</p>
          <TextArea label="Note (optional)" rows={2} hint="For example: collected 28 tablets from the pharmacy." value={note} onChange={e => setNote(e.target.value)} />
          <div className="form-actions"><Button variant="secondary" onClick={() => setCompleting(null)}>Cancel</Button><Button type="submit" loading={setStatus.isPending}>Mark done</Button></div>
        </form>
      </Modal>
    </div>
  )
}

function TaskForm({ pid, task, members, onDone }: { pid: number; task?: Task; members: Member[]; onDone: () => void }) {
  const toast = useToast()
  const f = useForm({ title: task?.title ?? '', description: task?.description ?? '', priority: task?.priority ?? 'normal', due_date: task?.due_date ?? '', assignee_user_id: task?.assignee_user_id ? String(task.assignee_user_id) : '' })
  return (
    <form className="form-grid" noValidate onSubmit={(e: FormEvent) => {
      e.preventDefault()
      f.submit(async () => {
        const body = { ...f.values, due_date: f.values.due_date || null, assignee_user_id: f.values.assignee_user_id ? Number(f.values.assignee_user_id) : null }
        if (task) await api.put(p(pid, `/tasks/${task.id}`), body); else await api.post(p(pid, '/tasks'), body)
        toast(task ? 'Task updated.' : 'Task created.'); onDone()
      })
    }}>
      {f.formError && <Alert tone="danger">{f.formError}</Alert>}
      <TextField label="Task" required placeholder="For example, collect repeat prescription" {...f.bind('title')} />
      <TextArea label="Details (optional)" rows={3} {...f.bind('description')} />
      <div className="form-grid two">
        <SelectField label="Assign to" {...f.bind('assignee_user_id')}>
          <option value="">Nobody yet</option>
          {members.map(m => <option key={m.user_id} value={m.user_id}>{m.full_name}{m.is_me ? ' (me)' : ''}</option>)}
        </SelectField>
        <TextField label="Due date (optional)" type="date" {...f.bind('due_date')} />
        <SelectField label="Priority" {...f.bind('priority')}><option value="low">Low</option><option value="normal">Normal</option><option value="high">High</option></SelectField>
      </div>
      <div className="form-actions"><Button type="submit" loading={f.busy}>{task ? 'Save task' : 'Create task'}</Button></div>
    </form>
  )
}

const NOTE_KINDS: [Note['kind'], string][] = [['note', 'Note'], ['care_instruction', 'Care instruction'], ['appointment_prep', 'Appointment preparation'], ['update', 'Important update']]
const NOTE_LABEL = Object.fromEntries(NOTE_KINDS) as Record<Note['kind'], string>

export function NotesPage() {
  const { pid, can } = usePatient()
  const qc = useQueryClient()
  const toast = useToast()
  const [kind, setKind] = useState<'' | Note['kind']>('')
  const [editing, setEditing] = useState<Note | 'new' | null>(null)
  const [removing, setRemoving] = useState<Note | null>(null)
  const q = useQuery({ queryKey: ['notes', pid, kind], queryFn: () => api.get<Note[]>(p(pid, `/notes${kind ? `?kind=${kind}` : ''}`)) })
  const remove = useMutation({ mutationFn: (n: Note) => api.del(p(pid, `/notes/${n.id}`)), onSuccess: () => { toast('Note removed.'); setRemoving(null); qc.invalidateQueries({ queryKey: ['notes', pid] }) } })
  const canWrite = can('view_profile') || can('view_appointments')
  return (
    <div className="page stack-lg" style={{ maxWidth: '56rem' }}>
      <PageHead title="Shared notes" intro="Care instructions, updates and visit preparation, visible to people allowed to see them."
        actions={canWrite && <Button icon={<Plus aria-hidden="true" />} onClick={() => setEditing('new')}>New note</Button>} />
      <div style={{ maxWidth: '18rem' }}>
        <SelectField label="Show" value={kind} onChange={e => setKind(e.target.value as typeof kind)}>
          <option value="">All notes</option>{NOTE_KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SelectField>
      </div>
      {q.isLoading ? <Skeleton /> : q.error ? <ErrorState error={q.error} /> : !q.data!.length ? (
        <div className="panel"><Empty title="No notes yet" action={canWrite && <Button onClick={() => setEditing('new')}>Write the first note</Button>}>Share how to help day to day, or what to raise at the next visit.</Empty></div>
      ) : (
        <div className="panel">
          <ul className="list">
            {q.data!.map(n => (
              <li key={n.id}>
                <div className="spread" style={{ alignItems: 'flex-start' }}>
                  <div className="stack" style={{ gap: 4, minWidth: 0 }}>
                    <p className="row" style={{ gap: 8 }}>{n.pinned && <Pin size={16} aria-label="Pinned" />}<strong style={{ color: 'var(--navy-800)' }}>{n.title}</strong><Badge tone={n.kind === 'update' ? 'warn' : 'neutral'}>{NOTE_LABEL[n.kind]}</Badge></p>
                    <p style={{ whiteSpace: 'pre-line' }}>{n.body}</p>
                    <p className="muted small">{n.author_name} &nbsp;|&nbsp; {fmtRelative(n.updated_at)}</p>
                  </div>
                  {n.can_edit && (
                    <div className="row" style={{ gap: 0, flexWrap: 'nowrap' }}>
                      <button type="button" className="icon-btn" aria-label={`Edit ${n.title}`} onClick={() => setEditing(n)}><Pencil aria-hidden="true" /></button>
                      <button type="button" className="icon-btn" aria-label={`Remove ${n.title}`} onClick={() => setRemoving(n)}><Trash2 aria-hidden="true" /></button>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing === 'new' ? 'New note' : 'Edit note'}>
        {editing && <NoteForm pid={pid} note={editing === 'new' ? undefined : editing} kinds={NOTE_KINDS.filter(([k]) => (k === 'appointment_prep' ? can('view_appointments') : can('view_profile')))} onDone={() => { setEditing(null); qc.invalidateQueries({ queryKey: ['notes', pid] }) }} />}
      </Modal>
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} danger busy={remove.isPending} title="Remove this note?" confirmLabel="Remove note"
        onConfirm={() => removing && remove.mutate(removing)} body={<p>The removal and the note's text are kept in the activity history.</p>} />
    </div>
  )
}

function NoteForm({ pid, note, kinds, onDone }: { pid: number; note?: Note; kinds: [Note['kind'], string][]; onDone: () => void }) {
  const toast = useToast()
  const f = useForm({ kind: note?.kind ?? kinds[0]?.[0] ?? 'note', title: note?.title ?? '', body: note?.body ?? '' })
  const [pinned, setPinned] = useState(note?.pinned ?? false)
  return (
    <form className="form-grid" noValidate onSubmit={e => {
      e.preventDefault()
      f.submit(async () => {
        const body = { ...f.values, pinned }
        if (note) await api.put(p(pid, `/notes/${note.id}`), body); else await api.post(p(pid, '/notes'), body)
        toast(note ? 'Note saved.' : 'Note shared.'); onDone()
      })
    }}>
      {f.formError && <Alert tone="danger">{f.formError}</Alert>}
      <SelectField label="Type" {...f.bind('kind')}>{kinds.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</SelectField>
      <TextField label="Title" required {...f.bind('title')} />
      <TextArea label="Note" required rows={5} {...f.bind('body')} />
      <Checkbox label="Pin to the top" checked={pinned} onChange={e => setPinned(e.target.checked)} />
      <div className="form-actions"><Button type="submit" loading={f.busy}>{note ? 'Save note' : 'Share note'}</Button></div>
    </form>
  )
}
