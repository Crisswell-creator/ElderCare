import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from './api'

afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('sends the CSRF cookie value as a header on writes', async () => {
    document.cookie = 'ec_csrf=abc123'
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"ok":true}', { status: 200 }))
    await api.post('/api/x', { a: 1 })
    const init = fetchMock.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('abc123')
    expect(init.credentials).toBe('same-origin')
  })
  it('turns the error envelope into ApiError with field messages', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { code: 'validation_error', message: 'Check fields', fields: { email: 'Required' } } }), { status: 422 }))
    const err = (await api.post("/api/x").catch((e: unknown) => e)) as ApiError
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.fields).toEqual({ email: 'Required' })
  })
  it('reports network failures in plain language', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
    const err = (await api.get("/api/x").catch((e: unknown) => e)) as ApiError
    expect(err.code).toBe('network')
    expect(err.message).toMatch(/could not be reached/)
  })
})
