// Non-component helpers shared by pages: formatting, labels, dose-state logic, hooks and
// the toast context. Kept apart from ui.tsx so that file exports only components.
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { ApiError, type DoseStatus, type Permission, type Role } from './api'

export const ToastCtx = createContext<(text: string, tone?: 'ok' | 'error') => void>(() => {})
export const useToast = () => useContext(ToastCtx)

// ---------- Formatting ----------
export const fmtTime = (hhmm: string) => {
  const [h, m] = hhmm.split(':').map(Number)
  const d = new Date(2000, 0, 1, h, m)
  return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

export const fmtDate = (iso: string, opts: Intl.DateTimeFormatOptions = { weekday: 'short', day: 'numeric', month: 'short' }) =>
  new Date(iso.length === 10 ? `${iso}T12:00:00` : iso).toLocaleDateString([], opts)

export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString([], { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' })

export function fmtRelative(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 60000
  if (diff < 1) return 'just now'
  if (diff < 60) return `${Math.round(diff)} min ago`
  if (diff < 60 * 24) return `${Math.round(diff / 60)} h ago`
  return fmtDateTime(iso)
}

export const fmtQty = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, '').replace(/\.$/, ''))

export const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map(s => s[0]?.toUpperCase()).join('')

export const ROLE_LABEL: Record<Role, string> = { elder: 'Elder', family: 'Family member', caregiver: 'Caregiver' }

export const PERMISSION_LABEL: Record<Permission, string> = {
  view_profile: 'See the health profile',
  edit_profile: 'Edit the health profile',
  view_medications: 'See medicines and doses',
  manage_medications: 'Add and change medicines',
  confirm_doses: 'Record doses and refills',
  view_appointments: 'See appointments',
  manage_appointments: 'Add and change appointments',
  view_documents: 'See documents',
  upload_documents: 'Upload documents',
  view_adherence: 'See adherence reports',
  view_activity: 'See the activity history',
  manage_care_team: 'Manage who has access',
  manage_tasks: 'Create and assign care tasks',
  use_assistant: 'Use the assistant with these records',
}

export const PERMISSION_ORDER = Object.keys(PERMISSION_LABEL) as Permission[]

/** Current time that refreshes on an interval, so time-derived states ("due", "overdue")
 *  stay correct while a screen is left open. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

/** Form state helper: values, server field errors, submit with loading. */
export function useForm<T extends Record<string, unknown>>(initial: T) {
  const [values, setValues] = useState<T>(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState('')
  const [busy, setBusy] = useState(false)
  const set = useCallback(<K extends keyof T>(key: K, value: T[K]) => {
    setValues(v => ({ ...v, [key]: value }))
    setErrors(e => { const n = { ...e }; delete n[key as string]; return n })
  }, [])
  const bind = (key: keyof T & string) => ({
    name: key,
    value: (values[key] ?? '') as string,
    error: errors[key],
    onChange: (e: { target: { value: string } }) => set(key, e.target.value as T[typeof key]),
  })
  async function submit(fn: () => Promise<void>) {
    setBusy(true); setFormError('')
    try { await fn() } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fields)
        setFormError(err.message)
      } else setFormError('Something went wrong. Please try again.')
    } finally { setBusy(false) }
  }
  return { values, setValues, set, bind, errors, setErrors, formError, setFormError, busy, submit }
}

/** Display state of a dose, including the time-derived "due" and "overdue". */
export type DoseView = 'upcoming' | 'due' | 'overdue' | DoseStatus

export function doseView(status: DoseStatus, scheduledAt: string, now = Date.now()): DoseView {
  if (status !== 'scheduled') return status
  const t = new Date(scheduledAt).getTime()
  if (now < t - 30 * 60000) return 'upcoming'
  if (now <= t + 30 * 60000) return 'due'
  return 'overdue'
}

/** Returns a field error when a password and its confirmation differ, else null. */
export function confirmError(password: string, confirm: string): string | null {
  if (!confirm) return 'Type the password again to confirm it'
  return password === confirm ? null : 'Passwords don\u2019t match. Type the same password in both boxes.'
}

export function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Something went wrong. Please try again.'
}
