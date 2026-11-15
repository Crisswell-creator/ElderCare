// Typed API client. Cookies carry the session (HttpOnly); the CSRF token is read from its
// non-HttpOnly cookie and echoed in a header on every state-changing request.

export type Permission =
  | 'view_profile' | 'edit_profile' | 'view_medications' | 'manage_medications'
  | 'confirm_doses' | 'view_appointments' | 'manage_appointments' | 'view_documents'
  | 'upload_documents' | 'view_adherence' | 'view_activity' | 'manage_care_team'
  | 'manage_tasks' | 'use_assistant'

export type Role = 'elder' | 'family' | 'caregiver'
export type DoseStatus = 'scheduled' | 'taken' | 'skipped' | 'missed' | 'unconfirmed' | 'cancelled'

export interface User {
  id: number; email: string; full_name: string; timezone: string
  text_scale: 'standard' | 'large' | 'xlarge'; email_verified: boolean
  preferences: Preferences
}
export interface Preferences { contrast: 'standard' | 'high'; reduce_motion: boolean; simplified_nav: boolean; read_aloud: boolean }
export interface MembershipSummary {
  patient_id: number; patient_name: string; preferred_name: string; role: Role
  relationship_label: string; permissions: Permission[]; is_representative: boolean
}
export interface Dose {
  id: number; medication_id: number; medication_name: string; strength: string
  dose_amount: number; dose_unit: string; instructions: string; scheduled_at: string
  local_date: string; local_time: string; status: DoseStatus; as_needed: boolean
  confirmed_at: string | null; confirmed_by: string | null; confirmation_source: string
  skip_reason: string; snoozed_until: string | null; cancelled_reason: string
}
export interface Medication {
  id: number; name: string; strength: string; form: string; dose_amount: number
  dose_unit: string; instructions: string; schedule_type: 'scheduled' | 'as_needed'
  start_date: string; end_date: string | null; status: 'active' | 'paused' | 'discontinued'
  status_reason: string; prescriber: string; refill_threshold_days: number
  times: { local_time: string; days: number[] }[]; quantity_on_hand: number | null
  daily_use: number; days_remaining: number | null; estimated_run_out: string | null
  low_stock: boolean; archived: boolean
}
export interface InventoryEvent {
  id: number; kind: string; quantity_delta: number; quantity_after: number; note: string
  actor_name: string | null; created_at: string
}
export interface Appointment {
  id: number; doctor_name: string; specialty: string; starts_at: string; local_date: string
  local_time: string; duration_minutes: number; location: string; purpose: string; notes: string
  status: 'scheduled' | 'completed' | 'cancelled'; reminder_offsets: number[]
}
export interface Activity { id: number; action: string; summary: string; actor_name: string | null; actor_user_id: number | null; created_at: string; changes?: Record<string, [unknown, unknown]> | null }
export interface Contact { id: number; name: string; relationship_label: string; phone: string; email: string; is_primary: boolean; priority: number }
export interface Allergy { id: number; substance: string; reaction: string; severity: string }
export interface HistoryEntry { id: number; kind: string; title: string; status: string; occurred_on: string | null; notes: string }
export interface Doctor { id: number; name: string; specialty: string; clinic: string; phone: string; is_primary: boolean }
export interface PatientRecord {
  id: number; full_name: string; preferred_name: string; date_of_birth: string | null
  timezone: string; phone: string; address: string; notes: string
  dose_grace_minutes: number; missed_after_minutes: number; managed_by_representative: boolean
}
export interface Profile {
  patient: PatientRecord; allergies: Allergy[]; history: HistoryEntry[]; contacts: Contact[]
  doctors: Doctor[]; my_role: Role; my_permissions: Permission[]; can_decide_access: boolean
}
export interface Counts {
  scheduled: number; taken: number; skipped: number; missed: number; unconfirmed: number
  pending: number; resolved: number; adherence_pct: number | null
}
export interface Overview {
  patient_id: number; patient_name: string; preferred_name: string; timezone: string
  local_date: string; my_role: Role; my_permissions: Permission[]; is_representative: boolean
  can_decide_access: boolean; today_doses: Dose[] | null
  low_stock: { id: number; name: string; strength: string; quantity_on_hand: number; days_remaining: number; estimated_run_out: string }[] | null
  upcoming_appointments: Appointment[] | null; adherence_7d: Counts | null
  adherence_30d: Counts | null; recent_activity: Activity[] | null; pending_requests: number
  unread_notifications: number
  emergency_contacts: { name: string; relationship_label: string; phone: string; is_primary: boolean }[]
}
export interface CircleSummary {
  patient_id: number; patient_name: string; preferred_name: string; role: Role
  local_date: string; doses_today: Record<string, number> | null; needs_attention: number | null
  next_appointment: Appointment | null; pending_requests: number
}
export interface Member {
  id: number; user_id: number; full_name: string; email: string; role: Role
  relationship_label: string; permissions: Permission[]; is_representative: boolean
  is_me: boolean; joined_at: string; notify_dose_reminders: boolean
  notify_escalations: boolean; notify_appointments: boolean; notify_low_stock: boolean
}
export interface Invitation {
  id: number; purpose: string; intended_role: Role; note: string; created_at: string
  expires_at: string; state: 'active' | 'redeemed' | 'expired' | 'revoked'; code: string | null
}
export interface AccessRequest {
  id: number; patient_id: number; patient_name: string; requester_name: string
  requester_email: string; requester_email_verified: boolean; requested_role: Role; relationship_label: string; message: string
  status: string; created_at: string; decided_at: string | null; suggested_permissions: Permission[]
}
export interface AdherenceReport {
  start: string; end: string; granularity: string; totals: Counts
  series: (Counts & { period: string })[]
  by_medication: (Counts & { medication_id: number; name: string })[]
  by_time_of_day: (Counts & { bucket: string; label: string })[]
  insights: { kind: string; text: string; basis: string }[]; rules: string[]
}
export interface DocumentItem {
  id: number; title: string; category: string; filename: string; content_type: string
  size_bytes: number; uploaded_by: string | null; created_at: string; can_delete: boolean
}
export interface NotificationItem {
  id: number; patient_id: number | null; kind: string; subject: string; body: string
  link_path: string; email_status: string; created_at: string; read: boolean
  severity: 'info' | 'reminder' | 'warning' | 'critical'; last_error: string; attempts: number
}
export interface Question { id: number; text: string; author_name: string | null; created_at: string; resolved: boolean; is_mine: boolean }

