import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDialog, DoseBadge, TextField } from './ui'
import { confirmError, doseView, fmtQty } from './lib'

describe('doseView', () => {
  const at = new Date('2026-03-10T08:00:00Z').getTime()
  const iso = '2026-03-10T08:00:00Z'
  it('derives upcoming, due and overdue only for scheduled doses', () => {
    expect(doseView('scheduled', iso, at - 60 * 60000)).toBe('upcoming')
    expect(doseView('scheduled', iso, at + 10 * 60000)).toBe('due')
    expect(doseView('scheduled', iso, at + 45 * 60000)).toBe('overdue')
  })
  it('never overrides a recorded status', () => {
    expect(doseView('taken', iso, at + 999 * 60000)).toBe('taken')
    expect(doseView('unconfirmed', iso, at)).toBe('unconfirmed')
  })
  it('labels unconfirmed doses without calling them missed', () => {
    render(<DoseBadge view="unconfirmed" />)
    expect(screen.getByText('Not confirmed')).toBeInTheDocument()
    expect(screen.queryByText(/missed/i)).not.toBeInTheDocument()
  })
})

describe('TextField', () => {
  it('associates label, hint and error for screen readers', () => {
    render(<TextField label="Email address" hint="We'll confirm it." error="Already registered" />)
    const input = screen.getByLabelText('Email address')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAccessibleDescription("We'll confirm it. Already registered")
    expect(screen.getByRole('alert')).toHaveTextContent('Already registered')
  })
  it('is not marked invalid without an error', () => {
    render(<TextField label="Name" />)
    expect(screen.getByLabelText('Name')).not.toHaveAttribute('aria-invalid')
  })
})

describe('ConfirmDialog', () => {
  it('asks before a destructive action and calls back only on confirm', async () => {
    HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) { this.open = true })
    HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) { this.open = false })
    const onConfirm = vi.fn()
    const onClose = vi.fn()
    render(<ConfirmDialog open title="Remove Metformin?" body="History is kept." confirmLabel="Remove medicine" danger onConfirm={onConfirm} onClose={onClose} />)
    await userEvent.click(screen.getByRole('button', { name: 'Keep as is' }))
    expect(onClose).toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Remove medicine' }))
    expect(onConfirm).toHaveBeenCalledOnce()
  })
})

describe('fmtQty', () => {
  it('formats quantities without float noise', () => {
    expect(fmtQty(2)).toBe('2')
    expect(fmtQty(0.5)).toBe('0.5')
    expect(fmtQty(1.25)).toBe('1.25')
  })
})

describe('confirmError', () => {
  it('accepts matching passwords and rejects mismatches or an empty confirmation', () => {
    expect(confirmError('long pass phrase', 'long pass phrase')).toBeNull()
    expect(confirmError('long pass phrase', 'long pass phrasE')).toMatch(/don.t match/)
    expect(confirmError('long pass phrase', '')).toMatch(/again/)
  })
})
