// Emergency screen for the elder: call a contact, or ask the care circle to get in touch.
// Wording keeps four things distinct: seeing a contact, starting a call (the phone does it),
// sending an alert (ElderCare queues it) and confirmed email acceptance (from delivery records).
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { BellRing, Phone } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, p, type Contact, type HelpStatus } from '../api'
import { usePatient } from '../session'
import { Alert, Button, ConfirmDialog, PageHead, Skeleton, TextField, errorText, fmtRelative } from '../ui'

const tel = (phone: string) => `tel:${phone.replace(/[^\d+]/g, '')}`

export function EmergencyPage() {
  const { pid, isElder, overview, can } = usePatient()
  const contacts = useQuery({ queryKey: ['emergency', pid], queryFn: () => api.get<{ contacts: Contact[]; primary_doctor: { name: string; phone: string } | null }>(p(pid, '/emergency')) })
  const status = useQuery({ queryKey: ['help-status', pid], queryFn: () => api.get<HelpStatus>(p(pid, '/help-alerts/latest')), refetchInterval: q => (q.state.data?.email_pending ? 5000 : false) })
  const [confirming, setConfirming] = useState(false)
  const [message, setMessage] = useState('')
  const send = useMutation({
    mutationFn: () => api.post(p(pid, '/help-alerts'), { message }),
    onSuccess: () => { setConfirming(false); setMessage(''); status.refetch() },
  })
  const canAlert = isElder || !!overview?.is_representative
  const s = status.data
  return (
    <div className="page stack-lg" style={{ maxWidth: '44rem' }}>
      <PageHead title="Emergency help" />
      <Alert tone="danger" title="In an emergency, call your local emergency number first">
        <p>For example 999 (UK), 112 (EU) or 911 (US). ElderCare does not contact emergency services.</p>
      </Alert>

      <section className="stack" aria-labelledby="call-h">
        <h2 id="call-h">Call someone</h2>
        <p className="muted">Pressing a button opens your phone's calling app. The call is made by your phone, not by ElderCare.</p>
        {contacts.isLoading ? <Skeleton /> : (contacts.data?.contacts.length ?? 0) === 0 ? (
          <Alert tone="warn" title="No emergency contacts yet">{can('edit_profile') ? <Link to={`/p/${pid}/health`}>Add an emergency contact</Link> : 'Ask the profile owner to add one.'}</Alert>
        ) : (
          <ol className="stack" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {contacts.data!.contacts.map((c, i) => (
              <li key={c.id}>
                <a href={tel(c.phone)} className="btn btn-secondary btn-block emergency-call" aria-label={`Call ${c.name}${c.relationship_label ? `, ${c.relationship_label}` : ''}, ${c.phone}`}>
                  <span className="stack" style={{ gap: 2 }}>
                    <span style={{ fontSize: 'var(--fs-lg)', fontWeight: 700 }}>{i === 0 && <span className="sr-only">First to call: </span>}{c.name}</span>
                    <span className="muted" style={{ fontWeight: 400 }}>{c.relationship_label}{c.relationship_label && ' — '}{c.phone}</span>
                  </span>
                  <span className="row" style={{ gap: 8, color: 'var(--teal-700)' }}><Phone aria-hidden="true" />Call</span>
                </a>
              </li>
            ))}
            {contacts.data!.primary_doctor?.phone && (
              <li><a href={tel(contacts.data!.primary_doctor.phone)} className="btn btn-secondary btn-block emergency-call">
                <span className="stack" style={{ gap: 2 }}><span style={{ fontSize: 'var(--fs-lg)', fontWeight: 700 }}>{contacts.data!.primary_doctor.name}</span><span className="muted" style={{ fontWeight: 400 }}>Doctor — {contacts.data!.primary_doctor.phone}</span></span>
                <span className="row" style={{ gap: 8, color: 'var(--teal-700)' }}><Phone aria-hidden="true" />Call</span>
              </a></li>
            )}
          </ol>
        )}
      </section>

      {canAlert && (
        <section className="panel panel-pad stack" aria-labelledby="alert-h">
          <h2 id="alert-h">Ask your care circle to get in touch</h2>
          <p>This sends a message to everyone in your care circle, in ElderCare and by email. It is not an emergency service.</p>
          <Button variant="danger-solid" size="lg" icon={<BellRing aria-hidden="true" />} onClick={() => setConfirming(true)}>Ask for help</Button>
          {send.error && <Alert tone="danger">{errorText(send.error)}</Alert>}
          {s?.created_at && (
            <div role="status" className="stack" style={{ gap: 4 }}>
              <p><strong>Alert sent {fmtRelative(s.created_at)} to {s.recipients} {s.recipients === 1 ? 'person' : 'people'}</strong> (shown in their ElderCare notifications).</p>
              <p className="small">Email: {s.email_sent} accepted by the mail service{s.email_pending > 0 && `, ${s.email_pending} waiting to send`}{s.email_failed > 0 && `, ${s.email_failed} failed`}{s.in_app_only > 0 && `, ${s.in_app_only} in-app only (email not confirmed)`}. {s.read} {s.read === 1 ? 'person has' : 'people have'} opened it.</p>
              <p className="small muted">ElderCare can't tell whether someone has read an email, so wait for a reply or call them.</p>
            </div>
          )}
        </section>
      )}

      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} busy={send.isPending} danger title="Send a help request?"
        confirmLabel="Send help request" onConfirm={() => send.mutate()}
        body={<div className="stack"><p>Everyone in your care circle will be asked to contact you.</p>
          <TextField label="Message (optional)" maxLength={300} value={message} onChange={e => setMessage(e.target.value)} placeholder="For example: I've had a fall but I'm OK" /></div>} />
    </div>
  )
}
