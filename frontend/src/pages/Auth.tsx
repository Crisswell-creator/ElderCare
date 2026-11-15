import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { api, type User } from '../api'
import { useSession } from '../hooks'
import { Alert, Button, Logo, TextField } from '../ui'
import { confirmError, useForm } from '../lib'
import { AuthArt } from '../art'

function AuthLayout({ title, intro, children }: { title: string; intro?: ReactNode; children: ReactNode }) {
  useEffect(() => { document.title = `${title} | ElderCare` }, [title])
  return (
    <div className="auth">
      <aside className="auth-aside">
        <span className="brand"><Logo /> ElderCare</span>
        <h2>Medicines and appointments, shared with the people you choose.</h2>
        <ul>
          <li><Check aria-hidden="true" /><span>Clear daily reminders and a simple way to record each dose.</span></li>
          <li><Check aria-hidden="true" /><span>Family and carers see only what you allow, and you can change that at any time.</span></li>
          <li><Check aria-hidden="true" /><span>A one-page summary to take to the doctor, made from your own records.</span></li>
        </ul>
        <AuthArt />
      </aside>
      <main className="auth-main" id="main">
        <div className="auth-card">
          <div className="stack" style={{ gap: 'var(--s2)' }}>
            <h1>{title}</h1>
            {intro && <p className="muted">{intro}</p>}
          </div>
          {children}
        </div>
      </main>
    </div>
  )
}

/** Only same-app paths: rejects '//host' and '/\host' forms. */
function safeNext(raw: string | null): string {
  return raw && raw.startsWith('/') && !raw.startsWith('//') && !raw.includes(String.fromCharCode(92)) ? raw : '/'
}

const TIMEZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'

export function LoginPage() {
  const { user } = useSession()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const f = useForm({ email: '', password: '' })
  const next = safeNext(params.get('next'))
  if (user) return <Navigate to={next} replace />
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    f.submit(async () => {
      await api.warmup()
      await api.post('/api/auth/login', f.values)
      await qc.invalidateQueries()
      navigate(next, { replace: true })
    })
  }
  return (
    <AuthLayout title="Sign in" intro="Welcome back.">
      <form className="form-grid" onSubmit={onSubmit} noValidate>
        {f.formError && <Alert tone="danger">{f.formError}</Alert>}
        <TextField label="Email address" type="email" autoComplete="email" required {...f.bind('email')} />
        <TextField label="Password" type="password" autoComplete="current-password" required {...f.bind('password')} />
        <Button type="submit" size="lg" block loading={f.busy}>Sign in</Button>
        <div className="spread small">
          <Link to="/forgot-password">Forgotten your password?</Link>
          <Link to={`/register${params.get('next') ? `?next=${encodeURIComponent(next)}` : ''}`}>Create an account</Link>
        </div>
      </form>
    </AuthLayout>
  )
}

export function RegisterPage() {
  const { user } = useSession()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const f = useForm({ full_name: '', email: '', password: '', confirm_password: '' })
  const next = safeNext(params.get('next'))
  if (user) return <Navigate to={next} replace />
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const mismatch = confirmError(f.values.password, f.values.confirm_password)
    if (mismatch) { f.setErrors({ confirm_password: mismatch }); return }
    f.submit(async () => {
      await api.warmup()
      const { confirm_password: _confirm, ...body } = f.values
      await api.post('/api/auth/register', { ...body, timezone: TIMEZONE })
      await qc.invalidateQueries()
      navigate(next, { replace: true })
    })
  }
  return (
    <AuthLayout title="Create your account" intro="Everyone has their own account: the person being cared for, family members and carers.">
      <form className="form-grid" onSubmit={onSubmit} noValidate>
        {f.formError && <Alert tone="danger">{f.formError}</Alert>}
        <TextField label="Your full name" autoComplete="name" required {...f.bind('full_name')} />
        <TextField label="Email address" type="email" autoComplete="email" required hint="We'll send a link to confirm it." {...f.bind('email')} />
        <TextField label="Password" type="password" autoComplete="new-password" required minLength={10}
          hint="At least 10 characters. A short phrase is easy to remember." {...f.bind('password')} />
        <TextField label="Confirm password" type="password" autoComplete="new-password" required {...f.bind('confirm_password')} />
        <Button type="submit" size="lg" block loading={f.busy}>Create account</Button>
        <p className="small">Already have an account? <Link to="/login">Sign in</Link></p>
      </form>
    </AuthLayout>
  )
}

export function ForgotPasswordPage() {
  const [sent, setSent] = useState(false)
  const f = useForm({ email: '' })
  return (
    <AuthLayout title="Reset your password" intro="Enter your email and we'll send a link to choose a new password.">
      {sent ? (
        <Alert tone="ok" title="Check your email">If an account exists for that address, a reset link is on its way. It works for one hour.</Alert>
      ) : (
        <form className="form-grid" noValidate onSubmit={e => { e.preventDefault(); f.submit(async () => { await api.warmup(); await api.post('/api/auth/forgot-password', f.values); setSent(true) }) }}>
          {f.formError && <Alert tone="danger">{f.formError}</Alert>}
          <TextField label="Email address" type="email" autoComplete="email" required {...f.bind('email')} />
          <Button type="submit" size="lg" block loading={f.busy}>Send reset link</Button>
        </form>
      )}
      <Link to="/login" className="small">Back to sign in</Link>
    </AuthLayout>
  )
}

export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const f = useForm({ password: '', confirm_password: '' })
  return (
    <AuthLayout title="Choose a new password" intro="Other devices will be signed out.">
      <form className="form-grid" noValidate onSubmit={e => {
        e.preventDefault()
        const mismatch = confirmError(f.values.password, f.values.confirm_password)
        if (mismatch) { f.setErrors({ confirm_password: mismatch }); return }
        f.submit(async () => {
          await api.warmup()
          await api.post('/api/auth/reset-password', { token: params.get('token') ?? '', password: f.values.password })
          navigate('/login', { replace: true })
        })
      }}>
        {f.formError && <Alert tone="danger">{f.formError}</Alert>}
        <TextField label="New password" type="password" autoComplete="new-password" required hint="At least 10 characters." {...f.bind('password')} />
        <TextField label="Confirm new password" type="password" autoComplete="new-password" required {...f.bind('confirm_password')} />
        <Button type="submit" size="lg" block loading={f.busy}>Save new password</Button>
      </form>
    </AuthLayout>
  )
}

export function VerifyEmailPage() {
  const [params] = useSearchParams()
  const qc = useQueryClient()
  const [state, setState] = useState<'working' | 'done' | 'failed'>('working')
  const [message, setMessage] = useState('')
  useEffect(() => {
    let live = true
    api.warmup()
      .then(() => api.post<User>('/api/auth/verify-email', { token: params.get('token') ?? '' }))
      .then(() => { if (live) { setState('done'); qc.invalidateQueries({ queryKey: ['session'] }) } })
      .catch(err => { if (live) { setState('failed'); setMessage(err.message) } })
    return () => { live = false }
  }, [params, qc])
  return (
    <AuthLayout title="Confirm your email">
      {state === 'working' && <p>Confirming…</p>}
      {state === 'done' && <Alert tone="ok" title="Email confirmed">You'll now receive reminders and care updates by email.</Alert>}
      {state === 'failed' && <Alert tone="danger" title="That link didn't work">{message}</Alert>}
      <Link to="/">Continue to ElderCare</Link>
    </AuthLayout>
  )
}
