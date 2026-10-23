<script setup>
import { ref, watch, computed } from "vue";
import { Dialog, Button, FormControl, ErrorMessage } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import { coreApi } from "../../services/coreApi";
import { sha256Hex, randomUUID } from "../../services/crypto";
import { useTask } from "../../composables/useTask";
const props = defineProps({ modelValue: Boolean, source: Object });
const emit = defineEmits(["update:modelValue"]);
const { busy, error, notice, run } = useTask();
const rows = ref([]),
  next = ref(""),
  flow = ref(""),
  screens = ref([]),
  screen = ref(""),
  body = ref(""),
  cta = ref("Open form"),
  receipt = ref(null);
let requestKey = "",
  storageKey = "";
const choices = computed(() =>
  rows.value.map((row) => ({ value: row.id, label: row.name })),
);
const screenChoices = computed(() =>
  screens.value.map((row) => ({ value: row.id, label: row.title })),
);
async function load(after = "") {
  const result = await coreApi("meta_flows.choices", {
    message: props.source.name,
    after,
  });
  rows.value = after ? [...rows.value, ...result.items] : result.items;
  next.value = result.next;
}
async function select() {
  screens.value = [];
  screen.value = "";
  if (!flow.value) return;
  const result = await coreApi("meta_flows.screens", {
    message: props.source.name,
    flow_id: flow.value,
  });
  screens.value = result.items;
  screen.value = result.items[0]?.id || "";
}
watch(
  () => props.modelValue,
  (value) => {
    if (value) {
      receipt.value = null;
      flow.value = "";
      screen.value = "";
      screens.value = [];
      body.value = "";
      requestKey = "";
      run(() => load());
    }
  },
);
async function submit() {
  if (receipt.value) {
    receipt.value = await coreApi(
      "messaging.reconcile",
      { action: receipt.value.action },
      true,
    );
  } else {
    const intent = {
      message: props.source.name,
      id: flow.value,
      body: body.value,
      cta: cta.value,
      screen: screen.value,
    };
    storageKey = "relay-form:" + sha256Hex(JSON.stringify(intent));
    try {
      requestKey = sessionStorage.getItem(storageKey) || randomUUID();
      sessionStorage.setItem(storageKey, requestKey);
    } catch {
      requestKey = requestKey || randomUUID();
    }
    receipt.value = await coreApi(
      "messaging.send",
      {
        message: props.source.name,
        kind: "flow",
        quote: 0,
        request_key: requestKey,
        data: {
          id: flow.value,
          body: body.value,
          cta: cta.value,
          screen: screen.value,
          token: requestKey,
        },
      },
      true,
    );
  }
  const status = receipt.value.status;
  notice.value =
    status === "Submitted"
      ? "Form sent."
      : status === "Rejected"
        ? "Delivery was rejected. Review it under Deliveries."
        : "Delivery is not confirmed yet. Check its status before sending another form.";
  if (status === "Submitted" || status === "Rejected") {
    try {
      sessionStorage.removeItem(storageKey);
    } catch {}
  }
}
</script>
<template>
  <Dialog
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    :options="{ title: 'Send a WhatsApp form', size: 'lg' }"
    ><template #body-content>
      <form class="space-y-4" @submit.prevent="run(submit)">
        <ErrorMessage :message="error" />
        <p v-if="notice" role="status" class="text-sm">{{ notice }}</p>
        <p v-if="!rows.length && !busy" class="text-sm text-ink-gray-5">
          No published forms are available. A manager can publish one under
          Flows → WhatsApp forms.
        </p>
        <RelaySelect
          label="Form"
          v-model="flow"
          :options="choices"
          :disabled="busy || !!receipt"
          @update:model-value="run(select)"
        />
        <Button
          v-if="next"
          label="Load more forms"
          :disabled="busy || !!receipt"
          @click="run(() => load(next))"
        />
        <RelaySelect
          label="Starting screen"
          v-model="screen"
          :options="screenChoices"
          :disabled="busy || !!receipt"
        />
        <FormControl
          label="Message"
          type="textarea"
          v-model="body"
          :disabled="busy || !!receipt"
        />
        <FormControl
          label="Button label"
          v-model="cta"
          :disabled="busy || !!receipt"
        />
        <p class="text-xs text-ink-gray-5">
          The form goes to this conversation’s verified WhatsApp contact. The
          24-hour reply window must be open.
        </p>
        <Button
          v-if="!receipt || !['Submitted', 'Rejected'].includes(receipt.status)"
          :label="receipt ? 'Check delivery' : 'Send form'"
          type="submit"
          :loading="busy"
          :disabled="
            !receipt && (!flow || !screen || !body.trim() || !cta.trim())
          "
        />
      </form> </template
  ></Dialog>
</template>
