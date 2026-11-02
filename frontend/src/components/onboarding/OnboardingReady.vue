<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { onRealtime, subscribeRoom } from '../../services/realtime'
import { VERIFICATION_LINK, limitText, managerLink, nameStatus } from '../../services/onboarding'

const props = defineProps({ state: { type: Object, required: true } })
const emit = defineEmits(['next', 'go', 'reload'])
const channels = computed(() => props.state.channels.filter(row => row.enabled))
const signup = computed(() => props.state.signup?.state === 'completed' ? props.state.signup : null)
const to = ref({}), tests = ref({}), busy = ref(''), error = ref('')
const COPY = { pending: 'Waiting', requested: 'Asked Meta', importing: 'Copying', done: 'Done', declined: 'Not shared', failed: 'Failed' }
const THEMES = { Sent: 'blue', Delivered: 'green', Read: 'green', Failed: 'red' }

const sessionOf = channel => signup.value && signup.value.channel === channel.name ? signup.value : null
async function task(name, work) {
  busy.value = name; error.value = ''
  try { return await work() }
  catch (e) { error.value = e.message }
  finally { busy.value = '' }
}
async function checkPayment(session) {
  if (await task('payment', () => coreApi('onboarding.api.signup_status', { session: session.session_id, refresh: 1 }))) emit('reload')
}
async function sendTest(channel) {
  const result = await task('test:' + channel.name, () => coreApi('onboarding.api.send_test', { channel: channel.name, to: to.value[channel.name] }, true))
  if (result) tests.value[channel.name] = { message: result.message, status: result.message ? 'Pending' : result.status, error: result.error || '' }
}
// Delivery receipts change the message; each change re-reads only the test messages.
async function readTests() {
  for (const [channel, test] of Object.entries(tests.value)) {
    if (!test.message) continue
    try { tests.value[channel] = { ...test, ...(await coreApi('onboarding.api.test_status', { message: test.message })) } }
    catch { /* The last known status stays. */ }
  }
}
let stopRoom, stopRealtime
onMounted(() => {
  stopRoom = subscribeRoom('Relay Message')
  stopRealtime = onRealtime(event => { if (['messages', 'reconnect'].includes(event?.kind)) readTests() })
})
onBeforeUnmount(() => { stopRoom?.(); stopRealtime?.() })
</script>
<template>
  <section class="workflow-card onboarding-card" aria-labelledby="onboarding-ready-title">
    <h2 id="onboarding-ready-title">Test and finish</h2>
    <ErrorMessage :message="error" />
    <p v-if="!channels.length">No WhatsApp number is connected yet. <a class="v1-link" href="#/setup?step=number">Connect a number</a></p>
    <article v-for="channel in channels" :key="channel.name" class="onboarding-number space-y-4">
      <h3 class="font-semibold">{{ sessionOf(channel)?.phone?.display_phone_number || channel.address || channel.label }}</h3>
      <dl>
        <div><dt>Name in WhatsApp</dt><dd>{{ sessionOf(channel)?.phone?.verified_name || channel.label }}<Badge v-if="sessionOf(channel)?.phone" class="ml-2" v-bind="nameStatus(sessionOf(channel).phone.name_status)" /></dd></div>
        <div v-if="sessionOf(channel)?.phone"><dt>Messaging limit</dt><dd>{{ limitText(sessionOf(channel).phone.messaging_limit) }}</dd></div>
        <div v-if="sessionOf(channel)?.phone?.quality_rating"><dt>Quality</dt><dd>{{ sessionOf(channel).phone.quality_rating }}</dd></div>
        <div><dt>Connection</dt><dd>{{ channel.connection_type === 'Coexistence' ? 'WhatsApp Business app and Relay' : 'Relay only' }}</dd></div>
      </dl>
      <div v-if="sessionOf(channel)?.payment_method_ready === false" class="onboarding-alert space-y-2" role="status">
        <p><strong>Add a payment method in WhatsApp Manager.</strong> Meta needs it before you can send templates to customers.</p>
        <div class="onboarding-actions"><a class="v1-link" :href="managerLink(channel.waba_id || sessionOf(channel).waba_id)" target="_blank" rel="noopener">Open WhatsApp Manager</a>
          <Button variant="outline" label="I have added it, check again" :loading="busy === 'payment'" @click="checkPayment(sessionOf(channel))" /></div>
      </div>
      <div v-if="channel.connection_type === 'Coexistence' && sessionOf(channel)?.coexistence" class="space-y-2">
        <p>Contacts: {{ COPY[sessionOf(channel).coexistence.contacts] }} · Chats: {{ COPY[sessionOf(channel).coexistence.history] }}<template v-if="sessionOf(channel).coexistence.history === 'importing'"> {{ sessionOf(channel).coexistence.history_progress }}%</template></p>
        <ul class="list-disc space-y-1 pl-5 onboarding-hint">
          <li>Turn off greeting and away messages in the WhatsApp Business app, so customers do not get two replies.</li>
          <li>Open the app on your phone at least every 14 days, or Meta disconnects it.</li>
          <li>This number sends up to 20 messages a second. Groups stay in the app only.</li>
        </ul>
      </div>
      <form class="space-y-2" @submit.prevent="sendTest(channel)">
        <FormControl v-model="to[channel.name]" label="Send a test message to" type="tel" placeholder="+91 98765 43210" :disabled="Boolean(busy)" />
        <div class="onboarding-actions"><Button type="submit" variant="outline" label="Send" :loading="busy === 'test:' + channel.name" :disabled="!to[channel.name]" />
          <Badge v-if="tests[channel.name]" :label="tests[channel.name].status" :theme="THEMES[tests[channel.name].status] || 'gray'" /></div>
        <p class="onboarding-hint">Relay sends Meta's hello_world template.<template v-if="tests[channel.name]?.error"> {{ tests[channel.name].error }}</template></p>
      </form>
    </article>
    <p class="onboarding-hint">Meta raises your limits after you <a class="v1-link" :href="VERIFICATION_LINK" target="_blank" rel="noopener">verify your business</a>.</p>
    <div class="onboarding-actions is-primary">
      <Button variant="solid" label="Continue" :disabled="!channels.length" @click="emit('next', 'records')" />
      <Button variant="outline" label="Add another number" @click="emit('go', 'number')" />
    </div>
  </section>
</template>
