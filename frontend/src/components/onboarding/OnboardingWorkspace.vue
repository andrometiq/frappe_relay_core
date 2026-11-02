<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Button, ErrorMessage, FeatherIcon } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { onRealtime, subscribeRoom } from '../../services/realtime'
import { CLOSED, STEPS, activeStep, setupQuery, setupRoute, watchSetup } from '../../services/onboarding'
import { useMobileLayout } from '../../composables/useMobileLayout'
import LoadingRows from '../LoadingRows.vue'
import OnboardingHub from './OnboardingHub.vue'
import OnboardingBusiness from './OnboardingBusiness.vue'
import OnboardingNumber from './OnboardingNumber.vue'
import OnboardingReady from './OnboardingReady.vue'
import OnboardingRecords from './OnboardingRecords.vue'

const views = { hub: OnboardingHub, business: OnboardingBusiness, number: OnboardingNumber, ready: OnboardingReady, records: OnboardingRecords }
const state = ref(null), error = ref(''), loading = ref(false)
const query = ref(setupQuery(location.hash))
const isMobile = useMobileLayout()
const step = computed(() => state.value ? activeStep(state.value.step, query.value.step) : 'hub')
const index = computed(() => STEPS.findIndex(item => item.name === step.value))
const reached = computed(() => state.value?.step === 'done' ? STEPS.length : STEPS.findIndex(item => item.name === state.value?.step))
const session = computed(() => state.value?.signup?.session_id || '')

async function load() {
  loading.value = true; error.value = ''
  try { state.value = await coreApi('onboarding.api.state') }
  catch (e) { error.value = e.message }
  finally { loading.value = false }
}
// A step that saved something reads the whole setup again, then moves on when it asks to.
async function next(name) {
  await load()
  go(name)
}
function go(name, sessionId = '') {
  history.replaceState(null, '', setupRoute(name, sessionId))
  query.value = setupQuery(location.hash)
}
function readRoute() { query.value = setupQuery(location.hash) }
// The Hub window's message, a visible tab or a reconnect may come before the Hub callback, so an open
// session is read from the Hub once; a realtime change already updated Core's copy.
async function reread(reason) {
  if (loading.value) return
  const open = query.value.session || (state.value?.signup && !['completed', ...CLOSED].includes(state.value.signup.state) ? session.value : '')
  if (open && reason !== 'onboarding' && reason !== 'channels') {
    try { await coreApi('onboarding.api.signup_status', { session: open }) } catch { /* Core's last copy is shown instead. */ }
  }
  await load()
}

let stopWatch, stopRoom
onMounted(() => {
  reread('open')
  window.addEventListener('hashchange', readRoute)
  stopRoom = subscribeRoom('Relay WhatsApp Signup')
  stopWatch = watchSetup({ hubOrigin: () => state.value?.hub?.hub_origin, sessionId: () => query.value.session || session.value,
    reread, onRealtime })
})
onBeforeUnmount(() => { window.removeEventListener('hashchange', readRoute); stopWatch?.(); stopRoom?.() })
</script>
<template>
  <section class="v1-screen onboarding">
    <div class="v1-content onboarding-layout">
      <nav v-if="!isMobile" class="onboarding-stepper" aria-label="Setup steps">
        <ol>
          <li v-for="(item, position) in STEPS" :key="item.name" :class="{ 'is-current': item.name === step, 'is-done': position < reached }">
            <button type="button" :disabled="!state || activeStep(state.step, item.name) !== item.name" :aria-current="item.name === step ? 'step' : undefined" @click="go(item.name)">
              <span class="onboarding-stepper__mark"><FeatherIcon v-if="position < reached" name="check" :size="14" /><template v-else>{{ position + 1 }}</template></span>
              <span>{{ item.label }}</span>
            </button>
          </li>
        </ol>
      </nav>
      <div class="onboarding-main">
        <header v-if="isMobile" class="onboarding-progress">
          <span>Step {{ index + 1 }} of {{ STEPS.length }} · {{ STEPS[index]?.label }}</span>
          <span class="onboarding-progress__bar" aria-hidden="true"><span :style="{ width: ((index + 1) / STEPS.length * 100) + '%' }" /></span>
        </header>
        <ErrorMessage :message="error" /><Button v-if="error && !state" label="Try again" @click="load" />
        <LoadingRows v-if="!state && !error" label="Loading setup…" :count="3" />
        <p v-else-if="state && !state.can_configure" class="workflow-card">Relay is being set up. Ask your administrator to finish setup.</p>
        <component :is="views[step]" v-else-if="state" :state="state" :session-id="query.session" @next="next" @go="go" @reload="load" />
      </div>
    </div>
  </section>
