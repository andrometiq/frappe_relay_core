<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Button, ErrorMessage, FeatherIcon, FormControl } from '@relay/ui'
import { coreApi } from '../../services/coreApi'

const props = defineProps({ state: { type: Object, required: true } })
const emit = defineEmits(['next'])
const code = ref(''), busy = ref(false), failure = ref(null), account = ref(props.state.hub.account)
const NEW_CODE = ['origin_not_allowed', 'token_revoked', 'token_expired', 'token_invalid', 'token_used_up', 'setup_code_invalid', 'setup_code_required']
let moving

async function connect(setupCode = '') {
  busy.value = true; failure.value = null
  try {
    const result = await coreApi('onboarding.api.connect_hub', setupCode ? { setup_code: setupCode } : {}, true)
    // A linked site whose check failed stays here, so Try again can check it again.
    if (result.error) failure.value = result.error
    else if (result.connected) { account.value = result.account; moving = setTimeout(() => emit('next', 'business'), 1000) }
  } catch (e) { failure.value = { code: 'unknown', message: e.message } }
  finally { busy.value = false }
}
const askCode = () => failure.value?.code !== 'hub_check_failed' && (!props.state.hub.enrolment_available || NEW_CODE.includes(failure.value?.code))
onMounted(() => { if (!props.state.hub.connected && props.state.hub.enrolment_available) connect() })
onBeforeUnmount(() => clearTimeout(moving))
</script>
<template>
  <section class="workflow-card onboarding-card" aria-labelledby="onboarding-hub-title">
    <h2 id="onboarding-hub-title">Connect to Relay</h2>
    <template v-if="account && !failure">
      <p class="onboarding-row onboarding-ok" role="status"><FeatherIcon name="check" :size="18" />Connected as {{ account }}</p>
      <div class="onboarding-actions is-primary"><Button variant="solid" label="Continue" @click="emit('next', 'business')" /></div>
    </template>
    <template v-else>
      <p v-if="busy && !code" class="onboarding-row" role="status"><FeatherIcon name="loader-circle" class="relay-button__spinner" :size="18" />Connecting this site to Relay Hub…</p>
      <ErrorMessage v-if="failure" :message="failure.message" />
      <form v-if="askCode()" class="space-y-3" @submit.prevent="connect(code)">
        <p>Enter your setup code</p>
        <FormControl v-model="code" label="Setup code" autocomplete="off" spellcheck="false" class="font-mono" :disabled="busy" />
        <p class="onboarding-hint">Your Relay provider gives you this code. You can also paste the whole setup link.</p>
        <div class="onboarding-actions is-primary"><Button type="submit" variant="solid" label="Connect" :loading="busy" :disabled="!code.trim()" /></div>
      </form>
      <div v-else-if="failure" class="onboarding-actions is-primary"><Button variant="solid" label="Try again" :loading="busy" @click="connect()" /></div>
    </template>
  </section>
</template>
