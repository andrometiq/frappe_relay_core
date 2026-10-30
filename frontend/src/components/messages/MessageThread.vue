<script setup>
import { useLoadMore } from '../../composables/useLoadMore';
import { readableName } from '../../services/recordTitle'
import { channelStatus } from '../../services/channelComposition';
import { useMessageInfo } from "../../composables/useMessageInfo";
import LoadingRows from "../LoadingRows.vue";
import ReadByBubble from "./ReadByBubble.vue";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import MessageMenu from "./MessageMenu.vue";
import ReactionPicker from "./ReactionPicker.vue";
import MessageInfoDialog from "./MessageInfoDialog.vue";
import { useMobileLayout } from "../../composables/useMobileLayout";
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount, inject } from "vue";
import { Button, FeatherIcon } from "@relay/ui";
import { coreApi } from "../../services/coreApi";
import MessageContent from "../MessageContent.vue";
import { messageData, objectValue, attachmentDownloadURL, reactionLabels, ownReaction } from "../messageContent";
import { channelCan, multipleChannels, onPickedChannel } from "../../services/enabledChannels";
import { messageNumberTags } from "../../services/whatsappNumbers";
import { createScrollHold } from "./scrollHold";
import { dayDividers, quoteIndex, timeOf } from "./threadIndex";
import { groupSends } from "../../services/sendGroups";
import { notesInThread } from "../../services/threadNotes";
import { selectMessages, selectableMessage } from '../../services/messageSelection'
const selecting = ref(false), selectedMessages = ref([]), selectionAnchor = ref('')
const selection = computed(() => selectedMessages.value.map(message => message.name))
let suppressTap = null
function cancelSelection() { selecting.value = false; selectedMessages.value = []; selectionAnchor.value = ''; suppressTap = null }
async function startSelection(message) {
  if (!props.canComment || !selectableMessage(message)) return
  selecting.value = true; selectedMessages.value = [message]; selectionAnchor.value = message.name; menu.value = null
  await nextTick()
  if (selecting.value && selectionAnchor.value === message.name) scroll.toMessage(message.name)
}
function toggleSelection(message, event) {
  if (!selecting.value) return
  event.preventDefault(); event.stopPropagation()
  const ghostTap = event.type === 'click' && suppressTap === message.name
  suppressTap = null
  if (ghostTap) return
  const next = selectMessages(sentRows.value, selection.value, message.name, selectionAnchor.value, event.shiftKey)
  if (next === selection.value && selectableMessage(message)) emit('toast', 'Select at most 50 messages')
  const messages = new Map([...selectedMessages.value, ...sentRows.value].map(row => [row.name, row]))
  selectedMessages.value = next.map(name => messages.get(name)); selectionAnchor.value = message.name
}
function ticketFromSelection() {
  emit('ticket', selectedMessages.value)
  cancelSelection()
}
const props = defineProps({
  rows: Array,
  contactName: String,
  canComment: Boolean,
  more: Boolean,
  busy: Boolean,
  paging: Boolean,
  pagingError: String,
  emoji: String,
  selected: String,
  anchor: String,
  position: Object,
  newer: Boolean,
  error: String,
  unread: String,
  notes: { type: Array, default: () => [] },
  replyClosed: Boolean,
  // The provider of the channel picked to send on; actions that send act only on its messages.
  provider: String,
});
const emit = defineEmits([
  "reconcile",
  "retry",
  "discard",
  "older",
  "retryPage",
  "newer",
  "position",
  "reply",
  "send",
  "ticket",
  "visible",
  "visibleMessages",
  "quote",
  "note",
  "toast",
]);
const capabilities = inject("relayCapabilities", ref({}));
const showChannel = computed(() => multipleChannels(capabilities.value));
const sentRows = computed(() => groupSends(props.rows || []));
const threadRows = computed(() => notesInThread(sentRows.value, props.notes, { more: props.more, newer: props.newer }));
const numberTags = computed(() => messageNumberTags(sentRows.value, capabilities.value));
// Built once per row change: every render, such as a page load or the paging flag, only looks rows up.
const quoted = computed(() => quoteIndex(props.rows || []));
const dividers = computed(() => dayDividers(threadRows.value));
// A message sent to several channels shows one delivery mark per channel.
const deliveries = message => message.sends || [message];
// A chat send the server rejected, or one that never reached the server, offers Retry and Delete.
const isUnsent = message => !message.emailRequest && (message.action ? message.status === 'Failed' : message.status === 'Unconfirmed' && !!message.request);
const can = (message, feature) => channelCan(capabilities.value, objectValue(message.provider_context).provider, feature);
const cursorReaders=ref([]);
let readerGeneration=0;
const readersByMessage=computed(()=>{const result={};for(const reader of cursorReaders.value)(result[reader.last_read_message]||=[]).push(reader);return result;});
async function loadReaders(){
 const current=++readerGeneration,names=(props.rows||[]).filter(row=>!row._pending).map(row=>row.name).slice(-150);
 if(!names.length){cursorReaders.value=[];return;}
 try{const result=await coreApi('message_reads.cursors',{messages:JSON.stringify(names)});if(current===readerGeneration)cursorReaders.value=result.readers||[]}catch{if(current===readerGeneration)cursorReaders.value=[];}
}
watch(()=>props.selected+'|'+(props.rows||[]).map(row=>row.name).join(','),()=>loadReaders(),{immediate:true});
useRealtimeRefresh([],['reads'],loadReaders);
const viewport = ref(null), content = ref(null);
// Before the newest page is loaded, the reader keeps their message while newer pages append below it.
const scroll = createScrollHold(() => viewport.value, () => !props.newer);
const reactionTarget = ref(null);
// One menu for the whole thread: a menu per bubble made every older page slow to draw.
const isMobile = useMobileLayout();
const menu = ref(null);
function openMenu(message, event) {
  const trigger = event.currentTarget;
  menu.value = menu.value?.message.name === message.name ? null : { message, trigger, sheet: isMobile.value };
}
// A long press starts selection; moving the pointer cancels it so scrolling stays natural.
let pressTimer, pressPoint, pressedMessage;
function pressStart(message, event) {
  pressEnd(); suppressTap = null;
  if (!isMobile.value || !props.canComment || selecting.value || message._pending || event.pointerType === "mouse") return;
  pressPoint = [event.clientX, event.clientY];
  pressTimer = setTimeout(() => { startSelection(message); pressedMessage = message.name; navigator.vibrate?.(10); }, 450);
}
function pressEnd(event) {
  clearTimeout(pressTimer); pressPoint = null;
  if (event?.type === 'pointerup') suppressTap = pressedMessage;
  pressedMessage = null;
}
function pressMove(event) { if (pressPoint && Math.hypot(event.clientX - pressPoint[0], event.clientY - pressPoint[1]) > 10) pressEnd(); }
onBeforeUnmount(pressEnd);
const reactionChoices = ["👍", "❤️", "🔥", "🥰", "👏", "😁", "🤔", "😢"];
const quickReactions = ["👍", "❤️", "😁", "👏", "😢"];
function canReact(message) {
  return !objectValue(message.provider_context).group_id && can(message, "reactions") && onPickedChannel(message, props.provider);
}
function deliveryKind(message) {
  const status = String(message.status || "");
  if (["Failed", "Rejected", "Unconfirmed", "Uncertain"].includes(status)) return "failed";
  if (["Pending", "Queued", "Sending"].includes(status)) return "sending";
  if (status === "Read") return "read";
  if (status === "Delivered") return "delivered";
  return "sent";
}
function channelLabel(message, copy) {
  return message.sends ? objectValue(copy.provider_context).provider + ': ' + channelStatus(copy) : channelStatus(copy);
}
function react(message, emoji) {
  if (props.busy) return;
  reactionTarget.value = null;
  emit("send", message, "reaction", { emoji });
}
watch(() => props.selected, () => { reactionTarget.value = null; menu.value = null; cancelSelection(); });
const {info,coverage,coverageError,infoOpen,showInfo,refreshCoverage,close:closeInfo}=useMessageInfo(()=>props.rows||[],()=>props.selected);
useRealtimeRefresh([],['reads'],refreshCoverage);
onBeforeUnmount(closeInfo);

