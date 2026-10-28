<script setup>
import ChoiceField from './fields/ChoiceField.vue'
import { computed, inject, ref } from 'vue'
import { Button, ErrorMessage, FeatherIcon } from '@relay/ui'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import { coreApi } from '../services/coreApi'
import { linkedTitle } from '../services/linkedTitle'
import { businessTypeOptions, isPrimaryLink, linksWith, linksWithout, primaryRequest, recordIcon } from '../services/contactLinks'

const props = defineProps({ contact: { type: String, required: true }, detail: { type: Object, required: true } })
const emit = defineEmits(['changed'])
const capabilities = inject('relayCapabilities', ref({}))
const busy = ref(false), error = ref(''), adding = ref(false), removing = ref(null)
const types = ref([]), doctype = ref(''), record = ref('')
const links = computed(() => props.detail.links || [])
const keyOf = link => link.doctype + '\u0000' + link.name
const desk = link => '/desk/' + link.doctype.toLowerCase().replaceAll(' ', '-') + '/' + encodeURIComponent(link.name)
const conversation = link => '#/messages?' + new URLSearchParams({ business_doctype: link.doctype, business_name: link.name, contact: props.contact })

async function save(method, values) {
  busy.value = true; error.value = ''
  try { emit('changed', await coreApi(method, values, true)); return true }
  catch (e) { error.value = e.message; return false }
  finally { busy.value = false }
}
const saveLinks = next => save('contacts.set_links', { contact: props.contact, links: next })
const setPrimary = (link, on) => save('contacts.set_primary', primaryRequest(props.contact, link, on))

async function startAdding() {
  adding.value = true; removing.value = null; error.value = ''
  if (types.value.length) return
  try { types.value = businessTypeOptions(await coreApi('business_types.list_types')); doctype.value = types.value[0]?.value || '' }
  catch (e) { error.value = e.message }
}
function stopAdding() { adding.value = false; record.value = '' }
async function addLink() {
  if (await saveLinks(linksWith(links.value, { doctype: doctype.value, name: record.value }))) stopAdding()
}
async function removeLink(link) {
  if (await saveLinks(linksWithout(links.value, link))) removing.value = null
}
</script>

<template>
  <div class="contact-links">
    <div class="info-group-title"><span>Linked records · {{ links.length }}</span>
      <button v-if="detail.can_edit_links && !adding" type="button" class="info-group-action" :disabled="busy" @click="startAdding">+ Link</button></div>
    <ErrorMessage :message="error" />
    <form v-if="adding" class="contact-link-form info-card" aria-label="Link a business record" @submit.prevent="addLink">
      <ChoiceField v-model="doctype" :field="{ label: 'Business type', options: types, readOnly: busy }" @update:model-value="record = ''" />
      <RemoteLinkField :key="doctype" v-model="record" :field="{ label: 'Record', method: 'api.business_records', params: { doctype }, placeholder: 'Search records…', readOnly: busy || !doctype }" />
      <div class="contact-link-form-actions"><Button label="Cancel" variant="ghost" :disabled="busy" @click="stopAdding" /><Button type="submit" label="Link record" variant="solid" :loading="busy" :disabled="!record" /></div>
    </form>
    <ul v-if="links.length" class="info-card">
      <li v-for="link in links" :key="keyOf(link)" class="info-item">
        <template v-if="removing === keyOf(link)">
          <span class="info-item-copy"><b>Remove {{ linkedTitle(link.doctype, link.name) }}?</b><small>The contact stays; only this link goes.</small></span>
          <Button label="Cancel" variant="ghost" size="xs" :disabled="busy" @click="removing = null" />
          <Button label="Remove" theme="red" variant="solid" size="xs" :loading="busy" @click="removeLink(link)" />
        </template>
        <template v-else>
          <span class="info-icon" :class="'is-' + recordIcon(link.doctype).tone" aria-hidden="true"><FeatherIcon :name="recordIcon(link.doctype).icon" :size="18" /></span>
          <span class="info-item-copy">
            <a :href="desk(link)"><b>{{ linkedTitle(link.doctype, link.name) }}</b><span v-if="isPrimaryLink(detail.primary, link)" class="info-primary">Primary</span></a>
            <small>{{ link.doctype }} · <a :href="conversation(link)">Open chat</a></small>
          </span>
          <button v-if="detail.can_set_primary" type="button" role="switch" class="info-switch" :aria-checked="isPrimaryLink(detail.primary, link)"
            :aria-label="'Primary record: ' + linkedTitle(link.doctype, link.name)" :disabled="busy || links.length < 2"
            :title="links.length < 2 ? 'A single linked record is the primary' : 'Primary record'" @click="setPrimary(link, !isPrimaryLink(detail.primary, link))" />
          <Button v-if="detail.can_edit_links" class="info-remove" icon="x" variant="ghost" size="xs" :aria-label="'Remove link: ' + linkedTitle(link.doctype, link.name)" :disabled="busy" @click="removing = keyOf(link); adding = false" />
        </template>
      </li>
    </ul>
    <p v-else class="info-hint">No linked records you can see yet.{{ detail.can_edit_links ? ' Link one to route this contact’s conversations.' : '' }}</p>
    <p v-if="links.length > 1" class="info-hint">The primary record shows in the chat header{{ capabilities.ai ? ' and gives AI its context' : '' }}. Only one record can be primary.</p>
  </div>
</template>

<style scoped>
.contact-links { display:flex; flex-direction:column; min-width:0; }
.contact-link-form { display:flex; flex-direction:column; gap:10px; padding:12px; }
.contact-link-form-actions { display:flex; justify-content:flex-end; gap:8px; }
</style>
