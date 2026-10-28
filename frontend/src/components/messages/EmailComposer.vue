<script setup>
import { computed, inject, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { messagesKey } from '../../composables/messagesContext'
import { coreApi } from '../../services/coreApi'
import { randomUUID } from '../../services/crypto'
import { addressList, compositionScope, emailComposition, channelStatus } from '../../services/channelComposition'
import { useStoredDraft } from '../../composables/useStoredDraft'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
const { source, busy, beginEmail, finishEmail } = inject(messagesKey)
let active = true
onBeforeUnmount(() => { active = false })
const anchor = source.value
const draft = reactive(emailComposition(anchor))
const error = ref(''), notice = ref(''), sending = ref(false), fileInput = ref(null)
const recipientsOpen = ref(false), focused = ref(false)
const expanded = computed(() => focused.value || !!draft.body || !!draft.request || recipientsOpen.value)
watch(() => [draft.cc, draft.bcc], ([cc, bcc]) => { if (cc || bcc) recipientsOpen.value = true }, { immediate:true })
const locked = computed(() => !!draft.request)
const disabled = computed(() => busy.value || sending.value || locked.value)
const clearStored = useStoredDraft(() => compositionScope(anchor, document.getElementById('app')?.dataset.user), () => ({...draft}), saved => Object.assign(draft, saved))
function modeChanged(mode) {
  const composition = emailComposition(anchor, mode)
  Object.assign(draft, {mode, to:composition.to, cc:composition.cc, bcc:'', subject:composition.subject})
  if (mode === 'forward' && !draft.body.trim()) draft.body = composition.body
}
async function attach(event) {
  const files = [...event.target.files]; event.target.value = ''; error.value = ''
  if (draft.attachments.length + files.length > 8 || files.reduce((sum,file) => sum + file.size, draft.attachments.reduce((sum,file) => sum + file.size,0)) > 4*1024*1024) {
    error.value = 'Choose up to eight attachments, at most 4 MiB combined.'; return
  }
  sending.value = true
  try {
    for (const file of files) {
      const content = await new Promise((resolve,reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result.split(',')[1]); reader.onerror = () => reject(Error('Could not read attachment')); reader.readAsDataURL(file) })
      draft.attachments.push(await coreApi('attachments.upload', {message:anchor.name,filename:file.name,content_base64:content},true))
    }
  } catch (e) { error.value = e.message }
  finally { sending.value = false }
}
async function completed(result) {
  if (!active) return
  draft.request = {...draft.request, action:result.action || draft.request?.action, status:result.status}
  notice.value = channelStatus({status:result.status,provider_context: { provider: 'Email' } })
  const pending = beginEmail(anchor, {body:draft.body}, draft.request.key)
  pending.action = result.action || draft.request.action
  pending.status = result.status || 'Uncertain'
  if (result.message) {
    await finishEmail(pending,result)
    Object.assign(draft, emailComposition(anchor)); clearStored()
  }
}
async function check() {
  if (!draft.request || draft.request.status === 'Rejected' || sending.value) return
  sending.value = true; error.value = ''
  try {
    const result = draft.request.action
      ? await coreApi('messaging.reconcile',{action:draft.request.action},true)
      : await coreApi('email.send_status',{message:anchor.name,request_key:draft.request.key})
    await completed(result)
  } catch(e) { error.value = e.message }
  finally { sending.value = false }
}
async function recover() {
  if (!draft.request?.values || draft.request.status === 'Rejected' || sending.value) return
  sending.value=true; error.value=''
  try { await completed(await coreApi('email.send',draft.request.values,true)) }
  catch(e){await failedSend(e)} finally{sending.value=false}
}
async function failedSend(e) {
  error.value = e.message
  if (!draft.request) return
  await completed({status:'Uncertain'})
  const validation = (e.status >= 400 && e.status < 500 && ['ValidationError','ValueError','PermissionError'].includes(e.exceptionType))
    || (e.status === 500 && e.exceptionType === 'ValueError')
  if (draft.request.action || !validation) return
  try {
    const result = await coreApi('email.send_status', {message:anchor.name,request_key:draft.request.key})
    await completed(result.status === 'Unconfirmed' && !result.action && !result.message
      ? {status:'Rejected'} : result)
  } catch (statusError) { error.value = e.message + ' ' + statusError.message }
}
async function send() {
  if (disabled.value) return
  error.value = ''; notice.value = ''
  try {
    const to = addressList(draft.to), cc = addressList(draft.cc), bcc = addressList(draft.bcc)
    if (!to.length || to.length + cc.length + bcc.length > 50) throw Error('Choose 1–50 recipients.')
    if (!draft.subject.trim() || /[\r\n]/.test(draft.subject) || draft.subject.length > 998) throw Error('Enter a single-line subject of at most 998 characters.')
    const body = draft.body + (draft.signature ? '\n\n' + draft.signature : '')
    if (!draft.body.trim() || body.length > 100000) throw Error('Enter a message of at most 100000 characters, including the signature.')
    const key = randomUUID()
    const values = {message:anchor.name,to,cc,bcc,subject:draft.subject,body,attachment_ids:draft.attachments.map(file=>file.name),forward:draft.mode==='forward'?1:0,request_key:key}
    draft.request = {key,status:'Queued',values}; sending.value = true
    beginEmail(anchor,values,key)
    await completed(await coreApi('email.send',values,true))
  } catch(e) { await failedSend(e) }
  finally { sending.value=false }
}
async function saveSignature() {
  sending.value=true;error.value=''
  try { await coreApi('email_preferences.save',{signature:draft.signature},true); notice.value='Signature saved.' }
  catch(e){error.value=e.message} finally{sending.value=false}
}
onMounted(async () => {
  if (draft.request) { await check(); return }
  if (!draft.signature) try { const result=await coreApi('email_preferences.read'); if(!draft.signature)draft.signature=result.signature } catch(e){error.value=e.message}
})
useRealtimeRefresh([],['message_actions'],check)
</script>
<template>
  <form class="message-composer email-composer compact-composer" :class="{'is-expanded': expanded}" aria-label="Email composer" @focusin="focused = true" @focusout="focused = $event.currentTarget.contains($event.relatedTarget)" @submit.prevent="send">
    <div v-if="expanded && $slots.recipient" class="composer-recipient"><slot name="recipient" /></div>
    <div v-if="expanded" class="flex flex-wrap gap-2" role="group" aria-label="Email action"><Button v-for="[value,label] in [['reply','Reply'],['reply-all','Reply all'],['forward','Forward']]" :key="value" :label="label" :variant="draft.mode===value?'solid':'ghost'" :disabled="disabled" @click="modeChanged(value)" /></div>
    <div v-if="expanded" class="email-address-row"><FormControl v-model="draft.to" class="email-inline-field" label="To" aria-label="To" :disabled="disabled" required /><Button label="CC / BCC" variant="ghost" size="xs" :aria-expanded="recipientsOpen" @click="recipientsOpen = !recipientsOpen" /></div>
    <div v-if="recipientsOpen" class="grid gap-2 sm:grid-cols-2"><FormControl v-model="draft.cc" label="CC" :disabled="disabled" /><FormControl v-model="draft.bcc" label="BCC (private delivery audit only)" :disabled="disabled" /></div>
    <FormControl v-if="expanded" v-model="draft.subject" class="email-inline-field" label="Subject" aria-label="Subject" maxlength="998" :disabled="disabled" required />
    <div class="email-input-row"><slot name="channel" /><FormControl v-model="draft.body" class="email-body" label="Message" aria-label="Message" type="textarea" rows="1" placeholder="Write an email…" :disabled="disabled" required /></div>
    <div v-if="expanded" class="email-footer"><details><summary>Signature &amp; sender</summary><p class="text-xs">From {{ anchor.channel_title || 'the configured email account' }}. Review recipients before sending.</p><FormControl v-model="draft.signature" label="Signature" type="textarea" maxlength="2000" :disabled="disabled" /><Button label="Save my signature" :disabled="disabled" @click="saveSignature" /></details>
    <div class="flex flex-wrap gap-2"><Button label="Attach files" icon-left="paperclip" :disabled="disabled" @click="fileInput.click()" /><input ref="fileInput" type="file" multiple hidden @change="attach" /><span v-for="(file,index) in draft.attachments" :key="file.name" class="break-all">{{ file.filename }} <Button label="Remove" :disabled="disabled" @click="draft.attachments.splice(index,1)" /></span></div>
    <Button v-if="!locked" type="submit" label="Send email" variant="solid" :disabled="disabled" :loading="sending" /></div>
    <ErrorMessage :message="error" /><p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="locked" role="status">{{ channelStatus({status:draft.request.status,provider_context: { provider: 'Email' } }) }} · This attempt is saved. Checking its status does not send another email.</p>
    <Button v-if="locked && draft.request.status!=='Rejected'" label="Check status" :loading="sending" @click="check" />
    <Button v-if="locked && draft.request.status!=='Rejected' && !draft.request.action" label="Recover saved attempt" :disabled="sending" @click="recover" />
    <Button v-if="draft.request?.status==='Rejected'" label="Edit rejected draft" :disabled="sending" @click="draft.request=null" />
  </form>
