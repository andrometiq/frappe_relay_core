<script setup>
import UncertainCalls from "./UncertainCalls.vue";
import { ref, watch } from "vue";
import { Button, ErrorMessage, Badge } from "@relay/ui";
import { coreApi } from "../services/coreApi";
const recordings = ref({});
async function showRecordings(call) {
  try {
    recordings.value[call] = await coreApi("call_records.recordings", { call });
  } catch (e) {
    error.value = e.message;
  }
}
const props = defineProps({ contact: String });
const rows = ref([]),
  before = ref(null),
  busy = ref(false),
  error = ref("");
let generation = 0;
async function load(older = false) {
  const current = ++generation;
  busy.value = true;
  error.value = "";
  try {
    const result = await coreApi("call_records.history", {
      contact: props.contact,
      ...(older && before.value ? { before: before.value } : {}),
    });
    if (current !== generation) return;
    rows.value = older
      ? [...rows.value, ...result.items].slice(-150)
      : result.items;
    before.value = result.before;
  } catch (e) {
    if (current === generation) error.value = e.message;
  } finally {
    if (current === generation) busy.value = false;
  }
}
watch(
  () => props.contact,
  () => load(),
  { immediate: true },
);
</script>
<template>
  <UncertainCalls :contact="contact" />
  <section class="workflow-card space-y-3" aria-label="Call history">
    <div class="flex justify-between gap-3">
      <h2 class="font-semibold">Call history</h2>
      <Button label="Refresh call history" :loading="busy" @click="load()" />
    </div>
    <ErrorMessage :message="error" />
    <p v-if="!rows.length && !busy" class="text-sm text-ink-gray-5">
      No calls recorded{{ contact ? " for this conversation" : "" }}.
    </p>
    <article
      v-for="row in rows"
      :key="row.name"
      class="border-b py-3 space-y-2"
    >
      <div class="flex flex-wrap items-center gap-2">
        <a
          :href="'#/messages?contact=' + encodeURIComponent(row.relay_contact)"
          class="text-sm font-medium underline"
          >{{ row.display_name || row.relay_contact }}</a
        ><Badge :label="row.state" />
      </div>
      <p class="text-sm">
        {{ row.direction }} · {{ new Date(row.started_at).toLocaleString()
        }}<span v-if="row.duration">
          · {{ Math.floor(row.duration / 60) }}m {{ row.duration % 60 }}s</span
        >
      </p>
      <Button label="Recordings" @click="showRecordings(row.name)" />
      <div v-if="recordings[row.name]" class="text-sm space-y-2">
        <p v-if="!recordings[row.name].length">No archived recordings.</p>
        <a
          v-for="recording in recordings[row.name]"
          :key="recording.name"
          class="block underline"
          :href="
            '/api/method/relay_core.call_records.download_recording?name=' +
            encodeURIComponent(recording.name)
          "
          >Download recording ·
          {{ (recording.file_size / 1024 / 1024).toFixed(1) }} MiB ·
          {{ recording.uploaded_by }}</a
        >
      </div>
    </article>
    <Button
      v-if="before"
      label="Earlier calls"
      :disabled="busy"
      @click="load(true)"
    />
  </section>
</template>
