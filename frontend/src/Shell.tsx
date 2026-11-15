import { useQuery } from '@tanstack/react-query'
import {
  Activity, Bell, BarChart3, CalendarDays, ClipboardList, FileText, HeartPulse, LayoutDashboard, LineChart,
  ListChecks, LogOut, MessageCircleQuestion, NotebookPen, Phone, Pill, Settings, SunMedium, Users,
} from 'lucide-react'
import { Suspense, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useNavigate, useParams } from 'react-router-dom'
import { api, type Permission } from './api'
import { useMemberships, usePatient, useSession } from './session'
import { initials, Logo, Skeleton } from './ui'
import { PageArt } from './art'

interface NavItem { to: string; label: string; short?: string; icon: ReactNode; perm?: Permission; badge?: number }

function useNav(): { primary: NavItem[]; secondary: NavItem[]; elder: boolean } {
  const { pid, overview, can, isElder } = usePatient()
  const { user } = useSession()
  const simple = !!user?.preferences?.simplified_nav
  if (!overview) return { primary: [], secondary: [], elder: false }
  const base = `/p/${pid}`
  const care: NavItem = { to: `${base}/care-team`, label: isElder ? 'Family & carers' : 'Care team', short: 'People', icon: <Users aria-hidden="true" />, badge: overview.pending_requests }
  if (isElder) {
    // The elder's navigation stays short: the things they do every day come first.
    return {
      elder: true,
      primary: [
        { to: `${base}/today`, label: 'Today', icon: <SunMedium aria-hidden="true" /> },
        { to: `${base}/medications`, label: 'My medicines', short: 'Medicines', icon: <Pill aria-hidden="true" /> },
        { to: `${base}/appointments`, label: 'Appointments', short: 'Visits', icon: <CalendarDays aria-hidden="true" /> },
        { to: `${base}/emergency`, label: 'Emergency help', short: 'Help', icon: <Phone aria-hidden="true" /> },
        care,
      ],
      // Simplified navigation keeps only the five everyday items.
      secondary: simple ? [] : [
        { to: `${base}/assistant`, label: 'Ask a question', icon: <MessageCircleQuestion aria-hidden="true" /> },
        { to: `${base}/health`, label: 'My health', icon: <HeartPulse aria-hidden="true" /> },
        { to: `${base}/notes`, label: 'Notes', icon: <NotebookPen aria-hidden="true" /> },
        { to: `${base}/tasks`, label: 'Tasks', icon: <ListChecks aria-hidden="true" /> },
        { to: `${base}/insights`, label: 'How it’s going', icon: <LineChart aria-hidden="true" /> },
        { to: `${base}/reports`, label: 'Reports', icon: <BarChart3 aria-hidden="true" /> },
        { to: `${base}/documents`, label: 'Documents', icon: <FileText aria-hidden="true" /> },
        { to: `${base}/activity`, label: 'Activity', icon: <Activity aria-hidden="true" /> },
      ],
    }
  }
  const items: NavItem[] = [
    { to: `${base}/overview`, label: 'Overview', icon: <LayoutDashboard aria-hidden="true" /> },
    { to: `${base}/today`, label: 'Today’s doses', short: 'Doses', icon: <ClipboardList aria-hidden="true" />, perm: 'view_medications' },
    { to: `${base}/medications`, label: 'Medicines', icon: <Pill aria-hidden="true" />, perm: 'view_medications' },
    { to: `${base}/appointments`, label: 'Appointments', short: 'Visits', icon: <CalendarDays aria-hidden="true" />, perm: 'view_appointments' },
    { to: `${base}/tasks`, label: 'Tasks', icon: <ListChecks aria-hidden="true" /> },
    { to: `${base}/health`, label: 'Health profile', short: 'Health', icon: <HeartPulse aria-hidden="true" />, perm: 'view_profile' },
  ]
  const more: NavItem[] = [
    { to: `${base}/notes`, label: 'Shared notes', icon: <NotebookPen aria-hidden="true" /> },
    { to: `${base}/assistant`, label: 'Assistant', icon: <MessageCircleQuestion aria-hidden="true" />, perm: 'use_assistant' },
    { to: `${base}/emergency`, label: 'Emergency contacts', icon: <Phone aria-hidden="true" /> },
    { to: `${base}/reports`, label: 'Reports', icon: <BarChart3 aria-hidden="true" /> },
    { to: `${base}/insights`, label: 'Adherence', icon: <LineChart aria-hidden="true" />, perm: 'view_adherence' },
    { to: `${base}/documents`, label: 'Documents', icon: <FileText aria-hidden="true" />, perm: 'view_documents' },
    { to: `${base}/activity`, label: 'Activity', icon: <Activity aria-hidden="true" />, perm: 'view_activity' },
    care,
  ]
  const allowed = (i: NavItem) => !i.perm || can(i.perm)
  return { elder: false, primary: items.filter(allowed), secondary: more.filter(allowed) }
}

