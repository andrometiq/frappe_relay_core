<script setup>
import { computed, ref, watch } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
const props = defineProps({ contact: String, links: Array, endpoints: Array, editable: Boolean })
const business = ref(''), rows = ref([]), busy = ref(false), error = ref(''), notice = ref('')
const selected = computed(() => props.links[Number(business.value)])
let generation = 0
async function load() {
  const current = ++generation; rows.value = []; error.value = ''; notice.value = ''
  if (business.value === '' || !selected.value) return
  busy.value = true
  try {
    const result = await coreApi('api.contact_preferences', { contact: props.contact, business_doctype: selected.value.doctype, business_name: selected.value.name })
    if (current === generation) rows.value = props.endpoints.map(endpoint => ({ endpoint: endpoint.name, consent: 'Denied', priority: 10, ...result.items.find(row => row.endpoint === endpoint.name) }))
  } catch (e) { if (current === generation) error.value = e.message }
  finally { if (current === generation) busy.value = false }
}
watch(business, load)
async function save(row) {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    await coreApi('api.save_contact_preference', { contact: props.contact, business_doctype: selected.value.doctype, business_name: selected.value.name, endpoint: row.endpoint, consent: row.consent, priority: row.priority }, true)
    notice.value = 'Consent saved for this business and person.'
  } catch (e) { error.value = e.message }
  finally { busy.value = false }
}
</script>
<template>
  <section class="space-y-3" aria-label="Channel preferences">
    <h4 class="font-medium">Business channel preferences</h4>
    <p class="text-sm">Record the person’s consent for each business separately. Lower priorities are tried first; equal priorities require review.</p>
    <FormControl v-model="business" type="select" label="Business" :disabled="busy" :options="[{value:'',label:'Choose a business'}, ...links.map((link, index) => ({value:String(index),label:link.doctype + ' · ' + link.name}))]" />
    <div v-for="row in rows" :key="row.endpoint" class="border-t pt-3 space-y-2">
      <p class="break-words">{{ endpoints.find(item => item.name === row.endpoint)?.provider }} · {{ endpoints.find(item => item.name === row.endpoint)?.endpoint }}</p>
      <div class="grid gap-3 sm:grid-cols-2"><FormControl v-model="row.consent" label="Consent" type="select" :options="['Denied','Granted']" :disabled="busy || !editable" /><FormControl v-model="row.priority" label="Priority (1–100)" type="number" min="1" max="100" :disabled="busy || !editable" /></div>
      <Button v-if="editable" label="Save consent" :disabled="busy" @click="save(row)" />
    </div>
    <p v-if="!editable" class="text-sm">A System Manager can record or withdraw consent.</p>
    <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p>
  </section>
</template>