</template>
<style>
.onboarding-layout { display:grid; grid-template-columns:240px minmax(0,640px); gap:24px; align-items:start; }
.onboarding-stepper ol { display:flex; flex-direction:column; gap:4px; margin:0; padding:0; list-style:none; }
.onboarding-stepper button { display:flex; width:100%; align-items:center; gap:10px; border-radius:8px; padding:8px 10px; color:var(--ink-gray-6); font-size:13px; text-align:left; }
.onboarding-stepper button:not(:disabled):hover { background:var(--surface-gray-2); }
.onboarding-stepper button:disabled { cursor:default; opacity:.6; }
.onboarding-stepper .is-current button { background:var(--surface-selected); color:var(--ink-gray-9); font-weight:600; }
.onboarding-stepper__mark { display:grid; width:24px; height:24px; flex:none; place-items:center; border:1px solid var(--outline-gray-3); border-radius:50%; font-size:12px; }
.onboarding-stepper .is-done .onboarding-stepper__mark { border-color:var(--ink-green-3, #2f7d4f); background:var(--ink-green-3, #2f7d4f); color:#fff; }
.onboarding-main { display:flex; min-width:0; flex-direction:column; gap:16px; }
.onboarding-card h2 { font-size:17px; font-weight:600; }
.onboarding-card p, .onboarding-card li { color:var(--ink-gray-7); font-size:14px; }
.onboarding-hint { color:var(--ink-gray-5) !important; font-size:13px !important; }
.onboarding-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
.onboarding-fields .is-wide { grid-column:1 / -1; }
.onboarding-actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px; }
.onboarding-row { display:flex; align-items:center; gap:10px; }
.onboarding-ok { color:var(--ink-green-3, #2f7d4f); }
.onboarding-steps { display:flex; flex-direction:column; gap:10px; margin:0; padding:0; list-style:none; }
.onboarding-steps li { display:flex; align-items:center; gap:10px; }
.onboarding-steps .is-failed { color:var(--ink-red-3, #c42b1c); }
.onboarding-steps .is-pending { color:var(--ink-gray-5); }
.onboarding-choices { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.onboarding-choice { display:flex; flex-direction:column; gap:8px; border:1px solid var(--outline-gray-2); border-radius:10px; padding:14px; cursor:pointer; text-align:left; }
.onboarding-choice:has(input:checked) { border-color:var(--outline-blue-2); box-shadow:0 0 0 2px color-mix(in srgb,var(--outline-blue-2) 18%,transparent); background:var(--surface-selected); }
.onboarding-choice input { position:absolute; opacity:0; pointer-events:none; }
.onboarding-choice strong { color:var(--ink-gray-9); font-size:14px; }
.onboarding-choice span, .onboarding-choice small { color:var(--ink-gray-6); font-size:13px; }
.onboarding-alert { border:1px solid var(--outline-gray-2); border-left:3px solid var(--ink-amber-3, #b7791f); border-radius:8px; padding:12px; background:var(--surface-gray-1); }
.onboarding-number dl { display:grid; gap:8px; margin:0; }
.onboarding-number dl > div { display:grid; grid-template-columns:170px minmax(0,1fr); align-items:center; gap:12px; }
.onboarding-number dt { color:var(--ink-gray-5); font-size:13px; }
.onboarding-number dd { margin:0; color:var(--ink-gray-8); font-size:14px; overflow-wrap:anywhere; }
.onboarding-records { display:flex; flex-direction:column; gap:10px; }
@media (max-width:1023px) { .onboarding-choices { grid-template-columns:1fr; } }
@media (max-width:768px) {
  .onboarding-layout { display:block; padding:0; }
  .onboarding-main { gap:12px; padding:12px 16px 0; }
  .onboarding-progress { display:flex; flex-direction:column; gap:6px; color:var(--ink-gray-7); font-size:13px; font-weight:500; }
  .onboarding-progress__bar { display:block; height:3px; overflow:hidden; border-radius:2px; background:var(--surface-gray-3, var(--outline-gray-2)); }
  .onboarding-progress__bar span { display:block; height:100%; background:var(--relay-accent); }
  .onboarding-card { padding:16px; }
  .onboarding-fields { grid-template-columns:1fr; }
  .onboarding-actions.is-primary { position:sticky; bottom:0; z-index:4; margin:0 -16px -16px; border-top:1px solid var(--outline-gray-2); padding:12px 16px calc(12px + env(safe-area-inset-bottom)); background:var(--surface-white); }
  .onboarding-actions.is-primary > .relay-button { flex:1 1 auto; }
  .onboarding-number dl > div { grid-template-columns:1fr; gap:2px; }
}
</style>
