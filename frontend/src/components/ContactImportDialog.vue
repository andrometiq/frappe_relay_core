<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Dialog, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../services/coreApi'
import { uploadFile } from '../services/uploadFile'
import { contactColumns, importCount, importFileError, importState } from '../services/contactImport'
import { linkedTitle } from '../services/linkedTitle'

const open = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['imported'])
const file = ref(null), fileUrl = ref(''), channel = ref(''), channels = ref([])
const result = ref(null), done = ref(false), busy = ref(false), error = ref(''), page = ref(0)
const state = computed(() => importState(result.value))
const visibleRows = computed(() => state.value.rows.slice(page.value * 50, (page.value + 1) * 50))
const channelOptions = computed(() => [{ value: '', label: 'Use default country; no channel enrollment' }, ...channels.value.map(row => ({ value: row.name, label: linkedTitle('Relay Channel', row.name, row.label || 'WhatsApp') }))])
function resetPreview() { result.value = null; done.value = false; error.value = ''; page.value = 0 }
function choose(event) { file.value = event.target.files?.[0] || null; fileUrl.value = ''; resetPreview(); error.value = importFileError(file.value) }
async function preview() {
  error.value = importFileError(file.value)
  if (error.value) return
  busy.value = true
  try {
    fileUrl.value ||= await uploadFile(file.value, 'Could not upload the file. Try again.')
    result.value = await coreApi('contact_import.preview', { file_url: fileUrl.value, channel: channel.value || undefined }, true)
    error.value = state.value.error; page.value = 0
  } catch { error.value = 'Could not preview this file. Check the file format and your permissions, then try again.' }
  finally { busy.value = false }
}
async function apply() {
  busy.value = true; error.value = ''
  try {
    result.value = await coreApi('contact_import.apply', { file_url: fileUrl.value, channel: channel.value || undefined }, true)
    error.value = state.value.error; page.value = 0
    if (!error.value) { done.value = true; emit('imported') }
  } catch { error.value = 'Import was not confirmed. Preview the file again before retrying; existing links will be skipped.'; result.value = null }
  finally { busy.value = false }
}
watch(channel, resetPreview)
watch(open, async value => {
  if (!value) return
  file.value = null; fileUrl.value = ''; resetPreview()
  try { channels.value = (await coreApi('api.channel_options')).items.filter(row => row.enabled && row.channel === 'WhatsApp') }
  catch { channels.value = [] }
})
</script>

<template>
  <Dialog v-model="open" class="contact-import-dialog" :options="{ title: done ? 'Import complete' : 'Import contacts', size: 'xl' }" :disable-outside-click-to-close="busy">
    <div class="contact-import" :aria-busy="busy">
      <template v-if="!done && !result?.counts">
        <p>1. Preview your file · 2. Import valid rows</p>
        <p>Use these columns: {{ contactColumns.join(', ') }}. Maximum 2000 rows. Leave both business columns blank for unlinked contacts.</p>
        <label class="contact-import-file">Contact spreadsheet
          <input type="file" accept=".xlsx,.csv" :disabled="busy" @change="choose" />
        </label>
        <FormControl v-model="channel" label="WhatsApp channel (optional)" type="select" :options="channelOptions" :disabled="busy" />
        <p>A selected channel supplies the country and enrolls new mobile contacts. This does not send messages.</p>
      </template>
      <div v-if="!done && result?.counts" class="contact-import-pages"><span>{{ file?.name }}</span><Button label="Change file" variant="outline" :disabled="busy" @click="resetPreview" /></div>
      <ErrorMessage v-if="error" :message="error" />
      <template v-if="result?.counts">
        <p role="status">{{ done ? importCount(result.counts.created, 'contact') + ' created · ' + importCount(result.counts.linked, 'link') + ' added' : importCount(state.valid, 'valid row') }} · {{ state.skipped }} skipped · {{ importCount(state.errors, 'error') }}</p>
        <p v-if="!done">Mobile country: {{ result.region || 'include country codes' }}. Only valid rows will be imported; errors and duplicates are skipped.</p>
        <div class="contact-import-table" tabindex="0" role="region" aria-label="Import preview">
          <table>
            <thead><tr><th scope="col">Row</th><th scope="col">Status</th><th v-for="column in contactColumns" :key="column" scope="col">{{ column }}</th></tr></thead>
            <tbody><tr v-for="row in visibleRows" :key="row.row"><td>{{ row.row }}</td><td :class="{ 'import-error': row.status === 'error' }">{{ row.status === 'error' ? 'Error · ' : '' }}{{ row.reason }}</td><td v-for="column in contactColumns" :key="column">{{ row.values[column] || '—' }}</td></tr></tbody>
          </table>
        </div>
        <div class="contact-import-pages">
          <Button label="Previous rows" :disabled="page === 0" @click="page--" />
          <span>{{ page * 50 + 1 }}–{{ Math.min((page + 1) * 50, state.rows.length) }} of {{ state.rows.length }}</span>
          <Button label="Next rows" :disabled="(page + 1) * 50 >= state.rows.length" @click="page++" />
        </div>
      </template>
    </div>
    <template #actions>
      <Button :label="done ? 'Done' : 'Cancel'" variant="ghost" :disabled="busy" @click="open = false" />
      <Button v-if="!done" label="Preview" variant="outline" :disabled="!file || busy" :loading="busy && !result" @click="preview" />
      <Button v-if="!done && result?.counts" :label="'Import ' + importCount(state.valid, 'valid row')" variant="solid" :disabled="!state.valid || busy" :loading="busy" @click="apply" />
    </template>
  </Dialog>
</template>

<style scoped>
.contact-import { display:flex; flex-direction:column; gap:16px; min-width:0; font-size:14px; color:var(--ink-gray-8); }
.contact-import p { overflow-wrap:anywhere; }
.contact-import-file { display:flex; flex-direction:column; gap:8px; }
.contact-import input { max-width:100%; min-height:44px; }
.contact-import-table { overflow:auto; max-height:45vh; border:1px solid var(--outline-gray-2); border-radius:8px; }
.contact-import table { width:100%; border-collapse:collapse; font-size:13px; }
.contact-import th { text-align:left; position:sticky; top:0; background:var(--surface-gray-1); }
.contact-import :is(th,td) { padding:12px; border-bottom:1px solid var(--outline-gray-2); min-width:100px; max-width:240px; overflow-wrap:anywhere; }
.contact-import :is(th,td):first-child { min-width:56px; width:56px; white-space:nowrap; }
.contact-import :is(th,td):nth-child(2) { min-width:180px; }
.contact-import .import-error { color:var(--ink-red-3); }
.contact-import-pages { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:8px; }
.contact-import :deep(button), .contact-import :deep(select) { min-height:44px; }
</style>

<style>
.relay-dialog.contact-import-dialog :is(.relay-button,.relay-control) { min-height:44px; }
.contact-import-file input::file-selector-button { min-height:44px; padding:8px 12px; }
</style>
