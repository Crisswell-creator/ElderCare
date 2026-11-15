import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, useLocation, useParams } from 'react-router-dom'
import { api, p, type MembershipSummary, type Overview, type Permission, type User } from './api'
import { Skeleton } from './ui'

interface SessionValue { user: User | null; loading: boolean; refresh: () => Promise<unknown>; signOut: () => Promise<void> }
const SessionCtx = createContext<SessionValue>({ user: null, loading: true, refresh: async () => {}, signOut: async () => {} })
export const useSession = () => useContext(SessionCtx)

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['session'], queryFn: () => api.get<{ user: User | null }>('/api/auth/session'), staleTime: 60_000 })
  const user = q.data?.user ?? null
  // Apply the user's text size to the whole document.
  useEffect(() => {
    const root = document.documentElement
    root.dataset.scale = user?.text_scale ?? localStorage.getItem('ec-scale') ?? 'standard'
    root.dataset.contrast = user?.preferences?.contrast ?? 'standard'
    root.dataset.motion = user?.preferences?.reduce_motion ? 'reduce' : 'full'
  }, [user?.text_scale, user?.preferences?.contrast, user?.preferences?.reduce_motion])
  const value: SessionValue = {
    user, loading: q.isLoading,
    refresh: () => qc.invalidateQueries({ queryKey: ['session'] }),
    signOut: async () => {
      try { await api.post('/api/auth/logout') } catch { /* already signed out on the server */ }
      // Set the session to "signed out" explicitly. Clearing the cache alone leaves mounted
      // observers holding the old user, which bounced the login page straight back in.
      qc.setQueryData(['session'], { user: null })
      qc.removeQueries({ predicate: q => q.queryKey[0] !== 'session' })
    },
  }
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useSession()
  const loc = useLocation()
  if (loading) return <div className="page"><Skeleton /></div>
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />
  return <>{children}</>
}

export function useMemberships() {
  return useQuery({ queryKey: ['memberships'], queryFn: () => api.get<MembershipSummary[]>('/api/auth/memberships') })
}

/** The current care circle (from the :pid route param) with the caller's role/permissions. */
export function usePatient() {
  const { pid } = useParams()
  const id = Number(pid)
  const q = useQuery({ queryKey: ['overview', id], queryFn: () => api.get<Overview>(p(id, '/overview')), enabled: Number.isFinite(id), refetchInterval: 60_000 })
  const perms = new Set<Permission>(q.data?.my_permissions ?? [])
  return {
    pid: id, overview: q.data, query: q,
    can: (perm: Permission) => perms.has(perm),
    isElder: q.data?.my_role === 'elder',
    name: q.data ? (q.data.preferred_name || q.data.patient_name.split(' ')[0]) : '',
  }
}
