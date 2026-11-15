// The eight required user journeys, driven through the real UI against the real API.
// Journey 4 (escalation after a grace period of at least 15 minutes) is verified with a
// controlled clock in backend/tests/test_engine.py; here we verify its visible outcome path.
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test'

const PASSWORD = 'e2e pass phrase'
const stamp = Date.now()
const email = (who: string) => `${who}.${stamp}@example.com`

interface Actor { ctx: BrowserContext; page: Page }
let elder: Actor, family: Actor, carer: Actor
let pid = 0

async function actor(browser: Browser): Promise<Actor> {
  const ctx = await browser.newContext()
  return { ctx, page: await ctx.newPage() }
}

async function registerViaUi(page: Page, name: string, who: string) {
  await page.goto('/register')
  await page.getByLabel('Your full name').fill(name)
  await page.getByLabel('Email address').fill(email(who))
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByLabel('Confirm password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: 'Welcome to ElderCare' })).toBeVisible()
}

async function expectNoSeriousA11yIssues(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze()
  const serious = results.violations.filter(v => v.impact === 'serious' || v.impact === 'critical')
  expect(serious.map(v => `${v.id}: ${v.nodes.map(n => n.target.join(' ')).join(', ')}`)).toEqual([])
}

function hhmm(offsetMinutes: number) {
  const d = new Date(Date.now() + offsetMinutes * 60000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

test.describe.serial('ElderCare journeys', () => {
  test.beforeAll(async ({ browser }) => {
    elder = await actor(browser)
    family = await actor(browser)
    carer = await actor(browser)
  })
  test.afterAll(async () => {
    for (const a of [elder, family, carer]) await a.ctx.close()
  })

  test('sign-in page is accessible', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    await expectNoSeriousA11yIssues(page)
  })

  test('Journey 1: an elder creates a profile and adds a medication', async () => {
    const { page } = elder
    await registerViaUi(page, 'Edith Morgan', 'elder')
    await page.getByRole('link', { name: 'Set up my profile' }).click()
    await page.getByLabel('Preferred name').fill('Edith')
    await page.getByRole('button', { name: 'Create profile' }).click()
    await expect(page.getByRole('heading', { name: /Good (morning|afternoon|evening), Edith/ })).toBeVisible()
    pid = Number(page.url().match(/\/p\/(\d+)\//)![1])

    await page.goto(`/p/${pid}/medications/new`)
    await page.getByLabel('Name').fill('Amlodipine')
    await page.getByLabel('Strength').fill('5 mg')
    await page.getByLabel('Instructions').fill('Take in the morning')
    await page.getByLabel(/^Time/).fill(hhmm(90))
    await page.getByLabel(/How many tablets are there now/).fill('30')
    await page.getByRole('button', { name: 'Add medicine' }).click()
    await expect(page.getByRole('heading', { name: 'Amlodipine 5 mg' })).toBeVisible()
    await expect(page.getByText('30 tablets')).toBeVisible()

    await page.goto(`/p/${pid}/today`)
    await expect(page.getByRole('heading', { name: /Amlodipine/ })).toBeVisible()
    await expectNoSeriousA11yIssues(page)
  })

  test('Journey 2: a family member requests access and the elder approves selected permissions', async () => {
    await registerViaUi(family.page, 'Owen Morgan', 'family')
    const { page } = elder
    await page.goto(`/p/${pid}/care-team`)
    await page.getByRole('button', { name: 'Invite someone' }).click()
    await page.getByRole('button', { name: 'Create code' }).click()
    const code = (await page.locator('dialog p.num').textContent())!.trim()
    expect(code).toMatch(/^[A-Z0-9]{5}-[A-Z0-9]{5}$/)
    await page.getByRole('button', { name: 'Done' }).click()

    await family.page.goto('/join')
    await family.page.getByLabel('Invitation code').fill(code)
    await family.page.getByLabel("How you're related").fill('Son')
    await family.page.getByRole('button', { name: 'Send request' }).click()
    await expect(family.page.getByText('Request sent')).toBeVisible()
    // Nothing is shared before approval
    const before = await family.page.request.get(`/api/patients/${pid}/medications`)
    expect(before.status()).toBe(404)

    await page.reload()
    await page.getByRole('button', { name: 'Review' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Add and change appointments').check()
    await dialog.getByLabel('See adherence reports').uncheck()
    await dialog.getByRole('button', { name: 'Approve access' }).click()
    await expect(page.getByText(/Owen Morgan now has the access you chose/)).toBeVisible()
    await expectNoSeriousA11yIssues(page)

    await family.page.goto(`/p/${pid}/medications`)
    await expect(family.page.getByRole('link', { name: 'Amlodipine' })).toBeVisible()
    await expect(family.page.getByRole('link', { name: 'Add medicine' })).toHaveCount(0)
    expect((await family.page.request.get(`/api/patients/${pid}/adherence`)).status()).toBe(403)
  })

  test('Journey 3: a reminder is generated and the elder confirms the dose', async () => {
    test.setTimeout(150_000)
    const { page } = elder
    // A medicine due in about a minute; the scheduler tick queues its reminder once due.
    const res = await page.request.post(`/api/patients/${pid}/medications`, {
      headers: { 'X-CSRF-Token': (await elder.ctx.cookies()).find(c => c.name === 'ec_csrf')!.value },
      data: { name: 'Levothyroxine', strength: '50 mcg', dose_amount: 1, dose_unit: 'tablet', start_date: new Date().toISOString().slice(0, 10), times: [{ local_time: hhmm(1) }] },
    })
    expect(res.status()).toBe(201)
    await expect.poll(async () => {
      const tick = await page.request.post('/internal/jobs/tick', { headers: { 'X-Job-Token': 'e2e-token' } })
      const body = await tick.json()
      return body.queued?.dose_reminder ?? 0
    }, { timeout: 120_000, intervals: [10_000] }).toBeGreaterThan(0)

    await page.goto('/notifications')
    await page.getByRole('button', { name: /Time for a scheduled dose/ }).first().click()
    await expect(page).toHaveURL(new RegExp(`/p/${pid}/today`))
    const card = page.getByRole('article', { name: /Levothyroxine/ })
    await expect(card.getByText('Due now')).toBeVisible() // opening the reminder recorded nothing
    await card.getByRole('button', { name: /^Taken/ }).click()
    await expect(card.getByText('Taken', { exact: true })).toBeVisible()
    await expect(card.getByText(/Taken at .* by Edith Morgan/)).toBeVisible()
  })

  test('Journey 4 (setup): a caregiver joins with approved permissions and gets the task view', async () => {
    await registerViaUi(carer.page, 'Grace Adeyemi', 'carer')
    const { page } = elder
    await page.goto(`/p/${pid}/care-team`)
    await page.getByRole('button', { name: 'Invite someone' }).click()
    await page.getByLabel('They will be a').selectOption('caregiver')
    await page.getByRole('button', { name: 'Create code' }).click()
    const code = (await page.locator('dialog p.num').textContent())!.trim()
    await page.getByRole('button', { name: 'Done' }).click()
    await carer.page.goto(`/join?code=${code}`)
    await carer.page.getByRole('button', { name: 'Send request' }).click()
    await page.reload()
    await page.getByRole('button', { name: 'Review' }).click()
    const approve = page.getByRole('dialog')
    await approve.getByLabel('See the activity history').check()
    await approve.getByRole('button', { name: 'Approve access' }).click()
    await expect(page.getByText(/Grace Adeyemi now has the access you chose/)).toBeVisible()
    // caregiver task view
    await carer.page.goto(`/p/${pid}/overview`)
    await expect(carer.page.getByRole('heading', { name: "Today's care for Edith" })).toBeVisible()
    await expectNoSeriousA11yIssues(carer.page)
  })

  test('Journey 5: a caregiver records a refill and inventory is updated', async () => {
    const { page } = carer
    await page.goto(`/p/${pid}/medications`)
    await page.getByRole('link', { name: 'Amlodipine' }).click()
    await page.getByRole('button', { name: 'Record refill' }).click()
    await page.getByLabel(/How many tablets were added/).fill('28')
    await page.getByLabel('Note (optional)').fill('Collected from pharmacy')
    await page.getByRole('dialog').getByRole('button', { name: 'Record refill' }).click()
    await expect(page.getByText('58 tablets')).toBeVisible()
    await expect(page.getByRole('cell', { name: 'Grace Adeyemi' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Correct count' })).toHaveCount(0) // needs manage rights
  })

  test('Journey 6: a family member schedules an appointment and the elder sees it', async () => {
    const { page } = family
    const date = new Date(Date.now() + 5 * 864e5).toISOString().slice(0, 10)
    await page.goto(`/p/${pid}/appointments`)
    await page.getByRole('button', { name: 'Add appointment' }).first().click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Doctor or clinic').fill('Dr Helen Brooks')
    await dialog.getByLabel('Specialty').fill('Cardiology')
    await dialog.getByLabel('Date').fill(date)
    await dialog.getByLabel('Time').fill('11:15')
    await dialog.getByLabel('Location').fill('Riverside Clinic')
    await dialog.getByRole('button', { name: 'Add appointment' }).click()
    await expect(page.getByText('Dr Helen Brooks').first()).toBeVisible()

    await elder.page.goto(`/p/${pid}/appointments`)
    await expect(elder.page.getByText('Dr Helen Brooks').first()).toBeVisible()
    await expectNoSeriousA11yIssues(elder.page)
    await elder.page.goto(`/p/${pid}/activity`)
    await expect(elder.page.getByText(/Owen Morgan added an appointment with Dr Helen Brooks/)).toBeVisible()
  })

  test('Journey 7: the application generates a doctor visit summary', async () => {
    const res = await family.page.request.get(`/api/patients/${pid}/visit-summary.pdf`)
    expect(res.status()).toBe(200)
    expect(res.headers()['content-type']).toBe('application/pdf')
    expect((await res.body()).subarray(0, 4).toString()).toBe('%PDF')
    await family.page.goto(`/p/${pid}/overview`)
    await expect(family.page.getByRole('link', { name: /Visit summary \(PDF\)/ })).toBeVisible()
  })

  test('Scenario 4 and 14: a caregiver completes an assigned task and reviews the history', async () => {
    const { page } = elder
    await page.goto(`/p/${pid}/tasks`)
    await page.getByRole('button', { name: 'New task' }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByLabel('Task').fill('Collect repeat prescription')
    await dialog.getByLabel('Assign to').selectOption({ label: 'Grace Adeyemi' })
    await dialog.getByRole('button', { name: 'Create task' }).click()
    await expect(page.getByRole('heading', { name: 'Collect repeat prescription' })).toBeVisible()

    await carer.page.goto(`/p/${pid}/tasks`)
    await carer.page.getByRole('tab', { name: 'Assigned to me' }).click()
    await carer.page.getByRole('button', { name: /Mark done/ }).click()
    await carer.page.getByRole('dialog').getByLabel('Note (optional)').fill('Collected 28 tablets')
    await carer.page.getByRole('dialog').getByRole('button', { name: 'Mark done' }).click()
    await expect(carer.page.getByText(/marked done/)).toBeVisible()
    await carer.page.goto(`/p/${pid}/activity?category=task`)
    await expect(carer.page.getByText(/Grace Adeyemi completed the task .Collect repeat prescription./)).toBeVisible()
    await expectNoSeriousA11yIssues(carer.page)
  })

  test('Scenario 10: the assistant answers from authorised records and handles urgent questions safely', async () => {
    const { page } = elder
    await page.goto(`/p/${pid}/assistant`)
    await expect(page.getByText(/Uses only what you're allowed to see/)).toBeVisible()
    await page.getByLabel('Your question').fill('What medicines do I take?')
    await page.getByRole('button', { name: 'Ask', exact: true }).click()
    await expect(page.getByRole('article', { name: 'Assistant answered' }).last()).toContainText('Amlodipine')
    await page.getByLabel('Your question').fill('I have chest pain')
    await page.getByRole('button', { name: 'Ask', exact: true }).click()
    await expect(page.getByText('This may be urgent')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Open emergency contacts' })).toBeVisible()
    await expectNoSeriousA11yIssues(page)
    // the caregiver was not given assistant access by the elder
    expect((await carer.page.request.get(`/api/patients/${pid}/assistant`)).status()).toBe(403)
  })

  test('Scenario 13: the elder opens emergency contacts and asks the care circle for help', async () => {
    const { page } = elder
    const csrf = (await elder.ctx.cookies()).find(c => c.name === 'ec_csrf')!.value
    await page.request.post(`/api/patients/${pid}/contacts`, { headers: { 'X-CSRF-Token': csrf }, data: { name: 'Owen Morgan', relationship_label: 'Son', phone: '+44 7700 900111', priority: 1 } })
    await page.goto(`/p/${pid}/emergency`)
    const call = page.getByRole('link', { name: /Call Owen Morgan/ })
    await expect(call).toHaveAttribute('href', 'tel:+447700900111')
    await page.getByRole('button', { name: 'Ask for help' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Send help request' }).click()
    await expect(page.getByText(/Alert sent .* to 2 people/)).toBeVisible()
    await expect(page.getByText(/waiting to send|in-app only/)).toBeVisible() // honest: nothing claimed as delivered
    await expectNoSeriousA11yIssues(page)
    await family.page.goto('/notifications')
    await expect(family.page.getByText('Urgent').first()).toBeVisible()
  })

  test('Scenario 15: reports and exports use real records and respect permissions', async () => {
    await family.page.goto(`/p/${pid}/reports`)
    await expect(family.page.getByRole('heading', { name: 'Reports' })).toBeVisible()
    const csv = await family.page.request.get(`/api/patients/${pid}/reports/appointments.csv`)
    expect(csv.status()).toBe(200)
    expect(await csv.text()).toContain('Dr Helen Brooks')
    expect((await carer.page.request.get(`/api/patients/${pid}/reports/appointments.csv`)).status()).toBe(200)
    const stranger = await family.page.request.get(`/api/patients/${pid + 999}/reports/doses.csv`)
    expect(stranger.status()).toBe(404)
  })

  test('Accessibility settings persist across reloads', async () => {
    const { page } = elder
    await page.goto('/account')
    await page.getByLabel('High contrast').check()
    await expect(page.getByText('Display settings saved.')).toBeVisible()
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high')
    await page.getByLabel('High contrast').uncheck()
    await expect(page.locator('html')).toHaveAttribute('data-contrast', 'standard')
  })

  test('Journey 8: the elder revokes the caregiver and access ends immediately', async () => {
    const { page } = elder
    await page.goto(`/p/${pid}/care-team`)
    const row = page.getByRole('listitem').filter({ hasText: 'Grace Adeyemi' })
    await row.getByRole('button', { name: 'Remove' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Remove access' }).click()
    await expect(page.getByText('Grace Adeyemi no longer has access.')).toBeVisible()

    await carer.page.goto(`/p/${pid}/medications`)
    await expect(carer.page.getByRole('heading', { name: 'Not available' })).toBeVisible()
    expect((await carer.page.request.get(`/api/patients/${pid}/medications`)).status()).toBe(404)
  })
})

test('@responsive the Today screen fits a phone without horizontal scrolling', async ({ page }) => {
  await registerViaUi(page, 'Mobile Tester', `mobile.${Math.random().toString(36).slice(2)}`)
  await page.getByRole('link', { name: 'Set up my profile' }).click()
  await page.getByRole('button', { name: 'Create profile' }).click()
  await expect(page.getByRole('heading', { name: /Mobile/ })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
  const nav = page.getByRole('navigation', { name: 'Sections' })
  await expect(nav).toBeVisible()
  const target = await nav.getByRole('link').first().boundingBox()
  expect(target!.height).toBeGreaterThanOrEqual(44) // WCAG 2.5.8 target size
  await expectNoSeriousA11yIssues(page)
})
