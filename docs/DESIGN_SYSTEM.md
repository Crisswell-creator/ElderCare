# Design system

ElderCare should read as calm, trustworthy and legible, closer to a well-run clinic than a
consumer app. Boldness is spent in one place, the elder's day timeline. Everything else is quiet.

## Tokens (`frontend/src/styles.css`)

| Role | Value | Use |
|---|---|---|
| Navy 800 | `#102a43` | Headings, structure, the "Next" panel |
| Teal 700 | `#0b5c58` | Primary actions, links, active navigation |
| Ground | `#f3f5f4` | Page background (cool neutral) |
| Surface | `#ffffff` | Panels |
| Line | `#d6ddda` | Rules and borders, used instead of shadows |
| Ink / Muted | `#1d2b36` / `#52616b` | Body text / secondary text (5.9:1 on ground) |
| OK | `#256b42` on `#e6f3ea` | Taken |
| Warn | `#7a4a00` on `#fff2d9` | Not confirmed, refill soon |
| Danger | `#b42318` on `#fdecea` | Missed, destructive actions only |

State colours are reserved for dose and stock states, so colour always carries meaning, and every
state also has a text label.

**Type.** Atkinson Hyperlegible Next, self-hosted, in weights 400, 600 and 700. It was designed by
the Braille Institute to keep similar letterforms distinct for low-vision readers. Body text is
17 px on a major-third scale (17 / 21 / 26 / 33 / 42 px). Times and counts use tabular numerals.
A text-size setting (Standard, Large, Extra large) scales the root size and is saved per account.

**Space and shape.** The spacing grid is 4 px. Radii are 4, 6 and 10 px, so controls are crisp
and panels softer. A single overlay shadow is used, for dialogs only.

**Targets and focus.** Controls are at least 44 px high, and 52 px in elder mode. Focus is a
3 px blue ring with a white gap, visible on every background.

**Motion.** Colour transitions only, plus a spinner. Everything is disabled under
`prefers-reduced-motion`.

## Components (`frontend/src/ui.tsx`)

| Component | Notes |
|---|---|
| Button | Primary, secondary, quiet, danger and danger-solid variants; loading state with `aria-busy` |
| TextField, SelectField, TextArea, Checkbox | Label, hint and error wired through `aria-describedby`; errors announced with `role=alert` |
| Modal, ConfirmDialog | Native `<dialog>` for a focus trap, Escape to close and inert background; every destructive action is confirmed |
| Alert, Badge, DoseBadge | Tone plus text and icon, never colour alone |
| Empty, Skeleton, ErrorState | Every list has loading, empty and error states with a next action |
| Toasts | Polite live region confirming each action in the same words as its button |
| PageHead | Title, breadcrumbs, contextual actions; sets the document title |

## Three experiences

- **Elder.** Five navigation items, large type, a "Next" panel, a day timeline with one-tap Taken
  and Skip, the next appointment, and one-tap calls to emergency contacts. No charts on the
  home screen.
- **Family.** A monitoring dashboard: today's numbers, things that need attention, schedule
  table, recent activity, appointments, 30-day adherence and refill warnings.
- **Caregiver.** A task view, "Today's care for ...", led by "To do now". A multi-person home
  lists people needing attention first.
- **Phones.** All three get a bottom tab bar and single-column layouts. The timeline compresses
  its time gutter but keeps 44 px targets. Verified at 375 px with no horizontal scroll.
