<script setup>
import ChoiceField from './fields/ChoiceField.vue'
import { computed, inject, nextTick, onMounted, ref } from 'vue'
import { Button, ErrorMessage, FeatherIcon, toast } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { linkedTitle } from '../services/linkedTitle'
import { businessTypeOptions, isPrimaryLink, linkFromChoice, linkHint, linksHeading, linksWith, linksWithout, primaryRequest, recordIcon, searchLinkChoices } from '../services/contactLinks'

// `start` opens the link form at once, with the search focused.
const props = defineProps({ contact: { type: String, required: true }, detail: { type: Object, required: true }, start: Boolean })
const emit = defineEmits(['changed', 'cancel'])
const capabilities = inject('relayCapabilities', ref({}))
const busy = ref(false), error = ref(''), adding = ref(false), removing = ref(null)
const types = ref([]), recordType = ref(''), choice = ref(''), linkForm = ref(null)
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

const choiceLabels = new Map()
// The record type comes first; the search then looks only in that type.
const pickedType = computed(() => types.value.find(type => type.value === recordType.value))
const recordField = computed(() => ({
  label: pickedType.value?.label || 'Record', placeholder: pickedType.value ? 'Find ' + pickedType.value.label.toLowerCase() : 'Choose a record type first',
  readOnly: busy.value || !pickedType.value,
  search: async (query, signal) => {
    if (!pickedType.value) return []
    const rows = await searchLinkChoices([pickedType.value], doctype => coreApi('api.business_records', { doctype, query }, false, { signal }))
    for (const row of rows) choiceLabels.set(row.value, row.label)
    return rows
  },
}))
function pickType(value) { recordType.value = value; choice.value = '' }

async function startAdding() {
  adding.value = true; removing.value = null; error.value = ''
  if (!types.value.length) {
    try { types.value = businessTypeOptions(await coreApi('business_types.list_types')) }
    catch (e) { error.value = e.message; return }
  }
  recordType.value = ''; choice.value = ''
  await nextTick()
  linkForm.value?.querySelector(recordType.value ? 'input' : 'button')?.focus()
}
function stopAdding() { adding.value = false; choice.value = ''; recordType.value = '' }
function cancelAdding() { stopAdding(); emit('cancel') }
onMounted(() => { if (props.start && props.detail.can_edit_links) startAdding() })
async function addLink() {
  const link = linkFromChoice(choice.value)
  if (!await saveLinks(linksWith(links.value, link))) return
  toast('Linked to ' + (choiceLabels.get(choice.value) || link.name))
  stopAdding()
}
async function removeLink(link) {
  if (await saveLinks(linksWithout(links.value, link))) removing.value = null
}
</script>

<template>
  <div class="contact-links">
    <p v-if="start && adding && types.length" class="info-hint">{{ linkHint(types) }}</p>
    <div class="info-group-title"><span>{{ linksHeading(links.length) }}</span>
      <button v-if="detail.can_edit_links && !adding" type="button" class="info-group-action" :disabled="busy" @click="startAdding">+ Link record</button></div>
    <ErrorMessage :message="error" />
    <form v-if="adding" ref="linkForm" class="contact-link-form info-card" aria-label="Link to a business record" @submit.prevent="addLink">
      <div v-if="types.length" class="contact-link-types" role="radiogroup" aria-label="Record type">
        <span class="contact-link-step">Record type</span>
        <div class="contact-link-type-options"><button v-for="type in types" :key="type.value" type="button" role="radio" :aria-checked="recordType === type.value" :disabled="busy" @click="pickType(type.value)">{{ type.label }}</button></div>
      </div>
      <ChoiceField :key="recordType" v-model="choice" :field="recordField" />
      <div class="contact-link-form-actions"><Button label="Cancel" variant="ghost" :disabled="busy" @click="cancelAdding" /><Button type="submit" label="Link" variant="solid" :loading="busy" :disabled="!choice" /></div>
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
            <a :href="desk(link)"><b>{{ linkedTitle(link.doctype, link.name) }}</b><span v-if="links.length > 1 && isPrimaryLink(detail.primary, link)" class="info-primary">Main</span></a>
            <small>{{ link.doctype }} · <a :href="conversation(link)">Open chat</a></small>
          </span>
          <span v-if="detail.can_set_primary && links.length > 1" class="info-switch-label" aria-hidden="true">Main</span>
          <button v-if="detail.can_set_primary && links.length > 1" type="button" role="switch" class="info-switch" :aria-checked="isPrimaryLink(detail.primary, link)"
            :aria-label="'Main record: ' + linkedTitle(link.doctype, link.name)" :disabled="busy" title="Main record" @click="setPrimary(link, !isPrimaryLink(detail.primary, link))" />
          <Button v-if="detail.can_edit_links" class="info-remove" icon="x" variant="ghost" size="xs" :aria-label="'Remove link: ' + linkedTitle(link.doctype, link.name)" :disabled="busy" @click="removing = keyOf(link); adding = false" />
        </template>
      </li>
    </ul>
    <p v-else-if="!adding" class="info-hint">{{ detail.can_edit_links ? 'Not linked to a business record yet.' : 'Not linked to a business record yet. A manager can link it.' }}</p>
    <p v-if="links.length > 1" class="info-hint">The main record shows in the chat header{{ capabilities.ai ? ' and gives AI its context' : '' }}.</p>
  </div>
</template>

<style scoped>
.contact-links { display:flex; flex-direction:column; min-width:0; }
.contact-link-form { display:flex; flex-direction:column; gap:10px; padding:12px; }
.contact-link-types { display:flex; flex-direction:column; gap:6px; }
.contact-link-step { color:var(--relay-ink-3); font-size:12px; }
.contact-link-type-options { display:flex; flex-wrap:wrap; gap:6px; }
.contact-link-type-options button { min-height:44px; padding:0 12px; border:1px solid var(--relay-stroke); border-radius:15px; color:var(--relay-ink-2); font-size:13px; }
.contact-link-type-options button[aria-checked="true"] { border-color:var(--relay-accent); background:var(--relay-accent-soft); color:var(--relay-accent-text); font-weight:600; }
.contact-link-form-actions { display:flex; justify-content:flex-end; gap:8px; }
.info-switch-label { flex:none; color:var(--relay-ink-3); font-size:11.5px; }
@media (max-width:768px) { .info-group-action, .info-item-copy a { display:inline-flex; align-items:center; min-height:44px; } .contact-links :deep(:is(button,input)) { min-height:44px !important; min-width:44px !important; } }
</style>
