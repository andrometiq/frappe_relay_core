<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Badge, Button, Dialog, ErrorMessage, FormControl, toast } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { ACCOUNTS_RELOAD_DELAY, ADMIN_OFF_TEXT, adminLocked, clearSecrets, mailboxBadge, mailboxChanges, mailboxConnect, mailboxDraft, mailboxRows, withSecrets } from '../../services/channelSetup'
import { watchRealtime } from '../../composables/useRealtimeRefresh'
import { dateTime } from '../relativeTime'

const SERVER_FIELDS = [
  { name: 'host', label: 'SMTP server', placeholder: 'smtp.example.com' },
  { name: 'port', label: 'SMTP port', placeholder: '587', type: 'number' },
  { name: 'username', label: 'SMTP user name', placeholder: 'Leave blank to use the address' },
  { name: 'password', label: 'SMTP password', type: 'password' },
  { name: 'imap_host', label: 'IMAP server', placeholder: 'Leave blank to use the SMTP server' },
  { name: 'imap_port', label: 'IMAP port', placeholder: '993', type: 'number' },
  { name: 'imap_username', label: 'IMAP user name', placeholder: 'Leave blank to use the SMTP user name' },
  { name: 'imap_password', label: 'IMAP password', type: 'password', placeholder: 'Leave blank to use the SMTP password' },
  { name: 'imap_folder', label: 'IMAP folder', placeholder: 'INBOX' },
]
const blankForm = () => ({ label: '', from: '', host: '', port: '', username: '', password: '', imap_host: '', imap_port: '', imap_username: '', imap_password: '', imap_folder: '' })

const accounts = ref([]), canConfigure = ref(false)
const loaded = ref(false), busy = ref(''), error = ref(''), notice = ref('')
const adding = reactive(blankForm()), editing = ref(null), draft = reactive({}), removing = ref(null)
let stop

async function load() {
  error.value = ''
  try {
    const result = await coreApi('channels_api.accounts', { channel: 'Email' })
    accounts.value = result.accounts; canConfigure.value = result.can_configure
  } catch (e) { error.value = e.message }
  finally { loaded.value = true }
}

// One action at a time. The password fields are cleared after every submit, sent or not.
async function run(key, method, values, done) {
  busy.value = key; error.value = ''; notice.value = ''
  try {
    const result = await coreApi('channels_api.' + method, values, true)
    notice.value = done(result) || ''
    if (notice.value) toast(notice.value)
    await load()
    return true
  } catch (e) { error.value = e.message; return false }
  finally { busy.value = ''; clearSecrets(adding); clearSecrets(draft) }
}

async function connect() {
  if (await run('connect', 'connect', { channel: 'Email', ...withSecrets('values', mailboxConnect(adding)) }, () => 'Mailbox connected.')) Object.assign(adding, blankForm())
}
const check = row => run(row.name + ':check', 'check', { channel: row.name }, () => 'Sign-in checked.')
const toggle = (row, value) => run(row.name + ':enabled', 'save_settings', { channel: row.name, settings: { enabled: value ? 1 : 0 } }, () => 'Saved.')
const makeDefault = row => run(row.name + ':default', 'set_default', { channel: row.name }, () => row.label + ' is now the default mailbox.')

function edit(row) {
  for (const key of Object.keys(draft)) delete draft[key]
  Object.assign(draft, mailboxDraft(row.health), { label: row.label })
  editing.value = row
}
async function saveEdit() {
  const row = editing.value, settings = mailboxChanges(row.health, draft)
  if (draft.label.trim() && draft.label.trim() !== row.label) settings.label = draft.label.trim()
  editing.value = null
  if (Object.keys(settings).length) await run(row.name + ':edit', 'save_settings', { channel: row.name, ...withSecrets('settings', settings) }, () => 'Saved.')
  else clearSecrets(draft)
}
function closeEdit() { editing.value = null; clearSecrets(draft) }
async function remove() {
  const row = removing.value
  removing.value = null
  await run(row.name + ':remove', 'remove', { channel: row.name, confirm: 1 }, result => result.removed ? 'The mailbox is removed from Relay. Its mail stays in Relay.' : '')
}
const checkedText = health => health.checked_at ? 'Checked ' + dateTime(health.checked_at) + '.' : 'Not checked yet.'

