<script setup>
import { inject, ref } from 'vue'
import { Button, ErrorMessage, FormControl, toast } from '@relay/ui'
import { coreApi } from '../../services/coreApi'

const props = defineProps({ state: { type: Object, required: true } })
const capabilities = inject('relayCapabilities')
const checked = ref(Object.fromEntries(props.state.record_types.map(row => [row.doctype, row.enabled])))
const busy = ref(false), error = ref('')

async function finish(save) {
  busy.value = true; error.value = ''
  try {
    if (save) {
      // Only changed types are written; an unchecked type that was never set up stays unset.
      for (const row of props.state.record_types) {
        if (checked.value[row.doctype] !== row.enabled && (row.configured || checked.value[row.doctype])) {
          await coreApi('business_types.save', { business_doctype: row.doctype, enabled: checked.value[row.doctype] ? 1 : 0 }, true)
        }
      }
    }
    await coreApi('onboarding.api.finish', {}, true)
    capabilities.value = { ...capabilities.value, onboarding: { required: false, step: 'done' } }
    toast('Relay is ready')
    location.hash = '#/messages'
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>
<template>
  <section class="workflow-card onboarding-card" aria-labelledby="onboarding-records-title">
    <h2 id="onboarding-records-title">Link chats to your records</h2>
    <p>Relay can show each chat with the customer, supplier or other record it belongs to. Choose the records your team works with.</p>
    <ErrorMessage :message="error" />
    <div v-if="state.record_types.length" class="onboarding-records">
      <FormControl v-for="row in state.record_types" :key="row.doctype" v-model="checked[row.doctype]" type="checkbox" :label="row.label" :disabled="busy" />
    </div>
    <p v-else class="onboarding-hint">This site has no customer or supplier records yet. You can add record types later in Settings.</p>
    <div class="onboarding-actions is-primary">
      <Button variant="solid" label="Save and finish" :loading="busy" @click="finish(true)" />
      <Button variant="ghost" label="Skip for now" :disabled="busy" @click="finish(false)" />
    </div>
  </section>
</template>
