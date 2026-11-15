import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, UserPlus, UserRound } from 'lucide-react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api, type AccessRequest, type CircleSummary, type NotificationItem, type Preferences, type Profile, type User } from '../api'
import { useMemberships, useSession } from '../hooks'
import { Alert, Badge, Button, Checkbox, Empty, ErrorState, PageHead, SelectField, Skeleton, TextArea, TextField } from '../ui'
import { ROLE_LABEL, confirmError, fmtDate, fmtRelative, fmtTime, useForm, useToast } from '../lib'

function VerifyBanner() {
  const { user } = useSession()
  const toast = useToast()
  const resend = useMutation({ mutationFn: () => api.post('/api/auth/resend-verification'), onSuccess: () => toast('Confirmation email sent.') })
  if (!user || user.email_verified) return null
  return (
    <Alert tone="warn" title="Please confirm your email address">
      <p>Reminder emails are only sent to confirmed addresses. Check your inbox for the link.</p>
      <Button variant="secondary" style={{ marginTop: 8 }} loading={resend.isPending} onClick={() => resend.mutate()}>Send the link again</Button>
    </Alert>
  )
}

/** Signed-in landing: one circle -> go straight there; several -> caregiver summary. */
export function HomePage() {
  const memberships = useMemberships()
  const overview = useQuery({ queryKey: ['me-overview'], queryFn: () => api.get<CircleSummary[]>('/api/me/overview'), enabled: (memberships.data?.length ?? 0) > 1 })
  const requests = useQuery({ queryKey: ['my-requests'], queryFn: () => api.get<AccessRequest[]>('/api/access-requests/mine') })
  if (memberships.isLoading) return <div className="page"><Skeleton lines={5} /></div>
  if (memberships.error) return <div className="page"><ErrorState error={memberships.error} retry={() => memberships.refetch()} /></div>
  const list = memberships.data ?? []
  if (list.length === 1) {
    const m = list[0]
    return <Navigate to={`/p/${m.patient_id}/${m.role === 'elder' ? 'today' : 'overview'}`} replace />
  }
  const pending = (requests.data ?? []).filter(r => r.status === 'pending')
  return (
    <div className="page stack-lg">
      <VerifyBanner />
      {list.length === 0 ? (
        <>
          <PageHead title="Welcome to ElderCare" intro="How will you use ElderCare? You can add more later." />
          {pending.length > 0 && (
            <Alert tone="info" title="Waiting for approval">
              {pending.map(r => <p key={r.id}>Your request to join {r.patient_name}'s care circle was sent {fmtRelative(r.created_at)}. Nothing is shared until they approve it.</p>)}
            </Alert>
          )}
          <div className="panel">
            <ul className="list">
              <li className="spread">
                <div className="row items-start nowrap">
                  <UserRound aria-hidden="true" style={{ color: 'var(--teal-700)', flex: 'none', marginTop: 4 }} />
                  <div><h2>For myself</h2><p className="muted">Keep track of your own medicines and appointments, and choose who can help.</p></div>
                </div>
                <Link className="btn btn-primary" to="/new-profile?mode=self">Set up my profile</Link>
              </li>
              <li className="spread">
                <div className="row items-start nowrap">
                  <KeyRound aria-hidden="true" style={{ color: 'var(--teal-700)', flex: 'none', marginTop: 4 }} />
                  <div><h2>I have an invitation code</h2><p className="muted">Someone you help gave you a code. They'll approve what you can see.</p></div>
                </div>
                <Link className="btn btn-secondary" to="/join">Enter code</Link>
              </li>
              <li className="spread">
                <div className="row items-start nowrap">
                  <UserPlus aria-hidden="true" style={{ color: 'var(--teal-700)', flex: 'none', marginTop: 4 }} />
                  <div><h2>On behalf of someone</h2><p className="muted">For a trusted representative, such as someone holding power of attorney, when the person can't set up an account themselves.</p></div>
                </div>
                <Link className="btn btn-secondary" to="/new-profile?mode=representative">Set up for someone</Link>
              </li>
            </ul>
          </div>
        </>
      ) : (
        <>
          <PageHead title="People you support" intro="Today at a glance. People needing attention are listed first." actions={<Link className="btn btn-secondary" to="/join">Enter a code</Link>} />
          {overview.isLoading ? <Skeleton /> : (
            <div className="panel">
              <ul className="list">
                {(overview.data ?? []).map(c => {
                  const d = c.doses_today
                  return (
                    <li key={c.patient_id} className="spread">
                      <div className="stack gap-1">
                        <h2><Link to={`/p/${c.patient_id}/${c.role === 'elder' ? 'today' : 'overview'}`}>{c.patient_name}{c.role === 'elder' ? ' (me)' : ''}</Link></h2>
                        <p className="muted small">{ROLE_LABEL[c.role]}
                          {c.next_appointment && <> &nbsp;|&nbsp; Next visit {fmtDate(c.next_appointment.local_date)} at {fmtTime(c.next_appointment.local_time)}</>}
                        </p>
                      </div>
                      <div className="row">
                        {d && <span className="num">{d.taken} of {d.taken + d.skipped + d.missed + d.unconfirmed + d.scheduled} doses recorded today</span>}
                        {!!c.needs_attention && <Badge tone="warn">{c.needs_attention} need attention</Badge>}
                        {c.pending_requests > 0 && <Badge tone="info">{c.pending_requests} access request{c.pending_requests > 1 ? 's' : ''}</Badge>}
                      </div>
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}

const TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

export function NewProfilePage() {
  const [params] = useSearchParams()
  const mode = params.get('mode') === 'representative' ? 'representative' : 'self'
  const { user } = useSession()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const f = useForm({
    full_name: mode === 'self' ? user?.full_name ?? '' : '', preferred_name: '', date_of_birth: '',
    phone: '', representative_role: 'family', relationship_label: '', attestation: '',
  })
  const [confirmed, setConfirmed] = useState(false)
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (mode === 'representative' && !confirmed) { f.setFormError('Please confirm you have the authority to manage this information.'); return }
    f.submit(async () => {
      const body = { ...f.values, mode, timezone: TIMEZONE, date_of_birth: f.values.date_of_birth || null }
      const res = await api.post<Profile>('/api/patients', body)
      await qc.invalidateQueries()
      navigate(`/p/${res.patient.id}/${mode === 'self' ? 'today' : 'overview'}`)
    })
  }
  return (
    <div className="page" style={{ maxWidth: '44rem' }}>
      <PageHead title={mode === 'self' ? 'Set up your profile' : 'Set up a profile for someone'}
        intro={mode === 'self' ? 'You stay in charge: nobody can see your information until you approve them.' : 'You will be recorded as their trusted representative. When they create their own account, they can take over the profile.'}
        crumbs={[{ to: '/', label: 'Home' }]} />
      <form className="panel panel-pad form-grid" onSubmit={onSubmit} noValidate>
        {f.formError && <Alert tone="danger">{f.formError}</Alert>}
        <div className="form-grid two">
          <TextField label="Full name" required autoComplete={mode === 'self' ? 'name' : 'off'} {...f.bind('full_name')} />
          <TextField label="Preferred name" hint="What they like to be called" {...f.bind('preferred_name')} />
          <TextField label="Date of birth" type="date" {...f.bind('date_of_birth')} />
          <TextField label="Phone" type="tel" autoComplete="tel" {...f.bind('phone')} />
        </div>
        {mode === 'representative' && (
          <>
            <div className="form-grid two">
              <SelectField label="Your role" {...f.bind('representative_role')}>
                <option value="family">Family member</option>
                <option value="caregiver">Caregiver</option>
              </SelectField>
              <TextField label="Your relationship" placeholder="For example, son" {...f.bind('relationship_label')} />
            </div>
            <TextArea label="Your authority" required hint="Describe the permission or legal authority you have, for example a lasting power of attorney. This is kept on record and shown to the person." {...f.bind('attestation')} />
            <Checkbox label="I confirm this is accurate" description="I have the person's permission, or legal authority, to manage their care information." checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
          </>
        )}
        <p className="muted small">Time zone for reminders: {TIMEZONE}</p>
        <div className="form-actions">
          <Link className="btn btn-secondary" to="/">Cancel</Link>
          <Button type="submit" loading={f.busy}>Create profile</Button>
        </div>
      </form>
    </div>
  )
}

export function JoinPage() {
  const [params] = useSearchParams()
  const qc = useQueryClient()
  const [done, setDone] = useState<AccessRequest | null>(null)
  const f = useForm({ code: params.get('code') ?? '', relationship_label: '', message: '' })
  return (
    <div className="page" style={{ maxWidth: '40rem' }}>
      <PageHead title="Join a care circle" intro="Enter the code you were given. The person (or their representative) will decide what you can see." crumbs={[{ to: '/', label: 'Home' }]} />
      {done ? (
        <Alert tone="ok" title="Request sent">
          <p>{done.patient_name} has been asked to approve your request. Nothing is shared until they do; you'll get a notification when they decide.</p>
          <Link to="/" style={{ display: 'inline-block', marginTop: 8 }}>Back to home</Link>
        </Alert>
      ) : (
        <form className="panel panel-pad form-grid" noValidate onSubmit={e => {
          e.preventDefault()
          f.submit(async () => { setDone(await api.post<AccessRequest>('/api/invitations/redeem', f.values)); qc.invalidateQueries({ queryKey: ['my-requests'] }) })
        }}>
          {f.formError && <Alert tone="danger">{f.formError}</Alert>}
          <TextField label="Invitation code" required autoComplete="off" spellCheck={false} placeholder="ABCDE-FGHJK"
            hint="10 letters and numbers. Codes work once and expire after 3 days." style={{ textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }} {...f.bind('code')} />
          <TextField label="How you're related" placeholder="For example, daughter or home carer" {...f.bind('relationship_label')} />
          <TextArea label="Message (optional)" rows={3} {...f.bind('message')} />
          <div className="form-actions"><Button type="submit" loading={f.busy}>Send request</Button></div>
        </form>
      )}
    </div>
  )
}

export function AccountPage() {
  const { user, refresh, signOut } = useSession()
  const navigate = useNavigate()
  const toast = useToast()
  const prof = useForm({ full_name: user?.full_name ?? '', timezone: user?.timezone ?? 'UTC', text_scale: user?.text_scale ?? 'standard' })
  const pw = useForm({ current_password: '', new_password: '', confirm_password: '' })
  const [prefs, setPrefs] = useState<Preferences>(user?.preferences ?? { contrast: 'standard', reduce_motion: false, simplified_nav: false, read_aloud: true })
  const [savingPrefs, setSavingPrefs] = useState(false)
  async function savePrefs(next: Preferences) {
    setPrefs(next)
    document.documentElement.dataset.contrast = next.contrast
    document.documentElement.dataset.motion = next.reduce_motion ? 'reduce' : 'full'
    setSavingPrefs(true)
    try { await api.patch<User>('/api/auth/me', { preferences: next }); await refresh(); toast('Display settings saved.') }
    catch { toast('Settings could not be saved. Please try again.', 'error') }
    finally { setSavingPrefs(false) }
  }
  const zones = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.('timeZone') ?? [prof.values.timezone]
  return (
    <div className="page stack-lg" style={{ maxWidth: '48rem' }}>
      <PageHead title="Account" intro={user?.email}
        actions={<Button variant="secondary" onClick={async () => { await signOut(); navigate('/login', { replace: true }) }}>Sign out</Button>} />
      <VerifyBanner />
      <form className="panel panel-pad form-grid" noValidate onSubmit={e => {
        e.preventDefault()
        prof.submit(async () => {
          await api.patch<User>('/api/auth/me', prof.values)
          localStorage.setItem('ec-scale', prof.values.text_scale)
          await refresh(); toast('Account details saved.')
        })
      }}>
        <h2>Your details</h2>
        {prof.formError && <Alert tone="danger">{prof.formError}</Alert>}
        <TextField label="Full name" autoComplete="name" {...prof.bind('full_name')} />
        <SelectField label="Time zone" {...prof.bind('timezone')}>
          {zones.map(z => <option key={z} value={z}>{z.replace(/_/g, ' ')}</option>)}
        </SelectField>
        <fieldset>
          <legend>Text size</legend>
          <div className="chips" role="radiogroup">
            {(['standard', 'large', 'xlarge'] as const).map(s => (
              <label key={s} className="chip">
                <input type="radio" name="text_scale" value={s} checked={prof.values.text_scale === s}
                  onChange={() => { prof.set('text_scale', s); document.documentElement.dataset.scale = s }} />
                <span style={{ fontSize: s === 'standard' ? '1rem' : s === 'large' ? '1.125rem' : '1.25rem' }}>{s === 'standard' ? 'Standard' : s === 'large' ? 'Large' : 'Extra large'}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="form-actions"><Button type="submit" loading={prof.busy}>Save details</Button></div>
      </form>
      <section className="panel panel-pad form-grid" aria-labelledby="a11y-h" aria-busy={savingPrefs}>
        <h2 id="a11y-h">Display and sound</h2>
        <p className="muted small">Saved to your account, so they follow you to any device.</p>
        <Checkbox label="High contrast" description="Darker text, stronger borders and underlined links." checked={prefs.contrast === 'high'} onChange={e => savePrefs({ ...prefs, contrast: e.target.checked ? 'high' : 'standard' })} />
        <Checkbox label="Reduce motion" description="Turns off spinners and transitions." checked={prefs.reduce_motion} onChange={e => savePrefs({ ...prefs, reduce_motion: e.target.checked })} />
        <Checkbox label="Simpler menu" description="Shows only the everyday sections in the menu." checked={prefs.simplified_nav} onChange={e => savePrefs({ ...prefs, simplified_nav: e.target.checked })} />
        <Checkbox label="Offer to read the day aloud" description="Shows a button on the Today screen that reads your schedule out loud, if your device supports speech." checked={prefs.read_aloud} onChange={e => savePrefs({ ...prefs, read_aloud: e.target.checked })} />
      </section>
      <form className="panel panel-pad form-grid" noValidate onSubmit={e => {
        e.preventDefault()
        const mismatch = confirmError(pw.values.new_password, pw.values.confirm_password)
        if (mismatch) { pw.setErrors({ confirm_password: mismatch }); return }
        pw.submit(async () => {
          await api.post('/api/auth/change-password', { current_password: pw.values.current_password, new_password: pw.values.new_password })
          pw.setValues({ current_password: '', new_password: '', confirm_password: '' })
          toast('Password changed. Other devices were signed out.')
        })
      }}>
        <h2>Change password</h2>
        {pw.formError && <Alert tone="danger">{pw.formError}</Alert>}
        <TextField label="Current password" type="password" autoComplete="current-password" {...pw.bind('current_password')} />
        <TextField label="New password" type="password" autoComplete="new-password" hint="At least 10 characters." {...pw.bind('new_password')} />
        <TextField label="Confirm new password" type="password" autoComplete="new-password" {...pw.bind('confirm_password')} />
        <div className="form-actions"><Button type="submit" loading={pw.busy}>Change password</Button></div>
      </form>
    </div>
  )
}

const KIND_LABEL: Record<string, string> = {
  dose_reminder: 'Dose reminder', dose_escalation: 'Unconfirmed dose', appointment_reminder: 'Appointment',
  low_stock: 'Refill', access_request: 'Access request', access_decision: 'Access', security: 'Security',
  task_assigned: 'Task', help_request: 'Help request',
}
const SEVERITY: Record<NotificationItem['severity'], [string, string]> = {
  info: ['Info', 'badge-neutral'], reminder: ['Reminder', 'badge-info'], warning: ['Needs attention', 'badge-warn'], critical: ['Urgent', 'badge-critical'],
}
const EMAIL_LABEL: Record<string, string> = {
  sent: 'Emailed', pending: 'Email queued', failed: 'Email failed', suppressed: 'In-app only',
}

export function NotificationsPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [kind, setKind] = useState('')
  const q = useQuery({ queryKey: ['notifications', 'list', kind], queryFn: () => api.get<{ items: NotificationItem[]; unread: number }>(`/api/notifications?limit=50${kind ? `&kind=${kind}` : ''}`) })
  const readAll = useMutation({ mutationFn: () => api.post('/api/notifications/read-all'), onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }) })
  async function open(n: NotificationItem) {
    if (!n.read) await api.post(`/api/notifications/${n.id}/read`)
    qc.invalidateQueries({ queryKey: ['notifications'] })
    if (n.link_path) navigate(n.link_path) // opening never records a dose
  }
  return (
    <div className="page" style={{ maxWidth: '52rem' }}>
      <PageHead title="Notifications" intro="Reminders and updates from your care circles. Opening one never records a dose."
        actions={(q.data?.unread ?? 0) > 0 && <Button variant="secondary" loading={readAll.isPending} onClick={() => readAll.mutate()}>Mark all as read</Button>} />
      <div style={{ maxWidth: '18rem', marginBottom: 'var(--s4)' }}>
        <SelectField label="Show" value={kind} onChange={e => setKind(e.target.value)}>
          <option value="">All notifications</option>{Object.entries(KIND_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SelectField>
      </div>
      {q.isLoading ? <Skeleton /> : q.error ? <ErrorState error={q.error} /> : !q.data?.items.length ? (
        <div className="panel"><Empty title="No notifications here">Reminders and care updates will appear here.</Empty></div>
      ) : (
        <div className="panel">
          <ul className="list">
            {q.data.items.map(n => (
              <li key={n.id}>
                <button type="button" onClick={() => open(n)} className="row-btn">
                  <span className="stack gap-1">
                    <span className="row gap-2">
                      {!n.read && <span className="badge badge-info">New</span>}
                      <span className={`badge ${SEVERITY[n.severity][1]}`}>{SEVERITY[n.severity][0]}</span>
                      <strong style={{ color: 'var(--navy-800)' }}>{n.subject}</strong>
                    </span>
                    <span className="muted small">{n.body.split('\n\n')[0]}</span>
                  </span>
                  <span className="muted small text-right">
                    {KIND_LABEL[n.kind] ?? n.kind}<br />{fmtRelative(n.created_at)} &nbsp;|&nbsp; {EMAIL_LABEL[n.email_status] ?? n.email_status}
                    {n.email_status === 'failed' && <><br /><span style={{ color: 'var(--danger)' }}>Email failed after {n.attempts} attempts</span></>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
