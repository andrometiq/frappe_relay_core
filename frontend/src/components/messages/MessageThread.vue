<script setup>
import { readableName } from '../../services/recordTitle'
import { channelStatus } from '../../services/channelComposition';
import { useMessageInfo } from "../../composables/useMessageInfo";
import LoadingRows from "../LoadingRows.vue";
import ReadByBubble from "./ReadByBubble.vue";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import ParticipantReceipts from "./ParticipantReceipts.vue";
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from "vue";
import { Button, FeatherIcon, Dropdown, Dialog } from "@relay/ui";
import { coreApi } from "../../services/coreApi";
import MessageContent from "../MessageContent.vue";
import { messageData, objectValue, attachmentDownloadURL } from "../messageContent";
const props = defineProps({
  rows: Array,
  contactName: String,
  canComment: Boolean,
  more: Boolean,
  busy: Boolean,
  emoji: String,
  selected: String,
  anchor: String,
  position: Object,
  newer: Boolean,
});
const emit = defineEmits([
  "reconcile",
  "older",
  "newer",
  "position",
  "reply",
  "send",
  "ticket",
  "visible",
  "visibleMessages",
  "quote",
  "note",
]);
const cursorReaders=ref([]);
let readerGeneration=0;
const readersByMessage=computed(()=>{const result={};for(const reader of cursorReaders.value)(result[reader.last_read_message]||=[]).push(reader);return result;});
async function loadReaders(){
 const current=++readerGeneration,names=(props.rows||[]).filter(row=>!row._pending).map(row=>row.name).slice(-150);
 if(!names.length){cursorReaders.value=[];return;}
 try{const result=await coreApi('message_reads.cursors',{messages:JSON.stringify(names)});if(current===readerGeneration)cursorReaders.value=result.readers||[]}catch{if(current===readerGeneration)cursorReaders.value=[];}
}
watch(()=>[props.selected,(props.rows||[]).map(row=>row.name).join(',')],()=>loadReaders(),{immediate:true});
useRealtimeRefresh([],['reads'],loadReaders);
const viewport = ref(null);
const reactionTarget = ref(null);
const reactionChoices = ["👍", "❤", "🔥", "🥰", "👏", "😁", "🤔", "😢"];
function canReact(message) {
  const context = objectValue(message.provider_context);
  return !context.group_id && context.provider === "WhatsApp";
}
function deliveryKind(message) {
  const status = String(message.status || "");
  if (["Failed", "Rejected", "Unconfirmed", "Uncertain"].includes(status)) return "failed";
  if (["Pending", "Queued", "Sending"].includes(status)) return "sending";
  if (status === "Read") return "read";
  if (status === "Delivered") return "delivered";
  return "sent";
}
function react(message, emoji) {
  if (props.busy) return;
  reactionTarget.value = null;
  emit("send", message, "reaction", { emoji });
}
watch(() => props.selected, () => { reactionTarget.value = null; });
const {info,coverage,coverageError,infoOpen,showInfo,refreshCoverage,close:closeInfo}=useMessageInfo(()=>props.rows||[],()=>props.selected);
useRealtimeRefresh([],['reads'],refreshCoverage);
onBeforeUnmount(closeInfo);

