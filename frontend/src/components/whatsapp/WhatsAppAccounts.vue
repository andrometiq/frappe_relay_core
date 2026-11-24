<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Badge, Button, Dialog, Dropdown, ErrorMessage, FeatherIcon, toast } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { whatsappHealth } from '../../services/whatsappHealth'
import { accountMetadata, ACCOUNTS_RELOAD_DELAY, ADMIN_OFF_TEXT, adminLocked, connectionBadge, deliveryRows, needsReconnect, PIN_TEXT, removalText, SWITCHES, switchValue, webhookText } from '../../services/channelSetup'
import { setupRoute } from '../../services/onboarding'
import { watchRealtime } from '../../composables/useRealtimeRefresh'
import { dateTime } from '../relativeTime'
import WhatsAppProfile from './WhatsAppProfile.vue'
import ToggleSwitch from '../fields/ToggleSwitch.vue'

const accounts = ref([]), metadata = ref({}), canConfigure = ref(false)
const loaded = ref(false), busy = ref(''), error = ref(''), notice = ref('')
const confirming = ref(null), profileOf = ref(null)
// Settings show for one number at a time, in their own card: the picked number, else the default one. `settingsTarget` names
// where that card goes; with none it follows the list.
defineProps({ settingsTarget: { type: String, default: '' } })
const picked = ref('')
const chosen = computed(() => accounts.value.find(row => row.name === picked.value) || accounts.value.find(row => row.is_default) || accounts.value[0])
let stop

async function load() {
  error.value = ''
  try {
    const result = await coreApi('channels_api.accounts', { channel: 'WhatsApp' })
    accounts.value = result.accounts; canConfigure.value = result.can_configure
    metadata.value = await accountMetadata(result.accounts, row =>
      coreApi('whatsapp.execute', { operation: 'account.metadata', channel: row.name }, true).catch(() => null))
  } catch (e) { error.value = e.message }
  finally { loaded.value = true }
}

// One action at a time; the Socket.IO channels event refreshes every open screen, this one included.
async function run(key, method, values, done) {
  busy.value = key; error.value = ''; notice.value = ''
  try {
    const result = await coreApi('channels_api.' + method, values, true)
    notice.value = done(result) || ''
    if (notice.value) toast(notice.value)
    await load()
  } catch (e) { error.value = e.message }
  finally { busy.value = '' }
}

const check = row => run(row.name + ':check', 'check_number', { channel: row.name, repair: 1 },
  result => result.reconnect_required ? 'Meta no longer gives Relay access to this number. Connect it again.' : 'Connection checked.')
const toggle = (row, name, value) => run(row.name + ':' + name, 'save_number_settings',
  { channel: row.name, settings: { [name]: value ? 1 : 0 } }, () => 'Saved.')
const makeDefault = row => run(row.name + ':default', 'set_default', { channel: row.name }, () => row.label + ' is now the default number.')

function confirm(row, action) { confirming.value = { row, action } }
async function confirmed() {
  const { row, action } = confirming.value
  confirming.value = null
  if (action === 'pin') await run(row.name + ':pin', 'reset_pin', { channel: row.name }, () => 'A new PIN is set. Relay keeps it.')
  else await run(row.name + ':remove', 'remove_number', { channel: row.name, confirm: 1 }, removalText)
}

function syncText(account) {
  if (!account) return ''
  if (account.status === 'not_synced') return 'Not synced from Meta yet. Turn on Hourly Meta sync for this number.'
  const synced = account.last_success ? 'Synced from Meta ' + dateTime(account.last_success) + '.' : 'Waiting for the first sync from Meta.'
  return account.status === 'failed' ? synced + ' The last refresh failed: ' + account.last_error : synced
}
// The number row's own actions, in the mockup's More menu; Connect again stays a visible link when Meta dropped access.
function actionsFor(row) {
  const disabled = !!busy.value
  return [
    ...(needsReconnect(row) ? [] : [{ label: 'Check connection', icon: 'activity', disabled, onClick: () => check(row) }]),
    ...(!row.is_default && row.enabled ? [{ label: 'Make default', icon: 'star', disabled, onClick: () => makeDefault(row) }] : []),
    ...(row.enabled ? [{ label: 'Edit profile', icon: 'edit-2', disabled, onClick: () => { profileOf.value = row } }] : []),
    ...(!row.coexistence ? [{ label: 'Reset PIN', icon: 'key', disabled, onClick: () => confirm(row, 'pin') }] : []),
    { label: 'Remove number', icon: 'trash-2', disabled, onClick: () => confirm(row, 'remove') },
  ]
}
// Quality and messaging limit from Meta, as short badges beside the connection state.
function metaBadges(row) {
  const health = whatsappHealth(metadata.value[row.name]?.profile)
  const quality = health.find(item => item.name === 'Quality rating'), limit = health.find(item => item.name === 'Messaging limit')
  return [quality?.theme && { label: 'Quality: ' + quality.label, theme: 'gray' }, limit?.text && limit.text !== 'Unknown' && { label: 'Limit: ' + limit.text.replace(/,000 customers a day$/, 'K/day').replace(' customers a day', '/day'), theme: 'gray' }].filter(Boolean)
}
const checkedText = health => health.checked_at ? 'Checked ' + dateTime(health.checked_at) + '.' : 'Not checked yet.'

