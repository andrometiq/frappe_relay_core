<script setup>
import { useLoadMore } from '../../composables/useLoadMore'
import { ref, watch, onBeforeUnmount } from "vue";
import { Button, ErrorMessage } from "@relay/ui";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import ChatPanel from "./ChatPanel.vue";
import { coreApi } from "../../services/coreApi";
import { dateTime } from "../relativeTime";
// The list of notes for one chat. New notes and replies are written in the composer's Internal note mode.
const props = defineProps({ contact: String });
const emit = defineEmits(["close", "open", "reply", "add"]);
const rows = ref([]),
  draft = ref(""),
  error = ref(""),
  busy = ref(false),
  more = ref(false),
  before = ref(null),
  editing = ref(null);
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
    editing.value = null;
    busy.value = false;
    run(async () => {
      await load();
    });
  },
  { immediate: true },
);
function edit(row) {
  editing.value = row.name;
  draft.value = row.body;
}
async function save() {
  await run(async () => {
    await coreApi("collaboration.edit", { name: editing.value, body: draft.value }, true);
    editing.value = null;
    await load();
  });
}
const notesViewport = ref(null)
const moreSentinel = useLoadMore({ loading: busy, hasMore: more, root: notesViewport, preserveScroll: true, error: error, load: () => run(() => load(true)) })
</script>
<template>
  <ChatPanel class="internal-notes" title="Internal notes" subtitle="Only your team sees these notes." @close="emit('close')">
    <ErrorMessage :message="error" />
    <div ref="notesViewport" class="notes-list">
      <Button label="Add note" icon-left="lock" @click="emit('add')" />
      <Button v-if="updatesAvailable" label="New note updates" :disabled="busy" @click="run(()=>load())" />
      <div v-if="more" ref="moreSentinel" class="h-px" aria-hidden="true" />
      <article v-for="row in rows" :key="row.name">
        <div class="note-author">
          <strong>{{ row.author_name }}</strong
          ><time>{{ dateTime(row.creation) }}</time>
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
        <form v-if="editing === row.name" class="note-edit" @submit.prevent="draft.trim() && save()">
          <textarea v-model="draft" aria-label="Edit note" rows="3" maxlength="4000" :readonly="busy" />
          <div class="note-controls">
            <Button label="Cancel" variant="ghost" :disabled="busy" @click="editing = null" />
            <Button type="submit" label="Save note" variant="solid" :loading="busy" :disabled="!draft.trim()" :title="draft.trim() ? undefined : 'Type a note first'" />
          </div>
        </form>
        <p v-else>{{ row.deleted ? "Note removed" : row.body }}</p>
        <div v-if="!row.deleted && editing !== row.name" class="note-controls">
          <Button
            label="Reply to note"
            :disabled="busy"
            @click="emit('reply', row)"
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
        No notes yet.
      </p>
    </div>
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
.note-edit {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 8px 0;
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
</style>