function timeOf(message) {
  const value = new Date(
    (message.sent_at || message.creation || "").replace(" ", "T"),
  );
  return Number.isNaN(value.getTime()) ? null : value;
}
function timeLabel(message) {
  return (
    timeOf(message)?.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    }) || ""
  );
}
function dayLabel(message) {
  const date = timeOf(message);
  if (!date) return '';
  const today = new Date();
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return 'Today';
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return (
    date.toLocaleDateString([], {
      day: "numeric",
      month: "long",
      year: "numeric",
    }) || ""
  );
}
function quoted(message) {
  const ctx = objectValue(message.provider_context);
  return props.rows.find(
    (row) =>
      row.channel === message.channel &&
      row.sender_endpoint === message.sender_endpoint &&
      String(
        objectValue(row.provider_context).message_id || row.provider_id,
      ) === String(ctx.reply_to_message_id),
  );
}
watch(
  () => props.anchor,
  async (value) => {
    if (!value) return;
    await nextTick();
    const node = [
      ...(viewport.value?.querySelectorAll("[data-message]") || []),
    ].find((node) => node.dataset.message === value);
    if(node && viewport.value)viewport.value.scrollTop+=node.getBoundingClientRect().top-viewport.value.getBoundingClientRect().top-(props.position?.offset??20);
  },
);
let visibleTimer;
function trackVisible() {
  clearTimeout(visibleTimer);
  visibleTimer = setTimeout(() => {
    const node = viewport.value;
    if (!node || document.visibilityState !== "visible" || !document.hasFocus()) return;
    const bounds = node.getBoundingClientRect();
    const visible = [...node.querySelectorAll("[data-message]")].filter(
      (row) => {
        const rect = row.getBoundingClientRect();
        return rect.top < bounds.bottom - 20 && rect.bottom > bounds.top + 20;
      },
    );
    if (visible.length) {
      emit("position", {name:visible[0].dataset.message, offset:visible[0].getBoundingClientRect().top-bounds.top,
        atBottom:node.scrollHeight-node.scrollTop-node.clientHeight<80});
      emit("visible", visible.at(-1).dataset.message);
      emit(
        "visibleMessages",
        visible.map((row) => row.dataset.message),
      );
    }
  }, 400);
}
onBeforeUnmount(() => clearTimeout(visibleTimer));
async function restorePosition() {
  await nextTick();
  const node=viewport.value;if(!node)return;
  const name=props.position?.name || props.anchor;
  const target=[...node.querySelectorAll('[data-message]')].find(row=>row.dataset.message===name);
  if(target)node.scrollTop+=target.getBoundingClientRect().top-node.getBoundingClientRect().top-(props.position?.offset??20);
  else node.scrollTop=node.scrollHeight;
  trackVisible();
}
onMounted(() => {
  restorePosition();
  window.addEventListener('focus', trackVisible);
  document.addEventListener('visibilitychange', trackVisible);
});
onBeforeUnmount(() => {
  window.removeEventListener('focus', trackVisible);
  document.removeEventListener('visibilitychange', trackVisible);
});
let pagingDirection='';
function requestPage(direction) {if(props.busy)return;pagingDirection=direction;emit(direction);}
async function fillViewport() {
  await nextTick();
  const node=viewport.value;
  if(node && props.more && !props.busy && props.rows?.length && node.scrollHeight<=node.clientHeight+32)
    requestPage('older');
}
watch(()=>[props.more,props.busy,props.rows?.length],fillViewport);
watch(
  () => props.rows,
  async (rows, previous) => {
    const node = viewport.value;
    if (!node) return;
    const height = node.scrollHeight,
      top = node.scrollTop;
    const viewportTop=node.getBoundingClientRect().top;
    const visibleAnchor=[...node.querySelectorAll('[data-message]')].find(row=>row.getBoundingClientRect().bottom>viewportTop+20);
    const stableName=visibleAnchor?.dataset.message, stableOffset=visibleAnchor?.getBoundingClientRect().top-viewportTop;
    const paging=!!pagingDirection;pagingDirection='';
    const prepended =
      previous?.length &&
      rows[0]?.name !== previous[0]?.name &&
      rows.some((row) => row.name === previous[0].name);
    const atBottom = height - top - node.clientHeight < 80;
    await nextTick();
    trackVisible();
    if (props.anchor && !previous?.length) {
      const target = [...node.querySelectorAll("[data-message]")].find(
        (row) => row.dataset.message === props.anchor,
      );
      if (target) {
        node.scrollTop+=target.getBoundingClientRect().top-node.getBoundingClientRect().top-(props.position?.offset??20);
        return;
      }
    }
    const stable=[...node.querySelectorAll('[data-message]')].find(row=>row.dataset.message===stableName);
    if((paging||prepended||!atBottom)&&stable)node.scrollTop+=stable.getBoundingClientRect().top-node.getBoundingClientRect().top-stableOffset;
    else if (prepended) node.scrollTop = top + node.scrollHeight - height;
    else if (atBottom || !previous?.length) node.scrollTop = node.scrollHeight;
  },
);
function scrolled() {
  trackVisible();
  const node = viewport.value;
  if (
    node &&
    node.scrollTop < 32 &&
    node.scrollHeight > node.clientHeight &&
    props.more &&
    !props.busy
  )
    requestPage("older");
  else if(node && props.newer && !props.busy && node.scrollHeight-node.scrollTop-node.clientHeight<60) requestPage('newer');
}
function actions(message) {
  const items = [
    { label: "Message info", icon: "info", onClick: () => showInfo(message) },
  ];
  const download = attachmentDownloadURL(message);
  if (download) items.push({label: 'Download attachment', icon: 'download', onClick: () => {
    const link = document.createElement('a');
    link.href = download;
    link.download = '';
    document.body.appendChild(link);
    link.click();
    link.remove();
  }});
  const context = objectValue(message.provider_context);
  if (props.canComment)
    items.push({
      label: "Discuss internally",
      icon: "message-square",
      onClick: () => emit("note", message),
    });
  if (!context.group_id && context.provider !== "Email")
    items.push(
      {
        label: "React",
        icon: "smile",
        onClick: () =>
          reactionTarget.value = message.name,
      },
      {
        label: "Clear reaction",
        icon: "x",
        onClick: () => emit("send", message, "reaction", { emoji: "" }),
      },
    );
  if (messageData(message).kind === "sticker")
    items.push({
      label: "Resend sticker",
      icon: "repeat",
      onClick: () => emit("send", message, "sticker"),
    });
  return items.map((item) => ({ ...item, disabled: props.busy }));
}
</script>
<template>
  <div
    ref="viewport"
    class="message-thread"
    aria-label="WhatsApp conversation"
    @scroll.passive="scrolled"
  >
    <LoadingRows v-if="busy && !rows.length" label="Loading messages…" :count="3" />
    <div v-if="!rows.length && !busy" class="conversation-empty">
      <h2>No messages yet</h2>
    </div>
    <template v-for="(message, index) in rows" :key="message.name">
      <div
        v-if="
          dayLabel(message) &&
          (!index || dayLabel(rows[index - 1]) !== dayLabel(message))
        "
        class="message-date-divider"
      >
        <span>{{ dayLabel(message) }}</span>
      </div>
      <article
        class="conversation-bubble"
        :class="{
          'ml-auto': message.direction === 'Outgoing',
          'anchored-message': message.name === anchor,
        }"
        :data-message="message._pending ? null : message.name"
      >
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
        <span class="text-xs text-ink-gray-5">{{ objectValue(message.provider_context).provider }}</span>
        <MessageContent :message="message" :show-reply-reference="false" />
        <p v-if="message._pending && message.error" class="text-sm text-ink-gray-7 mt-2" role="status">{{ message.error }}</p>
        <footer class="message-footer">
          <time
            :title="timeOf(message)?.toLocaleString()"
            :datetime="timeOf(message)?.toISOString()"
            >{{ timeLabel(message) }}</time
          >
          <span v-if="message.edited_at" title="Message edited">edited</span>
          <span
            v-if="message.direction === 'Outgoing'"
            :title="channelStatus(message)"
            :aria-label="channelStatus(message)"
            class="message-delivery"
            :class="{
              'delivery-failed': deliveryKind(message) === 'failed',
              'delivery-read': deliveryKind(message) === 'read',
            }"
          >
            <FeatherIcon
              v-if="['failed', 'sending', 'sent'].includes(deliveryKind(message))"
              :name="
                deliveryKind(message) === 'failed'
                  ? 'alert-circle'
                  : deliveryKind(message) === 'sending'
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
          <span v-if="!message._pending && message.direction === 'Outgoing' && objectValue(message.provider_context).provider !== 'WhatsApp'" class="pending-status">{{ channelStatus(message) }}</span>
          <span v-if="message._pending" class="pending-status">{{channelStatus(message)}}
            <Button v-if="(message.action && message.status !== 'Failed') || (message.emailRequest && message.status === 'Unconfirmed')" label="Check status" :disabled="busy" @click="emit('reconcile', message)" />
          </span>
          <div v-else class="message-actions">
            <Button v-if="canReact(message)" icon="smile" label="Add reaction" title="Add reaction"
              :disabled="busy" @click="reactionTarget = reactionTarget === message.name ? null : message.name" />
            <Button
              icon="corner-up-left"
              label="Reply"
              title="Reply"
              :disabled="busy"
              @click="emit('reply', message)"
            /><Dropdown :options="actions(message)" placement="right"
              ><Button
                icon="more-horizontal"
                label="Message actions"
                title="Message actions"
                :disabled="busy"
            /></Dropdown>
          </div>
        </footer>
        <div v-if="reactionTarget === message.name" class="reaction-picker" role="group" aria-label="Choose reaction" @keydown.esc="reactionTarget = null">
          <button v-for="reaction in reactionChoices" :key="reaction" type="button"
            :aria-label="'React ' + reaction" :disabled="busy" @click="react(message, reaction)">{{ reaction }}</button>
          <button type="button" aria-label="Remove reaction" title="Remove reaction" :disabled="busy" @click="react(message, '')">×</button>
          <button type="button" aria-label="Close reactions" title="Close reactions" @click="reactionTarget = null">Close</button>
        </div>
        <ReadByBubble v-if="!message._pending && readersByMessage[message.name]?.length" :message="message.name" :readers="readersByMessage[message.name]" />
      </article>
    </template>
  </div>
  <Dialog v-model="infoOpen" :options="{ title: 'Message info', size: 'lg' }"
    ><template #body-content
      ><div v-if="info">
        <p class="message-info-content">{{ info.content }}</p>
        <dl>
          <dt>Channel</dt>
          <dd>
            {{ objectValue(info.provider_context).provider || info.channel }}
          </dd>
          <dt>Direction</dt>
          <dd>{{ info.direction }}</dd>
          <dt>Status</dt>
          <dd>
            {{ info.direction === "Incoming" ? "Received" : channelStatus(info) }}
          </dd>
          <dt>Time</dt>
          <dd>{{ timeOf(info)?.toLocaleString() || "Unavailable" }}</dd>
          <dt v-if="info.edited_at">Edited</dt>
          <dd v-if="info.edited_at">{{ info.edited_at }}</dd>
          <dt>Message reference</dt>
          <dd>{{ info.name }}</dd>
        </dl>
        <ParticipantReceipts v-if="info.direction==='Outgoing' && objectValue(info.provider_context).provider==='WhatsApp' && objectValue(info.provider_context).group_id" :message="info.name" />
        <section aria-label="Operator read coverage" class="mt-4 space-y-2">
          <h3 class="font-medium">Seen by your team</h3>
          <p v-if="coverageError" role="alert">{{ coverageError }}</p>
          <template v-if="coverage"
            ><p v-if="coverage.expected">
              {{ coverage.read }} of {{ coverage.expected }} assigned operators
              have viewed this message.
            </p>
            <p v-else>No assigned team coverage requirement.</p>
            <p v-if="!coverage.read_by.length">No recorded views yet.</p>
            <p v-for="reader in coverage.read_by" :key="reader.user">
              {{ reader.full_name }} ·
              {{ new Date(reader.read_at).toLocaleString() }}
            </p>
            <p v-if="coverage.more">Showing the most recent 100 readers.</p>
            <p v-if="coverage.unread_by.length">
              Not yet viewed:
              {{
                coverage.unread_by.map((reader) => reader.full_name).join(", ")
              }}
            </p></template
          >
        </section>
      </div></template
    ></Dialog
  >
</template>

<style scoped>
.conversation-bubble:has(.message-readers){margin-bottom:18px}
</style>
