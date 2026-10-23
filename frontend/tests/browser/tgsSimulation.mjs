// Serve the built tgs fixture on loopback and run with an existing Playwright page.
import { gzipSync } from 'node:zlib'
import { tgsFixture } from './tgsFixture.js'
export default async function testTgs(page, origin = 'http://127.0.0.1:18123') {
  const errors = [], unexpected = []
  let requests = 0
  const onError = e => errors.push(e.message)
  page.on('pageerror', onError)
  await page.route('**/api/method/relay_core.messaging.sticker?message=*', async route => {
    requests++
    await route.fulfill({ status: 200, contentType: 'application/x-tgsticker', body: gzipSync(JSON.stringify(tgsFixture)) })
  })
  const onRequest = request => { if (!request.url().startsWith(origin)) unexpected.push(request.url()) }
  page.on('request', onRequest)
  const pixels = () => page.locator('.tgs-canvas canvas').evaluate(canvas => canvas.toDataURL())
  try {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto(origin + '/tests/browser/tgs.html')
    await page.getByRole('button', { name: 'Load animated sticker', exact: true }).waitFor()
    if (requests !== 0) throw new Error('TGS fetched eagerly')
    await page.getByRole('button', { name: 'Load animated sticker', exact: true }).click()
    await page.locator('[data-animation-state="playing"] canvas').waitFor()
    const initial = await pixels()
    await page.waitForTimeout(250)
    if (initial === await pixels()) throw new Error('Animation frames did not change')
    await page.getByRole('button', { name: 'Pause sticker', exact: true }).click()
    const stopped = await pixels()
    await page.waitForTimeout(200)
    if (stopped !== await pixels()) throw new Error('Paused animation kept rendering')
    await page.getByRole('button', { name: 'Play sticker', exact: true }).click()
    await page.evaluate(() => scrollTo(0, 1900))
    await page.waitForTimeout(100)
    const hidden = await pixels()
    await page.waitForTimeout(200)
    if (hidden !== await pixels()) throw new Error('Offscreen animation kept rendering')
    await page.evaluate(() => scrollTo(0, 0))
    await page.waitForTimeout(150)
    if (hidden === await pixels()) throw new Error('Visible animation did not resume')
    await page.getByRole('button', { name: 'Toggle sticker', exact: true }).click()
    if (await page.locator('canvas').count()) throw new Error('Unmount retained canvas')
    await page.getByRole('button', { name: 'Toggle sticker', exact: true }).click()
    if (requests !== 1) throw new Error('Unmount/remount fetched without user input')
    if (errors.length || unexpected.length) throw new Error(JSON.stringify({ errors, unexpected }))
    return { passed: true, explicitFetches: requests, changingFrames: true, pausedOffscreen: true, cleanedOnUnmount: true }
  } finally {
    page.off('pageerror', onError); page.off('request', onRequest)
    await page.unroute('**/api/method/relay_core.messaging.sticker?message=*')
  }
}

export async function testTgsAccessibility(page, origin = 'http://127.0.0.1:18123') {
  const errors = []
  const onError = e => errors.push(e.message)
  page.on('pageerror', onError)
  await page.route('**/api/method/relay_core.messaging.sticker?message=*', route =>
    route.fulfill({ status: 200, contentType: 'application/x-tgsticker', body: gzipSync(JSON.stringify(tgsFixture)) }))
  try {
    await page.setViewportSize({ width: 320, height: 568 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto(origin + '/tests/browser/tgs.html')
    const load = page.getByRole('button', { name: 'Load animated sticker', exact: true })
    await load.focus(); await load.press('Enter')
    await page.locator('[data-animation-state="paused"] canvas').waitFor()
    const pixels = () => page.locator('.tgs-canvas canvas').evaluate(canvas => canvas.toDataURL())
    const stopped = await pixels(); await page.waitForTimeout(200)
    if (stopped !== await pixels()) throw new Error('Reduced-motion preference ignored')
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Small-screen horizontal overflow')
    const play = page.getByRole('button', { name: 'Play sticker', exact: true })
    await play.focus(); await play.press('Enter')
    await page.waitForTimeout(250)
    if (stopped === await pixels()) throw new Error('Keyboard playback failed')
    await page.addInitScript(() => Object.defineProperty(window, 'DecompressionStream', { value: undefined, configurable: true }))
    await page.reload()
    await page.getByRole('button', { name: 'Load animated sticker', exact: true }).click()
    await page.getByRole('status').filter({ hasText: 'Animated sticker unavailable.' }).waitFor()
    if (!await page.getByRole('button', { name: 'Retry animated sticker', exact: true }).isVisible()) throw new Error('Unsupported-browser fallback missing')
    if (errors.length) throw new Error(errors.join('\n'))
    return { passed: true, keyboard: true, reducedMotion: true, viewport: '320x568', unsupportedBrowserFallback: true }
  } finally {
    page.off('pageerror', onError)
    await page.unroute('**/api/method/relay_core.messaging.sticker?message=*')
    await page.emulateMedia({ reducedMotion: 'no-preference' })
  }
}
