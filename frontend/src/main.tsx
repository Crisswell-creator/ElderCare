import { StrictMode, lazy } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { ApiError } from './api'
import { RequireAuth, SessionProvider, usePatient } from './session'
import { Shell } from './Shell'
import { ToastProvider, Skeleton } from './ui'
import { ForgotPasswordPage, LoginPage, RegisterPage, ResetPasswordPage, VerifyEmailPage } from './pages/Auth'
import { AccountPage, HomePage, JoinPage, NewProfilePage, NotificationsPage } from './pages/Home'
import { TodayPage } from './pages/Today'
import { OverviewPage } from './pages/Overview'
import './styles.css'

// Everyday screens load with the app; the rest are fetched on first visit.
const MedicationDetailPage = lazy(() => import('./pages/Medications').then(m => ({ default: m.MedicationDetailPage })))
const MedicationFormPage = lazy(() => import('./pages/Medications').then(m => ({ default: m.MedicationFormPage })))
const MedicationsPage = lazy(() => import('./pages/Medications').then(m => ({ default: m.MedicationsPage })))
const AppointmentsPage = lazy(() => import('./pages/Appointments').then(m => ({ default: m.AppointmentsPage })))
const DocumentsPage = lazy(() => import('./pages/Health').then(m => ({ default: m.DocumentsPage })))
const HealthPage = lazy(() => import('./pages/Health').then(m => ({ default: m.HealthPage })))
const CareTeamPage = lazy(() => import('./pages/CareTeam').then(m => ({ default: m.CareTeamPage })))
const ActivityPage = lazy(() => import('./pages/Insights').then(m => ({ default: m.ActivityPage })))
const InsightsPage = lazy(() => import('./pages/Insights').then(m => ({ default: m.InsightsPage })))
const NotesPage = lazy(() => import('./pages/Coordination').then(m => ({ default: m.NotesPage })))
const TasksPage = lazy(() => import('./pages/Coordination').then(m => ({ default: m.TasksPage })))
const AssistantPage = lazy(() => import('./pages/Assistant').then(m => ({ default: m.AssistantPage })))
const EmergencyPage = lazy(() => import('./pages/Emergency').then(m => ({ default: m.EmergencyPage })))
const ReportsPage = lazy(() => import('./pages/Reports').then(m => ({ default: m.ReportsPage })))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      refetchOnWindowFocus: true,
    },
  },
})

/** Role-aware landing for /p/:pid. Unknown or revoked profiles fall back home. */
function PatientIndex() {
  const { pid } = useParams()
  const { overview, query, isElder } = usePatient()
  if (query.error) return <Navigate to="/" replace />
  if (!overview) return <div className="page"><Skeleton /></div>
  return <Navigate to={`/p/${pid}/${isElder ? 'today' : 'overview'}`} replace />
}

function PatientGuard({ children }: { children: React.ReactNode }) {
  const { query } = usePatient()
  if (query.error) {
    return (
      <div className="page">
        <h1>Not available</h1>
        <p className="muted" style={{ marginTop: 8 }}>This profile doesn't exist or you no longer have access to it.</p>
        <a href="/" className="btn btn-primary" style={{ marginTop: 16 }}>Go home</a>
      </div>
    )
  }
  return <>{children}</>
}

function NotFound() {
  return <div className="page"><h1>Page not found</h1><a href="/" className="btn btn-primary" style={{ marginTop: 16 }}>Go home</a></div>
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SessionProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/reset-password" element={<ResetPasswordPage />} />
              <Route path="/verify-email" element={<VerifyEmailPage />} />
              <Route element={<RequireAuth><Shell /></RequireAuth>}>
                <Route path="/" element={<HomePage />} />
                <Route path="/new-profile" element={<NewProfilePage />} />
                <Route path="/join" element={<JoinPage />} />
                <Route path="/account" element={<AccountPage />} />
                <Route path="/notifications" element={<NotificationsPage />} />
                <Route path="/p/:pid" element={<PatientIndex />} />
                <Route path="/p/:pid/today" element={<PatientGuard><TodayPage /></PatientGuard>} />
                <Route path="/p/:pid/overview" element={<PatientGuard><OverviewPage /></PatientGuard>} />
                <Route path="/p/:pid/medications" element={<PatientGuard><MedicationsPage /></PatientGuard>} />
                <Route path="/p/:pid/medications/new" element={<PatientGuard><MedicationFormPage /></PatientGuard>} />
                <Route path="/p/:pid/medications/:mid" element={<PatientGuard><MedicationDetailPage /></PatientGuard>} />
                <Route path="/p/:pid/medications/:mid/edit" element={<PatientGuard><MedicationFormPage /></PatientGuard>} />
                <Route path="/p/:pid/appointments" element={<PatientGuard><AppointmentsPage /></PatientGuard>} />
                <Route path="/p/:pid/health" element={<PatientGuard><HealthPage /></PatientGuard>} />
                <Route path="/p/:pid/documents" element={<PatientGuard><DocumentsPage /></PatientGuard>} />
                <Route path="/p/:pid/care-team" element={<PatientGuard><CareTeamPage /></PatientGuard>} />
                <Route path="/p/:pid/activity" element={<PatientGuard><ActivityPage /></PatientGuard>} />
                <Route path="/p/:pid/insights" element={<PatientGuard><InsightsPage /></PatientGuard>} />
                <Route path="/p/:pid/tasks" element={<PatientGuard><TasksPage /></PatientGuard>} />
                <Route path="/p/:pid/notes" element={<PatientGuard><NotesPage /></PatientGuard>} />
                <Route path="/p/:pid/assistant" element={<PatientGuard><AssistantPage /></PatientGuard>} />
                <Route path="/p/:pid/emergency" element={<PatientGuard><EmergencyPage /></PatientGuard>} />
                <Route path="/p/:pid/reports" element={<PatientGuard><ReportsPage /></PatientGuard>} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </SessionProvider>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
)
