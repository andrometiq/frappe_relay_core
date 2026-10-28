<script setup>
import ChoiceField from './fields/ChoiceField.vue'
import { computed, ref, watch } from 'vue'
import { Button, Dialog, ErrorMessage, FormControl } from '@relay/ui'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import { coreApi } from '../services/coreApi'
import { linkedTitle } from '../services/linkedTitle'
import { businessTypeOptions } from '../services/contactLinks'

const open = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['created'])
const name = ref(''), phone = ref(''), channel = ref(''), doctype = ref(''), record = ref('')
const channels = ref([]), types = ref([]), busy = ref(false), error = ref('')
const channelOptions = computed(() => channels.value.map(row => ({ value: row.name, label: linkedTitle('Relay Channel', row.name, 'WhatsApp') })))
const ready = computed(() => name.value.trim() && phone.value.trim() && channel.value && (!doctype.value || record.value))

async function prepare() {
  name.value = phone.value = doctype.value = record.value = error.value = ''
  try {
    const [available, businessTypes] = await Promise.all([coreApi('api.channel_options'), coreApi('business_types.list_types')])
    channels.value = available.items.filter(row => row.channel === 'WhatsApp' && row.enabled)
    channel.value = channels.value[0]?.name || ''
    types.value = [{ value: '', label: 'No link' }, ...businessTypeOptions(businessTypes)]
    if (!channel.value) error.value = 'Enable a WhatsApp channel before you add contacts.'
  } catch (e) { error.value = e.message }
}
async function create() {
  busy.value = true; error.value = ''
  try {
    const links = doctype.value && record.value ? [{ doctype: doctype.value, name: record.value }] : []
    const result = await coreApi('contacts.create', { name: name.value.trim(), phone: phone.value.trim(), channel: channel.value, links }, true)
    open.value = false
    emit('created', result)
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
watch(open, value => { if (value) prepare() })
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'New contact', size: 'sm' }" :disable-outside-click-to-close="busy">
    <form id="relay-new-contact" class="new-contact-form" @submit.prevent="ready && create()">
      <FormControl v-model="name" label="Name" required maxlength="140" autocomplete="name" :disabled="busy" />
      <FormControl v-model="phone" label="WhatsApp number" type="tel" required inputmode="tel" autocomplete="tel" placeholder="+91 98765 43210" :disabled="busy" />
      <ChoiceField v-if="channels.length > 1" v-model="channel" :field="{ label: 'WhatsApp channel', options: channelOptions, readOnly: busy }" />
      <ChoiceField v-model="doctype" :field="{ label: 'Link to (optional)', options: types, readOnly: busy }" @update:model-value="record = ''" />
      <RemoteLinkField v-if="doctype" :key="doctype" v-model="record" :field="{ label: 'Record', method: 'api.business_records', params: { doctype }, placeholder: 'Search records…', readOnly: busy }" />
      <p class="new-contact-hint">Use the country code. The number becomes a verified WhatsApp identity for this contact.</p>
      <ErrorMessage :message="error" />
    </form>
    <template #actions="{ close }">
      <Button label="Cancel" variant="ghost" :disabled="busy" @click="close" />
      <Button type="submit" form="relay-new-contact" label="Create contact" variant="solid" :loading="busy" :disabled="!ready" />
    </template>
  </Dialog>
</template>

<style scoped>
.new-contact-form { display:flex; flex-direction:column; gap:12px; }
.new-contact-hint { color:var(--ink-gray-6); font-size:12px; line-height:1.4; }
</style>
