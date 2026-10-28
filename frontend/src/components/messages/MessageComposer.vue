<script setup>
import { inject, computed, watch, ref, onBeforeUnmount, nextTick } from "vue";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import { coreApi } from "../../services/coreApi";
import { attachmentAccept, attachmentFormatError } from "./attachmentFormats";
import { channelCan } from "../../services/enabledChannels";
import { channelOffText } from "../../services/chatErrors";
import { Button, FormControl, Dropdown, FeatherIcon } from "@relay/ui";
import { useWhatsAppIdentity } from "../../composables/useWhatsAppIdentity";
import { useMobileLayout } from "../../composables/useMobileLayout";
import { useSendChannel } from "../../composables/useSendChannel";
import { sendNumbersKey } from "../../composables/useSendNumbers";
import SendNumber from "./SendNumber.vue";
const { identity, load: loadIdentity } = useWhatsAppIdentity({ immediate: false });
import WhatsAppIdentity from "../WhatsAppIdentity.vue";
import CannedReplies from './CannedReplies.vue';
const showReplies=ref(false), focused=ref(false);
const isMobile = useMobileLayout();
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
const capabilities = inject("relayCapabilities", ref({}));
const can = feature => channelCan(capabilities.value, sourceContext.value.provider, feature);
// `mode` is "reply" or "note"; the note slot holds the internal note form, so a note never goes to the customer.
// `offText` marks a switched-off channel: replies show that banner and only notes stay open.
const props = defineProps({ recipient: String, contactName: String, mode: { type: String, default: "reply" }, offText: String });
const attachmentInput = ref(null);
const draftScope = computed(() => props.offText ? '' : compositionScope(source.value, document.getElementById('app')?.dataset.user));
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
  const formatError = attachmentFormatError(capabilities.value, sourceContext.value.provider, requestedAttachmentKind.value, file.name);
  if (formatError) { error.value = formatError; return; }
  const previous=attachment.value;
  await uploadAttachment(file);
  if (attachment.value) kind.value=requestedAttachmentKind.value;
  else attachment.value=previous;
}
const emit = defineEmits(["template", "mode", "closed"]);
const noting = computed(() => props.mode === "note");
// Only typing fields expand the composer. A button press must not move the tabs before its click lands.
const expandOn = event => { if (event.target.matches("textarea, input:not([type=file]), select")) focused.value = true; };
const { options: sendOptions } = useSendChannel();
// On a site with several WhatsApp numbers the "Send via" number picker replaces the channel menu.
const numbers = inject(sendNumbersKey, null);
const manyNumbers = computed(() => !!numbers?.active.value);
// The channel menu shows only when there is a real choice.
const channelChoice = computed(() => !manyNumbers.value && sendOptions.value.length > 1);
const windowState = ref({ open: true }),
  windowError = ref("");
