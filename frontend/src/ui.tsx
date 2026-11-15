// Shared components. Each exists once; pages compose them rather than restyling.
import {
  useCallback, useEffect, useId, useRef, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode,
  type SelectHTMLAttributes, type TextareaHTMLAttributes,
} from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, CircleAlert, Info, X } from 'lucide-react'
import { ApiError } from './api'
import { ToastCtx, type DoseView } from './lib'




// ---------- Brand ----------
export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="#102a43" />
      <circle cx="16" cy="16" r="9" fill="none" stroke="#7fd1c7" strokeWidth="3" strokeDasharray="44 13" strokeLinecap="round" transform="rotate(-60 16 16)" />
      <circle cx="16" cy="16" r="3.4" fill="#fff" />
    </svg>
  )
}

// ---------- Buttons ----------
type Variant = 'primary' | 'secondary' | 'quiet' | 'danger' | 'danger-solid'
interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant; size?: 'md' | 'lg'; block?: boolean; loading?: boolean; icon?: ReactNode
}
export function Button({ variant = 'primary', size = 'md', block, loading, icon, children, className = '', disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      className={`btn btn-${variant}${size === 'lg' ? ' btn-lg' : ''}${block ? ' btn-block' : ''} ${className}`}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading ? <span className="spinner" aria-hidden="true" /> : icon}
      {children}
    </button>
  )
}

// ---------- Fields ----------
interface FieldShell { label: string; hint?: string; error?: string; id?: string }
function useFieldIds(id?: string) {
  const auto = useId()
  const base = id ?? auto
  return { id: base, hint: `${base}-hint`, error: `${base}-error` }
}
function FieldFrame({ ids, label, hint, error, children }: { ids: ReturnType<typeof useFieldIds>; label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <div className="field">
      <label htmlFor={ids.id}>{label}</label>
      {hint && <span className="hint" id={ids.hint}>{hint}</span>}
      {children}
      {error && <span className="error" id={ids.error} role="alert"><CircleAlert size={16} aria-hidden="true" />{error}</span>}
    </div>
  )
}
const describedBy = (ids: ReturnType<typeof useFieldIds>, hint?: string, error?: string) =>
  [hint && ids.hint, error && ids.error].filter(Boolean).join(' ') || undefined

export function TextField({ label, hint, error, id, ...rest }: FieldShell & InputHTMLAttributes<HTMLInputElement>) {
  const ids = useFieldIds(id)
  return (
    <FieldFrame ids={ids} label={label} hint={hint} error={error}>
      <input id={ids.id} className="input" aria-invalid={error ? true : undefined} aria-describedby={describedBy(ids, hint, error)} {...rest} />
    </FieldFrame>
  )
}
export function SelectField({ label, hint, error, id, children, ...rest }: FieldShell & SelectHTMLAttributes<HTMLSelectElement>) {
  const ids = useFieldIds(id)
  return (
    <FieldFrame ids={ids} label={label} hint={hint} error={error}>
      <select id={ids.id} className="select" aria-invalid={error ? true : undefined} aria-describedby={describedBy(ids, hint, error)} {...rest}>{children}</select>
    </FieldFrame>
  )
}
export function TextArea({ label, hint, error, id, ...rest }: FieldShell & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ids = useFieldIds(id)
  return (
    <FieldFrame ids={ids} label={label} hint={hint} error={error}>
      <textarea id={ids.id} className="textarea" aria-invalid={error ? true : undefined} aria-describedby={describedBy(ids, hint, error)} {...rest} />
    </FieldFrame>
  )
}
export function Checkbox({ label, description, ...rest }: { label: string; description?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="check">
      <input type="checkbox" {...rest} />
      <span><strong>{label}</strong>{description && <span className="muted small">{description}</span>}</span>
    </label>
  )
}


