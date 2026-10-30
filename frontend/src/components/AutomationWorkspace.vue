<script setup>
import ChoiceField from './fields/ChoiceField.vue'
import { useLoadMore } from '../composables/useLoadMore'
import { recordTitle } from '../services/recordTitle'
import { linkedTitle } from '../services/linkedTitle'
import { computed, inject, onBeforeUnmount, onMounted, nextTick, ref, watch } from 'vue'
import { Badge, Button, Dropdown, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import { configurationChannelOptions, configurationValues, newConfiguration, toolRows, eventDescription, messagePreview, variantPreview, toolCount, referenceName, moveAction, eventErrors, templateField } from '../services/automationEditor'
import EventPicker from './fields/EventPicker.vue'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'
import WorkspaceState from './WorkspaceState.vue'
import LoadingRows from './LoadingRows.vue'
import { useEnabledChannels } from '../composables/useEnabledChannels'
const props = defineProps({ kind: String })
const capabilities = inject('relayCapabilities')
const configurationLinks = [
  { label: 'Models & provider accounts', onClick: () => { location.href = '/desk/ai-model' } },
  { label: 'Fallback handoff owner', onClick: () => { location.href = '/desk/relay-settings' } },
]
const skill = computed(() => props.kind === 'skills')
const pickerMethod = computed(() => skill.value ? 'ai.configuration.editor_options' : 'business_event_options.search')
const allowed = computed(() => Boolean(skill.value ? capabilities.value.ai && capabilities.value.skills : capabilities.value.business_events))
const api = computed(() => skill.value ? 'ai.configuration' : 'business_events')
const channels = ref([]), editor = ref(null)
const channelOptions = computed(() => [{ value: '', label: 'Choose a channel' },
  ...configurationChannelOptions(channels.value, draft.value?.channel)])
const channelProvider = computed(() => channels.value.find(row => row.name === draft.value?.channel)?.channel)
const channelEnabled = useEnabledChannels()
const variant = provider => channelEnabled(provider) && (!!draft.value?.use_preferences || channelProvider.value === provider)
const rows = ref([]), next = ref(null), draft = ref(null), tools = ref([]), parameterFields = ref([])
// Display fixture captions without rewriting the stored title on unrelated saves.
const titleCaption = computed({ get: () => recordTitle(draft.value?.title, ''), set: value => { draft.value.title = value } })
const busy = ref(false), error = ref(''), notice = ref(''), message = ref(''), preview = ref(null)
const reportOptions = ref([])
watch(() => draft.value?.business_doctype, async business => {
  reportOptions.value = []
  if (!skill.value || !business || !allowed.value) return
  try { const result = await coreApi('ai.configuration.editor_options', {kind:'report', business_doctype:business}); if (draft.value?.business_doctype === business) reportOptions.value = result.items }
  catch (e) { error.value = e.message }
})
function chooseReport(tool, value) {
  const selected = reportOptions.value.find(row => row.value === value)
  if (selected) Object.assign(tool, selected.contract)
}
const actionOptions = ref([]), actions = ref([]), validation = ref([]), validationSummary = ref(null), saved = ref('')
const snapshot = () => JSON.stringify([draft.value, tools.value, actions.value])
const dirty = computed(() => snapshot() !== saved.value)
const enabledFilter = ref('all'), templateBody = ref(''), previewError = ref('')
const visibleRows = computed(() => rows.value.filter(row => enabledFilter.value === 'all' || Boolean(row.enabled) === (enabledFilter.value === 'enabled')))
const parameters = computed({ get: () => parameterFields.value.join('\n'), set: value => { parameterFields.value = value ? value.split('\n') : [] } })
const livePreview = computed(() => messagePreview(templateBody.value, parameters.value))
const template = computed(() => draft.value && templateField(draft.value, busy.value, linkedTitle('Relay WhatsApp Template', draft.value.template, 'Saved template')))
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
  if (!allowed.value) return
  const request = ++generation; busy.value = true; error.value = ''
  try {
    const [page, available, catalog] = await Promise.all([coreApi(api.value + '.directory', { after: append ? next.value : null }), coreApi('api.channel_options'), skill.value ? coreApi('ai.configuration.editor_options', {kind:'action'}) : Promise.resolve({items:[]})])
    if (request === generation) { actionOptions.value = catalog.items; channels.value = available.items.filter(row => channelEnabled(row.channel)); rows.value = append ? [...rows.value, ...page.items] : page.items; next.value = page.next }
  } catch (e) { if (request === generation) error.value = e.message }
  finally { if (request === generation) busy.value = false }
}
async function edit(row) {
  draft.value = { ...newConfiguration(skill.value), ...row }; preview.value = null; message.value = ''; notice.value = ''; error.value = ''; validation.value = []
  try { actions.value = JSON.parse(row.allowed_actions || '[]'); tools.value = skill.value ? toolRows(row.allowed_tools).map(tool => ({...tool, identity_anchor: tool.identity_anchor || row.business_doctype})) : []; parameters.value = skill.value ? '' : JSON.parse(row.parameter_mapping || '[]').join('\n') }
  catch { error.value = 'This configuration contains invalid JSON. Repair it in Desk before editing.'; draft.value = null }
  saved.value = snapshot()
  await nextTick()
  if (window.matchMedia('(max-width: 900px)').matches) editor.value?.scrollIntoView({ block:'start' })
}
async function save() {
  validation.value = skill.value ? eventErrors(draft.value, tools.value, actions.value, channelProvider.value) : []
  if (validation.value.length) { await nextTick(); validationSummary.value?.focus(); return }
  busy.value = true; error.value = ''; preview.value = null
  try {
    if (skill.value && draft.value.execution_policy === 'Execute') {
      for (const action of actions.value.filter(row => row.action === 'create_draft')) {
        const options = await coreApi('ai.configuration.editor_options', {kind:'draft_field', action:action.action, doctype:action.doctype})
        const missing = options.items.filter(field => field.required && !action.fields.includes(field.value))
        if (missing.length) validation.value.push('Include required draft fields: ' + missing.map(field => field.label).join(', '))
      }
      if (validation.value.length) { await nextTick(); validationSummary.value?.focus(); return }
    }
    const result = await coreApi(api.value + '.save', { name: draft.value.name, values: configurationValues(draft.value, skill.value, tools.value, parameters.value, actions.value) }, true)
    draft.value.name = result.name; saved.value = snapshot(); notice.value = 'Saved.'; await load()
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
async function test() {
  if (dirty.value || !message.value) return
  busy.value = true; error.value = ''; preview.value = null
  try { preview.value = await coreApi('ai.configuration.test_skill', { name: draft.value.name, message: message.value }, true) }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
watch([draft, tools, actions, message], () => { preview.value = null }, {deep: true})
function addReference() {
  let number = 1
  while (tools.value.some(row => row.name === `reference_${number}`)) number++
  tools.value.push({name: `reference_${number}`, method: 'get_list', doctype: '', fields: [], scope_field: '', identity_anchor: draft.value.business_doctype, identity_fields: {}, company_field: ''})
}
function chooseBusiness(value) { draft.value.business_doctype = value; draft.value.recipient_field = ''; tools.value.forEach(tool => { tool.identity_anchor = value; tool.identity_fields = {}; tool.scope_field = '' }) }
function chooseSource(value) { draft.value.source_doctype = value; draft.value.recipient_field = ''; draft.value.contact_field = ''; draft.value.print_format = ''; draft.value.report_name = ''; parameters.value = '' }
function chooseActionType(row, value) { row.doctype = value; row.fields = [] }
watch(() => props.kind, () => { draft.value = null; rows.value = []; next.value = null; load() })
onMounted(load)
useRealtimeRefresh(['Relay AI Skill', 'Relay Business Event Rule'], ['skills', 'business_events'], () => load())
const moreSentinel = useLoadMore({ loading: busy, hasMore: next, error, load: () => load(true) })
</script>
<template>
  <section class="v1-screen" :class="{ 'event-workspace': skill }"><div class="v1-content space-y-4">
    <p v-if="!allowed">A Relay Communication Manager role is required to configure automation.</p>
    <template v-else>
      <header v-if="skill" class="event-toolbar"><strong>Skills</strong><Dropdown v-if="capabilities.configure" :options="configurationLinks"><Button label="Configure" icon-right="chevron-down" /></Dropdown><Button label="New skill" variant="solid" icon-left="plus" :disabled="busy" @click="edit(newConfiguration(true))" /></header>
      <p v-if="skill && !capabilities.configure" class="workspace-help">Ask a system administrator to configure AI models and the default handoff owner.</p>
      <WorkspaceHeading v-if="!skill" description="Keep customers informed when business documents change."><Button label="New event rule" variant="solid" icon-left="plus" :disabled="busy" @click="edit(newConfiguration(false))" /></WorkspaceHeading>
      <div v-if="!skill" class="workspace-toolbar"><div class="automation-chips" role="group" aria-label="Enabled state"><button v-for="value in ['all', 'enabled', 'disabled']" :key="value" type="button" class="automation-chip" :aria-pressed="enabledFilter === value" @click="enabledFilter = value">{{ value === 'all' ? 'All' : value === 'enabled' ? 'Enabled' : 'Disabled' }}</button></div></div>
      <ErrorMessage v-if="error" :message="error" /><p v-if="notice" role="status">{{ notice }}</p>
      <div class="v1-detail-grid" :class="{ 'v1-detail-grid--browse': !draft, 'event-detail-open': skill && draft }">
        <div class="space-y-3 event-list">
          <div v-if="skill" class="automation-chips" role="group" aria-label="Enabled state"><button v-for="value in ['all', 'enabled', 'disabled']" :key="value" type="button" class="automation-chip" :aria-pressed="enabledFilter === value" @click="enabledFilter = value">{{ value === 'all' ? 'All' : value === 'enabled' ? 'Enabled' : 'Disabled' }}</button></div>
          <LoadingRows v-if="busy && !rows.length" :label="skill ? 'Loading skills…' : 'Loading event rules…'" />
          <button v-for="row in visibleRows" :key="row.name" type="button" :aria-label="(skill ? 'Open skill: ' : 'Open event rule: ') + recordTitle(row, skill ? 'Skill' : 'Event rule')" class="v1-list-card" :aria-pressed="draft?.name === row.name" :disabled="busy" @click="edit(row)">
            <div class="automation-card-heading"><strong>{{ recordTitle(row, skill ? 'Skill' : 'Event rule') }}</strong><Badge :label="row.enabled ? 'Enabled' : 'Disabled'" :theme="row.enabled ? 'green' : 'gray'" /></div>
            <span v-if="skill && row.sample_key === 'relay-default-skill'">Default fallback for this channel and business type</span>
            <span v-if="skill">{{ row.business_doctype }} · {{ row.mode }} · {{ linkedTitle('Relay Channel', row.channel, 'Choose a channel') }} · {{ toolCount(row.allowed_tools) }} {{ toolCount(row.allowed_tools) === 1 ? 'reference' : 'references' }}</span>
            <span v-else>{{ eventDescription(row) }}</span>
          </button>
          <WorkspaceState v-if="!visibleRows.length && !busy && !error" :title="(rows.length ? 'No matching ' : 'No ') + (skill ? 'skills' : 'event rules') + (rows.length ? '' : ' yet')" :description="rows.length ? 'Change the filter to see other configurations.' : 'Create one when you need it. It starts disabled until you enable it.'" :icon="skill ? 'bot' : 'zap'"><Button :label="skill ? 'New skill' : 'New event rule'" variant="solid" icon-left="plus" @click="edit(newConfiguration(skill))" /></WorkspaceState>
          <div v-if="next" ref="moreSentinel" class="h-px" aria-hidden="true" />
        </div>
        <form v-if="draft" ref="editor" class="workflow-card min-w-0" @submit.prevent="save">
          <div class="automation-card-heading"><h2 class="font-semibold">{{ draft.name ? 'Edit' : 'New' }} {{ skill ? 'skill' : 'event rule' }}</h2><Button icon="x" aria-label="Dismiss editor" title="Dismiss editor" :disabled="busy" @click="draft = null" /></div>
          <FormControl v-model="titleCaption" label="Title" required :disabled="busy" />
          <div class="grid gap-3 sm:grid-cols-2"><EventPicker :model-value="draft.business_doctype" label="Business type" kind="business_doctype" :method="pickerMethod" :disabled="busy" @update:model-value="chooseBusiness" /><ChoiceField v-model="draft.channel" :field="{ label: 'Channel', options: channelOptions, readOnly: busy || !!draft.use_preferences }" /><FormControl v-model="draft.enabled" type="checkbox" label="Enabled" :disabled="busy" /></div>
          <template v-if="skill">
            <fieldset class="automation-section"><legend>Owner instructions</legend>
              <FormControl v-model="draft.target" label="Target" type="textarea" rows="2" maxlength="2000" :required="Boolean(draft.enabled)" :disabled="busy" />
              <FormControl v-model="draft.instructions" label="Skill instructions" type="textarea" rows="4" maxlength="8000" required :disabled="busy" />
              <FormControl v-model="draft.reply_style" label="Reply style" type="textarea" rows="2" maxlength="2000" :disabled="busy" />
              <FormControl v-model="draft.exact_trigger" label="Exact trigger (optional)" maxlength="140" :disabled="busy" />
            </fieldset>
            <fieldset class="automation-section"><legend>Configured reports · SEARCH</legend>
              <p class="text-sm">Only the authenticated sender’s records in this company can be searched. A number typed in a message grants no access.</p>
              <div v-for="(tool, index) in tools" :key="tool.name" class="event-reference">
                <div class="automation-card-heading"><strong>{{ referenceName(tool.name) }}</strong><Button label="Remove report" :disabled="busy" @click="tools.splice(index, 1)" /></div>
                <FormControl :model-value="tool.report || ''" label="Configured report" type="select" :options="[{value:'',label:'Choose a report'}, ...reportOptions]" :disabled="busy" @update:model-value="value => chooseReport(tool, value)" />
                <p v-if="!tool.report" class="text-sm">Choose a report. Legacy record references are unavailable to the AI.</p>
                <EventPicker v-if="channelProvider" v-model="tool.identity_fields[channelProvider]" :label="channelProvider + ' identity field'" kind="identity" :doctype="draft.business_doctype" :disabled="busy || !draft.business_doctype" />
                <p v-else class="text-sm">Choose a channel to map its authenticated sender identity.</p>
                <p v-if="tool.report" class="text-sm">Report fields and company scope are fixed. Ledger date ranges require confirmation.</p>
              </div>
              <Button label="Add report" :disabled="busy || tools.length >= 12 || !draft.business_doctype" @click="addReference" />
              <FormControl v-model="draft.search_confirmation" label="Search confirmation" type="select" :options="['Always', 'When required']" :disabled="busy" />
              <p class="text-sm">Searches are announced first. Ledger searches always require date-range confirmation.</p>
            </fieldset>
            <fieldset class="automation-section"><legend>Actions · EXECUTE</legend>
              <FormControl v-model="draft.execution_policy" label="Execution policy" type="select" :options="['Ticket only', 'Execute']" :disabled="busy" />
              <p v-if="draft.execution_policy === 'Ticket only'" class="text-sm">Only raise the conversation ticket.</p>
              <template v-else>
                <p class="text-sm">Follow the written steps in this order. Every created document stays a draft linked to the conversation ticket. Staff open, check and submit it.</p>
                <div v-for="(action, index) in actions" :key="action.action" class="event-reference">
                  <strong>{{ index + 1 }}. {{ referenceName(action.action) }}</strong>
                  <template v-if="action.action === 'create_draft'">
                    <EventPicker :model-value="action.doctype" label="Draft DocType" kind="draft_doctype" :action="action.action" :disabled="busy" @update:model-value="value => chooseActionType(action, value)" />
                    <EventPicker v-model="action.fields" label="Draft fields (include required fields)" kind="draft_field" :action="action.action" :doctype="action.doctype" multiple :disabled="busy || !action.doctype" />
                    <p class="text-sm">Field types are shown in the picker. Required fields must be included. Staff review and submit the linked draft.</p>
                  </template>
                  <p v-else class="text-sm">Reply to the sender in this conversation. No separate approval required.</p>
                  <p class="text-sm">Execution approval: {{ actionOptions.find(row => row.value === action.action)?.approval || 'Not required' }}</p>
                  <div class="event-action-buttons"><Button label="Move up" :disabled="busy || index === 0" @click="moveAction(actions, index, -1)" /><Button label="Move down" :disabled="busy || index === actions.length - 1" @click="moveAction(actions, index, 1)" /><Button label="Remove action" :disabled="busy" @click="actions.splice(index, 1)" /></div>
                </div>
                <div class="event-action-buttons"><Button v-for="option in actionOptions" :key="option.value" :label="'Add ' + option.label.toLowerCase()" :disabled="busy || actions.some(row => row.action === option.value)" @click="actions.push(option.value === 'reply' ? {action:option.value} : {action:option.value, doctype:'', fields:[]})" /></div>
              </template>
            </fieldset>
            <fieldset class="automation-section"><legend>Operation</legend>
              <EventPicker v-model="draft.handoff_owner" label="Handoff owner" kind="user" :disabled="busy" />
              <EventPicker v-model="draft.ai_model" label="AI Model" kind="model" :skill="draft.name" :disabled="busy" />
              <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.mode" label="Mode" type="select" :options="['Shadow', 'Automatic']" :disabled="busy" /><FormControl v-model="draft.daily_limit" label="Daily model limit" type="number" min="1" max="1000" :disabled="busy" /></div>
              <p class="text-sm">Shadow creates the live ticket and records proposals, without automatic replies or business writes.</p>
            </fieldset>
          </template>
          <template v-else>
            <div class="grid gap-3 sm:grid-cols-2"><EventPicker :model-value="draft.source_doctype" @update:model-value="chooseSource" label="Source DocType" kind="doctype" :method="pickerMethod" :disabled="busy" /><FormControl v-model="draft.event" label="Event" type="select" :options="[{ label: 'On submit', value: 'on_submit' }, { label: 'When created', value: 'after_insert' }, { label: 'On cancel', value: 'on_cancel' }]" :disabled="busy" /><EventPicker v-model="draft.recipient_field" label="Recipient business field" kind="recipient_field" :method="pickerMethod" :doctype="draft.source_doctype" :business-doctype="draft.business_doctype" :disabled="busy || !draft.source_doctype || !draft.business_doctype" /><RemoteLinkField v-if="variant('WhatsApp')" v-model="draft.template" :field="template" /></div>
            <FormControl v-model="draft.use_preferences" type="checkbox" label="Use this business/person’s consent and channel priorities" :disabled="busy" />
            <RemoteLinkField v-model="draft.contact" :field="{ label: 'Explicit Contact (required when several people are linked)', method: 'api.contact_directory', doctype: 'Contact', readOnly: busy }" />
            <FormControl v-if="variant('Telegram')" v-model="draft.telegram_body" label="Telegram template" type="textarea" rows="4" :disabled="busy" />
            <template v-if="variant('Email')"><FormControl v-model="draft.email_subject" label="Email subject template" :disabled="busy" /><FormControl v-model="draft.email_body" label="Email body template" type="textarea" rows="5" :disabled="busy" /><FormControl v-model="draft.email_signature" label="Email signature" type="textarea" :disabled="busy" maxlength="2000" /></template>
            <fieldset class="automation-section"><legend>Template parameters in order</legend>
              <div v-for="(value, index) in parameterFields" :key="index" class="flex items-end gap-2"><EventPicker class="flex-1" :model-value="value" :label="'Parameter ' + (index + 1)" kind="field" :method="pickerMethod" :doctype="draft.source_doctype" :disabled="busy || !draft.source_doctype" @update:model-value="parameterFields[index] = $event" /><Button label="Remove parameter" :disabled="busy" @click="parameterFields.splice(index, 1)" /></div>
              <Button label="Add parameter" :disabled="busy || !draft.source_doctype || parameterFields.length >= 20" @click="parameterFields.push('')" />
            </fieldset><p class="text-sm">Use name, total_qty, or other source fields. items_summary includes each item’s quantity and UOM. Choose a Contact when several people belong to the business. <template v-if="variant('Telegram') || variant('Email')">Telegram and email use {field} placeholders from this list; email content is escaped.</template> Consent is required. An uncertain send never switches channels.</p>
            <fieldset class="automation-section"><legend>Condition, recipients and PDF</legend>
              <FormControl v-model="draft.condition" label="Condition (optional)" placeholder="doc.commitment_level_label" :disabled="busy" />
              <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.recipients" label="Recipients" type="select" :options="[{ label: 'The only linked contact', value: '' }, 'Primary contact', 'All business contacts', 'Document contact field']" :disabled="busy" /><EventPicker v-if="draft.recipients === 'Document contact field'" v-model="draft.contact_field" label="Contact field" kind="contact_field" :method="pickerMethod" :doctype="draft.source_doctype" :disabled="busy || !draft.source_doctype" />
              <FormControl v-model="draft.attachment_type" label="Attach PDF" type="select" :options="[{ label: 'No PDF', value: '' }, 'Print Format', 'Report']" :disabled="busy" /><EventPicker v-if="draft.attachment_type === 'Print Format'" v-model="draft.print_format" label="Print format" kind="print_format" :method="pickerMethod" :doctype="draft.source_doctype" :disabled="busy || !draft.source_doctype" /><EventPicker v-if="draft.attachment_type === 'Report'" v-model="draft.report_name" label="Report" kind="report" :method="pickerMethod" :doctype="draft.source_doctype" :disabled="busy || !draft.source_doctype" /><FormControl v-if="draft.attachment_type" v-model="draft.file_name" label="File name" placeholder="Order_{{doc.name}}.pdf" :disabled="busy" /></div>
              <FormControl v-if="draft.attachment_type === 'Report'" v-model="draft.report_filters" label="Report filters (JSON)" type="textarea" rows="3" placeholder='{"customer": "{{doc.customer}}"}' :disabled="busy" />
              <p class="text-sm">The PDF goes in the template's document header, or as a document message after the template when the template has no document header. Recipient choices and PDFs need a fixed WhatsApp channel.</p>
            </fieldset>
          </template>
          <fieldset class="automation-section"><legend>Run-as user</legend><EventPicker v-model="draft.run_as_user" label="Run-as user" kind="user" :method="pickerMethod" :disabled="busy" /><p v-if="skill" class="text-sm">Use the sender’s linked user account when available; otherwise use this account. If that account lacks permission, the action stops.</p><p v-else class="text-sm">Reads and delivery follow this user’s permissions.</p></fieldset>
          <aside v-if="!skill" class="automation-preview space-y-3" aria-label="Message preview"><h3 class="font-semibold">Live message preview</h3><p class="text-sm">{{ eventDescription(draft) }}</p><ErrorMessage :message="previewError" /><p class="whitespace-pre-wrap">{{ variant('WhatsApp') ? livePreview : '' }}</p><p v-if="variant('Telegram')" class="whitespace-pre-wrap">Telegram: {{ variantPreview(draft.telegram_body, parameters) }}</p><p v-if="variant('Email')" class="whitespace-pre-wrap">Email: {{ variantPreview(draft.email_subject, parameters) }}
{{ variantPreview(draft.email_body, parameters) }}
{{ draft.email_signature }}</p><p class="text-sm">Bracketed fields are replaced with the submitted document’s values.</p></aside>
          <ul v-if="validation.length" ref="validationSummary" tabindex="-1" role="alert" class="event-validation"><li v-for="issue in validation" :key="issue">{{ issue }}</li></ul>
          <Button type="submit" label="Save" variant="solid" :loading="busy" />
          <div v-if="skill && draft.name" class="automation-section"><h3 class="font-semibold">Test skill</h3><p class="text-sm">Tests the saved skill. Sends nothing and creates no ticket, approval or business document.</p>
            <p v-if="dirty" role="status">Save your changes before testing.</p>
            <EventPicker v-model="message" label="Incoming message" kind="message" :skill="draft.name" :disabled="busy || dirty" />
            <Button label="Run preview" :disabled="busy || dirty || !message" @click="test" />
            <div v-if="preview" role="status" class="automation-preview space-y-2"><Badge label="Non-sending preview" theme="blue" />
              <p v-if="preview.identity_scope"><strong>Identity scope:</strong> {{ preview.identity_scope.identity }} · {{ preview.identity_scope.provider }} · {{ preview.identity_scope.company }} · {{ preview.identity_scope.business_type }} · {{ preview.identity_scope.execution_user }}</p>
              <p v-if="preview.match"><strong>Match:</strong> {{ preview.match.selected || 'Company triage' }} · {{ preview.match.reason }}</p>
              <p>{{ preview.reason }}</p><p class="whitespace-pre-wrap">{{ preview.reply }}</p>
              <div v-if="preview.search"><strong>Proposed SEARCH:</strong><p>{{ preview.search.purpose }}</p><p>{{ referenceName(preview.search.reference) }} · {{ preview.search.fields.map(referenceName).join(', ') }}</p><p v-for="(value, key) in preview.search.arguments?.filters || {}" :key="key">{{ referenceName(key) }}: {{ Array.isArray(value) ? value.flat().join(' · ') : value }}</p></div>
              <div v-for="(action, index) in preview.actions || []" :key="index"><strong>{{ index + 1 }}. Proposed {{ referenceName(action.action) }}</strong><p v-for="(value, key) in action.parameters" :key="key">{{ referenceName(key) }}: {{ value }}</p></div>
              <p v-if="!(preview.actions || []).length">No proposed writes.</p>
            </div>
          </div>
        </form>
      </div>
    </template>
  </div></section>
</template>

<style scoped>
.event-toolbar { display:flex; align-items:center; gap:8px; min-height:44px; }
.event-toolbar > strong { flex:1; }
.event-workspace .v1-detail-grid { grid-template-columns:minmax(220px, 28%) minmax(0, 1fr); }
.event-workspace .v1-detail-grid--browse { grid-template-columns:1fr; }
.event-workspace .event-list { display:flex; flex-direction:column; gap:8px; }
.event-workspace .event-list > * { flex-shrink:0; margin:0; }
.event-workspace .event-list .automation-chips { flex:none; }
.event-reference { display:grid; gap:10px; padding:12px; border:1px solid var(--outline-gray-2); border-radius:8px; min-width:0; }
.event-action-buttons { display:flex; flex-wrap:wrap; gap:8px; }
.event-validation { color:var(--ink-red-2); padding:8px; }
@media(max-width:900px) {
  .event-workspace .v1-detail-grid { grid-template-columns:1fr; grid-template-rows:minmax(0, 1fr); }
  .event-detail-open > .event-list { display:none; }
}
</style>