let windowGeneration = 0, expiryTimer;
async function checkWindow() {
  const generation = ++windowGeneration;
  clearTimeout(expiryTimer);
  if (!can("reply_window_hours") || sourceContext.value.group_id) {
    windowState.value = { open: true };
    windowError.value = "";
    return;
  }
  if (!source.value) return;
  if (manyNumbers.value) {
    const chosenWindow = numbers.chosen.value?.window || { open: false };
    windowState.value = chosenWindow;
    windowError.value = "";
    if (chosenWindow.open && Number.isFinite(chosenWindow.remaining_seconds)) expiryTimer = setTimeout(() => { windowState.value = { ...windowState.value, open: false }; }, Math.min(chosenWindow.remaining_seconds * 1000, 2147483647));
    return;
  }
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
      open: !can("reply_window_hours") || !!sourceContext.value.group_id,
    };
    checkWindow();
  },
  { immediate: true },
);
useRealtimeRefresh([], ['messages'], checkWindow);
watch(() => manyNumbers.value && numbers.chosen.value, checkWindow);
const windowClosedReason = "More than 24 hours since the customer wrote. You can only send a template.";
const offReason = computed(() => props.offText || (windowState.value.channel_disabled ? channelOffText(sourceContext.value.provider) : ""));
const closed = computed(() => !!offReason.value || !windowState.value.open);
// The thread hides Reply and reactions while only a template can be sent.
watch(closed, value => emit("closed", value), { immediate: true });
onBeforeUnmount(() => emit("closed", false));
const windowHint = computed(() => {
  const seconds = windowState.value.remaining_seconds;
  if (!windowState.value.open || !Number.isFinite(seconds)) return "";
  return Math.max(1, Math.ceil(seconds / 3600)) + " h left to reply";
});
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
const busyReason = "Wait for the current send to finish";
const sendTitle = computed(() => busy.value ? busyReason
  : limit.value && [...body.value].length > limit.value ? "The message is too long for this channel"
  : canSend.value ? "Send · Enter"
  : kind.value === "text" ? "Type a message first" : "Add the file or details first");
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
  <form class="message-composer compact-composer" :class="{ 'is-expanded': expanded, 'is-note': noting, 'is-closed': closed && !noting }"
    @focusin="expandOn" @focusout="focused = $event.currentTarget.contains($event.relatedTarget)" @submit.prevent="!noting && canSend && send()">
    <div class="composer-tabs" role="group" aria-label="Compose">
      <button type="button" :class="{ active: !noting }" :aria-pressed="!noting" @click="emit('mode', 'reply'); nextTick(() => draftInput?.focus())">Reply</button>
      <button type="button" :class="{ active: noting }" :aria-pressed="noting" @click="emit('mode', 'note')"><FeatherIcon name="lock" :size="12" />{{ isMobile ? "Note" : "Internal note" }}</button>
      <template v-if="isMobile && !noting && !closed">
        <span v-if="windowHint" class="composer-tabs-hint" :title="windowState.expires_at ? 'Open until ' + windowState.expires_at : undefined">{{ windowHint }}</span>
        <button v-if="can('templates')" type="button" class="composer-tab-action" :disabled="busy" :title="busy ? busyReason : 'Send an approved template'" @click="emit('template')"><FeatherIcon name="file-text" :size="13" />Template</button>
        <Button icon="zap" variant="ghost" class="composer-tab-icon" aria-label="Saved replies" :title="busy ? busyReason : 'Saved replies'" :disabled="busy" @click="showReplies = true" />
      </template>
    </div>
    <slot v-if="noting" name="note" />
    <div v-else-if="closed" class="composer-closed">
      <p role="status"><FeatherIcon :name="offReason ? 'alert-circle' : 'clock'" :size="15" />{{ offReason || (windowError ? "Could not check the 24-hour reply window. " + windowError : windowClosedReason) }}</p>
      <p v-if="error" role="alert" class="text-sm text-ink-red-3">{{ error }}</p>
      <div class="composer-closed-actions">
        <SendNumber v-if="manyNumbers" />
        <Button v-if="can('templates') && !offReason" class="composer-closed-send" label="Send template" icon-left="file-text" variant="solid" @click="emit('template')" />
      </div>
    </div>
    <template v-else>
      <div class="composer-extras">
        <div v-if="isMobile && (manyNumbers || channelChoice)" class="composer-via-row"><SendNumber v-if="manyNumbers" /><slot v-else name="channel" /></div>
        <div v-if="expanded && $slots.recipient" class="composer-recipient"><slot name="recipient" /></div>
        <p v-if="error" role="alert" class="text-sm text-ink-red-3">{{ error }}</p>
        <div v-if="quoting" class="composer-quote">
          <span class="composer-quote-body"><strong>{{ source.direction === "Outgoing" ? "You" : props.contactName || "Contact" }}</strong><span>{{ (source.content || "Message").split("\n")[0].slice(0, 120) }}</span></span>
          <Button icon="x" variant="ghost" aria-label="Cancel reply" title="Cancel reply" @click="cancelReply" />
        </div>
        <div v-else-if="sourceContext.message_thread_id" class="text-xs text-ink-gray-5">Topic {{ sourceContext.message_thread_id }}</div>
        <details v-if="expanded && sourceContext.provider === 'WhatsApp' && !manyNumbers && identity?.display_phone_number" class="composer-identity"><summary><span>From {{ identity.display_phone_number }}</span><small :title="windowState.expires_at ? 'Open until ' + windowState.expires_at : '24-hour reply window open'">24h reply window open</small></summary><WhatsAppIdentity /></details>
        <p v-if="expanded && limit" class="text-xs" :role="[...body].length > limit ? 'alert' : undefined">{{ [...body].length }} / {{ limit }} characters · Telegram plain text</p>
        <span v-if="kind !== 'text'" class="composer-selection">{{attachTypes[kind]?.[0] || kind}}
          <Button icon="x" aria-label="Cancel attachment" title="Cancel attachment" :disabled="busy" @click="kind='text';attachment=null" />
        </span>
      </div>
      <div v-if="isMobile" class="composer-plus"><Dropdown v-if="attachmentOptions.length" :options="attachmentOptions"><Button icon="plus" variant="ghost" aria-label="Attach" :title="busy ? busyReason : 'Attach a photo, file or more'" :disabled="busy" /></Dropdown></div>
      <div class="composer-input" :class="{ 'is-text': kind === 'text' }">
        <textarea ref="draftInput" v-if="kind === 'text'" v-model="body" class="chat-draft" aria-label="Message"
          :placeholder="isMobile ? 'Message' : props.recipient ? 'Write a reply to ' + props.recipient + '…' : 'Message'"
          rows="1" @keydown="keydown" @input="resizeDraft();typing()" />
        <div v-else-if="kind === 'location'" class="flex flex-wrap gap-3">
          <FormControl v-model="latitude" type="number" label="Latitude" /><FormControl v-model="longitude" type="number" label="Longitude" />
        </div>
        <div v-else-if="kind === 'contact'" class="flex flex-wrap gap-3">
          <FormControl v-model="contactName" label="Contact name" /><FormControl v-model="phone" label="Phone number" />
        </div>
        <div v-else-if="['photo', 'video', 'audio', 'voice', 'document'].includes(kind)" class="space-y-2">
          <div class="attachment-preview">
            <span>{{ attachment ? attachment.filename : 'Choose '+(attachTypes[kind]?.[0] || 'attachment').toLowerCase()+' · up to 4 MiB' }}</span>
            <Button :label="attachment?'Replace':'Choose file'" :disabled="busy" @click="chooseAttachment(kind)" />
          </div>
          <FormControl v-if="!(sourceContext.provider === 'WhatsApp' && ['audio', 'voice'].includes(kind))" label="Caption" type="textarea" v-model="body" @keydown="keydown" />
        </div>
        <p v-else class="text-sm">Select an existing sticker to resend.</p>
      </div>
      <div v-if="!isMobile" class="composer-toolbar">
        <Dropdown v-if="attachmentOptions.length" :options="attachmentOptions"><Button icon="paperclip" variant="ghost" aria-label="Add attachment" :title="busy ? busyReason : 'Add attachment'" :disabled="busy" /></Dropdown>
        <Dropdown :options="emojiOptions"><Button icon="smile" variant="ghost" aria-label="Insert emoji" :title="busy ? busyReason : 'Insert emoji'" :disabled="busy" /></Dropdown>
        <Button v-if="can('templates')" class="composer-chip" icon-left="file-text" label="Template" variant="ghost" :title="busy ? busyReason : 'Send an approved template'" :disabled="busy" @click="emit('template')" />
        <Button class="composer-chip" icon-left="zap" label="Saved replies" variant="ghost" :title="busy ? busyReason : 'Insert a saved reply'" :disabled="busy" @click="showReplies=true" />
        <span v-if="windowHint" class="composer-window-hint" :title="windowState.expires_at ? 'Open until ' + windowState.expires_at : undefined">{{ windowHint }}</span>
      </div>
      <input type="file" ref="attachmentInput" aria-label="Attachment" class="sr-only"
        :accept="attachmentAccept(capabilities, sourceContext.provider, requestedAttachmentKind)" :disabled="busy" @change="attachFile" />
      <span v-if="!isMobile && (manyNumbers || channelChoice)" class="composer-channel"><SendNumber v-if="manyNumbers" /><slot v-else name="channel" /></span>
      <Button class="composer-send" :label="isMobile ? '' : 'Send'" icon="send" aria-label="Send" :title="sendTitle" type="submit" variant="solid" :disabled="!canSend" />
    </template>
    <CannedReplies v-if="showReplies" :source="source" @close="showReplies=false" @select="applySavedReply" />
  </form>