onMounted(() => { load(); stop = watchRealtime(['Relay Channel'], ['channels', 'channel_automation'], load, ACCOUNTS_RELOAD_DELAY) })
onBeforeUnmount(() => stop?.())
</script>
<template>
  <section class="whatsapp-accounts" aria-label="WhatsApp accounts">
    <ErrorMessage v-if="error" :message="error" class="whatsapp-accounts-error" />
    <p v-if="notice" role="status" class="whatsapp-accounts-note">{{ notice }}</p>
    <p v-if="!loaded" role="status" class="settings-row">Reading WhatsApp numbers…</p>
    <p v-else-if="!accounts.length && !error" class="settings-row">No WhatsApp number is connected yet.</p>
    <article v-for="row in accounts" :key="row.name" class="whatsapp-account" :class="{ 'is-chosen': canConfigure && accounts.length > 1 && chosen?.name === row.name }">
      <div class="settings-row">
        <span class="settings-row-icon whatsapp"><FeatherIcon name="phone" :size="16" /></span>
        <component :is="canConfigure && accounts.length > 1 ? 'button' : 'span'" :type="canConfigure && accounts.length > 1 ? 'button' : undefined" class="settings-row-text"
          :aria-pressed="canConfigure && accounts.length > 1 ? chosen?.name === row.name : undefined" :title="canConfigure && accounts.length > 1 ? 'Show this number’s settings' : undefined" @click="picked = row.name">
          <b>{{ row.label || metadata[row.name]?.profile?.display_phone_number || row.address }}</b>
          <small>{{ [metadata[row.name]?.profile?.display_phone_number || row.address, metadata[row.name]?.profile?.verified_name].filter(Boolean).join(' · ') }}</small></component>
        <span class="settings-row-end"><Badge v-bind="connectionBadge(row)" /><Badge v-if="row.is_default" label="Default" theme="blue" /><Badge v-for="badge in metaBadges(row)" :key="badge.label" class="whatsapp-meta-badge" v-bind="badge" />
          <a v-if="canConfigure && needsReconnect(row)" class="relay-button relay-button--solid relay-button--sm" :href="setupRoute('number')">Connect again</a>
          <Dropdown v-if="canConfigure" :options="actionsFor(row)"><Button icon="more-horizontal" variant="ghost" :aria-label="`${row.label} actions`" :title="`${row.label} actions`" :loading="busy.startsWith(row.name + ':')" /></Dropdown></span>
      </div>
      <details class="whatsapp-account__more">
        <summary>Account health</summary>
        <ErrorMessage v-if="row.health.check_error" :message="row.health.check_error" />
        <dl class="whatsapp-account__health">
          <div><dt>Messages from Meta</dt><dd>{{ webhookText(row.health) }}</dd></div>
          <div v-for="item in deliveryRows(row.health, dateTime)" :key="item.name"><dt>{{ item.name }}</dt><dd>{{ item.text }}</dd></div>
          <div v-for="item in whatsappHealth(metadata[row.name]?.profile)" :key="item.name"><dt>{{ item.name }}</dt><dd><Badge v-if="item.theme" :label="item.label" :theme="item.theme" /><template v-else>{{ item.text }}</template></dd></div>
        </dl>
        <p>{{ checkedText(row.health) }} {{ syncText(metadata[row.name]) }}</p>
      </details>
    </article>
    <Teleport :to="settingsTarget || 'body'" :disabled="!settingsTarget" defer>
      <section v-if="canConfigure && chosen" class="settings-card whatsapp-number-settings" :aria-label="`${chosen.label} number settings`">
        <header><div><h3>{{ chosen.label || chosen.address }} number</h3><p>How this number behaves in the inbox.<template v-if="accounts.length > 1"> Pick a number above to see its settings.</template></p></div></header>
        <div v-for="item in SWITCHES" :key="item.name" class="settings-row">
          <span class="settings-row-text"><b>{{ item.label }}</b><small>{{ item.name === 'enabled' && adminLocked(chosen) ? ADMIN_OFF_TEXT : item.help }}</small></span>
          <ToggleSwitch :label="item.label" :model-value="switchValue(chosen, item.name)" :disabled="!!busy || (item.name !== 'enabled' && !chosen.enabled) || (item.name === 'enabled' && adminLocked(chosen))" @update:model-value="value => toggle(chosen, item.name, value)" />
        </div>
      </section>
    </Teleport>
    <div class="whatsapp-accounts-foot"><Button variant="outline" icon-left="refresh-cw" label="Refresh" :disabled="!!busy" @click="load" /></div>
    <Dialog :model-value="!!confirming" :options="{ title: confirming?.action === 'pin' ? 'Reset the two-step PIN?' : 'Remove this number?', size: 'md' }" @update:model-value="value => { if (!value) confirming = null }">
      <div v-if="confirming" class="space-y-4 text-sm text-ink-gray-8">
        <p v-if="confirming.action === 'pin'">{{ PIN_TEXT }}</p>
        <p v-else>Relay stops sending and receiving on {{ confirming.row.label }} and deregisters it from the WhatsApp Cloud API. Its chats stay in Relay. To use it again, connect it again.</p>
        <div class="flex justify-end gap-2">
          <Button variant="ghost" label="Cancel" @click="confirming = null" />
          <Button variant="solid" :theme="confirming.action === 'pin' ? 'gray' : 'red'" :label="confirming.action === 'pin' ? 'Reset PIN' : 'Remove number'" @click="confirmed" />
        </div>
      </div>
    </Dialog>
    <WhatsAppProfile v-if="profileOf" :channel="profileOf.name" :label="profileOf.label" @close="profileOf = null" />
  </section>
