// Decorative line illustrations drawn for ElderCare. They sit faintly behind page content,
// are hidden from assistive technology, and never carry information.
import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'

const S = { fill: 'none', stroke: 'currentColor', strokeWidth: 3, strokeLinecap: 'round', strokeLinejoin: 'round' } as const

function DoctorPatient() {
  return (
    <svg viewBox="0 0 520 420" {...S}>
      {/* doctor */}
      <circle cx="150" cy="92" r="38" />
      <path d="M128 84c8-14 34-16 46 0" />
      <path d="M92 300V196c0-34 26-58 58-58s58 24 58 58v104" />
      <path d="M150 138v162M126 140l24 40 24-40" />
      <path d="M118 196c0 34 10 52 26 56" />
      <circle cx="146" cy="258" r="9" />
      <path d="M182 190c0 26-4 40-12 46" />
      <rect x="170" y="200" width="26" height="34" rx="4" />
      <path d="M176 210h14M176 220h10" />
      <path d="M92 300h116M110 300v70M190 300v70" />
      {/* patient, seated */}
      <circle cx="380" cy="132" r="34" />
      <path d="M360 120c6 10 30 12 40 0" />
      <path d="M346 180c-12 20-16 56-14 92h96c2-36-2-72-14-92-10-16-58-16-68 0z" />
      <path d="M332 272h112v24H332z" />
      <path d="M344 296v74M432 296v74" />
      <path d="M346 210c-18 18-30 38-34 56M414 210c16 14 26 30 28 48" />
      {/* care heart between them */}
      <path d="M262 168c-10-14-34-8-30 10 3 12 30 30 30 30s27-18 30-30c4-18-20-24-30-10z" />
      <path d="M40 370h440" />
    </svg>
  )
}

function Emergency() {
  return (
    <svg viewBox="0 0 560 420" {...S}>
      {/* ambulance */}
      <path d="M40 300V170h220v130M260 200h90l50 50v50H260" />
      <path d="M280 210h56l34 34h-90z" />
      <circle cx="110" cy="310" r="28" /><circle cx="110" cy="310" r="10" />
      <circle cx="330" cy="310" r="28" /><circle cx="330" cy="310" r="10" />
      <path d="M40 300h42M138 300h164M358 300h42" />
      <path d="M134 210v60M104 240h60" strokeWidth="5" />
      <path d="M150 170v-22h40v22M160 148l10-16 10 16" />
      <path d="M200 132c10-12 24-12 34 0M188 118c18-22 46-22 64 0" />
      {/* phone */}
      <rect x="430" y="90" width="90" height="170" rx="16" />
      <path d="M462 106h26M455 240h40" />
      <path d="M454 150c6 26 22 44 46 54l10-14c4-6 12-6 16-2l10 8c4 4 4 10 0 14-18 18-70-12-90-48-6-12-2-26 8-30l12-6c6-2 12 2 12 8l-2 14c0 4-6 8-10 8z" transform="translate(-8 -14) scale(.9)" />
      <path d="M20 360h520" />
    </svg>
  )
}

function Medicines() {
  return (
    <svg viewBox="0 0 520 420" {...S}>
      <rect x="70" y="140" width="130" height="200" rx="14" />
      <rect x="60" y="100" width="150" height="44" rx="8" />
      <path d="M70 200h130M70 280h130M100 230h70M100 250h50" />
      <rect x="260" y="190" width="150" height="56" rx="28" transform="rotate(-30 335 218)" />
      <path d="M335 190v56" transform="rotate(-30 335 218)" />
      <circle cx="420" cy="320" r="34" /><path d="M396 296l48 48" />
      <circle cx="320" cy="340" r="18" />
      <path d="M440 120l10 20 22 4-16 15 4 22-20-10-20 10 4-22-16-15 22-4z" />
      <path d="M30 380h460" />
    </svg>
  )
}

function Appointments() {
  return (
    <svg viewBox="0 0 520 420" {...S}>
      <rect x="60" y="90" width="250" height="230" rx="14" />
      <path d="M60 140h250M120 70v40M250 70v40" />
      {[0, 1, 2, 3].map(r => [0, 1, 2, 3, 4].map(c => <rect key={`${r}${c}`} x={84 + c * 44} y={160 + r * 38} width="26" height="22" rx="4" />))}
      <path d="M224 238l8 8 16-18" strokeWidth="4" />
      {/* stethoscope */}
      <path d="M370 90v80c0 40 30 70 60 70s60-30 60-70V90" />
      <path d="M360 90h20M480 90h20" />
      <path d="M430 240v50c0 40-30 60-70 60s-50-30-50-30" />
      <circle cx="300" cy="316" r="20" /><circle cx="300" cy="316" r="7" />
      <path d="M30 380h460" />
    </svg>
  )
}

const ART: Record<string, () => ReactNode> = {
  emergency: Emergency, medications: Medicines, appointments: Appointments,
}

/** Picks an illustration for the current section and draws it faintly in a corner. */
export function PageArt() {
  const { pathname } = useLocation()
  const section = pathname.split('/')[3] ?? ''
  const Art = ART[section] ?? DoctorPatient
  return <div className={`page-art page-art-${section || 'home'}`} aria-hidden="true"><Art /></div>
}

export function AuthArt() {
  return <div className="auth-art" aria-hidden="true"><DoctorPatient /></div>
}
