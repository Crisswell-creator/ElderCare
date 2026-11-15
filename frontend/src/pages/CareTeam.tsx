import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, KeyRound, ShieldCheck, UserMinus } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { api, p, type AccessRequest, type Invitation, type Member, type Permission } from '../api'
import { usePatient } from '../hooks'
import { Alert, Badge, Button, Checkbox, ConfirmDialog, Empty, ErrorState, Modal, PageHead, SelectField, Skeleton, TextField } from '../ui'
import { PERMISSION_LABEL, PERMISSION_ORDER, ROLE_LABEL, errorText, fmtDate, fmtDateTime, fmtRelative, initials, useToast } from '../lib'

function PermissionPicker({ value, onChange }: { value: Permission[]; onChange: (v: Permission[]) => void }) {
  return (
    <fieldset>
      <legend>They can</legend>
      <div className="form-grid two" style={{ gap: 0 }}>
        {PERMISSION_ORDER.map(perm => (
          <Checkbox key={perm} label={PERMISSION_LABEL[perm]} checked={value.includes(perm)}
            onChange={() => onChange(value.includes(perm) ? value.filter(x => x !== perm) : [...value, perm])} />
        ))}
      </div>
    </fieldset>
  )
}

export function CareTeamPage() {
  const { pid, overview, isElder } = usePatient()
  const qc = useQueryClient()
  const toast = useToast()
  const navigate = useNavigate()
  const decider = !!overview?.can_decide_access
  const members = useQuery({ queryKey: ['members', pid], queryFn: () => api.get<Member[]>(p(pid, '/members')) })
  const requests = useQuery({ queryKey: ['requests', pid], queryFn: () => api.get<AccessRequest[]>(p(pid, '/access-requests')), enabled: decider })
  const invites = useQuery({ queryKey: ['invites', pid], queryFn: () => api.get<Invitation[]>(p(pid, '/invitations')), enabled: decider })
  const refresh = () => ['members', 'requests', 'invites', 'overview'].forEach(k => qc.invalidateQueries({ queryKey: [k, pid] }))

  const [reviewing, setReviewing] = useState<AccessRequest | null>(null)
  const [perms, setPerms] = useState<Permission[]>([])
  const [editing, setEditing] = useState<Member | null>(null)
  const [removing, setRemoving] = useState<Member | null>(null)
  const [newCode, setNewCode] = useState<Invitation | null>(null)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [inviteRole, setInviteRole] = useState<'family' | 'caregiver' | 'elder'>('family')
  const [inviteNote, setInviteNote] = useState('')

  const decide = useMutation({
    mutationFn: ({ r, decision }: { r: AccessRequest; decision: 'approve' | 'reject' }) =>
      api.post(p(pid, `/access-requests/${r.id}/decision`), { decision, permissions: perms }),
    onSuccess: (_, v) => { toast(v.decision === 'approve' ? `${v.r.requester_name} now has the access you chose.` : 'Request declined.'); setReviewing(null); refresh() },
    onError: e => toast(errorText(e), 'error'),
  })
  const update = useMutation({
    mutationFn: ({ m, body }: { m: Member; body: object }) => api.patch(p(pid, `/members/${m.id}`), body),
    onSuccess: () => { toast('Access updated.'); setEditing(null); refresh() },
    onError: e => toast(errorText(e), 'error'),
  })
  const revoke = useMutation({
    mutationFn: (m: Member) => api.del(p(pid, `/members/${m.id}`)),
    onSuccess: (_, m) => {
      setRemoving(null)
      if (m.is_me) { qc.invalidateQueries(); navigate('/') } else { toast(`${m.full_name} no longer has access.`); refresh() }
    },
    onError: e => toast(errorText(e), 'error'),
  })
  const createInvite = useMutation({
    mutationFn: () => api.post<Invitation>(p(pid, '/invitations'), { intended_role: inviteRole, note: inviteNote }),
    onSuccess: inv => { setInviteOpen(false); setInviteNote(''); setNewCode(inv); refresh() },
    onError: e => toast(errorText(e), 'error'),
  })
  const cancelInvite = useMutation({ mutationFn: (i: Invitation) => api.del(p(pid, `/invitations/${i.id}`)), onSuccess: () => { toast('Code cancelled.'); refresh() } })
  const prefs = useMutation({
    mutationFn: (body: object) => api.put(p(pid, '/members/me/preferences'), body),
    onSuccess: () => { toast('Email preferences saved.'); refresh() },
  })

  if (members.isLoading) return <div className="page"><Skeleton lines={6} /></div>
  if (members.error) return <div className="page"><ErrorState error={members.error} /></div>
  const me = members.data!.find(m => m.is_me)
  const activeInvites = (invites.data ?? []).filter(i => i.state === 'active')

  return (
    <div className="page stack-lg">
      <PageHead title={isElder ? 'Family & carers' : 'Care team'}
        intro={isElder ? 'You decide who can see your information and what they can do. You can change or remove access at any time.' : `People in ${overview?.patient_name}'s care circle and what each can do.`}
        actions={decider && <Button icon={<KeyRound aria-hidden="true" />} onClick={() => setInviteOpen(true)}>Invite someone</Button>} />

      {decider && (requests.data?.length ?? 0) > 0 && (
        <section className="panel" aria-labelledby="req-h" style={{ borderColor: 'var(--teal-700)', borderWidth: 2 }}>
          <div className="panel-head"><h2 id="req-h">Waiting for your answer</h2></div>
          <ul className="list">
            {requests.data!.map(r => (
              <li key={r.id} className="spread">
                <div>
                  <p><strong>{r.requester_name}</strong> ({r.requester_email}{!r.requester_email_verified && ', email not yet confirmed'}) asked to join as a {ROLE_LABEL[r.requested_role].toLowerCase()}{r.relationship_label && `, "${r.relationship_label}"`}.</p>
                  {r.message && <p className="muted">&ldquo;{r.message}&rdquo;</p>}
                  <p className="muted small">{fmtRelative(r.created_at)}. Nothing is shared until you decide.</p>
                </div>
                <Button onClick={() => { setReviewing(r); setPerms(r.suggested_permissions) }}>Review</Button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="panel" aria-labelledby="members-h">
        <div className="panel-head"><h2 id="members-h">People with access</h2>{overview?.my_permissions.includes('view_activity') && <Link className="small" to={`/p/${pid}/activity?category=access`}>Access history</Link>}</div>
        <ul className="list">
          {members.data!.map(m => (
            <li key={m.id} className="spread" style={{ alignItems: 'flex-start' }}>
              <div className="row" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
                <span className="avatar" aria-hidden="true">{initials(m.full_name)}</span>
                <div className="stack" style={{ gap: 4 }}>
                  <p><strong>{m.full_name}</strong>{m.is_me && ' (you)'} <span className="muted">{ROLE_LABEL[m.role]}{m.relationship_label && m.role !== 'elder' ? `, ${m.relationship_label}` : ''}</span></p>
                  <div className="row" style={{ gap: 6 }}>
                    {m.role === 'elder' && <Badge tone="info">Profile owner</Badge>}
                    {m.is_representative && <Badge tone="info"><ShieldCheck aria-hidden="true" />Trusted representative</Badge>}
                  </div>
                  {m.role !== 'elder' && <p className="muted small">{m.permissions.map(x => PERMISSION_LABEL[x]).join('; ')}</p>}
                  <p className="muted small">Joined {fmtDate(m.joined_at, { day: 'numeric', month: 'short', year: 'numeric' })}</p>
                </div>
              </div>
              <div className="row">
                {decider && m.role !== 'elder' && !m.is_me && <Button variant="secondary" onClick={() => { setEditing(m); setPerms(m.permissions) }}>Change access</Button>}
                {m.role !== 'elder' && (m.is_me || (decider && (!m.is_representative || isElder))) && (
                  <Button variant="danger" icon={<UserMinus aria-hidden="true" />} onClick={() => setRemoving(m)}>{m.is_me ? 'Leave' : 'Remove'}</Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      {decider && (
        <section className="panel" aria-labelledby="inv-h">
          <div className="panel-head"><h2 id="inv-h">Open invitation codes</h2></div>
          {activeInvites.length === 0 ? <Empty title="No open codes">Create a code and share it in person or by phone. It works once, expires in 3 days, and only lets someone ask for access.</Empty> : (
            <ul className="list list-compact">
              {activeInvites.map(i => (
                <li key={i.id} className="spread">
                  <span>For a {ROLE_LABEL[i.intended_role].toLowerCase()}{i.note && ` (${i.note})`}, expires {fmtDateTime(i.expires_at)}</span>
                  <Button variant="quiet" loading={cancelInvite.isPending} onClick={() => cancelInvite.mutate(i)}>Cancel code</Button>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {me && (
        <section className="panel panel-pad stack" aria-labelledby="prefs-h">
          <h2 id="prefs-h">Emails you receive about {isElder ? 'yourself' : overview?.patient_name}</h2>
          <p className="muted small">Everything also appears in Notifications. Emails never include medicine names.</p>
          <div className="form-grid two" style={{ gap: 0 }}>
            {([['notify_dose_reminders', 'Dose reminders', 'An email when a dose is due'], ['notify_escalations', 'Unconfirmed doses', 'When a dose hasn’t been recorded after the grace period'],
              ['notify_appointments', 'Appointment reminders', 'Before each visit'], ['notify_low_stock', 'Refill warnings', 'When stock is estimated to run low']] as const).map(([k, label, desc]) => (
              <Checkbox key={k} label={label} description={desc} checked={me[k]} disabled={prefs.isPending}
                onChange={e => prefs.mutate({ notify_dose_reminders: me.notify_dose_reminders, notify_escalations: me.notify_escalations, notify_appointments: me.notify_appointments, notify_low_stock: me.notify_low_stock, [k]: e.target.checked })} />
            ))}
          </div>
        </section>
      )}

      <Modal open={!!reviewing} onClose={() => setReviewing(null)} title={`Access for ${reviewing?.requester_name ?? ''}`}>
        {reviewing && (
          <div className="form-grid">
            {reviewing.requested_role === 'elder' ? (
              <Alert tone="info" title="Linking the elder's own account">Approving gives {reviewing.requester_name} full control of this profile as its owner, including deciding who else has access.</Alert>
            ) : (
              <>
                <p>Choose exactly what {reviewing.requester_name} can see and do. Suggestions for a {ROLE_LABEL[reviewing.requested_role].toLowerCase()} are ticked; change them as you like.</p>
                <PermissionPicker value={perms} onChange={setPerms} />
              </>
            )}
            <div className="form-actions">
              <Button variant="danger" loading={decide.isPending && decide.variables?.decision === 'reject'} onClick={() => decide.mutate({ r: reviewing, decision: 'reject' })}>Decline</Button>
              <Button disabled={reviewing.requested_role !== 'elder' && perms.length === 0} loading={decide.isPending && decide.variables?.decision === 'approve'} onClick={() => decide.mutate({ r: reviewing, decision: 'approve' })}>Approve access</Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={`Access for ${editing?.full_name ?? ''}`}>
        {editing && (
          <div className="form-grid">
            <PermissionPicker value={perms} onChange={setPerms} />
            {isElder && (
              <Checkbox label="Trusted representative" description="Can approve or remove access on your behalf. You are told about every change and can undo it."
                checked={editing.is_representative} onChange={e => setEditing({ ...editing, is_representative: e.target.checked })} />
            )}
            <div className="form-actions">
              <Button variant="secondary" onClick={() => setEditing(null)}>Cancel</Button>
              <Button disabled={perms.length === 0} loading={update.isPending}
                onClick={() => update.mutate({ m: editing, body: { permissions: perms, ...(isElder ? { is_representative: editing.is_representative } : {}) } })}>Save access</Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={inviteOpen} onClose={() => setInviteOpen(false)} title="Invite someone">
        <form className="form-grid" onSubmit={e => { e.preventDefault(); createInvite.mutate() }}>
          <p>You'll get a one-time code to share. Using it only sends you a request; you then choose what they can see.</p>
          <SelectField label="They will be a" value={inviteRole} onChange={e => setInviteRole(e.target.value as typeof inviteRole)}>
            <option value="family">Family member</option>
            <option value="caregiver">Caregiver</option>
            {overview?.is_representative && !isElder && <option value="elder">The person themself (to take over this profile)</option>}
          </SelectField>
          <TextField label="Who is it for? (optional)" hint="Only you see this note." value={inviteNote} onChange={e => setInviteNote(e.target.value)} maxLength={200} />
          <div className="form-actions"><Button type="submit" loading={createInvite.isPending}>Create code</Button></div>
        </form>
      </Modal>

      <Modal open={!!newCode} onClose={() => setNewCode(null)} title="Invitation code">
        {newCode?.code && (
          <div className="stack">
            <p>Share this code with the person. It works once and expires on {fmtDateTime(newCode.expires_at)}.</p>
            <p className="num" style={{ fontSize: 'var(--fs-3xl)', fontWeight: 700, letterSpacing: '0.12em', color: 'var(--navy-800)', textAlign: 'center', padding: 'var(--s4)', background: 'var(--surface-sunk)', borderRadius: 'var(--r-md)' }} aria-label={`Code: ${newCode.code.split('').join(' ')}`}>{newCode.code}</p>
            <p className="muted small">They can also open: {location.origin}/join?code={newCode.code}</p>
            <Alert tone="warn">This code won't be shown again. Share it only with the person it's for.</Alert>
            <div className="form-actions">
              <Button variant="secondary" icon={<Copy aria-hidden="true" />} onClick={async () => { await navigator.clipboard.writeText(newCode.code!); toast('Code copied.') }}>Copy code</Button>
              <Button onClick={() => setNewCode(null)}>Done</Button>
            </div>
          </div>
        )}
      </Modal>

      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} danger busy={revoke.isPending}
        title={removing?.is_me ? 'Leave this care circle?' : `Remove ${removing?.full_name ?? ''}?`}
        confirmLabel={removing?.is_me ? 'Leave' : 'Remove access'} onConfirm={() => removing && revoke.mutate(removing)}
        body={<p>{removing?.is_me ? 'You will lose access straight away. To return, you would need a new invitation and approval.' : 'They lose access straight away and are told their access changed. Past activity stays in the history.'}</p>} />
    </div>
  )
}
