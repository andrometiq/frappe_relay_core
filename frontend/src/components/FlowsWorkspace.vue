<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Badge, Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { linkedTitle } from '../services/linkedTitle'
import { CONTENT_TYPES, INPUT_TYPES, OPERATORS, STEP_KINDS, choicesText, flowValues, hasUnpublished, moveStep, newFlow, newStep, nextLabel, parseChoices, removeStep, renameStep, stepLabel, triggerSummary } from '../services/flowEditor'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'
import WorkspaceState from './WorkspaceState.vue'
import LoadingRows from './LoadingRows.vue'

const capabilities = inject('relayCapabilities')
const rows = ref([]), next = ref(null), query = ref(''), filter = ref('all')
const draft = ref(null), saved = ref(''), catalog = ref([]), runs = ref([]), responses = ref(null)
const busy = ref(false), error = ref(''), notice = ref(''), stepKind = ref('input'), editor = ref(null)
const visible = computed(() => rows.value.filter(row => filter.value === 'all' || Boolean(row.enabled) === (filter.value === 'enabled')))
const snapshot = () => JSON.stringify(draft.value && flowValues(draft.value))
const dirty = computed(() => Boolean(draft.value) && snapshot() !== saved.value)
const stepOptions = computed(() => (draft.value?.nodes || []).map(step => ({ value: step.id, label: step.id + ' · ' + stepLabel(step.kind) })))
const variables = computed(() => [...new Set((draft.value?.nodes || []).filter(step => ['input', 'action'].includes(step.kind) && step.variable).map(step => step.variable).concat('last_input'))])
const reference = kind => ({ label: { channel: 'WhatsApp channel', execution_user: 'Run as user', business_doctype: 'Business type' }[kind],
  method: 'flows.service.references', kind, required: true, readOnly: busy.value,
  initialOptions: draft.value?.[kind] ? [{ value: draft.value[kind], label: kind === 'channel' ? linkedTitle('Relay Channel', draft.value[kind], draft.value[kind]) : draft.value[kind] }] : [] })
let generation = 0

