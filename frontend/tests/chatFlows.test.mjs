import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')
const connected = await read('components/ConnectedMessages.vue')
const composer = await read('components/messages/MessageComposer.vue')
const messages = await read('composables/useMessages.js')

test('closing or switching the chat closes and clears the ticket dialog', () => {
  assert.match(connected, /function closeTicket\(\) \{ ticketOpen\.value = false; ticketMessage\.value = null;/)
  assert.match(connected, /watch\(selected, contact => \{\n[^\n]*closeTicket\(\)/)
  assert.match(connected, /watch\(\[businessType, businessName\], \(\) => \{\n[^\n]*closeTicket\(\)/)
  assert.match(connected, /<CreateTicketDialog v-if="ticketMessage" :key="ticketMessage\.name"/)
})

test('"Link record" opens the link form, not the full contact details', async () => {
  assert.match(connected, /capabilities.manage" type="button" class="conversation-linked" :aria-expanded="contextShown && linking" @click="openLinking">Not linked · Link/)
  assert.match(connected, /<ChatPanel v-if="contextShown && !isMobile" :title="linking \? 'Link record' : 'Contact info'"/)
  assert.match(connected, /<ContactDetails v-if="frappeContact" [^>]*compact [^>]*:link="linking"/)
  const details = await read('components/ContactDetails.vue')
  assert.match(details, /<ContactLinks [^>]*:start="link"/)
  assert.match(details, /<template v-if="!link">\s*<h4 class="info-group-title">Details<\/h4>/)
  const links = await read('components/ContactLinks.vue')
  assert.match(links, /onMounted\(\(\) => \{ if \(props\.start && props\.detail\.can_edit_links\) startAdding\(\) \}\)/)
})

test('composer tabs act in one click and show the open mode', () => {
  assert.match(composer, /@focusin="expandOn"/)
  assert.match(composer, /event\.target\.matches\("textarea, input:not\(\[type=file\]\), select"\)/)
  assert.match(composer, /:aria-pressed="!noteOpen"[^>]*>Reply</)
  assert.match(composer, /:aria-pressed="noteOpen"[^>]*@click="emit\('note'\)">Internal note</)
  assert.match(connected, /:note-open="notesOpen" @note="openNote\(\)" @reply="closeNotes\(\)" @template="openStart\(source\?\.frappe_contact \|\| '', true\)"/)
})

test('a closed reply window says why Send is off and opens this chat\'s template dialog', async () => {
  assert.match(composer, /The 24-hour window is closed\. Send an approved template\./)
  assert.match(composer, /:title="windowState\.open \? 'Send · Enter' : windowClosedReason"/)
  const start = await read('components/messages/StartConversation.vue')
  assert.match(start, /kind = ref\(props\.channel \|\| props\.template \? "template" : "text"\)/)
  assert.match(start, /title: props\.template \? 'Send approved template' : 'New conversation'/)
})

test('a chat that fails to load stays open with a retry; only 403 or 404 leaves', () => {
  assert.match(messages, /if\(\[403,404\]\.includes\(loadFailed\.value\?\.status\)&&selected\.value===contact\)/)
  assert.match(connected, /title="Could not load messages"/)
  assert.match(connected, /kinds\.has\('reconnect'\) \|\| kinds\.has\('visible'\)\)\) return retryChat\(\)/)
})
