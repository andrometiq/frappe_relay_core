<script setup>
import { computed, ref } from 'vue'
import { Badge, Button, ErrorMessage, FeatherIcon } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { CLOSED, FLOWS, WAITING, openSignupWindow, signupSteps } from '../../services/onboarding'
import { useMobileLayout } from '../../composables/useMobileLayout'

const props = defineProps({ state: { type: Object, required: true }, sessionId: String })
const emit = defineEmits(['next', 'go', 'reload'])
const isMobile = useMobileLayout()
const flow = ref(props.state.signup?.flow || 'new'), busy = ref(false), error = ref(''), blocked = ref(false)
const launchUrl = ref(''), restart = ref(false)
// Shown live only for a session started or asked for here; an old finished one leaves the choice open.
const watching = ref(Boolean(props.sessionId) || ['working', 'failed', ...WAITING].includes(props.state.signup?.state))
let popup = null

const session = computed(() => props.state.signup)
const phase = computed(() => {
  const value = session.value?.state
  if (!session.value || restart.value || !watching.value || CLOSED.includes(value)) return 'choose'
  return WAITING.includes(value) ? 'waiting' : 'progress'
})
const chosen = computed(() => FLOWS.find(item => item.value === flow.value))
const steps = computed(() => signupSteps(session.value))
const note = computed(() => CLOSED.includes(session.value?.state) && watching.value ? session.value.error?.message : '')
const disconnected = computed(() => props.state.channels.length && !props.state.channels.some(row => row.enabled))
const icons = { done: 'check', running: 'loader-circle', failed: 'alert-circle', pending: 'circle' }

async function call(work) {
  busy.value = true; error.value = ''
  try { return await work() }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
// The window opens inside the click; the Hub address follows when Core has it.
async function start() {
  blocked.value = false
  popup = openSignupWindow(window.open, isMobile.value)
  blocked.value = !popup
  const result = await call(() => coreApi('onboarding.api.start_whatsapp', { flow: flow.value }, true))
  if (!result) { popup?.close(); popup = null; return }
  launchUrl.value = result.launch_url; restart.value = false; watching.value = true
  popup?.location.replace(result.launch_url)
  emit('go', 'number', result.session.session_id)
  emit('reload')
}
function openAgain() {
  if (!launchUrl.value) return start()
  popup = openSignupWindow(window.open, isMobile.value, launchUrl.value)
  blocked.value = !popup
}
async function cancel() {
  popup?.close(); popup = null
  if (await call(() => coreApi('onboarding.api.cancel_signup', { session: session.value.session_id }, true))) emit('reload')
}
async function resume() {
  if (await call(() => coreApi('onboarding.api.resume_signup', { session: session.value.session_id }, true))) emit('reload')
}
</script>
<template>
  <section class="workflow-card onboarding-card" aria-labelledby="onboarding-number-title">
    <h2 id="onboarding-number-title">{{ disconnected && phase === 'choose' ? 'Reconnect WhatsApp' : 'WhatsApp number' }}</h2>
    <ErrorMessage :message="error" />
    <template v-if="phase === 'choose'">
      <p v-if="disconnected" class="onboarding-alert">WhatsApp was disconnected from Relay in Meta. Connect the number again to keep sending and receiving messages.</p>
      <p v-if="note" class="onboarding-alert" role="status">{{ note }}</p>
      <p>Which number do you want to use?</p>
      <div class="onboarding-choices" role="radiogroup" aria-label="Type of number">
        <label v-for="item in FLOWS" :key="item.value" class="onboarding-choice">
          <input v-model="flow" type="radio" name="onboarding-flow" :value="item.value" />
          <FeatherIcon :name="item.icon" :size="20" /><strong>{{ item.title }}</strong><span>{{ item.text }}</span>
          <small>What you need: {{ item.need }}</small>
        </label>
      </div>
      <div class="onboarding-actions is-primary"><Button variant="solid" label="Continue with Facebook" :loading="busy" @click="start" /></div>
    </template>
    <template v-else-if="phase === 'waiting'">
      <p class="onboarding-row" role="status"><FeatherIcon name="loader-circle" class="relay-button__spinner" :size="18" />Finish the steps in the Facebook window.</p>
      <p v-if="blocked" class="onboarding-alert">Your browser blocked the window. Select Open window.</p>
      <p>Meta asks you to:</p>
      <ol class="list-decimal space-y-1 pl-5"><li v-for="line in chosen.meta" :key="line">{{ line }}</li></ol>
      <div class="onboarding-actions is-primary">
        <Button v-if="blocked" variant="solid" label="Open window" @click="openAgain" />
        <template v-else><Button variant="outline" label="Bring window to front" @click="popup ? popup.focus() : openAgain()" /><Button variant="outline" label="Open window again" @click="openAgain" /></template>
        <Button variant="ghost" theme="red" label="Cancel setup" :disabled="busy" @click="cancel" />
      </div>
    </template>
    <template v-else>
      <p>Relay is setting up {{ session.phone?.display_phone_number || 'your number' }}. You can close this page; setup continues.</p>
      <ul class="onboarding-steps" aria-label="Setup progress">
        <li v-for="step in steps" :key="step.name" :class="'is-' + step.status">
          <FeatherIcon :name="icons[step.status]" :size="16" :class="{ 'relay-button__spinner': step.status === 'running' }" />
          <span>{{ step.label }}</span><Badge v-if="step.status === 'failed'" label="Failed" theme="red" />
        </li>
      </ul>
      <ErrorMessage v-if="session.error" :message="session.error.message" />
      <div class="onboarding-actions is-primary">
        <Button v-if="session.state === 'completed'" variant="solid" label="Continue" @click="emit('next', 'ready')" />
        <Button v-else-if="session.state === 'failed' && session.error?.retryable" variant="solid" label="Try again" :loading="busy" @click="resume" />
        <Button v-if="session.state === 'failed'" :variant="session.error?.retryable ? 'outline' : 'solid'" label="Start again" @click="restart = true" />
      </div>
    </template>
  </section>
</template>
