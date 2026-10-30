import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')
const connected = await read('components/ConnectedMessages.vue')

test('the chat header has no assignment control', async () => {
  assert.doesNotMatch(await read('components/messages/ConversationTools.vue'), /Assign|assignment|teams\.assign/)
})

test('the More menu lists delivery failures, notes, topics and search, and the header has no ticket button', () => {
  const menu = connected.split('const menuActions = computed')[1].split('const channelLine')[0]
  assert.deepEqual([...menu.matchAll(/label:'([^']+)'/g)].map(match => match[1]), ['Delivery failures and retry', 'Internal notes', 'Topics', 'Search conversation'])
  assert.doesNotMatch(connected, /Create ticket from this chat|conversation-ticket/)
})

test('the More menu is one dropdown that closes itself on choice', async () => {
  const tools = await read('components/messages/ConversationTools.vue')
  assert.equal((tools.match(/<Dropdown /g) || []).length, 1)
  assert.doesNotMatch(tools, /useConversationPresence/)
})

test('only one side panel is open at a time and the info button toggles contact info', () => {
  assert.match(connected, /const panel = ref\(''\);/)
  assert.match(connected, /notesOpen = computed\(\(\) => panel\.value === 'notes'/)
  assert.match(connected, /searchOpen = computed\(\(\) => panel\.value === 'search'\)/)
  assert.match(connected, /contextShown = computed\(\(\) => panel\.value === 'contact'\)/)
  assert.match(connected, /function toggleContext\(\) \{ linking\.value = false; togglePanel\('contact'\); \}/)
  assert.doesNotMatch(connected, /contextOpen|notesOpen\.value = |searchOpen\.value = /)
  assert.match(connected, /<Button icon="info" aria-label="Contact info"[^>]*@click="toggleInfo"/)
  assert.match(connected, /else if \(infoOpen\.value\) closeInfo\(\)/)
})

test('the header second line names the person, then phone, email and channel', () => {
  assert.match(connected, /whoLine = computed\(\(\) => \[whoName\.value, phone\.value, email\.value, channelCaption\.value\]/)
  assert.match(connected, /contactRecord\.value\?\.phone/, 'The saved mobile shows in an email chat too')
  assert.match(connected, /contactRecord\.value\?\.email/, 'The saved email shows in a WhatsApp chat too')
  assert.equal((connected.match(/<ContactEndpoints :phone="phone" :email="email" \/>/g) || []).length, 3, 'Phone and wide headers and the info panel mark each address')
  assert.match(connected, /<ContactEndpoints :phone="contact\.phone" :email="contact\.email"/, 'Business contacts show mobile and email')
})

test('a switched-off channel shows a plain banner in place of replies', () => {
  assert.match(connected, /const replyOff = computed\(\(\) => channelOff\.value && !numbers\.active\.value \? channelOffText\(provider\.value\) : ''\)/)
  assert.match(connected, /<EmailComposer v-if="!replyOff && /)
  assert.match(connected, /plainChatError\(loadFailed \? '' : error\)/)
})

test('the header shows at most three viewer avatars with names and a +n count', () => {
  assert.match(connected, /v-for="person in people\.slice\(0, 3\)"[^>]*size="sm"[^>]*:title="'Also viewing: ' \+/)
  assert.match(connected, /people\.length > 3[^]*\+\{\{ people\.length - 3 \}\}/)
})

test('the To bar shows only in a business chat with several contacts', async () => {
  assert.match(connected, /chooseRecipient = computed\(\(\) => !!businessName\.value && linkedContacts\.value\.length > 1\)/)
  assert.equal((connected.match(/<template v-if="chooseRecipient" #recipient>/g) || []).length, 2)
  const composer = await read('components/messages/MessageComposer.vue')
  assert.match(composer, /v-if="\$slots\.recipient"/)
})

test('a reply shows a quote strip with the author and a cancel button', async () => {
  const composer = await read('components/messages/MessageComposer.vue')
  assert.match(composer, /class="composer-quote-body"><strong>\{\{ source\.direction === 'Outgoing' \? 'You'/)
  assert.match(composer, /aria-label="Cancel reply"/)
  assert.doesNotMatch(composer, /Replying to/)
  assert.match(connected, /@reply="replyTo"/)
})
