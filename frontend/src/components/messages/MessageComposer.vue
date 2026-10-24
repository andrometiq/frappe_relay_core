<script setup>
import { inject, computed, watch, ref, onBeforeUnmount, nextTick } from "vue";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import { coreApi } from "../../services/coreApi";
import { attachmentAccept, attachmentFormatError } from "./attachmentFormats";
import { Button, FormControl, Dropdown } from "@relay/ui";
import { useWhatsAppIdentity } from "../../composables/useWhatsAppIdentity";
const { identity, load: loadIdentity } = useWhatsAppIdentity({ immediate: false });
import WhatsAppIdentity from "../WhatsAppIdentity.vue";
import CannedReplies from './CannedReplies.vue';
const showReplies=ref(false), focused=ref(false);
const expanded = computed(() => focused.value || !!body.value || quoting.value || kind.value !== 'text');

import { compositionScope, telegramLimit } from '../../services/channelComposition';
import { useStoredDraft } from '../../composables/useStoredDraft';
import { messagesKey } from "../../composables/messagesContext";
const {
  selected,
  businessType,
  businessName,
  rows,
  attachment,
  uploadAttachment,
  source,
  quoting,
  cancelReply,
  sourceContext,
  kind,
  kinds,
  body,
  emoji,
  latitude,
  longitude,
  contactName,
  phone,
  busy,
  error,
  send,
} = inject(messagesKey);
const attachmentInput = ref(null);
const draftScope = computed(() => compositionScope(source.value, document.getElementById('app')?.dataset.user));
useStoredDraft(() => draftScope.value,
  () => ({body:body.value,kind:kind.value,attachment:attachment.value}),
  saved => { body.value=saved.body || ''; kind.value=saved.kind || 'text'; attachment.value=saved.attachment || null; });
const limit = computed(() => sourceContext.value.provider === 'Telegram' ? telegramLimit(kind.value) : null);
watch(() => sourceContext.value.provider, provider => { if(provider === 'WhatsApp' && !identity.value) loadIdentity(); }, {immediate:true});
const draftInput = ref(null);
const requestedAttachmentKind = ref("document");
function applySavedReply(item) {
  const type=(item.reply_type||'Text').toLowerCase();
  if(!kinds.value.includes(type))return;
  attachment.value=null;
  kind.value=type;
  if(type==='text')body.value=item.body||'';
  else if(type==='location'){latitude.value=String(item.latitude);longitude.value=String(item.longitude);}
  else if(type==='contact'){contactName.value=item.contact_name;phone.value=item.phone;}
}
async function chooseAttachment(value = "document") {
  requestedAttachmentKind.value = value;
  await nextTick();
  attachmentInput.value?.click();
}
const attachTypes = {photo:['Photo','image','image/*'],video:['Video','video','video/*'],audio:['Audio','music','audio/*'],voice:['Voice message','mic','audio/ogg,audio/webm'],document:['File','file','']};
const attachmentOptions = computed(()=>[
  ...kinds.value.filter(value=>attachTypes[value]).map(value=>({label:attachTypes[value][0],icon:attachTypes[value][1],onClick:()=>chooseAttachment(value)})),
  ...kinds.value.filter(value=>['location','contact'].includes(value)).map(value=>({label:value==='location'?'Location':'Contact',icon:value==='location'?'map-pin':'user',onClick:()=>{kind.value=value;attachment.value=null;}})),
]);
const emojiOptions=['😀','😊','👍','❤️','🙏','🎉'].map(value=>({label:value,onClick:()=>body.value+=value}));
function resizeDraft() {
  const node=draftInput.value;
  if (!node) return;
  node.style.height='auto';
  node.style.height=Math.min(node.scrollHeight,130)+'px';
}
watch([body, kind], async () => { await nextTick(); resizeDraft(); }, {immediate:true});
async function attachFile(event) {
  const file=event.target.files?.[0];
  event.target.value='';
  if (!file) return;
  const formatError = attachmentFormatError(sourceContext.value.provider, requestedAttachmentKind.value, file.name);
  if (formatError) { error.value = formatError; return; }
  const previous=attachment.value;
  await uploadAttachment(file);
  if (attachment.value) kind.value=requestedAttachmentKind.value;
  else attachment.value=previous;
}
const emit = defineEmits(["template"]);
const windowState = ref({ open: true }),
  windowError = ref("");
