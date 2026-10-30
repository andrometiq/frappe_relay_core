<script setup>
import { dateTime } from '../relativeTime'
import { useLoadMore } from '../../composables/useLoadMore'
import { businessScope } from "../../services/businessScope.js";
import { ref, computed, watch, onBeforeUnmount } from "vue";
import { Button, Dialog, FormControl, ErrorMessage } from "@relay/ui";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import RelaySelect from "../RelaySelect.vue";
import { randomUUID } from "../../services/crypto.js";
import { coreApi } from "../../services/coreApi";
const props = defineProps({
  contact: String,
  businessDoctype: String,
  businessName: String,
  messages: { type: Array, default: () => [] },
});
const emit = defineEmits(["close", "open"]);
const shown = ref(true),
  rows = ref([]),
  after = ref(null),
  busy = ref(false),
  error = ref(""),
  draft = ref(null),
  notice = ref("");
watch(shown, (v) => {
  if (!v) emit("close");
});
let generation=0,requestGeneration=0,deferred=false;
const updatesAvailable=ref(false);
async function refreshTopics(){
 if(busy.value){deferred=true;return}
 if(draft.value){updatesAvailable.value=true;return}
 await load();
}
useRealtimeRefresh([],['topics'],refreshTopics);
watch(busy,value=>{if(!value&&deferred){deferred=false;refreshTopics()}});
onBeforeUnmount(()=>{++generation;++requestGeneration});
const candidates = computed(() => {
  const known = new Map(props.messages.map((m) => [m.name, m]));
  for (const name of draft.value?.messages || [])
    if (!known.has(name))
      known.set(name, { name, content: "Earlier message — open to view" });
  return [...known.values()];
});
async function load(more = false) {
  const current=generation,request=++requestGeneration;
  busy.value = true;
  error.value = "";
  try {
    const result = await coreApi("topics.directory", {
      contact: props.contact,
      ...(more ? { after: after.value } : {}),
    });
    if(current!==generation||request!==requestGeneration)return;
    updatesAvailable.value=false;
    rows.value = more ? [...rows.value, ...result.items] : result.items;
    after.value = result.next;
  } catch (e) {
    if(current===generation&&request===requestGeneration)error.value = e.message;
  } finally {
    if(current===generation&&request===requestGeneration)busy.value = false;
  }
}
function edit(row) {
  error.value = "";
  notice.value = "";
  draft.value = row
    ? { ...row, messages: [...row.messages] }
    : { request_key: randomUUID(), title: "", summary: "", category: "", status: "Open", messages: [] };
}
function toggle(name, checked) {
  const names = new Set(draft.value.messages);
  checked ? names.add(name) : names.delete(name);
  draft.value.messages = [...names];
}
async function save() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  const d = draft.value,current=generation;
  try {
    await coreApi(
      "topics.save",
      {
        contact: props.contact,
        name: d.name,
        request_key: d.request_key,
        values: {
          ...businessScope(d.name ? { businessDoctype: d.business_doctype, businessName: d.business_name } : props),
          title: d.title,
          summary: d.summary,
          category: d.category,
          status: d.status,
          messages: d.messages,
          modified: d.modified,
        },
      },
      true,
    );
    if(current!==generation)return;
    draft.value = null;
    await load();
    notice.value = "Topic saved.";
  } catch (e) {
    if(current===generation)error.value = e.message;
  } finally {
    if(current===generation)busy.value = false;
  }
}
watch(
  () => props.contact,
  () => {
    ++generation;++requestGeneration;deferred=false;updatesAvailable.value=false;rows.value=[];after.value=null;busy.value=false;
    draft.value = null;
    load();
  },
  { immediate: true },
);
const moreSentinel = useLoadMore({ loading: busy, hasMore: after, error: error, load: () => load(true) })
</script>
<template>
  <Dialog
    v-model="shown"
    :options="{ title: 'Conversation topics', size: 'xl' }"
    ><template #body-content>
      <div class="space-y-4 topic-content">
        <p class="text-sm text-ink-gray-5">
          Keep related messages together and track what still needs attention.
        </p>
        <ErrorMessage :message="error" />
        <p v-if="updatesAvailable" role="status" class="rounded p-3 bg-surface-gray-2 text-ink-gray-7">Topics may have changed. Your edits are kept. Cancel editing and refresh the list to review the latest version.</p>
        <p v-if="notice" role="status" class="text-sm">{{ notice }}</p>
        <form v-if="draft" class="space-y-4" @submit.prevent="save">
          <FormControl
            v-model="draft.title"
            label="Title"
            :maxlength="140"
            :disabled="busy"
            required
          />
          <FormControl
            v-model="draft.summary"
            type="textarea"
            label="Summary"
            :disabled="busy"
            :maxlength="10000"
          />
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <FormControl
              v-model="draft.category"
              label="Category"
              :maxlength="140"
              :disabled="busy"
            /><RelaySelect
              v-model="draft.status"
              label="Status"
              :options="['Open', 'Waiting', 'Resolved', 'Archived']"
              :disabled="busy"
            />
          </div>
          <fieldset :disabled="busy">
            <legend class="text-sm font-medium mb-2">
              Messages · {{ draft.messages.length }} selected
            </legend>
            <p class="text-xs text-ink-gray-5 mb-2">
              Choose from the loaded conversation. Existing earlier selections
              are retained. A message can belong to one topic.
            </p>
            <div class="topic-messages">
              <div
                v-for="message in candidates"
                :key="message.name"
                class="flex gap-3 py-2 border-b border-outline-gray-1"
              >
                <label class="topic-check" :for="'topic-' + message.name">
                <input
                  type="checkbox"
                  :id="'topic-' + message.name"
                  :checked="draft.messages.includes(message.name)"
                  @change="toggle(message.name, $event.target.checked)"
                />
                </label>
                <label
                  :for="'topic-' + message.name"
                  class="flex-1 min-w-0 text-sm"
                  ><span class="block text-xs text-ink-gray-5"
                    >{{ message.direction || "History" }} ·
                    {{
                      dateTime(message.sent_at || message.creation) || 'Message'
                    }}</span
                  >{{ (message.content || "Attachment").slice(0, 250) }}</label
                >
                <Button
                  label="View message"
                  icon="external-link"
                  @click="
                    emit('open', message.name);
                    shown = false;
                  "
                />
              </div>
            </div>
          </fieldset>
          <p class="text-xs text-ink-gray-5">
            Your edits are preserved when automation runs again. To release a
            message for another topic, uncheck it and save.
          </p>
          <div class="flex gap-2">
            <Button
              label="Save topic"
              type="submit"
              variant="solid"
              :loading="busy"
              :disabled="!draft.title.trim() || draft.messages.length > 500"
            /><Button label="Cancel" :disabled="busy" @click="draft = null" />
          </div>
        </form>
        <template v-else>
          <div class="flex gap-2">
            <Button
              label="New topic"
              icon-left="plus"
              :disabled="busy"
              @click="edit()"
            /><Button label="Refresh topics" :loading="busy" @click="load()" />
          </div>
          <p v-if="!rows.length && !busy" class="text-sm text-ink-gray-5">
            No topics yet. Create one to organize this conversation.
          </p>
          <article
            v-for="topic in rows"
            :key="topic.name"
            class="rounded-lg border border-outline-gray-2 p-3 space-y-2"
          >
            <div class="flex justify-between gap-3">
              <h3 class="font-medium text-sm">{{ topic.title }}</h3>
              <span class="text-xs text-ink-gray-5">{{ topic.status }}</span>
            </div>
            <p v-if="topic.summary" class="text-sm whitespace-pre-wrap">
              {{ topic.summary }}
            </p>
            <p class="text-xs text-ink-gray-5">
              {{ topic.category ? topic.category + " · " : ""
              }}{{ topic.message_count }} messages ·
              {{ topic.human_edited ? "Edited by your team" : topic.source }}
            </p>
            <div class="flex gap-2">
              <Button
                label="Edit topic"
                :disabled="busy"
                @click="edit(topic)"
              /><Button
                v-if="topic.messages.length"
                label="View first message"
                @click="
                  emit('open', topic.messages[0]);
                  shown = false;
                "
              />
            </div>
          </article>
          <div v-if="after" ref="moreSentinel" class="h-px" aria-hidden="true" />
        </template>
      </div> </template
  ></Dialog>
</template>
<style scoped>
.topic-content {
  overflow-wrap: anywhere;
}
.topic-messages {
  max-height: 280px;
  overflow: auto;
}
.topic-messages input {
  margin-top: 5px;
  align-self: start;
}
</style>