async function run(work) {
  busy.value = true; error.value = ''; notice.value = ''
  try { await work() } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function load(append = false) {
  const request = ++generation
  await run(async () => {
    const page = await coreApi('flows.service.directory', { after: append ? next.value : null, query: query.value })
    if (request !== generation) return
    rows.value = append ? [...rows.value, ...page.items] : page.items; next.value = page.next
  })
}
function edit(flow) {
  const nodes = typeof flow.nodes === 'string' ? JSON.parse(flow.nodes) : flow.nodes
  for (const step of nodes) if (step.kind === 'action') step._arguments = JSON.stringify(step.arguments || {})
  draft.value = { ...flow, nodes }; saved.value = snapshot(); responses.value = null; runs.value = []
  if (flow.name) coreApi('flows.service.runs', { flow: flow.name }).then(page => { if (draft.value?.name === flow.name) runs.value = page.items }).catch(() => {})
  nextTick(() => editor.value?.scrollIntoView?.({ block: 'start' }))
}
const open = row => run(async () => edit(await coreApi('flows.service.read', { name: row.name })))
function argumentsOf(step) {
  try { step.arguments = JSON.parse(step._arguments || '{}'); return true } catch { error.value = 'Step ' + step.id + ': arguments must be JSON, such as {"title": {"var": "title"}}'; return false }
}
async function save() {
  if (!draft.value.nodes.filter(step => step.kind === 'action').every(argumentsOf)) return
  await run(async () => {
    const values = flowValues(draft.value)
    if (!draft.value.name) delete values.enabled
    edit(await coreApi('flows.service.save', { name: draft.value.name, values }, true)); notice.value = 'Saved.'
    await load()
  })
}
const publish = () => run(async () => { edit(await coreApi('flows.service.publish', { name: draft.value.name }, true)); notice.value = 'Published. New conversations use this version.'; await load() })
const toggle = () => run(async () => { edit(await coreApi('flows.service.set_enabled', { name: draft.value.name, enabled: draft.value.enabled ? 0 : 1 }, true)); await load() })
const showResponses = row => run(async () => { responses.value = await coreApi('flows.service.responses', { name: row.name }) })
function addStep() { draft.value.nodes.push(newStep(stepKind.value, draft.value.nodes)) }
function toggleType(step, type) {
  const accept = new Set(step.accept || CONTENT_TYPES)
  accept.has(type) ? accept.delete(type) : accept.add(type)
  step.accept = CONTENT_TYPES.filter(item => accept.has(item))
}
// A #/flows?legacy=<old flow> link from WhatsApp Core opens the flow it was imported as.
async function openLegacy() {
  const legacy = new URLSearchParams(location.hash.split('?')[1] || '').get('legacy')
  if (!legacy) return
  const page = await coreApi('flows.service.directory', { query: legacy })
  const row = page.items.find(item => String(item.legacy_key || '').endsWith(':' + legacy))
  if (row) await open(row)
}
watch(query, () => load())
onMounted(async () => { if (!capabilities.value.flows) return; await load(); coreApi('flows.actions.catalog').then(rows => { catalog.value = rows }).catch(() => {}); openLegacy().catch(() => {}) })
onBeforeUnmount(() => { ++generation })
useRealtimeRefresh(['Relay Flow'], ['flows'], () => load())
</script>
<template>
  <section class="v1-screen flow-workspace"><div class="v1-content space-y-4">
    <p v-if="!capabilities.flows">Flows are turned off, or your role cannot manage them. A System Manager turns them on in Settings.</p>
    <template v-else>
      <WorkspaceHeading description="Guide customers through questions, answers and business actions on WhatsApp. A flow starts from a slash command, a keyword or a template button."><Button label="New flow" variant="solid" icon-left="plus" :disabled="busy" @click="edit(newFlow())" /></WorkspaceHeading>
      <div class="workspace-toolbar flow-toolbar"><div class="automation-chips" role="group" aria-label="Enabled state"><button v-for="value in ['all', 'enabled', 'disabled']" :key="value" type="button" class="automation-chip" :aria-pressed="filter === value" @click="filter = value">{{ value === 'all' ? 'All' : value === 'enabled' ? 'Enabled' : 'Disabled' }}</button></div><FormControl v-model="query" placeholder="Search flows" aria-label="Search flows" /></div>
      <ErrorMessage v-if="error" :message="error" /><p v-if="notice" role="status" class="workspace-success">{{ notice }}</p>
      <div class="v1-detail-grid" :class="{ 'v1-detail-grid--browse': !draft, 'flow-detail-open': draft }">
        <div class="flow-list">
          <LoadingRows v-if="busy && !rows.length" label="Loading flows…" />
          <button v-for="row in visible" :key="row.name" type="button" class="v1-list-card" :aria-pressed="draft?.name === row.name" :disabled="busy" @click="open(row)">
            <div class="automation-card-heading"><strong>{{ row.title }}</strong><Badge :label="row.enabled ? 'Enabled' : 'Disabled'" :theme="row.enabled ? 'green' : 'gray'" /></div>
            <span>{{ triggerSummary(row) }} · {{ linkedTitle('Relay Channel', row.channel, 'WhatsApp') }}<template v-if="row.legacy_key"> · Imported</template><template v-if="!row.published_version"> · Not published</template></span>
          </button>
          <WorkspaceState v-if="!visible.length && !busy && !error" :title="rows.length ? 'No matching flows' : 'No flows yet'" :description="rows.length ? 'Change the filter or search.' : 'Create a flow, or import WhatsApp Core flows with relay-import-whatsapp-flows. New flows start disabled.'" icon="git-branch"><Button label="New flow" variant="solid" icon-left="plus" @click="edit(newFlow())" /></WorkspaceState>
          <Button v-if="next" label="Load more" :disabled="busy" @click="load(true)" />
        </div>
        <form v-if="draft" ref="editor" class="workflow-card min-w-0 flow-editor" @submit.prevent="save">
          <div class="automation-card-heading"><h2 class="font-semibold">{{ draft.name ? draft.title || 'Flow' : 'New flow' }}</h2>
            <div class="flow-badges"><Badge v-if="draft.name" :label="draft.enabled ? 'Enabled' : 'Disabled'" :theme="draft.enabled ? 'green' : 'gray'" /><Badge v-if="draft.name && hasUnpublished(draft)" label="Unpublished changes" theme="orange" /><Badge v-if="draft.legacy_key" label="Imported" theme="blue" /></div>
            <Button label="Close" :disabled="busy" @click="draft = null" /></div>
          <p v-if="draft.missing_actions?.length" class="flow-warning" role="alert">Register these business actions before you enable the flow: {{ draft.missing_actions.join(', ') }}</p>
          <fieldset class="automation-section"><legend>Details</legend>
            <FormControl v-model="draft.title" label="Title" required maxlength="140" :disabled="busy" />
            <div class="grid gap-3 sm:grid-cols-3"><RemoteLinkField v-for="kind in ['channel', 'execution_user', 'business_doctype']" :key="kind" v-model="draft[kind]" :field="reference(kind)" /></div>
            <p class="text-sm">The flow reads and acts with the run-as user's permissions, only for the business record of the chat.</p>
          </fieldset>
          <fieldset class="automation-section"><legend>Starts when the customer sends</legend>
            <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.command" label="Slash command" placeholder="/help" :disabled="busy" /><FormControl v-model="draft.template_button" label="Template button payload" :disabled="busy" /></div>
            <FormControl v-model="draft.keywords" type="textarea" rows="2" label="Keywords (one per line, the whole message must match)" :disabled="busy" />
            <p class="text-sm">Exit, cancel or stop closes an open flow. A flow left unanswered for 7 days stops waiting.</p>
          </fieldset>
          <fieldset class="automation-section"><legend>Steps</legend>
            <datalist id="flow-variables"><option v-for="name in variables" :key="name" :value="name" /></datalist>
            <ol class="flow-steps">
              <li v-for="(step, index) in draft.nodes" :key="index" class="flow-step" :data-kind="step.kind">
                <div class="flow-step-heading"><span class="flow-step-number">{{ index + 1 }}</span><strong>{{ stepLabel(step.kind) }}</strong><input class="flow-step-id" :value="step.id" aria-label="Step name" :disabled="busy" @change="renameStep(draft.nodes, step, $event.target.value.trim())" /><span class="flow-step-next">{{ nextLabel(draft.nodes, index) }}</span></div>
                <FormControl v-if="!['condition', 'action', 'wait'].includes(step.kind)" v-model="step.text" type="textarea" rows="2" :label="step.kind === 'input' ? 'Question' : step.kind === 'end' ? 'Final message (optional)' : step.kind === 'topic' ? 'Summary' : 'Message'" :disabled="busy" />
                <template v-if="step.kind === 'input'">
                  <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="step.variable" label="Save answer as" :disabled="busy" /><FormControl v-model="step.input_type" type="select" label="Answer type" :options="INPUT_TYPES" :disabled="busy" /></div>
                  <FormControl v-if="['choice', 'multi_choice'].includes(step.input_type)" :model-value="choicesText(step.choices)" type="textarea" rows="3" label="Choices, one per line (Label = value)" :disabled="busy" @update:model-value="step.choices = parseChoices($event)" />
                  <div v-if="step.input_type === 'text'" class="grid gap-3 sm:grid-cols-2"><FormControl v-model="step.min_length" type="number" min="1" label="Shortest answer" :disabled="busy" /><FormControl v-model="step.max_length" type="number" min="1" max="4096" label="Longest answer" :disabled="busy" /></div>
                  <div v-if="step.input_type === 'number'" class="grid gap-3 sm:grid-cols-3"><FormControl v-model="step.minimum" type="number" label="Minimum" :disabled="busy" /><FormControl v-model="step.maximum" type="number" label="Maximum" :disabled="busy" /><FormControl v-model="step.integer_only" type="checkbox" label="Whole numbers only" :disabled="busy" /></div>
                  <div v-if="step.input_type === 'content'" class="flow-types" role="group" aria-label="Accepted messages"><button v-for="type in CONTENT_TYPES" :key="type" type="button" class="automation-chip" :aria-pressed="(step.accept || CONTENT_TYPES).includes(type)" @click="toggleType(step, type)">{{ type }}</button></div>
                  <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="step.error_text" label="Message for a wrong answer (optional)" :disabled="busy" /><FormControl v-model="step.optional" type="checkbox" label="Customer can reply skip" :disabled="busy" /></div>
                </template>
                <div v-if="step.kind === 'condition'" class="grid gap-3 sm:grid-cols-3">
                  <FormControl v-model="step.variable" label="Answer or result" list="flow-variables" placeholder="customer.authorized" :disabled="busy" /><FormControl v-model="step.operator" type="select" label="Check" :options="OPERATORS" :disabled="busy" /><FormControl v-if="step.operator !== 'is_set'" v-model="step.value" label="Value" :disabled="busy" />
                  <FormControl v-model="step.then" type="select" label="When true, go to" :options="stepOptions" :disabled="busy" /><FormControl v-model="step.otherwise" type="select" label="Otherwise go to" :options="stepOptions" :disabled="busy" />
                </div>
                <template v-if="step.kind === 'action'">
                  <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="step.action" type="select" label="Business action" :options="[...catalog.map(row => ({ value: row.key, label: row.label })), ...(step.action && !catalog.some(row => row.key === step.action) ? [{ value: step.action, label: step.action + ' (not registered)' }] : [])]" :disabled="busy" /><FormControl v-model="step.variable" label="Save result as (optional)" :disabled="busy" /></div>
                  <FormControl v-model="step._arguments" type="textarea" rows="3" label="Arguments (JSON; {&quot;var&quot;: &quot;answer&quot;} uses an answer)" class="flow-code" :disabled="busy" />
                </template>
                <FormControl v-if="step.kind === 'wait'" v-model="step.seconds" type="number" min="1" max="86400" label="Seconds" :disabled="busy" />
                <FormControl v-if="step.kind === 'ticket'" v-model="step.category" type="select" label="Ticket category" :options="['Query', 'Payment evidence', 'Support', 'Other']" :disabled="busy" />
                <div v-if="step.kind === 'topic'" class="grid gap-3 sm:grid-cols-3"><FormControl v-model="step.title" label="Topic title" :disabled="busy" /><FormControl v-model="step.category" label="Category" :disabled="busy" /><FormControl v-model="step.status" type="select" label="Status" :options="['Open', 'Waiting', 'Resolved', 'Archived']" :disabled="busy" /></div>
                <div class="flow-step-footer">
                  <FormControl v-if="!['end', 'handoff', 'condition'].includes(step.kind)" v-model="step.next" type="select" label="Then go to" :options="[{ value: '', label: 'The following step' }, ...stepOptions.filter(option => option.value !== step.id)]" :disabled="busy" />
                  <FormControl v-model="step.max_visits" type="number" min="1" max="100" label="Repeat limit" placeholder="20" :disabled="busy" />
                  <div class="flow-step-buttons"><Button icon="arrow-up" aria-label="Move step up" :disabled="busy || index === 0" @click="moveStep(draft.nodes, index, -1)" /><Button icon="arrow-down" aria-label="Move step down" :disabled="busy || index === draft.nodes.length - 1" @click="moveStep(draft.nodes, index, 1)" /><Button icon="trash" aria-label="Remove step" :disabled="busy || draft.nodes.length === 1" @click="removeStep(draft.nodes, index)" /></div>
                </div>
              </li>
            </ol>
            <div class="flow-add"><FormControl v-model="stepKind" type="select" label="New step" :options="STEP_KINDS" :disabled="busy" /><Button label="Add step" icon-left="plus" :disabled="busy || draft.nodes.length >= 30" @click="addStep" /></div>
            <p class="text-sm">Use <code v-pre>{{answer}}</code> in a message to insert an answer, or <code v-pre>{{result.field}}</code> for a business action result. A loop must stop at a question.</p>
          </fieldset>
          <div class="flow-actions"><Button type="submit" label="Save draft" variant="solid" :loading="busy" :disabled="!dirty && Boolean(draft.name)" />
            <Button v-if="draft.name" label="Publish" :disabled="busy || dirty || !hasUnpublished(draft)" @click="publish" />
            <Button v-if="draft.name" :label="draft.enabled ? 'Disable' : 'Enable'" :disabled="busy || dirty || !draft.published_version" @click="toggle" />
            <span v-if="dirty" class="text-sm" role="status">Unsaved changes</span></div>
          <div v-if="draft.name" class="automation-section"><h3 class="font-semibold">Recent runs</h3>
            <p v-if="!runs.length" class="text-sm">No runs yet.</p>
            <button v-for="row in runs" :key="row.name" type="button" class="flow-run" @click="showResponses(row)"><span>{{ row.display_name || row.relay_contact }}</span><Badge :label="row.status" :theme="row.status === 'Completed' ? 'green' : row.status === 'Cancelled' ? 'gray' : 'blue'" /><small>{{ row.creation }}</small></button>
            <dl v-if="responses" class="flow-responses"><template v-for="item in responses.responses" :key="item.field"><dt>{{ item.question }}</dt><dd>{{ Array.isArray(item.answer) ? item.answer.join(', ') : typeof item.answer === 'object' ? item.answer?.type + (item.answer?.text ? ': ' + item.answer.text : '') : item.answer }}</dd></template><p v-if="!responses.responses.length">No answers collected.</p></dl>
          </div>
        </form>
      </div>
    </template>
  </div></section>
</template>

<style scoped>
.flow-toolbar { display:flex; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; }
.flow-list { display:flex; flex-direction:column; gap:8px; }
.flow-badges { display:flex; flex-wrap:wrap; gap:6px; margin-left:auto; }
.flow-warning { color:var(--ink-amber-3, #9a6700); background:var(--surface-amber-1, #fff8e6); border-radius:8px; padding:8px 12px; font-size:13px; }
.flow-steps { display:flex; flex-direction:column; gap:12px; margin:0; padding:0; list-style:none; counter-reset:none; }
.flow-step { display:grid; gap:10px; padding:12px; border:1px solid var(--outline-gray-2); border-left:3px solid var(--outline-gray-3); border-radius:8px; background:var(--surface-white); min-width:0; }
.flow-step[data-kind=input] { border-left-color:#4377b9; }
.flow-step[data-kind=condition] { border-left-color:#b9852f; }
.flow-step[data-kind=action] { border-left-color:#7a5bc2; }
.flow-step[data-kind=end],.flow-step[data-kind=handoff] { border-left-color:#2f8f5b; }
.flow-step-heading { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.flow-step-number { display:grid; place-items:center; width:22px; height:22px; border-radius:50%; background:var(--surface-gray-2); font-size:12px; font-weight:600; }
.flow-step-id { font:12px ui-monospace, monospace; padding:2px 6px; border:1px solid var(--outline-gray-2); border-radius:6px; background:var(--surface-gray-1); max-width:180px; }
.flow-step-next { margin-left:auto; font-size:12px; color:var(--ink-gray-6); }
.flow-step-footer { display:grid; grid-template-columns:minmax(0,1fr) 120px auto; gap:10px; align-items:end; }
.flow-step-buttons { display:flex; gap:6px; }
.flow-types { display:flex; flex-wrap:wrap; gap:6px; }
.flow-add { display:flex; gap:10px; align-items:end; flex-wrap:wrap; }
.flow-actions { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
.flow-run { display:flex; align-items:center; gap:8px; width:100%; text-align:left; padding:8px 0; border-bottom:1px solid var(--outline-gray-2); }
.flow-run small { margin-left:auto; color:var(--ink-gray-6); }
.flow-responses { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:6px 12px; font-size:13px; }
.flow-responses dt { color:var(--ink-gray-6); }
.flow-code :deep(textarea) { font:12px ui-monospace, monospace; }
@media(max-width:900px) {
  .flow-detail-open > .flow-list { display:none; }
  .flow-step-footer { grid-template-columns:1fr; }
}
</style>