export interface Task {
  id: number; title: string; description: string; priority: 'low' | 'normal' | 'high'
  status: 'open' | 'in_progress' | 'done' | 'cancelled'; due_date: string | null; overdue: boolean
  assignee_user_id: number | null; assignee_name: string | null; created_by_name: string | null
  completion_note: string; completed_at: string | null; created_at: string; can_edit: boolean; can_update_status: boolean
}
export interface Note {
  id: number; kind: 'note' | 'care_instruction' | 'appointment_prep' | 'update'; title: string; body: string
  pinned: boolean; appointment_id: number | null; author_name: string | null; created_at: string; updated_at: string; can_edit: boolean
}
export interface HelpStatus { created_at: string | null; recipients: number; email_sent: number; email_pending: number; email_failed: number; in_app_only: number; read: number }
export interface AssistantInfo { provider: string; sources: string[]; disclaimer: string; suggestions: string[] }
export interface AssistantReply { answer: string; provider: string; sources: string[]; safety: 'urgent' | 'clinical' | null; notice: string; disclaimer: string }
export interface Report {
  start: string; end: string
  adherence: { totals: Counts; weekly: (Counts & { period: string })[] } | null
  appointments: { total: number; completed: number; cancelled: number; upcoming: number; past_unrecorded: number } | null
  tasks: { open: number; overdue: number; completed_in_period: number; by_person: { name: string; open?: number; overdue?: number; completed_in_period?: number }[] }
  refills: { medication: string; quantity: number; recorded_at: string; by: string | null }[] | null
  activity_by_person: { name: string; actions: number }[] | null
  notes: string[]
}

export class ApiError extends Error {
  status: number
  code: string
  fields: Record<string, string>
  constructor(status: number, code: string, message: string, fields: Record<string, string> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.fields = fields
  }
}

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|; )ec_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: 'same-origin', headers: {} }
  const headers = init.headers as Record<string, string>
  if (method !== 'GET') headers['X-CSRF-Token'] = csrfToken()
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    throw new ApiError(0, 'network', 'ElderCare could not be reached. Check your connection and try again.')
  }
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const err = data?.error ?? {}
    throw new ApiError(res.status, err.code ?? 'error', err.message ?? 'Something went wrong. Please try again.', err.fields ?? {})
  }
  return data as T
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T>(url: string, body: unknown) => request<T>('PUT', url, body),
  patch: <T>(url: string, body: unknown) => request<T>('PATCH', url, body),
  del: (url: string) => request<void>('DELETE', url),
  /** Ensures the CSRF cookie exists before the first state-changing call. */
  warmup: () => fetch('/api/auth/session', { credentials: 'same-origin' }),
}

export const p = (pid: number | string, path = '') => `/api/patients/${pid}${path}`
