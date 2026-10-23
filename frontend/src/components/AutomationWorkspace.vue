<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import { configurationValues, newConfiguration, toolRows } from '../services/automationEditor'
const props = defineProps({ kind: String })
const capabilities = inject('relayCapabilities')
const skill = computed(() => props.kind === 'skills')
const api = computed(() => skill.value ? 'ai.configuration' : 'business_events')
const rows = ref([]), next = ref(null), draft = ref(null), tools = ref([]), parameters = ref('')
const busy = ref(false), error = ref(''), notice = ref(''), message = ref(''), preview = ref(null)
let generation = 0
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
      <div class="flex flex-wrap gap-3 items-center"><Button :label="skill ? 'New skill' : 'New event rule'" :disabled="busy" @click="edit(newConfiguration(skill))" /><a v-if="skill" class="v1-link" href="/desk/ai-model">Manage AI Models & provider accounts</a><a v-if="skill" class="v1-link" href="/desk/relay-settings">Set fallback handoff owner</a></div>
      <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p><p v-if="busy" role="status">Working…</p>
      <div class="v1-detail-grid">
        <div class="space-y-3"><button v-for="row in rows" :key="row.name" class="v1-list-card" :aria-pressed="draft?.name === row.name" :disabled="busy" @click="edit(row)"><strong>{{ row.title }}</strong><span>{{ row.enabled ? 'Enabled' : 'Disabled' }} · {{ row.business_doctype }} · {{ skill ? row.mode : row.event }}</span></button><p v-if="!rows.length && !busy && !error">{{ skill ? 'No skills configured.' : 'No business event rules configured.' }}</p><Button v-if="next" label="Load more" :disabled="busy" @click="load(true)" /></div>
        <form v-if="draft" class="workflow-card space-y-4 min-w-0" @submit.prevent="save">
          <h2 class="font-semibold">{{ draft.name ? 'Edit' : 'New' }} {{ skill ? 'skill' : 'event rule' }}</h2>
          <FormControl v-model="draft.title" label="Title" required :disabled="busy" />
          <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.business_doctype" label="Business type" placeholder="Supplier or Customer" required :disabled="busy" /><FormControl v-model="draft.channel" label="WhatsApp channel" :required="skill || Boolean(draft.enabled)" :disabled="busy" /><FormControl v-model="draft.run_as_user" label="Run-as user" placeholder="User email" :required="skill || Boolean(draft.enabled)" :disabled="busy" /><FormControl v-model="draft.enabled" type="checkbox" label="Enabled" :disabled="busy" /></div>
          <template v-if="skill">
            <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.ai_model" label="AI Model" required :disabled="busy" /><FormControl v-model="draft.handoff_owner" label="Handoff owner" placeholder="User email" required :disabled="busy" /><FormControl v-model="draft.mode" label="Mode" type="select" :options="['Shadow', 'Automatic']" :disabled="busy" /><FormControl v-model="draft.daily_limit" label="Daily model limit" type="number" min="1" max="1000" :disabled="busy" /></div>
            <FormControl v-model="draft.instructions" label="Skill knowledge and instructions" type="textarea" rows="7" required :disabled="busy" />
            <fieldset class="space-y-3"><legend class="font-semibold">Allowed read tools</legend><p class="text-sm">Each tool is restricted to this conversation’s business record. Use a Link field to that business, or name when reading the business itself.</p>
              <div v-for="(tool, index) in tools" :key="index" class="border rounded p-3 grid gap-3 sm:grid-cols-2"><FormControl v-model="tool.name" label="Tool name" required :disabled="busy" /><FormControl v-model="tool.method" label="Read operation" type="select" :options="['get_doc', 'get_list']" :disabled="busy" /><FormControl v-model="tool.doctype" label="Allowed DocType" required :disabled="busy" /><FormControl v-model="tool.scope_field" label="Business link field" required :disabled="busy" /><FormControl v-model="tool.fields" label="Readable fields (comma separated)" required :disabled="busy" /><Button label="Remove tool" :disabled="busy" @click="tools.splice(index, 1)" /></div>
              <Button label="Add read tool" :disabled="busy || tools.length >= 12" @click="tools.push({ name: '', method: 'get_list', doctype: '', scope_field: '', fields: 'name' })" />
            </fieldset>
          </template>
          <template v-else>
            <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="draft.source_doctype" label="Source DocType" placeholder="Delivery Note" required :disabled="busy" /><FormControl v-model="draft.event" label="Event" type="select" :options="['on_submit', 'after_insert', 'on_cancel']" :disabled="busy" /><FormControl v-model="draft.recipient_field" label="Recipient business field" placeholder="customer" required :disabled="busy" /><FormControl v-model="draft.template" label="Approved WhatsApp template" :required="Boolean(draft.enabled)" :disabled="busy" /></div>
            <FormControl v-model="parameters" label="Template parameters in order (one source field per line)" type="textarea" rows="4" :disabled="busy" /><p class="text-sm">Use name, total_qty, or other source fields. items_summary includes each item’s quantity and UOM. The business must have exactly one linked Contact.</p>
          </template>
          <Button type="submit" label="Save" variant="solid" :loading="busy" />
          <div v-if="skill && draft.name" class="border-t pt-4 space-y-3"><h3 class="font-semibold">Test this skill</h3><p class="text-sm">Tests the saved skill against an incoming conversation message. No reply is sent and no ticket or pause is created.</p><FormControl v-model="message" label="Incoming message reference" placeholder="RELAY-MSG-…" :disabled="busy" /><Button label="Run shadow test" :disabled="busy || !message" @click="test" /><div v-if="preview" role="status" class="space-y-2"><strong>{{ preview.handoff ? 'Would hand off' : 'Would reply' }}</strong><p class="whitespace-pre-wrap">{{ preview.reply }}</p><p>{{ preview.reason }}</p></div></div>
        </form><p v-else class="v1-empty">Select a configuration or create one.</p>
      </div>
    </template>
  </div></section>
</template>
