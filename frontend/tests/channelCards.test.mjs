import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')
const CARDS = ['components/telegram/TelegramAccounts.vue', 'components/email/EmailAccounts.vue']

test('the bot and mailbox cards keep secrets write-only and refresh on the socket only', async () => {
  for (const path of CARDS) {
    const card = await read(path)
    assert.match(card, /type="password"|type: 'password'/, path)
    assert.match(card, /new-password/, path)
    assert.match(card, /clearSecrets\(adding\); clearSecrets\(draft\)/, path)
    assert.match(card, /watchRealtime\(\['Relay Channel'\], \['channels'\], load\)/, path)
    assert.doesNotMatch(card, /setInterval|setTimeout|console\./, path)
    assert.match(card, /v-if="canConfigure"/, path)
  }
})

test('Settings opens the Telegram and Email cards on their own tabs, not in Desk', async () => {
  const settings = await read('components/SiteSettings.vue')
  assert.doesNotMatch(settings, /\/desk\/relay-channel/)
  assert.match(settings, /'#\/settings\?tab=' \+ provider\.toLowerCase\(\)/)
  assert.match(settings, /<TelegramAccounts \/>/)
  assert.match(settings, /<EmailAccounts \/>/)
})
