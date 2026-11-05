import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')

test('a Telegram link is made for the user or a contact and its result arrives over Socket.IO', async () => {
  const link = await read('components/telegram/TelegramLink.vue')
  assert.match(link, /coreApi\('telegram_links\.link_contact', \{ contact: props\.contact \}, true\)/)
  assert.match(link, /coreApi\('telegram_links\.link_me', \{\}, true\)/)
  assert.match(link, /onRealtime\(changed\)/)
  assert.match(link, /event\?\.kind !== 'telegram_link'/)
  assert.doesNotMatch(link, /setInterval|setTimeout/, 'No polling for the link result')
  assert.match(link, /props\.contact \? 'Send Telegram link' : 'Link my Telegram'/)
})

test('the notification panel shows the user\'s Telegram chats and the link control', async () => {
  const inbox = await read('components/NotificationInbox.vue')
  assert.match(inbox, /<footer v-if="channelEnabled\('Telegram'\)" class="notification-telegram">/)
  assert.match(inbox, /<TelegramLink @linked="loadTelegram" \/>/)
  assert.match(inbox, /coreApi\("ticket_notifications\.destinations"\)/)
})

test('a manager sends a Telegram link from the saved numbers of a contact', async () => {
  const details = await read('components/ContactDetails.vue')
  assert.match(details, /<TelegramLink v-if="channelEnabled\('Telegram'\)" :contact="detail\.name" \/>/)
})
