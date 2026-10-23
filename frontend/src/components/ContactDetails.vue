<script setup>
import { ref, watch } from 'vue'
import { Button, Badge, ErrorMessage } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
const props = defineProps({ contact: String })
const detail = ref(null), busy = ref(false), error = ref('')
let generation = 0
const desk = (doctype, name) => '/desk/' + doctype.toLowerCase().replaceAll(' ', '-') + '/' + encodeURIComponent(name)
const conversation = link => '#/messages?' + new URLSearchParams({ business_doctype: link.doctype, business_name: link.name, contact: props.contact })
async function load() {
  const ticket = ++generation
  detail.value = null; error.value = ''; busy.value = true
  try { const data = await coreApi('api.contact_details', { contact: props.contact }); if (ticket === generation) detail.value = data }
  catch (e) { if (ticket === generation) error.value = e.message }
  finally { if (ticket === generation) busy.value = false }
}
watch(() => props.contact, load, { immediate: true })
useRealtimeRefresh(['Contact', 'Relay Contact Endpoint'], ['contacts', 'incoming'], load)
</script>
<template>
  <section class="workflow-card" aria-label="Contact and business links">
    <p v-if="busy" role="status">Loading contact details…</p>
    <ErrorMessage :message="error" /><Button v-if="error" label="Retry contact details" @click="load" />
    <template v-if="detail">
      <h3 class="font-semibold">{{ detail.label }}</h3>
      <p>{{ detail.phone || 'No phone number' }} <Badge :label="/^[0-9]{7,15}$/.test(detail.phone.replace(/[ +()\-]/g, '')) ? 'Phone format valid' : 'Country code and number required'" /></p>
      <a class="underline" :href="desk('Contact', detail.name)">Edit Contact and business links in Desk</a>
      <h4 class="font-medium">Permitted business links</h4>
      <div v-for="link in detail.links" :key="link.doctype + link.name" class="flex flex-wrap gap-3">
        <a class="underline" :href="desk(link.doctype, link.name)">{{ link.doctype }} · {{ link.name }}</a>
        <a class="underline" :href="conversation(link)">Open conversation</a>
      </div>
      <p v-if="!detail.links.length">No accessible, configured business links. Add a link in Contact and enable its business type in Settings.</p>
      <h4 class="font-medium">WhatsApp endpoints</h4>
      <article v-for="endpoint in detail.endpoints" :key="endpoint.name" class="border-t pt-3 space-y-1">
        <p>{{ endpoint.endpoint }} · {{ endpoint.channel }} <Badge :label="endpoint.verified ? 'Verified binding' : 'Needs review'" /></p>
        <p class="text-sm text-ink-gray-5">Created {{ endpoint.creation }} · Updated {{ endpoint.modified }}</p>
      </article>
      <p v-if="!detail.endpoints.length">No stored WhatsApp endpoints. Start a conversation from a business link or review an unlinked sender.</p>
    </template>
  </section>
</template>
