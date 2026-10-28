<script setup>
import { useLoadMore } from '../composables/useLoadMore'
import { ref, onMounted } from "vue";
import { Button, Badge, ErrorMessage, FormControl } from "@relay/ui";
import RelaySelect from "./RelaySelect.vue";
import { coreApi } from "../services/coreApi";
import { useRealtimeRefresh } from "../composables/useRealtimeRefresh";
import { useTask } from "../composables/useTask";
const metadata = ref(null);
const syncLabels = { ready: "Up to date", failed: "Last refresh failed", syncing: "Synchronization pending", not_synced: "Not synchronized yet", stale: "Refresh overdue" };
async function metadataStatus() {
  metadata.value = await coreApi("whatsapp.metadata_status");
}
const { busy, error, run } = useTask(),
  channel = ref("WhatsApp"),
  rows = ref([]),
  cursor = ref(null),
  more = ref(false),
  resolving = ref(null), actionId = ref(null),
  outcome = ref("submitted"),
  note = ref(""), providerId = ref("");

async function load(next = false) {
  const after = next ? rows.value.at(-1)?.id : null;
  const page = await coreApi(
    "delivery.page",
    { channel: channel.value, after },
    true,
  );
  rows.value = [...(next ? rows.value : []), ...(page.deliveries || [])];
  cursor.value = after;
  more.value = page.more ?? page.deliveries?.length === 50;
}
async function cancel(id) {
  await coreApi(
    "delivery.page",
    { channel: channel.value, cancel_id: id },
    true,
  );
  await load();
}
async function resolve() {
  await coreApi(
    "delivery.resolve",
    { delivery_id: resolving.value, outcome: outcome.value, note: note.value, channel: channel.value, provider_id: providerId.value },
    true,
  );
  resolving.value = null;
  note.value = "";
  await load();
}
onMounted(() => run(async () => { await load(); await metadataStatus(); }));
useRealtimeRefresh([], ["messages"], () => run(() => load()));
const moreSentinel = useLoadMore({ loading: busy, hasMore: more, error: error, load: () => run(() => load(true)) })
</script>
<template>
  <section class="page-body space-y-5">
    <div>
      <p class="text-sm text-ink-gray-5 mt-2">
        Track queued and submitted messages. Check uncertain outcomes before
        sending again.
      </p>
    </div>
    <div class="flex flex-wrap items-end gap-3">
      <Button
        label="Refresh deliveries"
        :loading="busy"
        @click="run(() => load())"
      /><Button
        v-if="cursor"
        label="First deliveries"
        :disabled="busy"
        @click="run(() => load())"
      />
    </div>
    <Button
      v-if="channel === 'WhatsApp'"
      label="Check WhatsApp sync"
      :disabled="busy"
      @click="run(metadataStatus)"
    />
    <section v-if="metadata && channel === 'WhatsApp'" class="workflow-card space-y-2" aria-label="WhatsApp synchronization">
      <h3 class="font-medium">Profile and template synchronization</h3>
      <p role="status">{{ syncLabels[metadata.status] }}</p>
      <p class="text-sm">Last successful refresh: {{ metadata.last_success || "Never" }}</p>
      <p class="text-sm">Last attempt: {{ metadata.last_attempt || "Not yet attempted" }}</p>
      <p class="text-sm">{{ metadata.template_count }} cached templates{{ metadata.truncated ? " · Partial snapshot" : "" }}</p>
      <p v-if="metadata.status !== 'ready'" class="text-sm text-ink-gray-5">Check the account’s scheduled metadata sync and channel connection in Hub. This check reads saved results.</p>
    </section>
    <ErrorMessage :message="error" />
    <p v-if="busy" role="status">Loading / updating deliveries…</p>
    <div class="workflow-card">
      <article
        v-for="row in rows"
        :key="row.id"
        class="flex flex-wrap items-center gap-3 border-b py-3"
      >
        <details class="text-sm"><summary>Delivery reference</summary>{{ row.id }}</details
        ><span class="text-sm">{{ row.operation || "WhatsApp" }}</span
        ><Badge :label="row.delivery_status || row.state" /><span
          class="text-xs text-ink-gray-5 flex-1"
          >{{ row.error }}</span
        ><Button
          v-if="row.state === 'queued'"
          label="Cancel delivery"
          :disabled="busy"
          @click="actionId = row.id; run(() => cancel(row.id))"
        /><Button
          v-if="row.state === 'uncertain'"
          label="Resolve outcome"
          :disabled="busy"
          @click="
            resolving = row.id;
            note = ''; providerId = ''; outcome = 'submitted';
          "
        />
        <ErrorMessage v-if="actionId === row.id" :message="error" />
      </article>
      <p v-if="!rows.length && !busy" class="text-sm text-ink-gray-5">
        No deliveries on this page.
      </p>
    </div>
    <form
      v-if="resolving"
      class="workflow-card space-y-3"
      @submit.prevent="run(resolve)"
    >
      <h3>Resolve delivery #{{ resolving }}</h3>
      <p class="text-sm">
        Check the provider's message history first. Record what you verified;
        this action does not send a message.
      </p>
      <RelaySelect
        label="Verified outcome"
        v-model="outcome"
        :options="[
          { label: 'Provider accepted the message', value: 'submitted' },
          { label: 'Provider did not accept the message', value: 'rejected' },
        ]"
      /><FormControl v-if="channel === 'WhatsApp' && outcome === 'submitted'" label="Provider message ID (required except reactions)" v-model="providerId" />
      <FormControl
        type="textarea"
        label="Verification evidence"
        v-model="note"
      />
      <ErrorMessage :message="error" />
      <div class="flex gap-2">
        <Button
          type="submit"
          label="Record resolution"
          :disabled="busy || note.trim().length < 10 || note.length > 2000"
        /><Button
          label="Close resolution"
          :disabled="busy"
          @click="resolving = null"
        />
      </div>
    </form>
    <div v-if="more" ref="moreSentinel" class="h-px" aria-hidden="true" />
  </section>
</template>
