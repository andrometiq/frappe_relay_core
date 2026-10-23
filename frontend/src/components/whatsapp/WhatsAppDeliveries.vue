<script setup>
import { inject } from "vue";
import { Button, FormControl, Badge } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import BusinessRecordPicker from "../BusinessRecordPicker.vue";
import { whatsappKey } from "../../composables/whatsapp/context";
const {
  deliveries,
  deliveryCursor,
  busy,
  error,
  text,
  template,
  supported,
  loadDeliveries,
  cancelDelivery,
} = inject(whatsappKey);
</script>
<template>
  <section class="workflow-card">
    <div class="flex gap-2">
      <Button
        label="Load deliveries"
        :disabled="busy || !supported"
        @click="loadDeliveries()"
      /><Button
        label="First page"
        :disabled="busy"
        @click="
          deliveryCursor = '';
          loadDeliveries();
        "
      /><Button
        label="Next"
        :disabled="busy || deliveries.length < 50"
        @click="loadDeliveries(true)"
      />
    </div>
    <div
      v-for="d in deliveries"
      :key="d.id"
      class="flex items-center gap-3 border-b py-3"
    >
      <span class="text-sm">#{{ d.id }}</span
      ><Badge :label="d.delivery_status || d.state" /><span
        class="text-xs text-ink-gray-5 flex-1"
        >{{ d.error }}</span
      ><Button
        v-if="d.state === 'queued'"
        label="Cancel"
        :disabled="busy"
        @click="cancelDelivery(d.id)"
      />
    </div>
  </section>
</template>