let windowGeneration = 0, expiryTimer;
async function checkWindow() {
  const generation = ++windowGeneration;
  clearTimeout(expiryTimer);
  if (
    sourceContext.value.provider !== "WhatsApp" ||
    sourceContext.value.group_id
  ) {
    windowState.value = { open: true };
    windowError.value = "";
    return;
  }
  if (!source.value) return;
  try {
    const result = await coreApi("messaging.reply_window", {
      message: source.value.name,
    });
    if (generation === windowGeneration) {
      windowState.value = result;
      if(result.open && Number.isFinite(result.remaining_seconds)) expiryTimer=setTimeout(()=>{windowState.value={...windowState.value,open:false};},Math.min(result.remaining_seconds*1000,2147483647));
      windowError.value = "";
    }
  } catch (e) {
    if (generation === windowGeneration) {
      windowState.value = { open: false };
      windowError.value = e.message;
    }
  }
}
watch(
  () => source.value?.name,
  () => {
    windowState.value = {
      open:
        sourceContext.value.provider !== "WhatsApp" ||
        !!sourceContext.value.group_id,
    };
    checkWindow();
  },
  { immediate: true },
);
useRealtimeRefresh([], ['messages'], checkWindow);
onBeforeUnmount(() => { ++windowGeneration; clearTimeout(expiryTimer); });
const canSend = computed(
  () =>
    !busy.value &&
    (!limit.value || [...body.value].length <= limit.value) &&
    windowState.value.open &&
    (kind.value === "text"
      ? !!body.value.trim()
      : ["photo", "video", "audio", "voice", "document"].includes(kind.value)
        ? !!attachment.value
        : kind.value === "location"
          ? latitude.value !== "" && longitude.value !== ""
          : kind.value === "contact"
            ? !!contactName.value.trim() && !!phone.value.trim()
            : false),
);
let lastTyping = 0,
  typingRequest = null, typingTimeout;
