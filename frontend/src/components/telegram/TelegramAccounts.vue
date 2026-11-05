<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Badge, Button, Dialog, ErrorMessage, FormControl, toast } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { botBadge, botRows, clearSecrets } from '../../services/channelSetup'
import { watchRealtime } from '../../composables/useRealtimeRefresh'
import { dateTime } from '../relativeTime'

const accounts = ref([]), canConfigure = ref(false)
const loaded = ref(false), busy = ref(''), error = ref(''), notice = ref('')
const adding = reactive({ label: '', bot_token: '' }), editing = ref(null), draft = reactive({ label: '', bot_token: '' }), removing = ref(null)
let stop

async function load() {
  error.value = ''
  try {
    const result = await coreApi('channels_api.accounts', { channel: 'Telegram' })
    accounts.value = result.accounts; canConfigure.value = result.can_configure
  } catch (e) { error.value = e.message }
  finally { loaded.value = true }
}

// One action at a time. The token fields are cleared after every submit, sent or not.
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
  const values = { label: adding.label, bot_token: adding.bot_token }
  if (await run('connect', 'connect', { channel: 'Telegram', values }, () => 'Bot connected.')) adding.label = ''
}
const check = row => run(row.name + ':check', 'check', { channel: row.name, repair: 1 }, () => 'Connection checked.')
const toggle = (row, value) => run(row.name + ':enabled', 'save_settings', { channel: row.name, settings: { enabled: value ? 1 : 0 } }, () => 'Saved.')
const makeDefault = row => run(row.name + ':default', 'set_default', { channel: row.name }, () => row.label + ' is now the default bot.')

function edit(row) { editing.value = row; draft.label = row.label; draft.bot_token = '' }
async function saveEdit() {
  const row = editing.value, settings = {}
  if (draft.label.trim() && draft.label.trim() !== row.label) settings.label = draft.label.trim()
  if (draft.bot_token.trim()) settings.bot_token = draft.bot_token.trim()
  editing.value = null
  if (Object.keys(settings).length) await run(row.name + ':edit', 'save_settings', { channel: row.name, settings }, () => 'Saved.')
  else clearSecrets(draft)
}
async function remove() {
  const row = removing.value
  removing.value = null
  await run(row.name + ':remove', 'remove', { channel: row.name, confirm: 1 }, result => result.removed ? 'The bot is removed from Relay. Its chats stay in Relay.' : '')
}
const checkedText = health => health.checked_at ? 'Checked ' + dateTime(health.checked_at) + '.' : 'Not checked yet.'

onMounted(() => { load(); stop = watchRealtime(['Relay Channel'], ['channels'], load) })
onBeforeUnmount(() => stop?.())
</script>
<template>
  <section class="space-y-4" aria-label="Telegram bots">
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status" class="text-sm text-ink-gray-7">{{ notice }}</p>
    <p v-if="!loaded" role="status">Reading Telegram bots…</p>
    <p v-else-if="!accounts.length && !error">No Telegram bot is connected yet.</p>
    <article v-for="row in accounts" :key="row.name" class="channel-account">
      <div class="channel-account__title">
        <h3>{{ row.label }}</h3>
        <Badge v-bind="botBadge(row)" />
        <Badge v-if="row.is_default" label="Default" theme="blue" />
      </div>
      <ErrorMessage v-if="row.health.check_error && row.health.webhook_status !== 'not_registered'" :message="row.health.check_error" />
      <dl class="channel-account__health">
        <div v-for="item in botRows(row.health)" :key="item.name"><dt>{{ item.name }}</dt><dd>{{ item.text }}</dd></div>
      </dl>
      <p class="text-sm text-ink-gray-5">{{ checkedText(row.health) }}</p>
      <template v-if="canConfigure">
        <FormControl type="checkbox" label="Bot is on" :model-value="row.enabled" :disabled="!!busy" @update:model-value="value => toggle(row, value)" />
        <div class="flex flex-wrap gap-2">
          <Button variant="outline" icon-left="activity" label="Check connection" :loading="busy === row.name + ':check'" :disabled="!!busy || !row.enabled" @click="check(row)" />
          <Button v-if="!row.is_default && row.enabled" variant="outline" label="Make default" :loading="busy === row.name + ':default'" :disabled="!!busy" @click="makeDefault(row)" />
          <Button variant="outline" icon-left="edit-2" label="Rename or new token" :disabled="!!busy" @click="edit(row)" />
          <Button variant="outline" theme="red" icon-left="trash-2" label="Remove bot" :loading="busy === row.name + ':remove'" :disabled="!!busy" @click="removing = row" />
        </div>
      </template>
    </article>
    <form v-if="canConfigure" class="channel-account__add" autocomplete="off" @submit.prevent="connect">
      <h3>Connect a bot</h3>
      <p class="text-sm text-ink-gray-5">Make a bot with @BotFather in Telegram and paste its token here. Relay Hub keeps the token; Relay never shows it again.</p>
      <FormControl v-model="adding.label" label="Name in Relay (optional)" :disabled="!!busy" />
      <FormControl v-model="adding.bot_token" label="Bot token" type="password" autocomplete="new-password" spellcheck="false" :disabled="!!busy" />
      <div><Button type="submit" variant="solid" label="Connect bot" :loading="busy === 'connect'" :disabled="!!busy || !adding.bot_token.trim()" /></div>
    </form>
    <Button variant="outline" icon-left="refresh-cw" label="Refresh" :disabled="!!busy" @click="load" />
    <Dialog :model-value="!!editing" :options="{ title: 'Change this bot', size: 'md' }" @update:model-value="value => { if (!value) { editing = null; clearSecrets(draft) } }">
      <form v-if="editing" class="space-y-4" autocomplete="off" @submit.prevent="saveEdit">
        <FormControl v-model="draft.label" label="Name in Relay" />
        <FormControl v-model="draft.bot_token" label="New bot token" type="password" autocomplete="new-password" spellcheck="false" placeholder="Saved — leave blank to keep" />
        <p class="text-sm text-ink-gray-5">A new token must belong to the same bot. To use another bot, connect it as a new bot.</p>
        <div class="flex justify-end gap-2">
          <Button variant="ghost" label="Cancel" @click="editing = null; clearSecrets(draft)" />
          <Button type="submit" variant="solid" label="Save" />
        </div>
      </form>
    </Dialog>
    <Dialog :model-value="!!removing" :options="{ title: 'Remove this bot?', size: 'md' }" @update:model-value="value => { if (!value) removing = null }">
      <div v-if="removing" class="space-y-4 text-sm text-ink-gray-8">
        <p>Relay stops sending and receiving on {{ removing.label }}, and Relay Hub deletes its token and its webhook. Its chats stay in Relay. To use it again, connect it again.</p>
        <div class="flex justify-end gap-2">
          <Button variant="ghost" label="Cancel" @click="removing = null" />
          <Button variant="solid" theme="red" label="Remove bot" @click="remove" />
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
