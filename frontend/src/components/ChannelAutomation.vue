<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { channelValues, channelLabel, displayedSteps, newChannelStep, STEP_TYPES, TICKET_RULES, WORKING_DAYS } from '../services/channelAutomation'
import { moveStep } from '../services/flowEditor'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'
import WorkspaceState from './WorkspaceState.vue'

const channel = ref(''), draft = ref(null), saved = ref(''), busy = ref(false), error = ref(''), notice = ref('')
const kind = ref('Flow'), text = ref(''), contact = ref(''), trace = ref(null), stale = ref(false)
let generation = 0
const snapshot = () => JSON.stringify(draft.value && channelValues(draft.value))
const dirty = computed(() => Boolean(draft.value) && snapshot() !== saved.value)
const usingDefaults = computed(() => Boolean(draft.value) && !draft.value.steps.length)
const visibleSteps = computed(() => draft.value ? displayedSteps(draft.value) : [])
const needsHours = computed(() => visibleSteps.value.some(step => step.enabled && step.step === 'Out of hours reply'))
const days = computed(() => (draft.value?.working_days || '').split(/[,\n]/).map(day => day.trim()).filter(Boolean))
const reference = (kind, value, label) => ({ label, method: 'automation.channel.references', kind, readOnly: busy.value,
  initialOptions: value ? [{ value, label: kind === 'channel' && draft.value ? channelLabel(draft.value) : value }] : [] })

