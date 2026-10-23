<script setup>
import { ref, onMounted } from "vue";
import { Button, ErrorMessage } from "@relay/ui";
import RelayForm from "./RelayForm.vue";
import { coreApi } from "../services/coreApi";
import { useTask } from "../composables/useTask";
const { busy, error, notice, run } = useTask(),
  rows = ref([]),
  next = ref(null),
  draft = ref(null),
  editing = ref(null);
const link = (name, label, kind, required = false) => ({
  name,
  label,
  kind,
  type: "RemoteLink",
  method: "automation.settings.references",
  required,
});
const fields = [
  link("channel", "Channel", "channel", true),
  link("provider", "Primary provider", "provider", true),
  link("fallback_provider", "Fallback provider", "provider"),
  link("execution_user", "Execution user", "execution_user", true),
  link("business_doctype", "Business type", "business_doctype", true),
  {
    name: "mode",
    label: "Mode",
    type: "Select",
    options: ["Shadow", "Automatic"],
    required: true,
  },
  {
    name: "daily_limit",
    label: "Daily provider attempt limit",
    type: "Int",
    required: true,
  },
  { name: "enabled", label: "Enabled", type: "Check" },
  { name: "allow_report", label: "Allow communication reports", type: "Check" },
  { name: "allow_ticket", label: "Allow ticket creation", type: "Check" },
  { name: "allow_reply", label: "Allow approved replies", type: "Check" },
  { name: "allow_images", label: "Allow image analysis", type: "Check" },
  { name: "allow_voice", label: "Allow voice transcription", type: "Check" },
  link("transcription_provider", "Voice transcription provider", "provider"),
  {
    name: "instructions",
    label: "Instructions",
    type: "Small Text",
    wide: true,
  },
  {
    name: "reply_ids",
    label: "Approved reply IDs (one per line)",
    type: "Small Text",
    wide: true,
  },
  link("fallback_reply", "Fallback reply", "reply"),
];
async function load(after = null) {
  const result = await coreApi("automation.settings.policies", { after });
  rows.value = result.items;
  next.value = result.next;
}
function edit(row) {
  editing.value = row?.name || null;
  draft.value = row
    ? Object.fromEntries(fields.map((field) => [field.name, row[field.name]]))
    : {
        enabled: 0,
        mode: "Shadow",
        daily_limit: 100,
        allow_ticket: 0,
        allow_reply: 0,
      };
  error.value = "";
  notice.value = "";
}
async function save() {
  await coreApi(
    "automation.settings.save_policy",
    { values: draft.value, name: editing.value },
    true,
  );
  draft.value = null;
  await load();
  notice.value = "Automation policy saved";
}
onMounted(() => run(() => load()));
</script>
<template>
  <section class="workflow-card space-y-4">
    <div class="flex flex-wrap gap-3 items-center">
      <h2 class="text-lg font-medium">Automation policies</h2>
      <Button label="Add policy" :disabled="busy" @click="edit(null)" /><Button
        label="First policies"
        :disabled="busy"
        @click="run(() => load())"
      />
    </div>
    <p class="text-sm text-ink-gray-5">
      Shadow mode records decisions for review. Automatic mode runs enabled
      actions using the execution user's permissions. Each provider attempt
      counts toward the daily limit.
    </p>
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="!rows.length && !busy" class="text-sm">No policies configured.</p>
    <button
      v-for="row in rows"
      :key="row.name"
      class="w-full text-left rounded border p-3 hover:bg-surface-gray-2"
      :disabled="busy"
      @click="edit(row)"
    >
      {{ row.channel }} · {{ row.mode }} ·
      {{ row.enabled ? "Enabled" : "Disabled" }}
    </button>
    <Button
      v-if="next"
      label="Next policies"
      :disabled="busy"
      @click="run(() => load(next))"
    />
    <RelayForm
      v-if="draft"
      :key="editing || 'new'"
      v-model="draft"
      :fields="fields"
      :busy="busy"
      label="Save policy"
      @submit="run(save)"
      ><template #actions
        ><Button
          label="Cancel policy edit"
          :disabled="busy"
          @click="draft = null" /></template
    ></RelayForm>
  </section>
</template>