</template>

<style scoped>
.message-composer.email-composer { display:flex; flex-direction:column; gap:6px; flex-shrink:0; max-height:40%; overflow-y:auto; min-width:0; }
.email-input-row { display:flex; align-items:center; gap:8px; min-width:0; }
.email-input-row > .email-body { flex:1; min-width:0; }
.is-expanded .email-body :deep(textarea) { min-height:64px; }
.email-address-row,.email-footer { display:flex; align-items:center; gap:8px; min-width:0; }
.email-address-row > .relay-field { flex:1; min-width:0; }
.email-inline-field { display:grid; grid-template-columns:58px minmax(0,1fr); align-items:center; gap:8px; }
.email-inline-field :deep(.relay-field__label) { margin:0; }
.email-body :deep(.relay-field__label) { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
.email-body :deep(textarea) { min-height:40px; max-height:100px; overflow-y:auto !important; }
.email-footer { flex-wrap:wrap; }
.email-footer details { flex:1; min-width:0; font-size:12px; }
.email-footer details[open] { flex-basis:100%; }
.email-footer > button[type=submit] { margin-left:auto; }
.email-composer :deep(.relay-button__label) { position:static; width:auto; height:auto; clip-path:none; overflow:visible; }
.email-inline-field :deep(.relay-field__label) { white-space:nowrap; }
</style>
