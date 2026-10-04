import { chromium } from 'playwright'

/**
 * record_demo_clips.mjs — record the HoldWatch demo clips against the LIVE
 * dashboard.
 *
 * Re-recorded 2026-10-03. The previous clips were rendered before the
 * four-states fix, so they showed the old conflated copy ("PayPal does not
 * disclose the reason in this event") while the narration spoke the corrected
 * wording — a contradiction on camera, and the exact thing a commenter had
 * publicly called out. Anything recorded here now matches what a judge sees.
 *
 * Records against the deployed dashboard rather than a local copy so the frames
 * are what the URL actually serves.
 */

const URL = process.env.URL || 'https://holdwatch-dashboard.onrender.com'
const OUT = '/root/web3alphatester/paypal/video/clips'
const W = 1920, H = 1080

import { mkdirSync } from 'node:fs'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })
const ctx = await browser.newContext({
  viewport: { width: W, height: H },
  deviceScaleFactor: 1,
  recordVideo: { dir: OUT, size: { width: W, height: H } },
})
const page = await ctx.newPage()

const errors = []
page.on('pageerror', (e) => errors.push(e.message))

console.log(`── loading ${URL} ──`)
await page.goto(URL, { waitUntil: 'networkidle', timeout: 120000 })
await page.waitForTimeout(3500)

// The dashboard polls every 5s and replaces the feed wholesale, which detaches
// element handles mid-capture. Pin it for the duration.
await page.evaluate(() => {
  const feed = document.getElementById('feed')
  window.__pin = setInterval(() => {
    if (!window.__snap && feed && feed.children.length) window.__snap = feed.innerHTML
    if (window.__snap && feed.innerHTML !== window.__snap) feed.innerHTML = window.__snap
  }, 100)
})
await page.waitForTimeout(600)

const state = await page.evaluate(() => {
  const t = document.body.innerText
  return {
    cards: document.querySelectorAll('.card').length,
    stats: [...document.querySelectorAll('.stat')].map((s) => s.innerText.replace(/\n/g, ' ')),
    has4200: t.includes('4,200'),
    hasJohnDoe: t.includes('John Doe'),
    // The corrected wording must be on screen.
    correctedCopy: t.includes('sent this event without a reason'),
    oldCopy: t.includes('PayPal does not disclose the reason in this event'),
  }
})
console.log('  state:', JSON.stringify(state))
if (!state.correctedCopy) {
  console.error('  ABORT: the live dashboard is not serving the corrected copy.')
  console.error('  Recording it would re-bake the contradiction this re-record exists to fix.')
  await browser.close()
  process.exit(1)
}
if (state.oldCopy) {
  console.error('  ABORT: old wording still present on screen.')
  await browser.close()
  process.exit(1)
}

// ── clip 1: overview, severity-ordered cards ──────────────────────────────
console.log('── clip 1: overview (6s) ──')
await page.mouse.move(960, 320, { steps: 14 })
await page.waitForTimeout(1500)
await page.mouse.move(1420, 640, { steps: 18 })
await page.waitForTimeout(4500)

// ── clip 2: the $4,200 order card, fields traced ─────────────────────────
console.log('── clip 2: the $4,200 card (7s) ──')
const order = await page.evaluateHandle(() => {
  const cards = [...document.querySelectorAll('.card')]
  return cards.find((c) => c.innerText.includes('4,200')) || cards[0]
})
if (order.asElement()) {
  await order.asElement().scrollIntoViewIfNeeded()
  await page.waitForTimeout(500)
  const box = await order.asElement().boundingBox()
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 10 })
    await page.waitForTimeout(1000)
    // trace the labelled fields: amount → payer → PayPal status
    await page.mouse.move(box.x + 110, box.y + box.height * 0.42, { steps: 18 })
    await page.waitForTimeout(1400)
    await page.mouse.move(box.x + 300, box.y + box.height * 0.42, { steps: 14 })
    await page.waitForTimeout(1400)
    await page.mouse.move(box.x + 520, box.y + box.height * 0.42, { steps: 14 })
    await page.waitForTimeout(3200)
  }
}

// ── clip 3: the cause state, on a hold card ──────────────────────────────
console.log('── clip 3: cause state (6s) ──')
const hold = await page.evaluateHandle(() => {
  const cards = [...document.querySelectorAll('.card')]
  return cards.find((c) => c.innerText.includes('PAYOUTS-ITEM.HELD'))
})
if (hold.asElement()) {
  await hold.asElement().scrollIntoViewIfNeeded()
  await page.waitForTimeout(500)
  const box = await hold.asElement().boundingBox()
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + 90, { steps: 12 })
    await page.waitForTimeout(5200)
  }
}

// ── clip 4: scroll the remaining events ──────────────────────────────────
console.log('── clip 4: scroll through (5s) ──')
await page.mouse.move(960, 540)
for (let i = 0; i < 9; i++) {
  await page.mouse.wheel(0, 230)
  await page.waitForTimeout(330)
}
await page.waitForTimeout(1600)
await page.mouse.move(760, 420, { steps: 12 })
await page.waitForTimeout(1400)

await page.evaluate(() => { if (window.__pin) clearInterval(window.__pin) })
console.log(`  page errors: ${errors.length}`)

await ctx.close()
await browser.close()
console.log('  context closed — Playwright finalises the webm')