async function load() {
  const request = ++generation
  if (!channel.value) { draft.value = null; return }
  busy.value = true; error.value = ''
  try {
    const result = await coreApi('automation.channel.read', { channel: channel.value })
    if (request !== generation) return
    draft.value = result; saved.value = snapshot(); stale.value = false; trace.value = null
  } catch (e) { if (request === generation) error.value = e.message }
  finally { if (request === generation) busy.value = false }
}
watch(channel, () => { draft.value = null; notice.value = ''; load() })
onBeforeUnmount(() => { ++generation })
async function save() {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    draft.value = await coreApi('automation.channel.save', { channel: channel.value, values: channelValues(draft.value), modified: draft.value.modified }, true)
    saved.value = snapshot(); stale.value = false; trace.value = null; notice.value = 'Channel automation saved.'
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
async function testMessage() {
  busy.value = true; error.value = ''; trace.value = null
  try { trace.value = (await coreApi('automation.channel.dry_run', { channel: channel.value, text: text.value, contact: contact.value || undefined })).trace }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
function toggleDay(day) {
  draft.value.working_days = WORKING_DAYS.filter(item => item === day ? !days.value.includes(item) : days.value.includes(item)).join('\n')
}
useRealtimeRefresh(['Relay Channel'], ['channel_automation'], () => {
  if (!channel.value || busy.value) return
  if (dirty.value) stale.value = true
  else return load()
})
</script>
<template>
  <section class="v1-screen"><div class="v1-content space-y-4 channel-automation">
    <WorkspaceHeading description="Choose what handles incoming messages, in order. Identity, consent and human ownership checks always come first." />
    <RemoteLinkField v-model="channel" :field="reference('channel', channel, 'Channel')" />
    <ErrorMessage v-if="error" :message="error" />
    <p v-if="notice" role="status" class="workspace-success">{{ notice }}</p>
    <p v-if="busy && !draft" role="status">Loading channel automation…</p>
    <WorkspaceState v-if="!channel" title="Choose a channel" description="Configure its incoming steps and business hours, then test a message without sending it." icon="zap" />
    <form v-if="draft" class="workflow-card space-y-4" @submit.prevent="save">
      <div class="automation-card-heading"><h2 class="font-semibold">{{ channelLabel(draft) }}</h2><FormControl v-model="draft.automation_enabled" type="checkbox" label="Automation enabled" :disabled="busy" /></div>
      <p v-if="stale" role="status">This channel changed elsewhere. <Button label="Reload saved settings" :disabled="busy" @click="load" /></p>
      <fieldset class="automation-section" :disabled="busy"><legend>On incoming message</legend>
        <p class="text-sm">Steps run top to bottom. A step that replies stops the list unless set to Continue. A waiting flow keeps handling replies. A confirmed search continues at the AI step.</p>
        <ol class="channel-steps">
          <li v-for="(step, index) in visibleSteps" :key="index" class="channel-step">
            <div class="automation-card-heading"><strong>{{ index + 1 }}. {{ step.step }}</strong><span v-if="usingDefaults" class="text-sm">Default</span><FormControl v-model="step.enabled" type="checkbox" label="Enabled" :disabled="busy || usingDefaults" /></div>
            <RemoteLinkField v-if="step.step === 'AI skill' && !usingDefaults" v-model="step.ai_skill" :field="reference('ai_skill', step.ai_skill, 'AI skill (leave blank to match automatically)')" />
            <div v-if="step.step === 'Assign'" class="grid gap-3 sm:grid-cols-2"><RemoteLinkField v-model="step.team" :field="reference('team', step.team, 'Team')" /><RemoteLinkField v-model="step.user" :field="reference('user', step.user, 'User')" /></div>
            <FormControl v-if="step.step === 'Ticket'" v-model="step.ticket_rule" type="select" label="Ticket rule" :options="TICKET_RULES" :disabled="busy || usingDefaults" />
            <FormControl v-if="step.step === 'Out of hours reply'" v-model="step.message" type="textarea" label="Out of hours message" rows="3" maxlength="2000" :disabled="busy || usingDefaults" />
            <p v-if="usingDefaults" class="text-sm">{{ step.step === 'Flow' ? 'Run a matching flow.' : 'Find an automatic AI skill for this message.' }}</p><div class="channel-step-footer"><FormControl v-model="step.on_reply" type="select" label="After this step handles the message" :options="['Stop', 'Continue']" :disabled="busy || usingDefaults" /><div v-if="!usingDefaults" class="channel-step-buttons"><Button icon="arrow-up" :aria-label="`Move step ${index + 1} up`" :disabled="busy || index === 0" @click="moveStep(draft.steps, index, -1)" /><Button icon="arrow-down" :aria-label="`Move step ${index + 1} down`" :disabled="busy || index === draft.steps.length - 1" @click="moveStep(draft.steps, index, 1)" /><Button icon="trash" :aria-label="`Remove step ${index + 1}`" :disabled="busy || usingDefaults" @click="draft.steps.splice(index, 1)" /></div></div>
          </li>
        </ol>
        <Button v-if="usingDefaults" label="Customize default steps" :disabled="busy" @click="draft.steps = displayedSteps(draft)" />
        <div class="channel-add"><FormControl v-model="kind" type="select" label="New step" :options="STEP_TYPES" :disabled="busy" /><Button label="Add step" icon-left="plus" :disabled="busy || draft.steps.length >= 20" @click="draft.steps = [...displayedSteps(draft), newChannelStep(kind)]" /></div>
        <p class="text-sm">Steps that do not match are skipped. After a reply, only Assign and Ticket steps can continue. Ticket rule Never leaves the existing conversation ticket unchanged.</p>
      </fieldset>
      <fieldset class="automation-section" :disabled="busy"><legend>Business hours</legend>
        <div class="grid gap-3 sm:grid-cols-3"><FormControl v-model="draft.timezone" :label="`Timezone (default: ${draft.timezone_default})`" :placeholder="draft.timezone_default" :disabled="busy" /><FormControl v-model="draft.open_time" type="time" label="Opens at" :disabled="busy" /><FormControl v-model="draft.close_time" type="time" label="Closes at" :disabled="busy" /></div>
        <div class="channel-days" role="group" aria-label="Working days"><button v-for="day in WORKING_DAYS" :key="day" class="automation-chip" type="button" :aria-pressed="days.includes(day)" :disabled="busy" @click="toggleDay(day)">{{ day }}</button></div>
        <p class="text-sm">{{ needsHours ? 'Set opening times and working days for the out of hours reply.' : 'Optional. Only out of hours replies use these hours.' }} Times use {{ draft.timezone || draft.timezone_default }}. Overnight hours belong to the day they open.</p>
      </fieldset>
      <div class="channel-add"><Button type="submit" label="Save automation" variant="solid" :loading="busy" :disabled="busy || !dirty || stale" /><span v-if="dirty" role="status">Unsaved changes</span></div>
    </form>
    <form v-if="draft" class="workflow-card space-y-3" @submit.prevent="testMessage">
      <h2 class="font-semibold">Test with a message</h2>
      <p class="text-sm">Uses saved settings. No messages, assignments or tickets are created.</p>
      <RemoteLinkField v-model="contact" :field="reference('contact', contact, 'Contact (optional)')" />
      <FormControl v-model="text" type="textarea" label="Incoming message" rows="3" maxlength="4000" :disabled="busy" />
      <Button type="submit" label="Test message" :loading="busy" :disabled="busy || dirty || !text.trim()" />
      <ol v-if="trace" class="channel-trace" aria-live="polite"><li v-for="(row, index) in trace" :key="index"><strong>{{ row.step }} · {{ row.runs ? 'Would run' : 'Skipped' }}</strong><p>{{ row.reason }}</p></li></ol>
    </form>
  </div></section>
</template>
<style scoped>
.channel-automation { max-width: 1000px; }
.channel-steps { list-style: none; padding: 0; display: grid; gap: 12px; }
.channel-step { border: 1px solid var(--outline-gray-2); border-radius: 8px; padding: 16px; display: grid; gap: 12px; min-width: 0; }
.channel-step-footer { display: flex; justify-content: space-between; align-items: end; flex-wrap: wrap; gap: 12px; }
.channel-step-buttons, .channel-add, .channel-days { display: flex; align-items: end; flex-wrap: wrap; gap: 8px; }
.channel-days { margin-top: 12px; }
.channel-trace { display: grid; gap: 12px; padding-left: 24px; }
.channel-trace p { color: var(--ink-gray-6); }
</style>
