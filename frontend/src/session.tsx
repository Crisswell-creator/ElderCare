import { useEffect, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, useLocation } from 'react-router-dom'
import { api, type User } from './api'
import { SessionCtx, useSession, type SessionValue } from './hooks'
import { Skeleton } from './ui'


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
  // No sign-in hint cookie: this browser has no session, so go to sign-in now rather than
  // waiting for the session check (slow on a cold start). The hint grants no access.
  if (loading && !document.cookie.includes('ec_hint=')) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />
  if (loading) return <div className="page"><Skeleton /></div>
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />
  return <>{children}</>
}
