// Session and current-patient hooks. Components that provide the session live in session.tsx.
import { createContext, useContext } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api, p, type MembershipSummary, type Overview, type Permission, type User } from './api'

export interface SessionValue { user: User | null; loading: boolean; refresh: () => Promise<unknown>; signOut: () => Promise<void> }
export const SessionCtx = createContext<SessionValue>({ user: null, loading: true, refresh: async () => {}, signOut: async () => {} })
export const useSession = () => useContext(SessionCtx)

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
