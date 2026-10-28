<script setup>
import { useLoadMore } from '../../composables/useLoadMore'
import { businessScope } from "../../services/businessScope.js";
import { ref, watch, computed, onBeforeUnmount } from "vue";
import { Button, ErrorMessage } from "@relay/ui";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import RemoteLinkField from "../fields/RemoteLinkField.vue";
import ChatPanel from "./ChatPanel.vue";
import { coreApi } from "../../services/coreApi";
import { stableSubmission } from "../../services/submission";
const props = defineProps({
  contact: String,
  businessDoctype: String,
  businessName: String,
  messages: { type: Array, default: () => [] },
});
const emit = defineEmits(["close", "open", "clear-messages", "added"]);
const rows = ref([]),
  body = ref(""),
  error = ref(""),
  busy = ref(false),
  more = ref(false),
  before = ref(null),
  reply = ref(null),
  editing = ref(null);
const assignedTo=ref(''),mentions=ref([]);
const colleagueField=computed(()=>({method:'collaboration.colleagues',params:{contact:props.contact},readOnly:busy.value}));
function selectMentions(values){
 if(values.length>10){error.value='Choose at most 10 colleagues';return}
 mentions.value=values;
}
let generation = 0, loadGeneration=0, deferredRefresh=false;
const olderLoaded=ref(false),updatesAvailable=ref(false);
async function refreshNotes(){
 if(busy.value){deferredRefresh=true;return}
 if(olderLoaded.value){updatesAvailable.value=true;return}
 const current=generation;
 try{await load()}catch(e){if(current===generation)error.value=e.message}
}
useRealtimeRefresh([],['comments'],refreshNotes);
watch(busy,value=>{if(!value&&deferredRefresh){deferredRefresh=false;refreshNotes()}});
onBeforeUnmount(()=>{++generation;++loadGeneration});
async function load(older = false) {
  const current = generation, request=++loadGeneration;
  const result = await coreApi("collaboration.comments", {
    contact: props.contact,
    ...(older ? { before: before.value } : {}),
  });
  if (current !== generation || request!==loadGeneration) return;
  rows.value = older
    ? [...result.items, ...rows.value]
    : result.items;
  olderLoaded.value=older;updatesAvailable.value=false;
  more.value = result.more;
  before.value = result.before;
}
async function run(task) {
  if (busy.value) return;
  const ticket = generation;
  busy.value = true;
  error.value = "";
  try {
    await task();
  } catch (e) {
    if (ticket === generation) error.value = e.message;
  } finally {
    if (ticket === generation) busy.value = false;
  }
}
watch(
  () => props.contact,
  () => {
    ++generation;
    rows.value = [];olderLoaded.value=false;updatesAvailable.value=false;deferredRefresh=false;
    body.value = "";
    reply.value = null;
    editing.value = null;
    busy.value = false;
    assignedTo.value = "";
    mentions.value = [];
    run(async () => {
      await load();
    });
  },
  { immediate: true },
);
async function submit() {
  const ticket = generation;
  await run(async () => {
    if (editing.value)
      await coreApi(
        "collaboration.edit",
        { name: editing.value.name, body: body.value },
        true,
      );
    else {
      const payload = {
        ...businessScope(props),
        contact: props.contact,
        body: body.value,
        messages: props.messages.map((m) => m.name),
        reply_to: reply.value?.name,
        assigned_to: assignedTo.value || null,
        mentions: mentions.value,
      };
      await stableSubmission("relay-comment", payload, (key) =>
        coreApi("collaboration.add", { ...payload, request_key: key }, true),
      );
    }
    if (ticket !== generation) return;
    if (!editing.value) emit("added");
    body.value = "";
    editing.value = null;
    reply.value = null;
    assignedTo.value = "";
    mentions.value = [];
    emit("clear-messages");
    await load();
  });
}
function edit(row) {
  editing.value = row;
  reply.value = null;
  body.value = row.body;
}
function cancel() {
  editing.value = null;
  reply.value = null;
  body.value = "";
}
const notesViewport = ref(null)
const moreSentinel = useLoadMore({ loading: busy, hasMore: more, root: notesViewport, preserveScroll: true, error: error, load: () => run(() => load(true)) })
</script>
<template>
  <ChatPanel class="internal-notes" title="Internal notes" subtitle="Only your team sees these notes." @close="emit('close')">
    <ErrorMessage :message="error" />
    <div ref="notesViewport" class="notes-list">
      <Button v-if="updatesAvailable" label="New note updates" :disabled="busy" @click="run(()=>load())" />
      <div v-if="more" ref="moreSentinel" class="h-px" aria-hidden="true" />
      <article v-for="row in rows" :key="row.name">
        <div class="note-author">
          <strong>{{ row.author_name }}</strong
          ><time>{{ row.creation }}</time>
        </div>
        <div v-if="row.assigned_to" class="note-task">
          {{ row.task_status === "Done" ? "Completed" : "Open task" }} ·
          {{ row.assigned_to }}
          <Button
            v-if="row.can_complete"
            :label="
              row.task_status === 'Done' ? 'Reopen task' : 'Complete task'
            "
            :disabled="busy"
            @click="
              run(async () => {
                await coreApi(
                  'collaboration.task_status',
                  {
                    name: row.name,
                    status: row.task_status === 'Done' ? 'Open' : 'Done',
                  },
                  true,
                );
                await load();
              })
            "
          />
        </div>
        <small v-if="row.mentions?.length"
          >Mentioned: {{ row.mentions.join(", ") }}</small
        ><small v-if="row.reply_to">Reply in discussion</small>
        <p>{{ row.deleted ? "Note removed" : row.body }}</p>
        <div v-if="!row.deleted" class="note-controls">
          <Button
            label="Reply to note"
            :disabled="busy"
            @click="
              reply = row;
              editing = null;
            "
          /><Button
            v-if="row.can_edit"
            label="Edit note"
            :disabled="busy"
            @click="edit(row)"
          /><Button
            v-if="row.can_edit"
            label="Remove note"
            :disabled="busy"
            @click="
              run(async () => {
                await coreApi(
                  'collaboration.edit',
                  { name: row.name, remove: 1 },
                  true,
                );
                await load();
              })
            "
          />
        </div>
        <button
          v-for="(message, index) in row.messages"
          :key="message"
          class="note-reference"
          @click="emit('open', message)"
        >
          View linked message {{ index + 1 }}
        </button>
      </article>
      <p v-if="!rows.length && !busy" class="notes-empty">
        Keep handoff details and team discussion here.
      </p>
    </div>
    <form @submit.prevent="submit">
      <div v-if="messages.length" class="note-selected">
        {{ messages.length }} messages linked
        <Button label="Clear linked messages" @click="emit('clear-messages')" />
      </div>
      <div v-if="reply || editing" class="note-selected">
        {{ editing ? "Editing note" : "Replying to " + reply.author_name
        }}<Button icon="x" aria-label="Cancel note reply or edit" title="Cancel note reply or edit" @click="cancel" />
      </div>
      <details v-if="!editing">
        <summary class="text-xs cursor-pointer">
          Assign a task or notify colleagues
        </summary>
        <div class="space-y-2 mt-2">
          <RemoteLinkField :field="{...colleagueField,label:'Task owner (optional)'}" v-model="assignedTo" />
          <RemoteLinkField :field="{...colleagueField,label:'Mention colleagues (up to 10)'}" :model-value="mentions" multiple @update:model-value="selectMentions" />
        </div>
      </details>
      <textarea
        v-model="body"
        aria-label="Internal note"
        placeholder="Write an internal note…"
        rows="3"
        maxlength="4000"
      /><Button
        :label="editing ? 'Save note' : 'Add internal note'"
        type="submit"
        variant="solid"
        :disabled="busy || !body.trim()"
      />
    </form>
  </ChatPanel>
</template>
<style scoped>
.notes-list {
  padding: 16px;
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.notes-list article {
  padding: 12px 0;
  @apply border-b border-outline-gray-2;
}
.note-author {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
}
.note-author time {
  font-size: 10px;
  @apply text-ink-gray-5;
}
.notes-list article p {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 13px;
  margin: 8px 0;
}
.note-controls {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.note-reference {
  display: block;
  @apply text-ink-blue-3;
  font-size: 11px;
  margin-top: 5px;
}
.notes-empty {
  font-size: 13px;
  @apply text-ink-gray-5;
}
.internal-notes form {
  @apply border-t border-outline-gray-2;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.internal-notes textarea {
  @apply border border-outline-gray-2 bg-surface-gray-1 text-ink-gray-8;
  border-radius: 7px;
  padding: 9px;
  resize: vertical;
  max-height: 180px;
  font-size: 13px;
}
.note-task {
  font-size: 11px;
  margin-top: 8px;
  padding: 6px;
  @apply bg-surface-gray-2;
  border-radius: 5px;
}
.note-selected {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
}
</style>
