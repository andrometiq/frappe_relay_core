<script setup>
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Badge, Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import { configurationValues, newConfiguration, toolRows, eventDescription, messagePreview, toolCount } from '../services/automationEditor'
import WorkspaceHeading from './WorkspaceHeading.vue'
import WorkspaceState from './WorkspaceState.vue'
import LoadingRows from './LoadingRows.vue'
const props = defineProps({ kind: String })
const capabilities = inject('relayCapabilities')
const skill = computed(() => props.kind === 'skills')
const api = computed(() => skill.value ? 'ai.configuration' : 'business_events')
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
    const page = await coreApi(api.value + '.directory', { after: append ? next.value : null })
    if (request === generation) { rows.value = append ? [...rows.value, ...page.items] : page.items; next.value = page.next }
  } catch (e) { if (request === generation) error.value = e.message }
  finally { if (request === generation) busy.value = false }
}
function edit(row) {
  draft.value = { ...row }; preview.value = null; notice.value = ''; error.value = ''
  try { tools.value = skill.value ? toolRows(row.allowed_tools) : []; parameters.value = skill.value ? '' : JSON.parse(row.parameter_mapping || '[]').join('\n') }
  catch { error.value = 'This configuration contains invalid JSON. Repair it in Desk before editing.'; draft.value = null }
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
      <WorkspaceHeading :title="skill ? 'AI & skills' : 'Business events'" :description="skill ? 'Give each assistant a clear purpose, safe read tools and a human owner.' : 'Keep customers informed when business documents change.'" :icon="skill ? 'bot' : 'zap'"><Button :label="skill ? 'New skill' : 'New event rule'" :disabled="busy" @click="edit(newConfiguration(skill))" /></WorkspaceHeading><div v-if="skill" class="flex flex-wrap gap-3"><a class="v1-link" href="/desk/ai-model">Manage AI Models & provider accounts</a><a v-if="skill" class="v1-link" href="/desk/relay-settings">Set fallback handoff owner</a></div>
      <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p><div class="automation-chips" role="group" aria-label="Enabled state"><button v-for="value in ['all', 'enabled', 'disabled']" :key="value" type="button" class="automation-chip" :aria-pressed="enabledFilter === value" @click="enabledFilter = value">{{ value === 'all' ? 'All' : value === 'enabled' ? 'Enabled' : 'Disabled' }}</button></div>
      <div class="v1-detail-grid">
        <div class="space-y-3">
          <LoadingRows v-if="busy && !rows.length" :label="skill ? 'Loading skills…' : 'Loading event rules…'" />
          <button v-for="row in visibleRows" :key="row.name" class="v1-list-card" :aria-pressed="draft?.name === row.name" :disabled="busy" @click="edit(row)">
            <div class="automation-card-heading"><strong>{{ row.title }}</strong><Badge :label="row.enabled ? 'Enabled' : 'Disabled'" :theme="row.enabled ? 'green' : 'gray'" /></div>
            <template v-if="skill"><span>{{ row.business_doctype }} · {{ row.mode }}</span><span>{{ row.ai_model || 'Choose a model' }}</span><span>{{ toolCount(row.allowed_tools) }} read tools</span></template>
            <span v-else>{{ eventDescription(row) }}</span>
          </button>
          <WorkspaceState v-if="!visibleRows.length && !busy && !error" :title="skill ? 'No matching skills' : 'No matching event rules'" description="Start with a disabled configuration and enable it when ready." :icon="skill ? 'bot' : 'zap'"><Button :label="skill ? 'New skill' : 'New event rule'" @click="edit(newConfiguration(skill))" /></WorkspaceState>
          <Button v-if="next" label="Load more" :disabled="busy" @click="load(true)" />
        </div>
        <form v-if="draft" class="workflow-card min-w-0" @submit.prevent="save">
          <div class="automation-card-heading"><h2 class="font-semibold">{{ draft.name ? 'Edit' : 'New' }} {{ skill ? 'skill' : 'event rule' }}</h2><Button label="Dismiss" :disabled="busy" @click="draft = null" /></div>
          <FormControl v-model="draft.title" label="Title" required :disabled="busy" />
          <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.business_doctype" label="Business type" placeholder="Supplier or Customer" required :disabled="busy" /><FormControl v-model="draft.channel" label="WhatsApp channel" :required="Boolean(draft.enabled)" :disabled="busy" /><FormControl v-model="draft.enabled" type="checkbox" label="Enabled" :disabled="busy" /></div>
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
            <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.source_doctype" label="Source DocType" placeholder="Delivery Note" required :disabled="busy" /><FormControl v-model="draft.event" label="Event" type="select" :options="[{ label: 'On submit', value: 'on_submit' }, { label: 'When created', value: 'after_insert' }, { label: 'On cancel', value: 'on_cancel' }]" :disabled="busy" /><FormControl v-model="draft.recipient_field" label="Recipient business field" placeholder="customer" required :disabled="busy" /><FormControl v-model="draft.template" label="Approved WhatsApp template" :required="Boolean(draft.enabled)" :disabled="busy" /></div>
            <FormControl v-model="parameters" label="Template parameters in order (one source field per line)" type="textarea" rows="4" :disabled="busy" /><p class="text-sm">Use name, total_qty, or other source fields. items_summary includes each item’s quantity and UOM. The business must have exactly one linked Contact.</p>
          </template>
          <fieldset class="automation-section"><legend>Run-as user</legend><FormControl v-model="draft.run_as_user" label="User email" :required="Boolean(draft.enabled)" :disabled="busy" /><p class="text-sm">Reads and delivery follow this user’s permissions.</p></fieldset>
          <aside v-if="!skill" class="automation-preview space-y-3" aria-label="Message preview"><h3 class="font-semibold">Live message preview</h3><p class="text-sm">{{ eventDescription(draft) }}</p><ErrorMessage :message="previewError" /><p class="whitespace-pre-wrap">{{ livePreview || 'Choose an approved template to preview its wording.' }}</p><p class="text-sm">Bracketed fields are replaced with the submitted document’s values.</p></aside>
          <Button type="submit" label="Save" variant="solid" :loading="busy" />
          <div v-if="skill && draft.name" class="border-t pt-4 space-y-3"><h3 class="font-semibold">Test skill</h3><p class="text-sm">Tests the saved skill against an incoming conversation message. No reply is sent and no ticket or pause is created.</p><FormControl v-model="message" label="Incoming message reference" placeholder="RELAY-MSG-…" :disabled="busy" /><Button label="Run shadow test" :disabled="busy || !message" @click="test" /><div v-if="preview" role="status" class="automation-preview space-y-2"><Badge label="Shadow result" theme="blue" /><strong>{{ preview.handoff ? 'Would hand off' : 'Would reply' }}</strong><p class="whitespace-pre-wrap">{{ preview.reply }}</p><p>{{ preview.reason }}</p></div></div>
        </form><WorkspaceState v-else :title="skill ? 'A focused assistant' : 'Messages at the right moment'" description="Select a card to review its configuration." :icon="skill ? 'bot' : 'zap'" />
      </div>
    </template>
  </div></section>
</template>
