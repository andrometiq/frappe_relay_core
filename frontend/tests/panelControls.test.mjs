import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
const read = name => readFile(new URL(`../src/components/${name}`, import.meta.url), 'utf8')

test('opening notes, cases and topics never waits for the message load', async () => {
  const file = await read('ConnectedMessages.vue')
  for (const label of ['Internal notes', 'Cases', 'Topics']) assert.doesNotMatch(file, new RegExp(`label:'${label}',disabled`))
  assert.match(file, /:can-organize="!!conversationContact"/)
})

test('panel close controls are icon buttons', async () => {
  for (const name of ['messages/ConversationSummary.vue', 'NotificationInbox.vue']) {
    const file = await read(name)
    assert.match(file, /<Button icon="x" aria-label="(Close|Cancel)[^"]*"/, name)
    assert.doesNotMatch(file, /<Button icon="x" label=/, name)
  }
})

test('chat side panels share one close control', async () => {
  const panel = await read('messages/ChatPanel.vue')
  assert.match(panel, /onMounted\(\(\) => \{ if \(props\.takeFocus\) panel\.value\?\.querySelector\('button'\)\?\.focus/, 'Only a panel the person opened takes focus')
  assert.match(panel, /const origin = props\.takeFocus \? document\.activeElement : null/, 'A panel that took no focus gives none back')
  assert.match(await read('ConnectedMessages.vue'), /<ChatPanel v-if="contextShown && !isMobile" [^>]*:take-focus="panel === 'contact' \|\| !docked"/,
    'The details panel that docks by default on a wide screen leaves focus in the chat')
  assert.match(panel, /<Button v-if="isMobile" icon="chevron-left" variant="ghost" aria-label="Close"/)
  assert.match(panel, /<Button v-if="!isMobile" icon="x" variant="ghost" aria-label="Close"/)
  for (const name of ['messages/InternalNotes.vue', 'messages/MessageSearch.vue', 'messages/BusinessMessageSearch.vue']) {
    assert.match(await read(name), /<ChatPanel [^>]*@close="emit\('close'\)"/, name)
  }
  assert.match(await read('messages/ContactInfoPage.vue'), /icon="chevron-left" variant="ghost" aria-label="Close"/)
})
