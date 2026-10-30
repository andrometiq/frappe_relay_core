<script setup>
import { deadlineTime } from "../relativeTime";
import { inject, computed, watch, ref, onBeforeUnmount, nextTick } from "vue";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import { coreApi } from "../../services/coreApi";
import { attachmentAccept, attachmentFormatError, attachmentMaxBytes, sizeError, sizeLabel } from "./attachmentFormats";
import { channelCan } from "../../services/enabledChannels";
import { channelOffText } from "../../services/chatErrors";
import { Button, FormControl, FeatherIcon } from "@relay/ui";
import { useWhatsAppIdentity } from "../../composables/useWhatsAppIdentity";
import { useMobileLayout } from "../../composables/useMobileLayout";
import ComposerMore from "./ComposerMore.vue";
import { attachmentKinds, composerActions } from "../../services/composerActions";
import { sha256Hex } from "../../services/crypto";
import { messageData } from "../messageContent";
import { formatBytes } from "../../services/mediaCache";
import { useSendChannel } from "../../composables/useSendChannel";
import { sendNumbersKey } from "../../composables/useSendNumbers";
import SendNumber from "./SendNumber.vue";
const { identity, load: loadIdentity } = useWhatsAppIdentity({ immediate: false });
import WhatsAppIdentity from "../WhatsAppIdentity.vue";
import CannedReplies from './CannedReplies.vue';
const showReplies = ref(false), editing = ref(false), uploading = ref(false), preview = ref("");
const isMobile = useMobileLayout();

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
  latitude,
  longitude,
  contactName,
  phone,
  busy: working,
  sending = ref(0),
  error,
  send,
} = inject(messagesKey);
const busy = computed(() => working.value || sending.value > 0);
const capabilities = inject("relayCapabilities", ref({}));
const can = feature => channelCan(capabilities.value, sourceContext.value.provider, feature);
// `mode` is "reply" or "note"; the note slot holds the internal note form, so a note never goes to the customer.
// `offText` marks a switched-off channel: replies show that banner and only notes stay open.
const props = defineProps({ recipient: String, contactName: String, mode: { type: String, default: "reply" }, offText: String, noteBusy: Boolean });
const attachmentInput = ref(null);
// Chat drafts belong to the conversation/route, even when a different message is quoted.
const draftScope = computed(() => compositionScope(source.value ? {
  ...source.value, name: undefined, sender_endpoint: undefined,
  // Historical outgoing messages can store our number as sender_endpoint. The selected contact owns this draft.
  business_doctype: businessType.value, business_name: businessName.value,
  relay_contact: selected.value || source.value.relay_contact,
} : null, document.getElementById('app')?.dataset.user));
useStoredDraft(() => draftScope.value,
  () => ({ body: body.value, kind: kind.value, attachment: attachment.value, latitude: latitude.value, longitude: longitude.value, contactName: contactName.value, phone: phone.value }),
  saved => { body.value = saved.body || ''; kind.value = saved.kind || 'text'; attachment.value = saved.attachment || null;
    latitude.value = saved.latitude || ''; longitude.value = saved.longitude || ''; contactName.value = saved.contactName || ''; phone.value = saved.phone || ''; },
  // Restore drafts saved by the previous, per-message composer on first use of the conversation key.
  () => JSON.parse(sessionStorage.getItem('relay-draft-' + sha256Hex(compositionScope(source.value, document.getElementById('app')?.dataset.user))) || 'null') || {});
