<script setup>
import { inject, ref, watch, nextTick, computed } from "vue";
import { Button, FormControl } from "@relay/ui";
import MessageContent from "../MessageContent.vue";
import { objectValue } from "../messageContent";
import { telegramKey } from "../../composables/telegramContext";
const {
  pendingSend, pendingCursor, pendingPage, restorePending, checkGroupSend, retryGroupSend, atBottom, newMessages, latest,
  busy,
  info,
  text,
  topic,
  group,
  history,
  hasMore,
  reply,
  run,
  loadHistory,
  send,
} = inject(telegramKey);
const viewport=ref(null), retrying=ref(null);
watch(group,()=>{retrying.value=null;});
const canSend=computed(()=>!!group.value && !busy.value && !!text.value.trim());
function submit(){if(canSend.value)run(send);}
function keydown(event){
  if(event.key!=="Enter" || event.shiftKey || event.isComposing || event.keyCode===229)return;
  event.preventDefault();
  if(!event.repeat)submit();
}
watch(history,async (rows,previous)=>{
  const node=viewport.value;if(!node)return;
  const top=node.scrollTop,height=node.scrollHeight,follow=atBottom.value;
  const prepended=previous?.length && rows.findIndex(row=>row.name===previous[0].name)>0;
  await nextTick();
  if(prepended)node.scrollTop=top+node.scrollHeight-height;
  else if(follow)node.scrollTop=node.scrollHeight;
});
watch(atBottom,async value=>{if(value){await nextTick();if(viewport.value)viewport.value.scrollTop=viewport.value.scrollHeight;}});
function scrolled(){const node=viewport.value;if(node)atBottom.value=node.scrollHeight-node.scrollTop-node.clientHeight<60;}
</script>
<template>
  <form class="space-y-3" @submit.prevent="submit">
    <div class="flex gap-2">
      <Button
        label="Refresh messages"
        :disabled="busy"
        @click="run(() => loadHistory())"
      /><Button
        v-if="hasMore"
        label="Earlier messages"
        :disabled="busy"
        @click="run(() => loadHistory(true))"
      />
    </div>
    <div
      class="max-h-96 overflow-auto space-y-3"
      aria-label="Group conversation"
      ref="viewport" @scroll="scrolled"
    >
      <article
        v-for="message in history"
        :key="message.name"
        class="rounded border p-3 space-y-2"
      >
        <div class="text-xs text-ink-gray-5">
          {{ message.direction }} · {{ message.creation }}
        </div>
        <MessageContent :message="message" /><Button
          v-if="objectValue(message.provider_context).message_id"
          label="Reply"
          :disabled="busy"
          @click="
            reply = message;
            topic = String(
              objectValue(message.provider_context).message_thread_id || '',
            );
          "
        />
      </article>
      <p v-if="!history.length" class="text-sm text-ink-gray-5">
        No messages in this group yet.
      </p>
    </div>
    <Button v-if="newMessages" label="New messages" icon="arrow-down" :disabled="busy" @click="latest" />
    <div v-if="reply" class="rounded border p-2 flex items-center gap-3">
      <span class="text-sm truncate">Replying to {{ reply.content }}</span
      ><Button label="Cancel reply" @click="reply = null" />
    </div>
    <div v-for="pending in pendingSend" :key="pending.action" class="rounded border p-3 space-y-2" role="status">
      <p>{{ ({Queued:'Queued',Dispatching:'Sending',Uncertain:'Unconfirmed',Rejected:'Failed'})[pending.status] || pending.status }}</p>
      <p class="text-sm whitespace-pre-wrap">{{ pending.args.text }}</p>
      <p v-if="pending.error" class="text-sm">{{ pending.error }}</p>
      <Button v-if="pending.status !== 'Rejected'" label="Check status" :disabled="busy" @click="checkGroupSend(pending)" />
      <Button v-else-if="retrying !== pending.action" label="Review retry" :disabled="busy" @click="retrying = pending.action" />
      <div v-if="retrying === pending.action" class="space-y-2">
        <p class="text-sm text-ink-gray-5">Send this failed message again to {{ info?.title || group?.label }}? Its original reply and topic are preserved.</p>
        <Button label="Retry rejected send" variant="solid" :disabled="busy" @click="retryGroupSend(pending); retrying = null" />
        <Button label="Cancel retry" :disabled="busy" @click="retrying = null" />
      </div>
    </div>
    <Button v-if="pendingPage" label="Latest pending sends" :disabled="busy" @click="run(()=>restorePending())" />
    <Button v-if="pendingCursor" label="Earlier pending sends" :disabled="busy" @click="run(()=>restorePending(true))" />
    <FormControl
      v-if="info?.is_forum"
      label="Topic ID (optional)"
      v-model="topic"
    /><FormControl type="textarea" label="Message" v-model="text" @keydown="keydown" /><Button
      type="submit"
      label="Send message"
      variant="solid"
      :disabled="!canSend"
    />
    <p class="text-xs text-ink-gray-5">Enter to send · Shift+Enter for a new line</p>
  </form>
</template>
