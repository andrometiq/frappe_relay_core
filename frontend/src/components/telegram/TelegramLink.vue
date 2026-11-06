<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Button, ErrorMessage } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { onRealtime } from '../../services/realtime'

// With a contact, a manager makes a link to send to that contact; without one, the link is for the signed-in user.
const props = defineProps({ contact: String })
const emit = defineEmits(['linked'])
const link = ref(null), busy = ref(false), error = ref(''), copied = ref(false)
const label = computed(() => props.contact ? 'Send Telegram link' : 'Link my Telegram')
async function create() {
  busy.value = true; error.value = ''; copied.value = false
  try { link.value = props.contact ? await coreApi('telegram_links.link_contact', { contact: props.contact }, true) : await coreApi('telegram_links.link_me', {}, true) }
  catch (e) { error.value = e.message }
  finally { busy.value = false }
}
async function copy() {
  await navigator.clipboard?.writeText(link.value.url)
  copied.value = true
}
function changed(event) {
  if (event?.kind !== 'telegram_link' || !link.value) return
  link.value = null
  if (event.linked) emit('linked')
  else error.value = 'This Telegram account is already linked to another contact. Ask a manager to check it.'
}
let stop
onMounted(() => { stop = onRealtime(changed) })
onBeforeUnmount(() => stop?.())
</script>
<template>
  <div class="telegram-link">
    <Button v-if="!link" :label="label" icon-left="send" variant="outline" size="sm" :loading="busy" @click="create" />
    <div v-else class="telegram-link-ready" role="status">
      <p v-if="contact">Send this link to the contact. When they open it and press Start, Relay saves their Telegram chat. It works once, within {{ link.expires_in / 60 }} minutes.</p>
      <p v-else>Open the link and press Start in Telegram. It works once, within {{ link.expires_in / 60 }} minutes.</p>
      <code>{{ link.url }}</code>
      <div class="telegram-link-actions">
        <a v-if="!contact" class="v1-link" :href="link.url" target="_blank" rel="noopener">Open Telegram</a>
        <Button :label="copied ? 'Copied' : 'Copy link'" icon-left="copy" variant="ghost" size="sm" @click="copy" />
      </div>
    </div>
    <ErrorMessage :message="error" />
  </div>
</template>
<style scoped>
.telegram-link { display:flex; flex-direction:column; gap:6px; }
.telegram-link-ready { display:flex; flex-direction:column; gap:6px; font-size:12px; color:var(--ink-gray-7); }
.telegram-link-ready code { overflow-wrap:anywhere; font-size:11px; padding:6px 8px; border-radius:6px; background:var(--surface-gray-2); }
.telegram-link-actions { display:flex; align-items:center; gap:8px; }
</style>