const limit = computed(() => sourceContext.value.provider === 'Telegram' && ['text', 'photo', 'video', 'audio', 'voice', 'document'].includes(kind.value) ? telegramLimit(kind.value) : null);
watch(() => sourceContext.value.provider, provider => { if(provider === 'WhatsApp' && !identity.value) loadIdentity(); }, {immediate:true});
const draftInput = ref(null);
const requestedAttachmentKind = ref("document");
const attachmentLimit = computed(() => attachmentMaxBytes(capabilities.value, sourceContext.value.provider, kind.value));
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
const actions = computed(() => composerActions({ can, kinds: kinds.value, closed: closed.value, off: !!offReason.value, busy: busy.value }));
const hasSticker = computed(() => rows.value.some(row => messageData(row).kind === 'sticker'));
const mediaKind = computed(() => ['photo', 'video', 'audio', 'voice', 'document'].includes(kind.value));
const captionAllowed = computed(() => !(sourceContext.value.provider === 'WhatsApp' && ['audio', 'voice'].includes(kind.value)));
const characterCount = computed(() => [...body.value].length);
const showCount = computed(() => limit.value && characterCount.value >= limit.value * .9 && (editing.value || characterCount.value > limit.value));
async function focusDraft() { await nextTick(); resizeDraft(); draftInput.value?.focus({ preventScroll: true }); }
function clearQuote() { cancelReply(); focusDraft(); }
function clearAttachment() { kind.value = 'text'; attachment.value = null; clearPreview(); focusDraft(); }
function clearPreview() { if (preview.value) URL.revokeObjectURL(preview.value); preview.value = ''; }
watch(attachment, value => { if (!value) clearPreview(); });
onBeforeUnmount(clearPreview);
function moreAction(action) {
  if (action === 'saved') showReplies.value = true;
  else if (action === 'template') emit('template');
  else if (action === 'note') { stopTyping(); emit('mode', 'note'); }
  else if (['location', 'contact'].includes(action)) { kind.value = action; attachment.value = null; }
  else chooseAttachment(action);
}
function insertEmoji(value) { body.value += value; focusDraft(); }
function closeReplies() { showReplies.value = false; focusDraft(); }
watch(() => props.mode, value => { if (value === 'reply') focusDraft(); else stopTyping(); });
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
  const provider = sourceContext.value.provider;
  const formatError = attachmentFormatError(capabilities.value, provider, requestedAttachmentKind.value, file.name)
    || sizeError(file.size, attachmentMaxBytes(capabilities.value, provider, requestedAttachmentKind.value), `A ${provider} ${requestedAttachmentKind.value}`);
  if (formatError) { error.value = formatError; if (!attachment.value) kind.value = requestedAttachmentKind.value; return; }
  const previous = attachment.value;
  uploading.value = true;
  try {
    await uploadAttachment(file);
    if (attachment.value) {
      kind.value = requestedAttachmentKind.value;
      clearPreview();
      if (['photo', 'video'].includes(kind.value)) preview.value = URL.createObjectURL(file);
    } else {
      attachment.value = previous;
      // Keep the requested kind visible after a first upload failure; never send its caption as text.
      if (!previous) kind.value = requestedAttachmentKind.value;
    }
  } finally { uploading.value = false; }
  focusDraft();
}
const emit = defineEmits(["template", "mode", "closed"]);
const noting = computed(() => props.mode === "note");
const { choices: sendChoices } = useSendChannel();
// On a site with several WhatsApp numbers the "Send via" number picker replaces the channel menu.
const numbers = inject(sendNumbersKey, null);
const manyNumbers = computed(() => !!numbers?.active.value);
// The channel menu shows only when there is a real choice.
const channelChoice = computed(() => !manyNumbers.value && sendChoices.value.size > 1);
const windowChecking = ref(false), windowReceivedAt = ref(Date.now()), now = ref(Date.now());
const clockTimer = setInterval(() => { now.value = Date.now(); }, 30000);
const windowState = ref({ open: true }),
  windowError = ref("");
