import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')
const CARDS = ['components/telegram/TelegramAccounts.vue', 'components/email/EmailAccounts.vue']
const ALL_CARDS = [...CARDS, 'components/whatsapp/WhatsAppAccounts.vue']

test('the bot and mailbox cards keep secrets write-only and refresh on the socket only', async () => {
  for (const path of CARDS) {
    const card = await read(path)
    assert.match(card, /type="password"|type: 'password'/, path)
    assert.match(card, /new-password/, path)
    assert.match(card, /clearSecrets\(adding\); clearSecrets\(draft\)/, path)
    assert.match(card, /\{ channel: '(Telegram|Email)', \.\.\.withSecrets\('values', /, path)
    assert.match(card, /'save_settings', \{ channel: row\.name, \.\.\.withSecrets\('settings', settings\) \}/, path)
    assert.match(card, /watchRealtime\(\['Relay Channel'\], \['channels'\], load, ACCOUNTS_RELOAD_DELAY\)/, path)
    assert.doesNotMatch(card, /setInterval|setTimeout|console\./, path)
    assert.match(card, /v-if="canConfigure"/, path)
  }
})

test('every Account card waits for a burst of channels events to end before it asks the Hub again', async () => {
  for (const path of ALL_CARDS) {
    const card = await read(path)
    assert.match(card, /watchRealtime\(\['Relay Channel'\], \[[^\]]*'channels'[^\]]*\], load, ACCOUNTS_RELOAD_DELAY\)/, path)
    assert.doesNotMatch(card, /setInterval/, path)
  }
})

test('a burst of channels events reloads an Account card once', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const { ACCOUNTS_RELOAD_DELAY } = await import('../src/services/channelSetup.js')
  const { realtimeRefreshQueue } = await import('../src/services/realtimeRefreshQueue.js')
  let reloads = 0
  const queue = realtimeRefreshQueue(async () => { reloads++ }, () => true, ACCOUNTS_RELOAD_DELAY)
  for (let event = 0; event < 5; event++) { queue.schedule('channels'); t.mock.timers.tick(150) }
  assert.equal(reloads, 0)
  t.mock.timers.tick(ACCOUNTS_RELOAD_DELAY)
  await Promise.resolve()
  assert.equal(reloads, 1)
  queue.dispose()
})

test('Settings opens the Telegram and Email cards on their own tabs, not in Desk', async () => {
  const settings = await read('components/SiteSettings.vue')
  assert.doesNotMatch(settings, /\/desk\/relay-channel/)
  assert.match(settings, /'#\/settings\?tab=' \+ provider\.toLowerCase\(\)/)
  assert.match(settings, /<TelegramAccounts \/>/)
  assert.match(settings, /<EmailAccounts \/>/)
})
