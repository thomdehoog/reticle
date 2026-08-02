import { chromium, devices } from 'playwright'
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' })
for (const [label, opts] of [['phone', { ...devices['iPhone 12'] }], ['tablet', { viewport: { width: 768, height: 1024 } }], ['desktop', { viewport: { width: 1440, height: 900 } }]]) {
  const ctx = await b.newContext(opts); const p = await ctx.newPage()
  await p.goto('http://localhost:5175/', { waitUntil: 'networkidle' })
  await p.fill('input[type="email"]', 'thom@zmb.uzh.ch')
  await p.fill('input[type="password"]', 'demo-password-not-real')
  await p.click('button[type="submit"]')
  await p.waitForSelector('.app__main', { timeout: 20000 })
  const slug = await p.evaluate(async () => (await (await fetch('/api/guides?status=published', {credentials:'same-origin'})).json()).find(g=>g.title.startsWith('Starting a Session'))?.slug)
  await p.goto(`http://localhost:5175/g/${slug}`, { waitUntil: 'networkidle' })
  // Scroll the whole page so lazy images below the fold actually load.
  await p.evaluate(async () => { for (let y = 0; y < document.body.scrollHeight; y += 400) { window.scrollTo(0, y); await new Promise(r => setTimeout(r, 60)) } window.scrollTo(0, 0) })
  await p.waitForTimeout(1200)
  console.log(label, JSON.stringify(await p.evaluate(() => [...document.querySelectorAll('.step')].map((s, i) => {
    const st = s.querySelector('.step__stage')
    return { step: i + 1, stage: st ? Math.round(st.getBoundingClientRect().height) : null,
             thumbs: s.querySelectorAll('.step__thumb').length,
             loaded: [...s.querySelectorAll('.step__thumb img')].filter(x => x.naturalWidth > 0).length }
  }))))
  await p.screenshot({ path: `/var/tmp/tour/fix-${label}-guide.png`, fullPage: true })
  await ctx.close()
}
await b.close()