let windowGeneration = 0, expiryTimer;
async function checkWindow() {
  const generation = ++windowGeneration;
  clearTimeout(expiryTimer);
  windowChecking.value = false;
  windowReceivedAt.value = Date.now();
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
  windowChecking.value = true;
  try {
    const result = await coreApi("messaging.reply_window", {
      message: source.value.name,
    });
    if (generation === windowGeneration) {
      windowReceivedAt.value = Date.now();
      windowState.value = result;
      if(result.open && Number.isFinite(result.remaining_seconds)) expiryTimer=setTimeout(()=>{windowState.value={...windowState.value,open:false};},Math.min(result.remaining_seconds*1000,2147483647));
      windowError.value = "";
    }
  } catch (e) {
    if (generation === windowGeneration) {
      windowState.value = { open: false };
      windowError.value = e.message;
    }
  } finally { if (generation === windowGeneration) windowChecking.value = false; }
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

const offReason = computed(() => props.offText || (windowState.value.channel_disabled ? channelOffText(sourceContext.value.provider) : ""));
const closed = computed(() => !!offReason.value || (!windowState.value.open && !windowError.value && !windowChecking.value));
// The thread hides Reply and reactions while only a template can be sent.
watch(() => closed.value || !!windowError.value || windowChecking.value, value => emit("closed", value), { immediate: true });
onBeforeUnmount(() => emit("closed", false));
const remainingSeconds = computed(() => Math.max(0, (windowState.value.remaining_seconds || 0) - Math.max(0, now.value - windowReceivedAt.value) / 1000));
const windowHint = computed(() => windowState.value.open && Number.isFinite(windowState.value.remaining_seconds) && remainingSeconds.value <= 3600
  ? `${Math.max(1, Math.ceil(remainingSeconds.value / 60))} min left to reply` : '');
onBeforeUnmount(() => { ++windowGeneration; clearTimeout(expiryTimer); clearInterval(clockTimer); });
const canSend = computed(
  () =>
    !busy.value && !offReason.value && !windowChecking.value && !windowError.value &&
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
const sendTitle = computed(() => windowError.value ? "Check the reply window before sending" : windowChecking.value ? "Checking reply window" : busy.value ? busyReason
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
  <form class="message-composer composer-dock" :class="{ 'is-note': noting }" aria-label="Message composer" @submit.prevent="!noting && canSend && send()">
    <template v-if="noting">
      <div class="composer-note-head"><FeatherIcon name="lock" :size="16" /><span><strong>Internal note</strong><span>Only your team sees this</span></span>
        <Button label="Back to reply" variant="ghost" :disabled="busy || noteBusy" @click="emit('mode', 'reply')" /></div>
      <slot name="note" />
    </template>
    <template v-else>
      <div v-if="$slots.recipient" class="composer-recipient"><slot name="recipient" /></div>
      <div v-if="manyNumbers || channelChoice || windowHint" class="composer-context-bar">
        <SendNumber v-if="manyNumbers" /><slot v-else-if="channelChoice" name="channel" />
        <span v-if="windowHint" class="composer-window-hint" role="status">{{ windowHint }}</span>
      </div>
      <p v-if="sourceContext.message_thread_id" class="composer-status">Topic {{ sourceContext.message_thread_id }}</p>
      <div v-if="quoting" class="composer-context composer-quote">
        <span class="composer-quote-body"><strong>{{ source.direction === 'Outgoing' ? 'You' : props.contactName || 'Contact' }}</strong><span>{{ (source.content || 'Message').split('\n')[0].slice(0, 120) }}</span></span>
        <Button icon="x" variant="ghost" aria-label="Cancel reply" title="Cancel reply" :disabled="busy" @click="clearQuote" />
      </div>
      <p v-if="error" role="alert" class="composer-error">{{ error }}</p>
      <div v-if="windowError" class="composer-error" role="alert"><span>Could not check the reply window. Your draft is saved. {{ windowError }}</span><Button label="Check again" variant="ghost" :disabled="windowChecking" @click="checkWindow" /></div>
      <p v-if="busy || windowChecking" role="status" class="composer-status">{{ uploading ? 'Uploading…' : busy ? 'Sending…' : 'Checking reply window…' }}</p>
      <template v-if="!closed">
        <div v-if="mediaKind" class="composer-context composer-attachment">
          <img v-if="preview && kind === 'photo'" :src="preview" alt="Selected attachment" />
          <video v-else-if="preview && kind === 'video'" :src="preview" muted preload="metadata" />
          <FeatherIcon v-else :name="attachmentKinds[kind]?.[1] || 'file'" />
          <span><strong>{{ attachment?.filename || 'Choose ' + attachmentKinds[kind]?.[0].toLowerCase() }}</strong><small>{{ attachment ? formatBytes(attachment.size) : attachmentLimit ? 'Up to ' + sizeLabel(attachmentLimit) : '' }}</small></span>
          <Button :label="attachment ? 'Replace' : 'Choose file'" variant="ghost" :disabled="busy" @click="chooseAttachment(kind)" />
          <Button icon="x" aria-label="Remove attachment" title="Remove attachment" variant="ghost" :disabled="busy" @click="clearAttachment" />
        </div>
        <div v-if="['location', 'contact'].includes(kind)" class="composer-detail-fields">
          <div class="composer-context"><strong>{{ kind === 'location' ? 'Share a location' : 'Share a contact' }}</strong><Button label="Cancel" variant="ghost" :disabled="busy" @click="clearAttachment" /></div>
          <div class="composer-field-grid">
            <template v-if="kind === 'location'"><FormControl v-model="latitude" type="number" step="any" min="-90" max="90" label="Latitude" :disabled="busy" /><FormControl v-model="longitude" type="number" step="any" min="-180" max="180" label="Longitude" :disabled="busy" /></template>
            <template v-else><FormControl v-model="contactName" label="Contact name" :disabled="busy" /><FormControl v-model="phone" label="Phone number" :disabled="busy" /></template>
          </div>
        </div>
        <p v-if="showCount" class="composer-status" :class="{ 'composer-error': characterCount > limit }" :role="characterCount > limit ? 'alert' : 'status'">{{ characterCount.toLocaleString() }} / {{ limit.toLocaleString() }}<template v-if="characterCount > limit"> · {{ characterCount - limit }} over limit</template></p>
      </template>
      <div class="composer-writing" :class="{ 'composer-closed': closed }">
        <ComposerMore :actions="actions" :disabled="busy" :has-sticker="hasSticker" @action="moreAction" @emoji="insertEmoji">
          <template #details>
            <p>{{ sourceContext.provider || 'No channel' }} · {{ source.channel_title || source.channel }}</p>
            <p v-if="recipient">To {{ recipient }}</p>
            <WhatsAppIdentity v-if="sourceContext.provider === 'WhatsApp' && !manyNumbers" />
            <p v-if="manyNumbers">From {{ numbers.chosen.value?.label }} · {{ numbers.chosen.value?.address }}</p>
            <p v-if="offReason">{{ offReason }}</p>
            <p v-else-if="windowError">Could not check the reply window.</p>
            <p v-else-if="can('reply_window_hours') && !sourceContext.group_id">{{ windowState.open ? 'Reply window open' : 'Reply window closed' }}<template v-if="windowState.expires_at_iso"> · {{ windowState.open ? 'Expires' : 'Expired' }} {{ deadlineTime(windowState.expires_at_iso, now) }}</template><template v-else-if="windowState.open && Number.isFinite(windowState.remaining_seconds)"> · {{ Math.ceil(remainingSeconds / 60) }} minutes remaining</template></p>
          </template>
        </ComposerMore>
        <template v-if="closed">
          <div class="composer-closed-copy" role="status"><strong><FeatherIcon :name="offReason ? 'alert-circle' : 'clock'" :size="16" />{{ offReason || '24-hour reply window closed' }}</strong><p v-if="!offReason">Send an approved template to continue.</p></div>
          <Button v-if="can('templates') && !offReason" label="Choose template" icon-left="file-text" variant="solid" :disabled="busy" @click="emit('template')" />
        </template>
        <template v-else>
          <textarea v-if="kind === 'text' || (mediaKind && captionAllowed)" ref="draftInput" v-model="body" class="chat-draft"
            :aria-label="mediaKind ? 'Caption' : 'Message'" :placeholder="mediaKind ? 'Add a caption…' : 'Message…'" rows="1" :readonly="busy"
            @focus="editing = true" @blur="editing = false" @keydown="keydown" @input="resizeDraft(); typing()" />
          <span v-else class="composer-status composer-kind-hint">{{ mediaKind ? 'This file sends without a caption.' : 'Review the details before sending.' }}</span>
          <Button class="composer-send" :label="isMobile ? '' : busy && !uploading ? 'Sending…' : 'Send'" icon="send" aria-label="Send" :aria-description="sendTitle" :title="sendTitle" type="submit" variant="solid" :disabled="!canSend" />
        </template>
      </div>
      <input type="file" ref="attachmentInput" aria-label="Attachment" hidden :accept="attachmentAccept(capabilities, sourceContext.provider, requestedAttachmentKind)" :disabled="busy" @change="attachFile" />
    </template>
    <CannedReplies v-if="showReplies" :source="source" @close="closeReplies" @select="applySavedReply" />
  </form>
</template>
