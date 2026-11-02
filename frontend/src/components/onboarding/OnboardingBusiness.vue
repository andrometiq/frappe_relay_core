<script setup>
import { reactive, ref } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../../services/coreApi'

const props = defineProps({ state: { type: Object, required: true } })
const emit = defineEmits(['next'])
const form = reactive({ ...props.state.draft })
const busy = ref(false), error = ref('')
// Every half hour from UTC-12:00 to UTC+14:00, and the three quarter-hour zones.
const OFFSETS = [...Array.from({ length: 53 }, (_, step) => -720 + step * 30), 345, 525, 765]
const timezones = [...new Set([...OFFSETS.map(offset), form.timezone].filter(Boolean))].sort((a, b) => minutes(a) - minutes(b))
  .map(value => ({ value, label: value === form.timezone && form.timezone_name ? `${value} (${form.timezone_name})` : value }))

function offset(total) {
  const sign = total < 0 ? '-' : '+', value = Math.abs(total)
  return `UTC${sign}${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}
function minutes(value) {
  const [, sign, hours, mins] = value.match(/UTC([+-])(\d\d):(\d\d)/) || [, '+', '0', '0']
  return (sign === '-' ? -1 : 1) * (Number(hours) * 60 + Number(mins))
}
async function save() {
  busy.value = true; error.value = ''
  try {
    await coreApi('onboarding.api.save_draft', { ...form, no_website: form.no_website ? 1 : 0 }, true)
    emit('next', 'number')
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>
<template>
  <form class="workflow-card onboarding-card" aria-labelledby="onboarding-business-title" @submit.prevent="save">
    <h2 id="onboarding-business-title">Business details</h2>
    <p>Meta asks for these when you connect WhatsApp. Relay fills them in for you.</p>
    <ErrorMessage :message="error" />
    <div class="onboarding-fields">
      <FormControl v-model="form.name" class="is-wide" label="Business name" required maxlength="100" :disabled="busy" />
      <FormControl v-model="form.email" label="Business email" type="email" required :disabled="busy" />
      <FormControl v-model="form.country" label="Country" type="select" required :options="state.options.countries" :disabled="busy" />
      <div class="is-wide space-y-2">
        <FormControl v-model="form.website" label="Website" type="url" placeholder="https://example.com" :disabled="busy || form.no_website" />
        <FormControl v-model="form.no_website" type="checkbox" label="We have no website" :disabled="busy" />
      </div>
      <FormControl v-model="form.timezone" label="Time zone" type="select" :options="timezones" :disabled="busy" />
      <FormControl v-model="form.category" label="Category" type="select" :options="state.options.categories" :disabled="busy" />
      <FormControl v-model="form.display_name" class="is-wide" label="WhatsApp display name" maxlength="100" :disabled="busy" />
    </div>
    <p class="onboarding-hint">Customers see the display name in WhatsApp. Meta checks that it matches your business.</p>
    <div class="onboarding-actions is-primary"><Button type="submit" variant="solid" label="Continue" :loading="busy" /></div>
  </form>
</template>