// ---------- Feedback ----------
const ALERT_ICON = { info: Info, warn: AlertTriangle, danger: CircleAlert, ok: CheckCircle2 }
export function Alert({ tone = 'info', title, children }: { tone?: keyof typeof ALERT_ICON; title?: string; children?: ReactNode }) {
  const Icon = ALERT_ICON[tone]
  return (
    <div className={`alert alert-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      <Icon aria-hidden="true" />
      <div>{title && <strong>{title}</strong>}{children}</div>
    </div>
  )
}

export function Badge({ tone = 'neutral', children }: { tone?: 'ok' | 'warn' | 'danger' | 'neutral' | 'info'; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

const DOSE_BADGE: Record<DoseView, [string, 'ok' | 'warn' | 'danger' | 'neutral' | 'info']> = {
  upcoming: ['Upcoming', 'neutral'], due: ['Due now', 'info'], overdue: ['Not yet recorded', 'warn'],
  scheduled: ['Scheduled', 'neutral'], taken: ['Taken', 'ok'], skipped: ['Skipped', 'neutral'],
  missed: ['Missed', 'danger'], unconfirmed: ['Not confirmed', 'warn'], cancelled: ['Cancelled', 'neutral'],
}
export function DoseBadge({ view }: { view: DoseView }) {
  const [label, tone] = DOSE_BADGE[view]
  return <Badge tone={tone}>{label}</Badge>
}

export function Empty({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return <div className="empty"><h3>{title}</h3>{children && <p className="muted">{children}</p>}{action}</div>
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton" style={{ height: 18, width: `${90 - i * 12}%` }} />)}
    </div>
  )
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof ApiError ? error.message : 'This page could not be loaded.'
  return (
    <Alert tone="danger" title="Couldn't load this">
      <p>{msg}</p>
      {retry && <Button variant="secondary" className="mt" onClick={retry} style={{ marginTop: 8 }}>Try again</Button>}
    </Alert>
  )
}

export function PageHead({ title, intro, actions, crumbs }: { title: string; intro?: ReactNode; actions?: ReactNode; crumbs?: { to: string; label: string }[] }) {
  useEffect(() => { document.title = `${title} | ElderCare` }, [title])
  return (
    <header className="page-head">
      <div>
        {crumbs && (
          <nav aria-label="Breadcrumb" className="crumbs">
            <ol>{crumbs.map(c => <li key={c.to}><Link to={c.to}>{c.label}</Link></li>)}<li aria-current="page">{title}</li></ol>
          </nav>
        )}
        <h1>{title}</h1>
        {intro && <p>{intro}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  )
}

// ---------- Dialog ----------
export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])
  return (
    <dialog ref={ref} className="modal" aria-labelledby={titleId} onClose={onClose} onCancel={onClose}>
      {open && (
        <>
          <div className="modal-head">
            <h2 id={titleId}>{title}</h2>
            <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><X aria-hidden="true" /></button>
          </div>
          <div className="modal-body">{children}</div>
        </>
      )}
    </dialog>
  )
}

export function ConfirmDialog({ open, title, body, confirmLabel, danger, busy, onConfirm, onClose }: {
  open: boolean; title: string; body: ReactNode; confirmLabel: string; danger?: boolean; busy?: boolean
  onConfirm: () => void; onClose: () => void
}) {
  return (
    <Modal open={open} onClose={onClose} title={title}>
      <div className="stack">
        <div>{body}</div>
        <div className="form-actions">
          <Button variant="secondary" onClick={onClose}>Keep as is</Button>
          <Button variant={danger ? 'danger-solid' : 'primary'} loading={busy} onClick={onConfirm}>{confirmLabel}</Button>
        </div>
      </div>
    </Modal>
  )
}

// ---------- Toasts ----------
interface ToastMsg { id: number; text: string; tone: 'ok' | 'error' }
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastMsg[]>([])
  const push = useCallback((text: string, tone: 'ok' | 'error' = 'ok') => {
    const id = Date.now() + Math.random()
    setItems(list => [...list, { id, text, tone }])
    setTimeout(() => setItems(list => list.filter(t => t.id !== id)), 5000)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-region" role="status" aria-live="polite">
        {items.map(t => (
          <div key={t.id} className={`toast ${t.tone === 'error' ? 'error' : ''}`}>
            {t.tone === 'error' ? <CircleAlert aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}


