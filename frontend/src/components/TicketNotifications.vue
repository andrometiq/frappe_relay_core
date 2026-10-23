<script setup>
import { ref, watch } from "vue";
import { Button, FormControl, ErrorMessage } from "@relay/ui";
import RelaySelect from "./RelaySelect.vue";
import { coreApi } from "../services/coreApi";
import { useTask } from "../composables/useTask";
const props = defineProps({ ticket: String });
const { busy, error, notice, run } = useTask(),
  query = ref(""),
  endpoint = ref(""),
  items = ref([]),
  next = ref(null),
  enabled = ref(false);
async function search(after = null) {
  const result = await coreApi("ticket_notifications.destinations", {
    query: query.value,
    after,
  });
  items.value = result.items;
  next.value = result.next;
}
async function load() {
  const row = await coreApi("ticket_notifications.subscription", {
    ticket: props.ticket,
  });
  endpoint.value = row.destination || "";
  enabled.value = !!row.enabled;
  await search();
}
async function save(value) {
  await coreApi(
    "ticket_notifications.subscribe",
    { ticket: props.ticket, endpoint: endpoint.value, enabled: value },
    true,
  );
  enabled.value = !!value;
  notice.value = value
    ? "Ticket notifications enabled"
    : "Ticket notifications disabled";
}
watch(
  () => props.ticket,
  () => run(load),
  { immediate: true },
);
</script>
<template>
  <section class="space-y-3 border-t pt-4">
    <h4 class="text-sm font-medium">Your ticket notifications</h4>
    <p class="text-sm text-ink-gray-5">
      Choose your own verified email or Telegram endpoint. Updates are sent when
      status or assignment changes.
    </p>
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="flex flex-wrap gap-2 items-end">
      <FormControl label="Find notification endpoint" v-model="query" /><Button
        label="Search endpoints"
        :disabled="busy"
        @click="run(() => search())"
      /><Button
        v-if="next"
        label="Next endpoints"
        :disabled="busy"
        @click="run(() => search(next))"
      />
    </div>
    <RelaySelect
      label="Notification endpoint"
      v-model="endpoint"
      :disabled="busy"
      :options="[
        ...(!items.some((row) => row.value === endpoint) && endpoint
          ? [{ value: endpoint, label: endpoint }]
          : []),
        ...items,
      ]"
    />
    <p v-if="!items.length && !busy" class="text-xs">
      No matching endpoints on this page. Your contact must have a verified
      email or Telegram address.
    </p>
    <div class="flex flex-wrap gap-2">
      <Button
        :label="enabled ? 'Update subscription' : 'Enable notifications'"
        :disabled="busy || !endpoint"
        @click="run(() => save(1))"
      /><Button
        v-if="enabled"
        label="Disable notifications"
        :disabled="busy"
        @click="run(() => save(0))"
      />
    </div>
  </section>
</template>
