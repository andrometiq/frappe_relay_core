<script setup>
import ChoiceField from '../fields/ChoiceField.vue';
import { inject, ref, watch } from "vue";
import { Button, FormControl, Badge } from "@relay/ui";
import MessageContent from "../MessageContent.vue";
import { objectValue } from "../messageContent";
import { telegramKey } from "../../composables/telegramContext";
const {
  knownTopics, topicCursor, loadTopics,
  busy, error,
  notice,
  info,
  text,
  topic,
  topicName,
  group,
  run,
  operation,
  topicAction,
} = inject(telegramKey);
const deleting = ref(false), confirmation = ref(""), generalName = ref("");
watch([group, topic], () => {deleting.value=false;confirmation.value="";});
async function removeTopic() {
  if (!topic.value || confirmation.value !== topic.value || busy.value) return;
  await run(async () => {await topicAction('topics.delete');topic.value="";deleting.value=false;notice.value="Topic deleted";});
}
async function general(action) {
  await run(async () => {await operation('topics.general.'+action, action==='edit'?{name:generalName.value}:{});notice.value="General topic updated";});
}
watch(() => group.value?.name, () => { if (info.value?.is_forum) run(() => loadTopics()) }, {immediate: true});
</script>
<template>
  <div class="space-y-3">
    <p v-if="!info?.is_forum" class="text-sm text-ink-gray-5">
      Topics require a Telegram forum group.
    </p>

    <ChoiceField :model-value="topic" :field="{ label: 'Known topic', options: knownTopics.map(row=>({value:row.thread_id,label:row.title+' · '+row.state})), loading: busy, error, hasMore: !!topicCursor, loadMore: () => run(() => loadTopics(true)) }" @update:model-value="value=>{topic=value;topicName=knownTopics.find(row=>row.thread_id===value)?.title||'';}" />
    <p class="text-xs text-ink-gray-5">Topics appear after Relay observes them or creates them. Use a topic ID below if it has not been observed yet.</p>
    <FormControl label="Topic name" v-model="topicName" /><Button
      label="Create topic"
      :disabled="busy || !info?.is_forum || !topicName.trim()"
      @click="
        run(async () => {
          topic = String(
            (await operation('topics.create', { name: topicName }))
              .message_thread_id,
          );
          notice = 'Topic created';
        })
      "
    /><FormControl label="Topic ID" v-model="topic" :disabled="busy" />
    <div class="flex flex-wrap gap-2">
      <Button
        label="Rename topic"
        :disabled="busy || !topic || !topicName"
        @click="run(() => topicAction('topics.edit'))"
      /><Button
        label="Close topic"
        :disabled="busy || !topic"
        @click="run(() => topicAction('topics.close'))"
      /><Button
        label="Reopen topic"
        :disabled="busy || !topic"
        @click="run(() => topicAction('topics.reopen'))"
      />
      <Button label="Unpin topic messages" :disabled="busy || !topic || !info?.is_forum" @click="run(() => topicAction('topics.unpin_all'))" />
      <Button label="Delete topic…" :disabled="busy || !topic || !info?.is_forum" @click="deleting=!deleting;confirmation=''" />
    </div>
    <form v-if="deleting" class="space-y-2 rounded border p-3" @submit.prevent="removeTopic">
      <p class="text-sm">Deleting this topic removes its messages in Telegram. Type topic ID {{ topic }} to confirm.</p>
      <FormControl label="Confirm topic ID" v-model="confirmation" :disabled="busy" />
      <Button type="submit" label="Delete this topic" :disabled="busy || confirmation!==topic" />
    </form>
    <details v-if="info?.is_forum" class="rounded border p-3 space-y-3">
      <summary class="text-sm font-medium cursor-pointer">General topic</summary>
      <FormControl label="General topic name" v-model="generalName" :maxlength="128" :disabled="busy" />
      <div class="flex flex-wrap gap-2">
        <Button label="Rename general topic" :disabled="busy || !generalName.trim()" @click="general('edit')" />
        <Button label="Close general topic" :disabled="busy" @click="general('close')" />
        <Button label="Reopen general topic" :disabled="busy" @click="general('reopen')" />
        <Button label="Hide general topic" :disabled="busy" @click="general('hide')" />
        <Button label="Show general topic" :disabled="busy" @click="general('unhide')" />
        <Button label="Unpin general-topic messages" :disabled="busy" @click="general('unpin_all')" />
      </div>
    </details>
  </div>
</template>