</template>

<style scoped>
.composer-tabs > button { display:inline-flex; align-items:center; gap:5px; }
.composer-tabs > button:nth-child(2).active { background:var(--surface-amber-1); color:var(--relay-amber); }
.v1-shell.relay-shell .compact-composer.is-note:not(.email-composer) { grid-template-areas:"tabs" "note"; grid-template-columns:minmax(0,1fr); border-color:color-mix(in srgb, var(--relay-amber) 45%, transparent); border-bottom-color:var(--relay-amber); background:var(--surface-amber-1); }
.v1-shell.relay-shell .compact-composer.is-closed:not(.email-composer) { grid-template-areas:"tabs" "closed"; grid-template-columns:minmax(0,1fr); }
.composer-closed { grid-area:closed; display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; margin:6px 8px 8px; padding:10px 12px; border:1px solid color-mix(in srgb, var(--relay-amber) 45%, transparent); border-radius:8px; background:var(--surface-amber-1); }
.composer-closed > p { flex:1 1 260px; }
.composer-closed > p[role=status] { display:flex; align-items:center; gap:8px; font-size:13px; font-weight:600; color:var(--relay-ink, var(--ink-gray-8)); }
.composer-closed-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; }
.v1-shell.relay-shell .compact-composer .composer-toolbar .composer-chip.relay-button { width:auto; padding:0 8px; gap:5px; font-size:12px; }
.composer-tab-action { margin-left:auto; color:var(--relay-ink-2) !important; }
.composer-tabs-hint { margin-left:auto; color:var(--relay-ink-3); font-size:11px; white-space:nowrap; align-self:center; }
.composer-tabs-hint + .composer-tab-action { margin-left:0; }
.v1-shell.relay-shell .compact-composer .composer-tab-icon.relay-button { width:28px; height:28px; min-height:28px; color:var(--relay-ink-2); }
@media (max-width: 768px) {
  .v1-shell.relay-shell .compact-composer:not(.email-composer) { grid-template-areas:"tabs tabs tabs" "extras extras extras" "plus input send"; }
  .v1-shell.relay-shell .compact-composer.is-note:not(.email-composer) { grid-template-areas:"tabs" "note"; grid-template-columns:minmax(0,1fr); }
  .v1-shell.relay-shell .compact-composer.is-closed:not(.email-composer) { grid-template-areas:"tabs" "closed"; grid-template-columns:minmax(0,1fr); }
  .compact-composer > .composer-tabs { align-items:center; padding:0 0 6px; }
  .composer-closed { margin:0; }
  .composer-closed-actions { width:100%; }
  .composer-closed-send { flex:1; }
}
</style>