function PatientSwitcher() {
  const { pid } = useParams()
  const navigate = useNavigate()
  const { data } = useMemberships()
  if (!data || data.length < 2) return null
  return (
    <div className="switcher">
      <label htmlFor="patient-switch" className="sr-only">Switch person</label>
      <select id="patient-switch" className="select" value={pid ?? ''} onChange={e => navigate(`/p/${e.target.value}`)}>
        {!pid && <option value="">Choose a person</option>}
        {data.map(m => (
          <option key={m.patient_id} value={m.patient_id}>
            {m.role === 'elder' ? `${m.patient_name} (me)` : m.patient_name}
          </option>
        ))}
      </select>
    </div>
  )
}

function NotificationBell() {
  const { data } = useQuery({
    queryKey: ['notifications', 'count'],
    queryFn: () => api.get<{ unread: number }>('/api/notifications?limit=1'),
    refetchInterval: 60_000,
  })
  const unread = data?.unread ?? 0
  return (
    <Link to="/notifications" className="icon-btn" aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}>
      <Bell aria-hidden="true" />
      {unread > 0 && <span className="dot" aria-hidden="true">{unread > 9 ? '9+' : unread}</span>}
    </Link>
  )
}

export function Shell() {
  const { user, signOut } = useSession()
  const { pid } = useParams()
  const navigate = useNavigate()
  const { primary, secondary, elder } = useNav()
  const { overview } = usePatient()
  const mobile = primary.slice(0, 5)

  return (
    <div className={`shell${elder ? ' elder' : ''}`}>
      <a href="#main" className="skip-link">Skip to main content</a>
      <aside className="sidebar" aria-label="Main navigation">
        <Link to="/" className="brand"><Logo /> ElderCare</Link>
        {pid && overview && (
          <nav className="nav" aria-label={`Sections for ${overview.patient_name}`}>
            {primary.map(i => <NavLink key={i.to} to={i.to}>{i.icon}{i.label}{!!i.badge && <span className="count">{i.badge}</span>}</NavLink>)}
            {secondary.length > 0 && <div className="nav-group">{elder ? 'More' : 'Records'}</div>}
            {secondary.map(i => <NavLink key={i.to} to={i.to}>{i.icon}{i.label}{!!i.badge && <span className="count">{i.badge}<span className="sr-only"> waiting</span></span>}</NavLink>)}
          </nav>
        )}
        <div className="sidebar-foot nav">
          <NavLink to="/account"><Settings aria-hidden="true" />Account & text size</NavLink>
          <button type="button" className="btn btn-quiet" style={{ justifyContent: 'flex-start' }}
            onClick={async () => { await signOut(); navigate('/login', { replace: true }) }}>
            <LogOut aria-hidden="true" />Sign out
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <Link to="/" className="brand hide-desktop" aria-label="ElderCare home" style={{ padding: 0 }}><Logo size={28} /></Link>
          <PatientSwitcher />
          <div className="grow" />
          <NotificationBell />
          <Link to="/account" className="person" aria-label={`Account: ${user?.full_name}`}>
            <span className="avatar" aria-hidden="true">{initials(user?.full_name ?? '')}</span>
            <span className="hide-mobile" style={{ color: 'var(--ink)', fontWeight: 600 }}>{user?.full_name}</span>
          </Link>
        </header>
        <PageArt />
        <main id="main" tabIndex={-1}>
          <Suspense fallback={<div className="page"><Skeleton lines={6} /></div>}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      {pid && mobile.length > 0 && (
        <nav className="mobile-nav" aria-label="Sections">
          {mobile.map(i => <NavLink key={i.to} to={i.to}>{i.icon}<span>{i.short ?? i.label}</span></NavLink>)}
        </nav>
      )}
    </div>
  )
}
