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
      <div class="is-wide space-y-2">
        <FormControl v-model="form.website" label="Website" type="url" placeholder="https://example.com" :disabled="busy || form.no_website" />
        <FormControl v-model="form.no_website" type="checkbox" label="We have no website" :disabled="busy" />
      </div>
      <FormControl v-model="form.street1" class="is-wide" label="Street address" required maxlength="140" autocomplete="address-line1" :disabled="busy" />
      <FormControl v-model="form.street2" class="is-wide" label="Street address line 2" maxlength="140" autocomplete="address-line2" :disabled="busy" />
      <FormControl v-model="form.city" label="City" required maxlength="100" autocomplete="address-level2" :disabled="busy" />
      <FormControl v-model="form.state" label="State" required maxlength="100" autocomplete="address-level1" :disabled="busy" />
      <FormControl v-model="form.zip_code" label="PIN or ZIP code" required maxlength="20" autocomplete="postal-code" :disabled="busy" />
      <FormControl v-model="form.country" label="Country" type="select" required :options="state.options.countries" :disabled="busy" />
      <div class="onboarding-phone">
        <FormControl v-model="form.phone_code" label="Country code" required inputmode="numeric" maxlength="5" placeholder="91" :disabled="busy" />
        <FormControl v-model="form.phone_number" label="Business phone" type="tel" required maxlength="20" autocomplete="tel-national" :disabled="busy" />
      </div>
      <FormControl v-model="form.timezone" label="Time zone" type="select" required :options="timezones" :disabled="busy" />
      <FormControl v-model="form.category" label="Category" type="select" required :options="state.options.categories" :disabled="busy" />
      <FormControl v-model="form.display_name" class="is-wide" label="WhatsApp display name" maxlength="100" :disabled="busy" />
      <FormControl v-model="form.description" class="is-wide" label="Business description" type="textarea" rows="3" required maxlength="512" :disabled="busy" />
    </div>
    <p class="onboarding-hint">Customers see the display name in WhatsApp. Meta checks that it matches your business.</p>
    <div class="onboarding-actions is-primary"><Button type="submit" variant="solid" label="Continue" :loading="busy" /></div>
  </form>
</template>
<style scoped>
.onboarding-phone { display:grid; grid-template-columns:minmax(0,96px) minmax(0,1fr); gap:8px; }
</style>
