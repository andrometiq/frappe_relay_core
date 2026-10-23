<script setup>
import { ref, watch } from "vue";
import { Button, ErrorMessage, Dialog } from "@relay/ui";
import { coreApi } from "../../services/coreApi";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
const props = defineProps({ contact: String });
const emit = defineEmits(["close", "open"]);
const shown = ref(true),
  rows = ref([]),
  before = ref(null),
  busy = ref(false),
  error = ref(""),
  notice = ref(""),
  retrying = ref(null);
watch(shown, (value) => {
  if (!value) emit("close");
});
const statusLabel=value=>({Dispatching:'Sending',Submitted:'Sent',Uncertain:'Unconfirmed',Rejected:'Failed'})[value]||value;
let generation = 0;
let refreshPending = false;
useRealtimeRefresh([], ['message_actions'], async () => {
  if (busy.value) { refreshPending = true; return; }
  await load(false, true);
});
watch(busy, value => {
  if (!value && refreshPending) {
    refreshPending = false;
    load(false, true);
  }
});
async function load(older = false, preserveDepth = false) {
  const current = ++generation;
  busy.value = true;
  error.value = "";
  try {
    let result = await coreApi("messaging.actions", {
      contact: props.contact,
      ...(older && before.value ? { before: before.value } : {}),
    });
    if (current !== generation) return;
    const targetCount = preserveDepth ? Math.min(rows.value.length, 100) : 0;
    let pages = 1;
    while (pages < 5 && result.items.length < targetCount && result.before) {
      pages++;
      const next = await coreApi("messaging.actions", {contact: props.contact, before: result.before});
      if (current !== generation) return;
      result = {items: [...result.items, ...next.items], before: next.before};
    }
    if (current !== generation) return;
    rows.value = older
      ? [...rows.value, ...result.items].slice(-100)
      : result.items;
    before.value = result.before;
  } catch (e) {
    if (current === generation) error.value = e.message;
  } finally {
    if (current === generation) busy.value = false;
  }
}
async function act(row, retry = false) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await coreApi(
      retry ? "messaging.retry" : "messaging.reconcile",
      { action: row.name },
      true,
    );
    notice.value = "Message status: " + statusLabel(result.status);
    retrying.value = null;
    await load();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
watch(
  () => props.contact,
  () => {
    retrying.value = null;
    load();
  },
  { immediate: true },
);
</script>
<template>
  <Dialog
    v-model="shown"
    :options="{ title: 'Message activity', size: 'lg' }"
    ><template #body-content
      ><div class="space-y-4">
        <p class="text-sm text-ink-gray-5">
          Queued and unconfirmed sends are checked against their original
          delivery record. Only confirmed rejected sends can be retried.
        </p>
        <Button
          label="Refresh activity"
          :loading="busy"
          @click="load()"
        /><ErrorMessage :message="error" />
        <p v-if="busy" role="status">Loading / updating message activity…</p>
        <p v-if="notice" role="status">{{ notice }}</p>
        <p v-if="!rows.length && !busy">
          No outgoing actions in this conversation.
        </p>
        <article
          v-for="row in rows"
          :key="row.name"
          class="border rounded-lg p-3 space-y-2"
        >
          <div class="flex justify-between gap-2 text-sm">
            <strong>{{ statusLabel(row.status) }}</strong
            ><time>{{ new Date(row.creation).toLocaleString() }}</time>
          </div>
          <p class="text-sm whitespace-pre-wrap break-words">
            {{ row.preview || row.operation }}
          </p>
          <p v-if="row.error" class="text-sm text-ink-gray-7" role="status">{{ row.error }}</p>
          <Button
            v-if="['Queued', 'Uncertain', 'Dispatching'].includes(row.status)"
            label="Check delivery"
            :disabled="busy"
            @click="act(row)"
          /><Button
            v-if="row.message"
            label="Open message"
            :disabled="busy"
            @click="
              emit('open', row.message);
              shown = false;
            "
          /><Button
            v-if="row.can_retry && retrying !== row.name"
            label="Review retry"
            :disabled="busy"
            @click="retrying = row.name"
          />
          <div v-if="retrying === row.name" class="space-y-2">
            <ErrorMessage :message="error" />
            <p class="text-sm">
              Send the content shown above again? The destination, permissions
              and reply window will be checked before submission.
            </p>
            <Button
              label="Retry rejected send"
              variant="solid"
              :disabled="busy"
              @click="act(row, true)"
            /><Button
              label="Cancel retry"
              :disabled="busy"
              @click="retrying = null"
            />
          </div>
        </article>
        <Button
          v-if="before"
          label="Earlier activity"
          :disabled="busy"
          @click="load(true)"
        /></div></template
  ></Dialog>
</template>
