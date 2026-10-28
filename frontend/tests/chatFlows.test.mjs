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

test('composer has two modes, Reply and Internal note, and Template is a button', () => {
  assert.match(composer, /@focusin="expandOn"/)
  assert.match(composer, /event\.target\.matches\("textarea, input:not\(\[type=file\]\), select"\)/)
  assert.match(composer, /:aria-pressed="!noting" @click="emit\('mode', 'reply'\)/)
  assert.match(composer, /:aria-pressed="noting" @click="emit\('mode', 'note'\)"><FeatherIcon name="lock"/)
  assert.doesNotMatch(composer.split('class="composer-tabs"')[1].split('</div>')[0], /aria-pressed="false"/)
  assert.match(composer, /class="composer-chip" icon-left="file-text" label="Template"/)
  assert.match(connected, /:mode="composeMode" @mode="setComposeMode" @template="startInChat\(true\)"/)
})

test('note mode swaps the whole composer for the note form, so a note cannot reach the customer', async () => {
  assert.match(composer, /<slot v-if="noting" name="note" \/>/)
  assert.match(composer, /@submit\.prevent="!noting && canSend && send\(\)"/)
  const note = await read('components/messages/NoteComposer.vue')
  assert.match(note, /placeholder="Note for your team\. The customer will not see this\."/)
  assert.match(note, /icon-left="lock" label="Add note"/)
  assert.match(note, /coreApi\("collaboration\.add"/)
  assert.doesNotMatch(note, /messaging\.|send\(/)
  assert.match(connected, /<template #note><NoteComposer /)
  assert.match(connected, /@note="startNote"/)
  const notes = await read('components/messages/InternalNotes.vue')
  assert.doesNotMatch(notes, /collaboration\.add|Add internal note/)
})

test('the phone "+" holds only attach options', () => {
  assert.match(composer, /<div v-if="isMobile" class="composer-plus"><Dropdown v-if="attachmentOptions\.length" :options="attachmentOptions">/)
  assert.doesNotMatch(composer, /plusOptions/)
})

test('the inbox "+" starts an empty new conversation', () => {
  assert.match(connected, /@start="openStart\(\)"/)
  assert.match(connected, /function openStart\(\{ contact = "", template = false, business = false \} = \{\}\)/)
  assert.match(connected, /:business-name="startBusiness \? businessName : ''"/)
})

test('a closed reply window replaces the text box with a banner and one Send template button', async () => {
  assert.match(composer, /More than 24 hours since the customer wrote\. You can only send a template\./)
  assert.match(composer, /<div v-else-if="closed" class="composer-closed">/)
  assert.match(composer, /class="composer-closed-send" label="Send template"[^>]*variant="solid" @click="emit\('template'\)"/)
  assert.match(composer, /:title="sendTitle"/)
  const start = await read('components/messages/StartConversation.vue')
  assert.match(start, /kind = ref\(props\.channel \|\| props\.template \? "template" : "text"\)/)
  assert.match(start, /title: props\.template \? 'Send template' : 'New conversation'/)
})

test('the new message dialog asks only what it needs and has a Cancel button', async () => {
  const start = await read('components/messages/StartConversation.vue')
  assert.match(start, /<RelaySelect v-if="can\('templates'\) && kindOptions\.length > 1"/)
  assert.match(start, /<ChoiceField v-if="endpoints\.length > 1" v-model="endpoint"/)
  assert.match(start, /<Button label="Cancel" variant="ghost" :disabled="busy" @click="close" \/>/)
  assert.match(start, /contactCaption\(row\.display_name \|\| row\.contact, "Unknown number"\)/)
  assert.match(start, /initialOptions: templateId && templateLabel/)
  assert.match(start, /approvedTemplates\(after => coreApi\("whatsapp\.execute"/)
})

test('a chat that fails to load stays open with a retry; only 403 or 404 leaves', () => {
  assert.match(messages, /if\(\[403,404\]\.includes\(loadFailed\.value\?\.status\)&&selected\.value===contact\)/)
  assert.match(connected, /title="Could not load messages"/)
  assert.match(connected, /kinds\.has\('reconnect'\) \|\| kinds\.has\('visible'\)\)\) return retryChat\(\)/)
})

test('internal notes work in every chat: email chats and switched-off channels too', async () => {
  const email = await read('components/messages/EmailComposer.vue')
  assert.match(email, /<slot v-if="noting" name="note" \/>/)
  assert.match(email, /@submit\.prevent="!noting && send\(\)"/)
  assert.match(connected, /<EmailComposer v-if="[^"]*" :key="source\.name" :mode="composeMode" @mode="setComposeMode">/)
  assert.equal(connected.match(/<template #note><NoteComposer /g)?.length, 2)
  assert.match(connected, /<MessageComposer v-else-if="source && \(replyOff \|\| channelEnabled\([^"]*" [^>]*:off-text="replyOff"/)
  assert.doesNotMatch(connected, /class="chat-channel-off"/)
})

test('a switched-off channel shows the plain banner in reply mode and never offers a template', () => {
  assert.match(composer, /offText: String/)
  assert.match(composer, /windowState\.value\.channel_disabled \? channelOffText\(sourceContext\.value\.provider\)/)
  assert.match(composer, /const closed = computed\(\(\) => !!offReason\.value \|\| !windowState\.value\.open\)/)
  assert.match(composer, /<Button v-if="can\('templates'\) && !offReason" class="composer-closed-send"/)
  assert.match(composer, /draftScope = computed\(\(\) => props\.offText \? '' :/)
})
