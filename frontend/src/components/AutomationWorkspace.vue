<script setup>
import { recordTitle } from '../services/recordTitle'
import { linkedTitle } from '../services/linkedTitle'
import { computed, inject, onBeforeUnmount, onMounted, nextTick, ref, watch } from 'vue'
import { Badge, Button, Dropdown, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import { configurationChannels, configurationValues, newConfiguration, toolRows, eventDescription, messagePreview, variantPreview, toolCount } from '../services/automationEditor'
import WorkspaceHeading from './WorkspaceHeading.vue'
import WorkspaceState from './WorkspaceState.vue'
import LoadingRows from './LoadingRows.vue'
const props = defineProps({ kind: String })
const capabilities = inject('relayCapabilities')
const configurationLinks = [
  { label: 'Models & provider accounts', onClick: () => { location.href = '/desk/ai-model' } },
  { label: 'Fallback handoff owner', onClick: () => { location.href = '/desk/relay-settings' } },
]
const skill = computed(() => props.kind === 'skills')
const api = computed(() => skill.value ? 'ai.configuration' : 'business_events')
const channels = ref([]), editor = ref(null)
const channelOptions = computed(() => [{ value: '', label: 'Choose a channel' },
  ...configurationChannels(channels.value, draft.value?.channel).map(row => ({
    value: row.name, label: linkedTitle('Relay Channel', row.name, row.title || row.channel || 'Saved channel'),
  }))])
const channelProvider = computed(() => channels.value.find(row => row.name === draft.value?.channel)?.channel)
const variant = provider => !!draft.value?.use_preferences || channelProvider.value === provider
const rows = ref([]), next = ref(null), draft = ref(null), tools = ref([]), parameters = ref('')
const busy = ref(false), error = ref(''), notice = ref(''), message = ref(''), preview = ref(null)
const enabledFilter = ref('all'), templateBody = ref(''), previewError = ref('')
const visibleRows = computed(() => rows.value.filter(row => enabledFilter.value === 'all' || Boolean(row.enabled) === (enabledFilter.value === 'enabled')))
const livePreview = computed(() => messagePreview(templateBody.value, parameters.value))
let generation = 0, previewGeneration = 0, previewTimer
watch(() => draft.value?.template, name => {
  clearTimeout(previewTimer); const current = ++previewGeneration; templateBody.value = ''; previewError.value = ''
  if (!name || skill.value) return
  previewTimer = setTimeout(async () => {
    try { const result = await coreApi('business_events.template_preview', { name }); if (current === previewGeneration) templateBody.value = result.body }
    catch (e) { if (current === previewGeneration) previewError.value = e.message }
  }, 300)
})
onBeforeUnmount(() => { clearTimeout(previewTimer); ++previewGeneration; ++generation })
async function load(append = false) {
  if (!capabilities.value.configure) return
  const request = ++generation; busy.value = true; error.value = ''
  try {
    const [page, available] = await Promise.all([coreApi(api.value + '.directory', { after: append ? next.value : null }), coreApi('api.channel_options')])
    if (request === generation) { channels.value = available.items; rows.value = append ? [...rows.value, ...page.items] : page.items; next.value = page.next }
  } catch (e) { if (request === generation) error.value = e.message }
  finally { if (request === generation) busy.value = false }
}
async function edit(row) {
  draft.value = { ...row }; preview.value = null; notice.value = ''; error.value = ''
  try { tools.value = skill.value ? toolRows(row.allowed_tools) : []; parameters.value = skill.value ? '' : JSON.parse(row.parameter_mapping || '[]').join('\n') }
  catch { error.value = 'This configuration contains invalid JSON. Repair it in Desk before editing.'; draft.value = null }
  await nextTick()
  if (window.matchMedia('(max-width: 900px)').matches) editor.value?.scrollIntoView({ block:'start' })
}
async function save() {
  busy.value = true; error.value = ''; preview.value = null
  try {
    const result = await coreApi(api.value + '.save', { name: draft.value.name, values: configurationValues(draft.value, skill.value, tools.value, parameters.value) }, true)
    draft.value.name = result.name; notice.value = 'Saved.'; await load()
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
async function test() {
  busy.value = true; error.value = ''; preview.value = null
  try { preview.value = await coreApi('ai.configuration.test_skill', { name: draft.value.name, message: message.value }, true) }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
watch(() => props.kind, () => { draft.value = null; rows.value = []; next.value = null; load() })
onMounted(load)
useRealtimeRefresh(['Relay AI Skill', 'Relay Business Event Rule'], ['skills', 'business_events'], () => load())
</script>
<template>
  <section class="v1-screen"><div class="v1-content space-y-4">
    <p v-if="!capabilities.configure">A System Manager role is required to configure automation.</p>
    <template v-else>
      <WorkspaceHeading :description="skill ? 'Give each assistant a clear purpose, safe read tools and a human owner.' : 'Keep customers informed when business documents change.'"><Button :label="skill ? 'New skill' : 'New event rule'" :disabled="busy" @click="edit(newConfiguration(skill))" /></WorkspaceHeading><div class="workspace-toolbar"><Dropdown v-if="skill" :options="configurationLinks"><Button label="Configure" icon-right="chevron-down" aria-label="AI configuration" /></Dropdown>
      <div class="automation-chips" role="group" aria-label="Enabled state"><button v-for="value in ['all', 'enabled', 'disabled']" :key="value" type="button" class="automation-chip" :aria-pressed="enabledFilter === value" @click="enabledFilter = value">{{ value === 'all' ? 'All' : value === 'enabled' ? 'Enabled' : 'Disabled' }}</button></div></div><ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p>
      <div class="v1-detail-grid" :class="{ 'v1-detail-grid--browse': !draft }">
        <div class="space-y-3">
          <LoadingRows v-if="busy && !rows.length" :label="skill ? 'Loading skills…' : 'Loading event rules…'" />
          <button v-for="row in visibleRows" :key="row.name" class="v1-list-card" :aria-pressed="draft?.name === row.name" :disabled="busy" @click="edit(row)">
            <div class="automation-card-heading"><strong>{{ recordTitle(row, skill ? 'Skill' : 'Event rule') }}</strong><Badge :label="row.enabled ? 'Enabled' : 'Disabled'" :theme="row.enabled ? 'green' : 'gray'" /></div>
            <span v-if="skill">{{ row.business_doctype }} · {{ row.mode }} · {{ linkedTitle('Relay Channel', row.channel, 'Choose a channel') }} · {{ toolCount(row.allowed_tools) }} {{ toolCount(row.allowed_tools) === 1 ? 'tool' : 'tools' }}</span>
            <span v-else>{{ eventDescription(row) }}</span>
          </button>
          <WorkspaceState v-if="!visibleRows.length && !busy && !error" :title="skill ? 'No matching skills' : 'No matching event rules'" description="Start with a disabled configuration and enable it when ready." :icon="skill ? 'bot' : 'zap'"><Button :label="skill ? 'New skill' : 'New event rule'" @click="edit(newConfiguration(skill))" /></WorkspaceState>
          <Button v-if="next" label="Load more" :disabled="busy" @click="load(true)" />
        </div>
        <form v-if="draft" ref="editor" class="workflow-card min-w-0" @submit.prevent="save">
          <div class="automation-card-heading"><h2 class="font-semibold">{{ draft.name ? 'Edit' : 'New' }} {{ skill ? 'skill' : 'event rule' }}</h2><Button label="Dismiss" :disabled="busy" @click="draft = null" /></div>
          <FormControl v-model="draft.title" label="Title" required :disabled="busy" />
          <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.business_doctype" label="Business type" placeholder="Supplier or Customer" required :disabled="busy" /><FormControl v-model="draft.channel" label="Channel" type="select" :options="channelOptions" :required="Boolean(draft.enabled) && !draft.use_preferences" :disabled="busy || !!draft.use_preferences" /><FormControl v-model="draft.enabled" type="checkbox" label="Enabled" :disabled="busy" /></div>
          <template v-if="skill">
            <fieldset class="automation-section"><legend>Instructions</legend><FormControl v-model="draft.instructions" label="Knowledge and instructions" type="textarea" rows="7" required :disabled="busy" /></fieldset>
            <fieldset class="automation-section"><legend>Read tools</legend><p class="text-sm">Each tool is restricted to this conversation’s business record. Use a Link or Dynamic Link field to that business, or name when reading the business itself.</p>
              <div v-for="(tool, index) in tools" :key="index" class="border rounded p-3 grid gap-3 sm:grid-cols-2"><FormControl v-model="tool.name" label="Tool name" required :disabled="busy" /><FormControl v-model="tool.method" label="Read operation" type="select" :options="['get_doc', 'get_list']" :disabled="busy" /><FormControl v-model="tool.doctype" label="Allowed DocType" required :disabled="busy" /><FormControl v-model="tool.scope_field" label="Business link field" required :disabled="busy" /><FormControl v-model="tool.fields" label="Readable fields (comma separated)" required :disabled="busy" /><Button label="Remove tool" :disabled="busy" @click="tools.splice(index, 1)" /></div>
              <Button label="Add read tool" :disabled="busy || tools.length >= 12" @click="tools.push({ name: '', method: 'get_list', doctype: '', scope_field: '', fields: 'name' })" />
            </fieldset>
            <fieldset class="automation-section"><legend>Handoff owner</legend><FormControl v-model="draft.handoff_owner" label="Owner’s user email" :required="Boolean(draft.enabled)" :disabled="busy" /><p class="text-sm">Requests outside this skill become tickets assigned to this person.</p></fieldset>
            <fieldset class="automation-section"><legend>Model</legend><FormControl v-model="draft.ai_model" label="AI Model" :required="Boolean(draft.enabled)" :disabled="busy" /><div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.mode" label="Mode" type="select" :options="['Shadow', 'Automatic']" :disabled="busy" /><FormControl v-model="draft.daily_limit" label="Daily model limit" type="number" min="1" max="1000" :disabled="busy" /></div></fieldset>
          </template>
          <template v-else>
            <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.source_doctype" label="Source DocType" placeholder="Delivery Note" required :disabled="busy" /><FormControl v-model="draft.event" label="Event" type="select" :options="[{ label: 'On submit', value: 'on_submit' }, { label: 'When created', value: 'after_insert' }, { label: 'On cancel', value: 'on_cancel' }]" :disabled="busy" /><FormControl v-model="draft.recipient_field" label="Recipient business field" placeholder="customer" required :disabled="busy" /><FormControl v-if="variant('WhatsApp')" v-model="draft.template" label="Approved WhatsApp template" :required="Boolean(draft.enabled) && !draft.use_preferences" :disabled="busy" /></div>
            <FormControl v-model="draft.use_preferences" type="checkbox" label="Use this business/person’s consent and channel priorities" :disabled="busy" />
            <FormControl v-model="draft.contact" label="Explicit Contact (required when several people are linked)" :disabled="busy" />
            <FormControl v-if="variant('Telegram')" v-model="draft.telegram_body" label="Telegram template" type="textarea" rows="4" :disabled="busy" />
            <template v-if="variant('Email')"><FormControl v-model="draft.email_subject" label="Email subject template" :disabled="busy" /><FormControl v-model="draft.email_body" label="Email body template" type="textarea" rows="5" :disabled="busy" /><FormControl v-model="draft.email_signature" label="Email signature" type="textarea" :disabled="busy" maxlength="2000" /></template>
            <FormControl v-model="parameters" label="Template parameters in order (one source field per line)" type="textarea" rows="4" :disabled="busy" /><p class="text-sm">Use name, total_qty, or other source fields. items_summary includes each item’s quantity and UOM. Choose a Contact when several people belong to the business. Telegram and email use {field} placeholders from this list; email content is escaped. Consent is required. An uncertain send never switches channels.</p>
          </template>
          <fieldset class="automation-section"><legend>Run-as user</legend><FormControl v-model="draft.run_as_user" label="User email" :required="Boolean(draft.enabled)" :disabled="busy" /><p class="text-sm">Reads and delivery follow this user’s permissions.</p></fieldset>
          <aside v-if="!skill" class="automation-preview space-y-3" aria-label="Message preview"><h3 class="font-semibold">Live message preview</h3><p class="text-sm">{{ eventDescription(draft) }}</p><ErrorMessage :message="previewError" /><p class="whitespace-pre-wrap">{{ variant('WhatsApp') ? livePreview : '' }}</p><p v-if="variant('Telegram')" class="whitespace-pre-wrap">Telegram: {{ variantPreview(draft.telegram_body, parameters) }}</p><p v-if="variant('Email')" class="whitespace-pre-wrap">Email: {{ variantPreview(draft.email_subject, parameters) }}
{{ variantPreview(draft.email_body, parameters) }}
{{ draft.email_signature }}</p><p class="text-sm">Bracketed fields are replaced with the submitted document’s values.</p></aside>
          <Button type="submit" label="Save" variant="solid" :loading="busy" />
          <div v-if="skill && draft.name" class="border-t pt-4 space-y-3"><h3 class="font-semibold">Test skill</h3><p class="text-sm">Tests the saved skill against an incoming conversation message. No reply is sent and no ticket or pause is created.</p><FormControl v-model="message" label="Incoming message reference" placeholder="RELAY-MSG-…" :disabled="busy" /><Button label="Run shadow test" :disabled="busy || !message" @click="test" /><div v-if="preview" role="status" class="automation-preview space-y-2"><Badge label="Shadow result" theme="blue" /><strong>{{ preview.handoff ? 'Would hand off' : 'Would reply' }}</strong><p class="whitespace-pre-wrap">{{ preview.reply }}</p><p>{{ preview.reason }}</p></div></div>
        </form>
      </div>
    </template>
  </div></section>
</template>
