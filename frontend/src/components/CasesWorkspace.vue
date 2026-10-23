<script setup>
import { ref, onMounted } from "vue";
import { Button, FormControl, ErrorMessage } from "@relay/ui";
import RelaySelect from "./RelaySelect.vue";
import ConversationCases from "./messages/ConversationCases.vue";
import { coreApi } from "../services/coreApi";
const rows = ref([]),
  next = ref(null),
  query = ref(""),
  state = ref(""),
  busy = ref(false),
  error = ref(""),
  selected = ref(null);
async function load(more = false) {
  busy.value = true;
  error.value = "";
  try {
    const result = await coreApi("cases.workspace", {
      query: query.value,
      state: state.value,
      ...(more ? { after: next.value } : {}),
    });
    rows.value = more
      ? [...rows.value, ...result.items].slice(-200)
      : result.items;
    next.value = result.next;
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function close() {
  selected.value = null;
  load();
}
onMounted(() => load());
</script>
<template>
  <section class="space-y-4" aria-label="Cases workspace">
    <div>
      <h2 class="text-xl font-semibold">Cases</h2>
      <p class="text-sm text-ink-gray-5 mt-2">
        Track follow-ups and the evidence needed to complete them.
      </p>
    </div>
    <form class="flex flex-wrap gap-3 items-end" @submit.prevent="load()">
      <FormControl
        v-model="query"
        label="Search cases"
        type="search"
        :disabled="busy"
        :maxlength="80"
      /><RelaySelect
        v-model="state"
        label="State"
        :disabled="busy"
        :options="[
          { value: '', label: 'All states' },
          { value: 'open', label: 'Open' },
          { value: 'active', label: 'In progress' },
          { value: 'waiting', label: 'Waiting' },
          { value: 'done', label: 'Completed' },
          { value: 'cancelled', label: 'Cancelled' },
        ]"
      /><Button type="submit" label="Search cases" :loading="busy" />
    </form>
    <ErrorMessage :message="error" />
    <p v-if="!rows.length && !busy" class="text-sm text-ink-gray-5">
      No accessible cases on this page.
    </p>
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <article
        v-for="row in rows"
        :key="row.name"
        class="rounded-lg border border-outline-gray-2 p-4 space-y-3 min-w-0"
      >
        <h3 class="font-medium text-sm break-words">{{ row.title }}</h3>
        <p class="text-xs text-ink-gray-5">
          {{ row.priority }} · {{ row.stage.replaceAll("_", " ") }}
        </p>
        <div class="flex gap-2 flex-wrap">
          <Button label="Open case" @click="selected = row" /><a
            class="text-sm underline"
            :href="
              '#/messages?contact=' + encodeURIComponent(row.relay_contact)
            "
            >Conversation</a
          >
        </div>
      </article>
    </div>
    <Button
      v-if="next"
      label="More cases"
      :loading="busy"
      @click="load(true)"
    />
    <ConversationCases
      v-if="selected"
      :key="selected.name"
      :contact="selected.relay_contact"
      :initial-case="selected.name"
      @close="close"
    />
  </section>
</template>
