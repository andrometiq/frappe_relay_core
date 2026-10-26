<script setup>
import { computed, ref } from 'vue'
import { Button, ErrorMessage, FeatherIcon, FormControl } from '@relay/ui'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import { coreApi } from '../services/coreApi'
import { linkedTitle } from '../services/linkedTitle'
import { businessTypeOptions, isPrimaryLink, linksWith, linksWithout, primaryRequest } from '../services/contactLinks'

const props = defineProps({ contact: { type: String, required: true }, detail: { type: Object, required: true } })
const emit = defineEmits(['changed'])
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
    <div class="contact-links-title"><h4>Linked records · {{ links.length }}</h4>
      <button v-if="detail.can_edit_links && !adding" type="button" class="contact-links-add" :disabled="busy" @click="startAdding"><FeatherIcon name="plus" :size="14" />Link</button></div>
    <ErrorMessage :message="error" />
    <form v-if="adding" class="contact-link-form" aria-label="Link a business record" @submit.prevent="addLink">
      <FormControl v-model="doctype" type="select" label="Business type" :options="types" :disabled="busy" @update:model-value="record = ''" />
      <RemoteLinkField :key="doctype" v-model="record" :field="{ label: 'Record', method: 'api.business_records', params: { doctype }, placeholder: 'Search records…', readOnly: busy || !doctype }" />
      <div class="contact-link-form-actions"><Button label="Cancel" variant="ghost" :disabled="busy" @click="stopAdding" /><Button type="submit" label="Link record" variant="solid" :loading="busy" :disabled="!record" /></div>
    </form>
    <ul v-if="links.length" class="contact-link-list">
      <li v-for="link in links" :key="keyOf(link)" class="contact-link">
        <template v-if="removing === keyOf(link)">
          <span class="contact-link-copy"><strong>Remove {{ linkedTitle(link.doctype, link.name) }}?</strong><small>The contact stays; only this link goes.</small></span>
          <Button label="Cancel" variant="ghost" size="xs" :disabled="busy" @click="removing = null" />
          <Button label="Remove" theme="red" variant="solid" size="xs" :loading="busy" @click="removeLink(link)" />
        </template>
        <template v-else>
          <span class="contact-link-icon" aria-hidden="true"><FeatherIcon name="file-text" :size="16" /></span>
          <span class="contact-link-copy">
            <a :href="desk(link)"><strong>{{ linkedTitle(link.doctype, link.name) }}</strong><span v-if="isPrimaryLink(detail.primary, link)" class="contact-link-primary">Primary</span></a>
            <small>{{ link.doctype }} · <a :href="conversation(link)">Open conversation</a></small>
          </span>
          <button v-if="detail.can_set_primary" type="button" role="switch" class="contact-link-switch" :aria-checked="isPrimaryLink(detail.primary, link)"
            :aria-label="'Primary record: ' + linkedTitle(link.doctype, link.name)" :disabled="busy || links.length < 2"
            :title="links.length < 2 ? 'A single linked record is the primary' : 'Primary record'" @click="setPrimary(link, !isPrimaryLink(detail.primary, link))"><span class="contact-link-track" /></button>
          <Button v-if="detail.can_edit_links" icon="x" variant="ghost" size="xs" :aria-label="'Remove link: ' + linkedTitle(link.doctype, link.name)" :disabled="busy" @click="removing = keyOf(link); adding = false" />
        </template>
      </li>
    </ul>
    <p v-else class="contact-links-hint">No linked records you can see yet.{{ detail.can_edit_links ? ' Link one to route this contact’s conversations.' : '' }}</p>
    <p v-if="links.length > 1" class="contact-links-hint">The primary record shows in the chat header and gives AI its context. Only one record can be primary.</p>
  </div>
</template>

<style scoped>
.contact-links { display:flex; flex-direction:column; gap:8px; min-width:0; }
.contact-links-title { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.contact-links-title h4 { color:var(--ink-gray-6); font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:.02em; }
.contact-links-add { display:inline-flex; align-items:center; gap:4px; min-height:32px; padding:0 8px; border-radius:var(--relay-radius-sm); color:var(--relay-accent-text); font-size:13px; font-weight:600; }
.contact-links-add:hover { background:var(--relay-hover); }
.contact-link-list { border-radius:var(--relay-radius); background:var(--relay-layer-strong); box-shadow:var(--relay-shadow-1); overflow:hidden; }
.contact-link { display:flex; align-items:center; gap:10px; min-height:56px; padding:8px 8px 8px 12px; border-top:1px solid var(--relay-stroke); }
.contact-link:first-child { border-top:0; }
.contact-link-icon { display:grid; place-items:center; width:34px; height:34px; flex:none; border-radius:7px; background:var(--relay-accent-soft); color:var(--relay-accent-text); }
.contact-link-copy { flex:1; min-width:0; }
/* Beat the page-wide 40px link touch target; the whole row is the touch target here. */
.contact-links .contact-link .contact-link-copy a { display:inline; min-height:0; color:inherit; text-decoration:none; }
.contact-links .contact-link .contact-link-copy > a { display:flex; align-items:center; gap:6px; min-width:0; }
.contact-link-copy > strong { display:block; }
.contact-link-copy strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:13.5px; font-weight:600; color:var(--ink-gray-9); }
.contact-link-copy small { display:block; margin-top:1px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--ink-gray-6); font-size:12px; }
.contact-links .contact-link .contact-link-copy small a { color:var(--relay-accent-text); }
.contact-link-primary { flex:none; padding:1px 6px; border-radius:4px; background:var(--relay-accent-soft); color:var(--relay-accent-text); font-size:10.5px; font-weight:700; text-transform:uppercase; }
.contact-link-switch { display:grid; place-items:center; width:48px; flex:none; border:0; border-radius:var(--relay-radius-sm); background:transparent; box-shadow:none; }
.contact-link-switch:disabled { opacity:.55; cursor:default; }
.contact-link-switch:focus-visible { outline:2px solid var(--relay-accent); outline-offset:-2px; }
.contact-link-track { position:relative; width:40px; height:20px; border:1px solid var(--ink-gray-5); border-radius:10px; transition:background-color var(--relay-fast) ease; }
.contact-link-track::after { content:""; position:absolute; left:4px; top:4px; width:10px; height:10px; border-radius:50%; background:var(--ink-gray-5); transition:left var(--relay-fast) var(--relay-ease); }
[aria-checked=true] > .contact-link-track { border-color:var(--relay-accent); background:var(--relay-accent); }
[aria-checked=true] > .contact-link-track::after { left:23px; top:3px; width:12px; height:12px; background:var(--relay-accent-ink); }
.contact-link-form { display:flex; flex-direction:column; gap:10px; padding:12px; border-radius:var(--relay-radius); background:var(--relay-layer-strong); box-shadow:var(--relay-shadow-1); }
.contact-link-form-actions { display:flex; justify-content:flex-end; gap:8px; }
.contact-links-hint { margin:0 4px; color:var(--ink-gray-6); font-size:11.5px; line-height:1.4; }
</style>