function timeLabel(message) {
  return (
    timeOf(message)?.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }) || ""
  );
}
watch(
  () => props.anchor,
  async (value) => {
    if (!value) return;
    await nextTick();
    scroll.toMessage(value, props.position?.offset ?? 20);
  },
);
let visibleTimer;
// Go to latest clears the saved position; release the reader's scroll anchor too.
watch(() => props.position, async (position, previous) => {
  if (position || !previous) return;
  await nextTick();
  scroll.toBottom();
  trackVisible();
});
function trackVisible() {
  clearTimeout(visibleTimer);
  visibleTimer = setTimeout(() => {
    const node = viewport.value;
    if (!node) return;
    const bounds = node.getBoundingClientRect();
    const visible = [...node.querySelectorAll("[data-message]")].filter(
      (row) => {
        const rect = row.getBoundingClientRect();
        return rect.top < bounds.bottom - 20 && rect.bottom > bounds.top + 20;
      },
    );
    if (!visible.length) return;
    // The position drives "Go to latest" and arrivals, so it is kept even when the window has no focus.
    emit("position", {name:visible[0].dataset.message, offset:visible[0].getBoundingClientRect().top-bounds.top,
      atBottom:node.scrollHeight-node.scrollTop-node.clientHeight<80});
    // Only a reader who can see the thread has seen these messages.
    if (document.visibilityState !== "visible" || !document.hasFocus()) return;
    emit("visible", visible.at(-1).dataset.message);
    emit("visibleMessages", visible.map((row) => row.dataset.message));
  }, 400);
}
onBeforeUnmount(() => clearTimeout(visibleTimer));
async function restorePosition() {
  await nextTick();
  const name=props.position?.atBottom ? props.anchor : props.position?.name || props.anchor;
  if(!name || !scroll.toMessage(name, props.position?.offset ?? 20)) scroll.toBottom();
  trackVisible();
}
let resizes;
onMounted(() => {
  restorePosition();
  resizes = new ResizeObserver(() => scroll.apply());
  resizes.observe(viewport.value);
  resizes.observe(content.value);
  window.addEventListener('focus', trackVisible);
  document.addEventListener('visibilitychange', trackVisible);
});
onBeforeUnmount(() => {
  resizes?.disconnect();
  window.removeEventListener('focus', trackVisible);
  document.removeEventListener('visibilitychange', trackVisible);
});
// Older pages load about three screens ahead, so a fast scroll does not reach the top first.
// Newer pages load only after a jump to an older message (search, unread, quote): loaded rows are never dropped.
const earlier = useLoadMore({ root: viewport, margin: '3000px 0px', loading: () => props.paging, error: () => props.pagingError, hasMore: () => props.more && props.rows?.length, load: () => emit('older') });
const later = useLoadMore({ root: viewport, margin: '1500px 0px', loading: () => props.paging, error: () => props.pagingError, hasMore: () => props.newer, load: () => emit('newer') });
watch(
  () => props.rows,
  async (_rows, previous) => {
    await nextTick();
    trackVisible();
    // A held row that is gone (Go to latest replaced the rows) falls back to the anchor or the end.
    if (previous?.length && scroll.apply()) return;
    if (!props.anchor || !scroll.toMessage(props.anchor, props.position?.offset ?? 20)) scroll.toBottom();
  },
);
function scrolled() {
  trackVisible();
  scroll.scrolled();

}
// Plain-HTTP sites have no Clipboard API, so the copy falls back to a hidden text area.
async function copyText(text) {
  try {
    if (navigator.clipboard) await navigator.clipboard.writeText(text);
    else {
      const area = Object.assign(document.createElement("textarea"), { value: text });
      document.body.appendChild(area); area.select();
      const copied = document.execCommand("copy"); area.remove();
      if (!copied) throw Error("Copy refused");
    }
    emit("toast", "Copied");
  } catch { emit("toast", "Could not copy"); }
}
// Quick reactions sit on top of the menu; the actions follow, most used first.
function actions(message) {
  const sends = onPickedChannel(message, props.provider);
  const items = props.replyClosed || !sends ? [] : [{ label: "Reply", icon: "corner-up-left", onClick: () => emit("reply", message) }];
  if (message.content) items.push({ label: "Copy text", icon: "copy", onClick: () => copyText(message.content) });
  const download = attachmentDownloadURL(message);
  if (download) items.push({label: 'Download', icon: 'download', onClick: () => {
    const link = document.createElement('a');
    link.href = download;
    link.download = '';
    if (!download.startsWith('/')) Object.assign(link, { target: '_blank', rel: 'noopener noreferrer' });
    document.body.appendChild(link);
    link.click();
    link.remove();
  }});
  items.push({ label: "Message info", icon: "info", onClick: () => showInfo(message) });
  if (sends && messageData(message).kind === "sticker")
    items.push({ label: "Resend sticker", icon: "repeat", onClick: () => emit("send", message, "sticker") });
  if (props.canComment) items.push({ label: "Select", icon: "check-square", onClick: () => startSelection(message) });
  if (props.canComment)
    items.push({ divider: true }, { label: "Add internal note", icon: "message-square", onClick: () => emit("note", message) },
      {
        label: "Create ticket",
        icon: "bookmark",
        onClick: () => emit("ticket", message),
      });
  return items.map((item) => ({ ...item, disabled: props.busy }));
}
</script>
<template>
  <div class="message-thread-region">
    <div v-if="selecting" class="message-selection-bar" @keydown.esc="cancelSelection" role="toolbar" aria-label="Selected messages">
      <span role="status">{{ selection.length }} selected</span>
      <Button label="Create ticket" variant="solid" :disabled="!selection.length" @click="ticketFromSelection" />
      <Button label="Cancel" variant="ghost" @click="cancelSelection" />
    </div>
  <div
    ref="viewport"
    class="message-thread" style="scroll-padding-block:20px"
    :class="{ 'has-menu-sheet': menu?.sheet }"
    aria-label="Conversation"
    @keydown.esc="cancelSelection"
    @scroll.passive="scrolled"
  >
    <LoadingRows v-if="busy && !rows.length" label="Loading messages…" :count="3" />
    <div v-if="!rows.length && !busy" class="conversation-empty">
      <h2>No messages yet</h2>
    </div>
    <p v-if="pagingError" class="message-page-error" role="alert">Could not load more messages. <button type="button" @click="emit('retryPage')">Retry</button></p>
    <div v-if="more" ref="earlier" class="h-px" aria-hidden="true" />
    <div ref="content" class="message-thread-content">
    <template v-for="message in threadRows" :key="message.name">
      <div v-if="dividers.has(message.name)" class="message-date-divider">
        <span>{{ dividers.get(message.name) }}</span>
      </div>
      <div v-if="message.name === unread" class="message-date-divider message-unread-divider" role="separator">
        <span>Unread messages</span>
      </div>
      <div v-if="numberTags[message.name]" class="message-number-line" :class="{ 'is-outgoing': message.direction === 'Outgoing' }">
        <span class="number-tag">{{ numberTags[message.name] }}</span>
      </div>
      <article v-if="message.note" class="note-bubble" aria-label="Internal note">
        <header><FeatherIcon name="lock" :size="13" /><span>Internal note</span><strong>{{ message.note.author_name }}</strong>
          <time :title="timeOf(message)?.toLocaleString()" :datetime="timeOf(message)?.toISOString()">{{ timeLabel(message) }}</time></header>
        <p>{{ message.note.body }}</p>
        <small>Only your team sees this</small>
      </article>
      <article
        v-else
        class="conversation-bubble"
        :class="{
          'ml-auto': message.direction === 'Outgoing',
          'anchored-message': message.name === anchor,
          'menu-target': menu?.message.name === message.name,
          'is-selecting': selecting && selectableMessage(message),
          'is-selected': selection.includes(message.name),
        }"
        :data-message="message._pending ? null : message.name"
        :tabindex="selecting && selectableMessage(message) ? 0 : -1"
        :role="selecting && selectableMessage(message) ? 'checkbox' : undefined"
        :aria-checked="selecting && selectableMessage(message) ? selection.includes(message.name) : undefined"
        @click.capture="toggleSelection(message, $event)"
        @keydown.space="selecting && toggleSelection(message, $event)"
        v-memo="[selecting, selection.includes(message.name), message, message.status, message.error, message.action, busy, message.name === anchor, reactionTarget === message.name, menu?.message.name === message.name, readersByMessage[message.name], quoted(message), showChannel, contactName, capabilities]"
        @pointermove="pressMove" @pointerdown="pressStart(message, $event)" @pointerup="pressEnd" @pointercancel="pressEnd" @pointerleave="pressEnd"
        @contextmenu="isMobile && $event.preventDefault()"
      >
        <span v-if="selecting && selectableMessage(message)" class="message-selection-check" aria-hidden="true"><FeatherIcon :name="selection.includes(message.name) ? 'check-square' : 'square'" :size="20" /></span>
        <div v-if="message.contact_label" class="message-sender">
          {{ message.direction === "Outgoing" ? "To " + readableName(message.contact_label, "Contact") : readableName(message.contact_label, "Contact") }}
        </div>
        <button
          v-if="objectValue(message.provider_context).reply_to_message_id"
          type="button"
          class="message-quote"
          @click="emit('quote', message)"
        >
          <strong>{{
            quoted(message)?.direction === "Outgoing"
              ? "You"
              : contactName || "Contact"
          }}</strong
          ><span>{{
            quoted(message)?.content || "View original message"
          }}</span>
        </button>
        <span v-if="showChannel && !message.sends" class="message-channel">{{ objectValue(message.provider_context).provider }}</span>
        <MessageContent :message="message" :show-reply-reference="false" :show-reactions="false" />
        <p v-if="message._pending && message.error" class="text-sm text-ink-gray-7 mt-2" role="status">{{ message.error }}</p>
        <footer class="message-footer">
          <time
            :title="timeOf(message)?.toLocaleString()"
            :datetime="timeOf(message)?.toISOString()"
            >{{ timeLabel(message) }}</time
          >
          <span v-if="message.edited_at" title="Message edited">edited</span>
          <span
            v-for="copy in message.direction === 'Outgoing' ? deliveries(message) : []"
            :key="copy.name"
            :title="channelLabel(message, copy)"
            :aria-label="channelLabel(message, copy)"
            class="message-delivery"
            :class="{
              'delivery-failed': deliveryKind(copy) === 'failed',
              'delivery-read': deliveryKind(copy) === 'read',
            }"
          >
            <span v-if="message.sends" class="message-send-channel">{{ objectValue(copy.provider_context).provider }}</span>
            <FeatherIcon
              v-if="['failed', 'sending', 'sent'].includes(deliveryKind(copy))"
              :name="
                deliveryKind(copy) === 'failed'
                  ? 'alert-circle'
                  : deliveryKind(copy) === 'sending'
                    ? 'clock'
                    : 'check'
              "
              class="h-3 w-3"
            />
            <span v-else class="delivery-checks" aria-hidden="true"
              ><FeatherIcon name="check" class="h-3 w-3" /><FeatherIcon
                name="check"
                class="h-3 w-3"
            /></span>
          </span>
          <span v-if="!message._pending && !message.sends && message.direction === 'Outgoing' && !can(message, 'read_receipts')" class="pending-status">{{ channelStatus(message) }}</span>
          <span v-if="message._pending && isUnsent(message)" class="pending-status is-unsent">Not sent
            <Button label="Retry" :disabled="busy" @click="emit('retry', message)" /><Button label="Delete" :disabled="busy" @click="emit('discard', message)" />
          </span>
          <span v-else-if="message._pending" class="pending-status">{{channelStatus(message)}}
            <Button v-if="(message.action && message.status !== 'Failed') || (message.emailRequest && message.status === 'Unconfirmed')" label="Check status" :disabled="busy" @click="emit('reconcile', message)" />
          </span>
        </footer>
        <button v-if="!message._pending && !selecting" type="button" class="message-menu-trigger" aria-label="Message actions" title="Message actions"
          aria-haspopup="menu" :aria-expanded="menu?.message.name === message.name" @pointerdown.stop @click="openMenu(message, $event)"><FeatherIcon name="chevron-down" :size="16" /></button>
        <ReactionPicker v-if="reactionTarget === message.name" :choices="reactionChoices" :current="ownReaction(message.reactions)" :busy="busy"
          @pick="react(message, $event)" @close="reactionTarget = null" />
        <div v-if="reactionLabels(message.reactions).length" class="message-reactions" aria-label="Reactions">
          <span v-for="reaction in reactionLabels(message.reactions)" :key="reaction" class="message-reaction">{{ reaction }}</span>
        </div>
        <ReadByBubble v-if="!message._pending && readersByMessage[message.name]?.length" :message="message.name" :readers="readersByMessage[message.name]" />
      </article>
    </template>
    </div>
    <div v-if="newer" ref="later" class="h-px" aria-hidden="true" />
  </div>
  </div>
  <MessageMenu v-if="menu" :key="menu.message.name" :trigger="menu.trigger" :area="viewport" :sheet="menu.sheet" :items="actions(menu.message)"
    :emoji="!replyClosed && canReact(menu.message) ? quickReactions : []" :current="ownReaction(menu.message.reactions)"
    @close="menu = null" @react="react(menu.message, $event)" @more="reactionTarget = menu.message.name" />
  <MessageInfoDialog v-model="infoOpen" :info="info" :coverage="coverage" :coverage-error="coverageError" :contact-name="contactName"
    :receipts="!!info && can(info, 'read_receipts')" :group-receipts="!!info && can(info, 'group_receipts')" />