onMounted(() => { load(); stop = watchRealtime(['Relay Channel'], ['channels'], load, ACCOUNTS_RELOAD_DELAY) })
onBeforeUnmount(() => stop?.())
</script>
<template>
  <section class="space-y-4" aria-label="Mailboxes">
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status" class="text-sm text-ink-gray-7">{{ notice }}</p>
    <p v-if="!loaded" role="status">Reading mailboxes…</p>
    <p v-else-if="!accounts.length && !error">No mailbox is connected yet.</p>
    <article v-for="row in accounts" :key="row.name" class="channel-account">
      <div class="channel-account__title">
        <h3>{{ row.label }}</h3>
        <Badge v-bind="mailboxBadge(row)" />
        <Badge v-if="row.is_default" label="Default" theme="blue" />
      </div>
      <p class="text-sm text-ink-gray-7">{{ row.address || row.health.address }}</p>
      <ErrorMessage v-if="row.health.check_error" :message="row.health.check_error" />
      <dl class="channel-account__health">
        <div v-for="item in mailboxRows(row.health, dateTime)" :key="item.name"><dt>{{ item.name }}</dt><dd>{{ item.text }}</dd></div>
      </dl>
      <p class="text-sm text-ink-gray-5">{{ checkedText(row.health) }}</p>
      <template v-if="canConfigure">
        <FormControl type="checkbox" label="Mailbox is on" :model-value="row.enabled" :disabled="!!busy || adminLocked(row)" @update:model-value="value => toggle(row, value)" />
        <p v-if="adminLocked(row)" class="text-sm text-ink-gray-5">{{ ADMIN_OFF_TEXT }}</p>
        <div class="flex flex-wrap gap-2">
          <Button variant="outline" icon-left="activity" label="Check sign-in" :loading="busy === row.name + ':check'" :disabled="!!busy || !row.enabled" @click="check(row)" />
          <Button v-if="!row.is_default && row.enabled" variant="outline" label="Make default" :loading="busy === row.name + ':default'" :disabled="!!busy" @click="makeDefault(row)" />
          <Button variant="outline" icon-left="edit-2" label="Change settings" :disabled="!!busy" @click="edit(row)" />
          <Button variant="outline" theme="red" icon-left="trash-2" label="Remove mailbox" :loading="busy === row.name + ':remove'" :disabled="!!busy" @click="removing = row" />
        </div>
      </template>
    </article>
    <form v-if="canConfigure" class="channel-account__add" autocomplete="off" @submit.prevent="connect">
      <h3>Connect a mailbox</h3>
      <p class="text-sm text-ink-gray-5">Relay Hub signs in to the mail server before it keeps anything. Relay never shows a saved password again. Use an app password when your mail provider has one.</p>
      <FormControl v-model="adding.from" label="Mailbox address" placeholder="sales@example.com" :disabled="!!busy" />
      <FormControl v-model="adding.label" label="Name in Relay (optional)" :disabled="!!busy" />
      <FormControl v-for="field in SERVER_FIELDS" :key="field.name" v-model="adding[field.name]" :label="field.label" :type="field.type || 'text'" :placeholder="field.placeholder" :autocomplete="field.type === 'password' ? 'new-password' : 'off'" spellcheck="false" :disabled="!!busy" />
      <div><Button type="submit" variant="solid" label="Connect mailbox" :loading="busy === 'connect'" :disabled="!!busy || !adding.from.trim() || !adding.host.trim() || !adding.password" /></div>
    </form>
    <Button variant="outline" icon-left="refresh-cw" label="Refresh" :disabled="!!busy" @click="load" />
    <Dialog :model-value="!!editing" :options="{ title: 'Change this mailbox', size: 'lg' }" @update:model-value="value => { if (!value) closeEdit() }">
      <form v-if="editing" class="space-y-3" autocomplete="off" @submit.prevent="saveEdit">
        <FormControl v-model="draft.label" label="Name in Relay" />
        <FormControl v-for="field in SERVER_FIELDS" :key="field.name" v-model="draft[field.name]" :label="field.label" :type="field.type || 'text'" :placeholder="field.type === 'password' ? 'Saved — leave blank to keep' : field.placeholder" :autocomplete="field.type === 'password' ? 'new-password' : 'off'" spellcheck="false" />
        <p class="text-sm text-ink-gray-5">Relay Hub signs in with the new settings before it saves them.</p>
        <div class="flex justify-end gap-2">
          <Button variant="ghost" label="Cancel" @click="closeEdit" />
          <Button type="submit" variant="solid" label="Save" />
        </div>
      </form>
    </Dialog>
    <Dialog :model-value="!!removing" :options="{ title: 'Remove this mailbox?', size: 'md' }" @update:model-value="value => { if (!value) removing = null }">
      <div v-if="removing" class="space-y-4 text-sm text-ink-gray-8">
        <p>Relay stops sending and receiving mail on {{ removing.label }}, and Relay Hub deletes its passwords. Its mail stays in Relay. To use it again, connect it again.</p>
        <div class="flex justify-end gap-2">
          <Button variant="ghost" label="Cancel" @click="removing = null" />
          <Button variant="solid" theme="red" label="Remove mailbox" @click="remove" />
        </div>
      </div>
    </Dialog>
  </section>
</template>
<style scoped>
.channel-account { display:flex; flex-direction:column; gap:8px; padding-bottom:16px; border-bottom:1px solid var(--outline-gray-2); }
.channel-account__title { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
.channel-account h3, .channel-account__add h3 { font-size:15px; font-weight:600; overflow-wrap:anywhere; }
.channel-account__health { display:grid; gap:8px; margin:4px 0; }
.channel-account__health > div { display:grid; grid-template-columns:minmax(120px,170px) minmax(0,1fr); align-items:center; gap:12px; }
.channel-account__health dt { color:var(--ink-gray-5); }
.channel-account__health dd { margin:0; color:var(--ink-gray-8); overflow-wrap:anywhere; }
.channel-account__add { display:grid; gap:10px; max-width:520px; }
</style>
