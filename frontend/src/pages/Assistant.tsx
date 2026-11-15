// The ElderCare assistant: answers from the records this user may view, with visible
// privacy and safety framing. History lives only in this page's memory.
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Lock, Mic, Send, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, p, type AssistantInfo, type AssistantReply } from '../api'
import { usePatient } from '../session'
import { Alert, Button, ErrorState, PageHead, Skeleton, errorText } from '../ui'

interface Turn { role: 'user' | 'assistant'; content: string; reply?: AssistantReply }

type SpeechCtor = new () => { lang: string; interimResults: boolean; start: () => void; onresult: (e: { results: { 0: { transcript: string } }[] }) => void; onerror: () => void; onend: () => void }
const Speech: SpeechCtor | undefined = (window as unknown as { SpeechRecognition?: SpeechCtor; webkitSpeechRecognition?: SpeechCtor }).SpeechRecognition
  ?? (window as unknown as { webkitSpeechRecognition?: SpeechCtor }).webkitSpeechRecognition

const PROVIDER_LABEL: Record<string, string> = {
  gemini: 'Google Gemini', vertex: 'Google Gemini on Vertex AI', offline: 'Record lookup (no AI service)', safety: 'Safety guidance',
}

export function AssistantPage() {
  const { pid, name, isElder } = usePatient()
  const info = useQuery({ queryKey: ['assistant', pid], queryFn: () => api.get<AssistantInfo>(p(pid, '/assistant')), retry: false })
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [listening, setListening] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }) }, [turns, busy])

  async function ask(message: string) {
    if (!message.trim() || busy) return
    setError(''); setBusy(true)
    const history = turns.slice(-10).map(t => ({ role: t.role, content: t.content.slice(0, 4000) }))
    setTurns(ts => [...ts, { role: 'user', content: message }])
    setText('')
    try {
      const reply = await api.post<AssistantReply>(p(pid, '/assistant'), { message, history })
      setTurns(ts => [...ts, { role: 'assistant', content: reply.answer, reply }])
    } catch (err) {
      setError(errorText(err))
      setTurns(ts => ts.slice(0, -1)); setText(message)
    } finally { setBusy(false) }
  }

  function dictate() {
    if (!Speech) return
    const rec = new Speech()
    rec.lang = navigator.language || 'en-GB'
    rec.interimResults = false
    rec.onresult = e => setText(t => `${t} ${e.results[0][0].transcript}`.trim()) // fills the box; never sends by itself
    rec.onerror = () => setListening(false)
    rec.onend = () => setListening(false)
    setListening(true); rec.start()
  }

  if (info.isLoading) return <div className="page"><Skeleton lines={6} /></div>
  if (info.error) return <div className="page"><PageHead title="Assistant" /><ErrorState error={info.error} /></div>
  const i = info.data!
  return (
    <div className="page stack-lg" style={{ maxWidth: '52rem' }}>
      <PageHead title="Assistant" intro={`Questions about ${isElder ? 'your' : `${name}’s`} records, appointments and general health terms.`} />
      <section className="panel panel-pad stack" aria-label="About this assistant" style={{ gap: 'var(--s3)' }}>
        <p className="row" style={{ gap: 8, flexWrap: 'nowrap', alignItems: 'flex-start' }}><Lock size={18} aria-hidden="true" style={{ flex: 'none', marginTop: 3, color: 'var(--teal-700)' }} />
          <span>Uses only what you're allowed to see: {i.sources.length ? i.sources.join(', ') : 'nothing yet'}. Answers come from {PROVIDER_LABEL[i.provider] ?? i.provider}. Conversations aren't saved.</span></p>
        <p className="row small muted" style={{ gap: 8, flexWrap: 'nowrap', alignItems: 'flex-start' }}><ShieldCheck size={18} aria-hidden="true" style={{ flex: 'none', marginTop: 2 }} /><span>{i.disclaimer} In an emergency, call your local emergency number.</span></p>
      </section>

      <section aria-label="Conversation" className="stack" aria-live="polite" aria-busy={busy}>
        {turns.length === 0 && (
          <div className="stack">
            <p className="muted">Try asking:</p>
            <div className="chips">{i.suggestions.map(s => <button key={s} type="button" className="btn btn-secondary" onClick={() => ask(s)}>{s}</button>)}</div>
          </div>
        )}
        {turns.map((t, idx) => (
          <article key={idx} className={t.role === 'user' ? 'msg msg-user' : 'msg msg-ai'} aria-label={t.role === 'user' ? 'You asked' : 'Assistant answered'}>
            {t.reply?.safety === 'urgent' && <p className="row" style={{ gap: 6, color: 'var(--danger)', fontWeight: 700 }}><AlertTriangle size={18} aria-hidden="true" />This may be urgent</p>}
            <p style={{ whiteSpace: 'pre-line' }}>{t.content}</p>
            {t.reply?.safety === 'urgent' && <p style={{ marginTop: 8 }}><Link className="btn btn-danger" to={`/p/${pid}/emergency`}>Open emergency contacts</Link></p>}
            {t.reply && (
              <p className="small muted" style={{ marginTop: 8 }}>
                {PROVIDER_LABEL[t.reply.provider] ?? t.reply.provider}{t.reply.sources.length > 0 && <> &nbsp;|&nbsp; Based on: {t.reply.sources.join(', ')}</>}
              </p>
            )}
            {t.reply?.notice && <p className="small" style={{ color: 'var(--warn)', marginTop: 4 }}>{t.reply.notice}</p>}
          </article>
        ))}
        {busy && <p className="muted row" style={{ gap: 8 }}><span className="spinner" style={{ width: 16, height: 16 }} aria-hidden="true" />Looking at the records…</p>}
        <div ref={endRef} />
      </section>

      {error && <Alert tone="danger">{error}</Alert>}
      <form className="panel panel-pad stack" onSubmit={(e: FormEvent) => { e.preventDefault(); void ask(text) }} style={{ position: 'sticky', bottom: 'var(--s4)' }}>
        <label htmlFor="ask" className="label" style={{ fontWeight: 600 }}>Your question</label>
        <textarea id="ask" className="textarea" rows={2} maxLength={1000} value={text} onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void ask(text) } }} placeholder="For example: when is my next appointment?" />
        <div className="spread">
          <span className="small muted">{text.length}/1000</span>
          <div className="row">
            {Speech && <Button variant="secondary" icon={<Mic aria-hidden="true" />} onClick={dictate} disabled={listening}>{listening ? 'Listening…' : 'Speak'}</Button>}
            <Button type="submit" icon={<Send aria-hidden="true" />} loading={busy} disabled={!text.trim()}>Ask</Button>
          </div>
        </div>
      </form>
    </div>
  )
}