</template>

<style scoped>
.message-thread-region { display:flex; flex-direction:column; flex:1; min-width:0; min-height:0; overflow:hidden; }
.message-selection-bar { flex:none; z-index:5; display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:8px; background:var(--surface-modal); border:1px solid var(--outline-gray-3); border-radius:8px; }
.message-selection-bar span { margin-right:auto; }
.message-selection-bar :deep(button) { min-height:44px; }
.message-thread .message-thread-content .conversation-bubble.is-selecting { cursor:pointer; user-select:none; min-height:44px; padding-left:40px; }
.conversation-bubble.is-selected { outline:2px solid var(--relay-accent); }
.message-selection-check { position:absolute; left:10px; top:12px; color:inherit; }

.conversation-bubble:has(.message-readers){margin-bottom:24px}
.conversation-bubble{position:relative}
/* The menu button sticks to the top of the visible thread, so a tall message scrolled under the header keeps it. */
.conversation-bubble:has(>.message-menu-trigger){display:flex;flex-direction:column}
.message-menu-trigger{order:-1;position:sticky;top:4px;z-index:2;align-self:flex-end;flex:none;margin:-4px -8px -20px 0;display:grid;place-items:center;width:24px;height:24px;min-height:0;padding:0;border-radius:999px;background:var(--surface-modal,var(--surface-white));box-shadow:0 1px 3px #0002;color:var(--ink-gray-6);opacity:0;transition:opacity .1s}
.conversation-bubble:is(:hover,:focus-within)>.message-menu-trigger,.message-menu-trigger[aria-expanded="true"]{opacity:1}
.message-menu-trigger:focus-visible{opacity:1;outline:2px solid var(--outline-blue-1,#5b9bd5)}
@media (hover:none){
  .message-menu-trigger{display:grid;opacity:.7;position:absolute;top:0;right:0;width:44px;height:44px;margin:0;background:transparent;box-shadow:none;color:inherit}
  .message-thread .message-thread-content .conversation-bubble:has(>.message-menu-trigger){padding-right:48px}
}
.has-menu-sheet .conversation-bubble:not(.menu-target){opacity:.35}
.note-bubble{align-self:center;width:min(420px,90%);margin:6px auto;padding:8px 12px;border:1px solid color-mix(in srgb,var(--relay-note-ink) 45%,transparent);border-radius:8px;background:var(--relay-note-bg);color:var(--relay-ink,var(--ink-gray-8));font-size:13px}
.note-bubble header{display:flex;flex-wrap:wrap;align-items:center;gap:6px;color:var(--relay-note-ink);font-size:12px}
.note-bubble time{margin-left:auto;font-size:12px;color:var(--relay-note-ink)}
.note-bubble p{margin:4px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.note-bubble small{font-size:12px;color:var(--relay-note-ink)}
.conversation-bubble.menu-target{box-shadow:0 0 0 2px var(--relay-accent,#2f6fdb)}
</style>