function stopTyping() {
  clearTimeout(typingTimeout);
  const request = typingRequest;
  typingRequest = null;
  lastTyping = 0;
  if (request)
    coreApi(request.method, { ...request.values, active: 0 }, true).catch(() => {});
}
function typing() {
  const contact = selected.value || source.value?.relay_contact;
  if (!contact || document.visibilityState !== "visible") return;
  if (!body.value.trim()) {
    stopTyping();
    return;
  }
  clearTimeout(typingTimeout);typingTimeout=setTimeout(stopTyping,5000);
  if (Date.now() - lastTyping < 4000) return;
  lastTyping = Date.now();
  typingRequest = businessName.value
    ? { method: "business_inbox.typing", values: {
        doctype: businessType.value, name: businessName.value, contact,
      } }
    : { method: "inbox.typing", values: { contact } };
  coreApi(typingRequest.method, { ...typingRequest.values, active: 1, message: source.value?.name }, true).catch(
    () => {},
  );
}
watch([selected, source, businessType, businessName], stopTyping);
watch(body, (value) => {
  if (!value) stopTyping();
});
onBeforeUnmount(stopTyping);
function keydown(event) {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    if (!event.repeat && canSend.value) send();
  }
}
</script>
<template>
  <form class="message-composer compact-composer" :class="{'is-expanded': expanded}" @focusin="focused = true" @focusout="focused = $event.currentTarget.contains($event.relatedTarget)" @submit.prevent="canSend && send()">
    <div v-if="expanded" class="composer-recipient"><slot name="recipient" /></div>
    <p v-if="error" role="alert" class="text-sm text-ink-red-3">{{ error }}</p>
    <p v-if="windowError" role="alert" class="text-sm">{{ windowError }}</p>
    <div v-else-if="!windowState.open" class="composer-window-notice">
      <span>The WhatsApp reply window is closed.</span
      ><Button label="Use an approved template" @click="emit('template')" />
    </div>
    <div v-if="quoting" class="composer-quote">
      Replying to {{ (source.content || "Message").slice(0, 80)
      }}<span v-if="sourceContext.message_thread_id">
        · Topic {{ sourceContext.message_thread_id }}</span
      >
      <Button
        icon="x"
        label="Cancel reply"
        title="Cancel reply"
        @click="cancelReply"
      />
    </div>
    <div
      v-else-if="sourceContext.message_thread_id"
      class="text-xs text-ink-gray-5"
    >
      Topic {{ sourceContext.message_thread_id }}
    </div>
    <CannedReplies v-if="showReplies" :source="source" @close="showReplies=false" @select="applySavedReply" />
    <details v-if="expanded && sourceContext.provider === 'WhatsApp'" class="composer-identity"><summary><span>From {{ identity?.display_phone_number || 'Number unavailable' }}</span><small v-if="windowState.open" :title="windowState.expires_at ? 'Open until ' + windowState.expires_at : '24-hour reply window open'">24h reply window open</small></summary><WhatsAppIdentity /></details>
    <p v-if="expanded && limit" class="text-xs" :role="[...body].length > limit ? 'alert' : undefined">{{ [...body].length }} / {{ limit }} characters · Telegram plain text</p>
    <div v-show="expanded" class="composer-toolbar">
      <Button v-if="sourceContext.provider === 'WhatsApp'" label="Template" :disabled="busy" @click="emit('template')" />
      <Dropdown :options="attachmentOptions"><Button icon="paperclip" aria-label="Add attachment" title="Add attachment" :disabled="busy || !windowState.open" /></Dropdown>
      <Dropdown :options="emojiOptions"><Button icon="smile" aria-label="Insert emoji" title="Insert emoji" :disabled="busy" /></Dropdown>
      <Button icon="zap" aria-label="Saved replies" title="Saved replies" :disabled="busy" @click="showReplies=true" />
      <span v-if="kind !== 'text'" class="composer-selection">{{attachTypes[kind]?.[0] || kind}}
        <Button icon="x" aria-label="Cancel attachment" title="Cancel attachment" :disabled="busy" @click="kind='text';attachment=null" />
      </span>
    </div>
    <input type="file" ref="attachmentInput" aria-label="Attachment" class="sr-only"
      :accept="attachmentAccept(sourceContext.provider, requestedAttachmentKind)" :disabled="busy" @change="attachFile" />
    <span class="composer-channel"><slot name="channel" /></span>
    <textarea ref="draftInput"
      v-if="kind === 'text'"
      v-model="body"
      class="chat-draft"
      aria-label="Message"
      :placeholder="sourceContext.provider ? 'Reply on ' + sourceContext.provider + '…' : 'Write a message…'"
      rows="1"
      @keydown="keydown"
      @input="resizeDraft();typing()"
    />
    <div v-else-if="kind === 'location'" class="flex flex-wrap gap-3">
      <FormControl
        v-model="latitude"
        type="number"
        label="Latitude"
      /><FormControl v-model="longitude" type="number" label="Longitude" />
    </div>
    <div v-else-if="kind === 'contact'" class="flex flex-wrap gap-3">
      <FormControl v-model="contactName" label="Contact name" /><FormControl
        v-model="phone"
        label="Phone number"
      />
    </div>
    <div
      v-else-if="
        ['photo', 'video', 'audio', 'voice', 'document'].includes(kind)
      "
      class="space-y-2"
    >
      <div class="attachment-preview">
        <span>{{ attachment ? attachment.filename : 'Choose '+(attachTypes[kind]?.[0] || 'attachment').toLowerCase()+' · up to 4 MiB' }}</span>
        <Button :label="attachment?'Replace':'Choose file'" :disabled="busy" @click="chooseAttachment(kind)" />
      </div>
      <FormControl
        v-if="
          !(
            sourceContext.provider === 'WhatsApp' &&
            ['audio', 'voice'].includes(kind)
          )
        "
        label="Caption"
        type="textarea"
        v-model="body"
        @keydown="keydown"
      />
    </div>
    <p v-else class="text-sm">Select an existing sticker to resend.</p>
    <Button
      label="Send"
      icon="send"
      title="Send · Enter"
      type="submit"
      variant="solid"
      :disabled="!canSend"
    />
    <span v-if="expanded && kind === 'text'" class="composer-keyboard-hint"
      >Enter to send · Shift+Enter for a new line</span
    >
  </form>
</template>