</template>
<style scoped>
.whatsapp-account { border-bottom:1px solid var(--relay-stroke); }
.whatsapp-account .settings-row { border-bottom:0; }
.whatsapp-accounts-error { margin:12px 16px 0; }
.whatsapp-accounts-note { margin:12px 16px 0; font-size:13px; color:var(--relay-ink-2); }
.whatsapp-account__more { padding:0 16px 10px 62px; font-size:13px; color:var(--relay-ink-3); }
.whatsapp-account__more summary { cursor:pointer; font-size:12.5px; }
.whatsapp-account .settings-row-end :deep(.relay-button--ghost) { width:30px; min-width:30px; height:30px; min-height:30px; padding:0; color:var(--relay-ink-3); }
.whatsapp-account__health { display:grid; gap:8px; margin:8px 0; }
.whatsapp-account__health > div { display:grid; grid-template-columns:170px minmax(0,1fr); align-items:center; gap:12px; }
.whatsapp-account__health dt { color:var(--relay-ink-3); }
.whatsapp-account__health dd { margin:0; color:var(--relay-ink); overflow-wrap:anywhere; }
.whatsapp-account button.settings-row-text { padding:0; border:0; background:none; color:inherit; font:inherit; text-align:left; cursor:pointer; }
.whatsapp-account.is-chosen { background:var(--relay-accent-soft); }
.whatsapp-account button.settings-row-text:focus-visible { outline:2px solid var(--relay-accent); outline-offset:2px; border-radius:4px; }
.whatsapp-accounts-foot { padding:12px 16px; }
/* Phones keep the state and default badges and the menu on one line; quality and limit are in Account health. */
@media (max-width:768px) { .whatsapp-account__more { padding-left:16px; } .whatsapp-account__health > div { grid-template-columns:1fr; gap:2px; }
  .whatsapp-meta-badge { display:none; } .whatsapp-account .settings-row { flex-wrap:nowrap; } .whatsapp-account .settings-row-text { flex:1; min-width:0; }
  .whatsapp-account .settings-row-text > :is(b,small) { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .whatsapp-account .settings-row-end { flex:none; flex-wrap:nowrap; } }
</style>
