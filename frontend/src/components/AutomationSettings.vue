<script setup>
import { ref, onMounted } from "vue";
import { Button, ErrorMessage } from "@relay/ui";
import RelayForm from "./RelayForm.vue";
import { coreApi } from "../services/coreApi";
import { useTask } from "../composables/useTask";
const { busy, error, notice, run } = useTask(),
  rows = ref([]),
  next = ref(null),
  editing = ref(null),
  draft = ref(null);
const fields = [
  {
    name: "provider",
    label: "Provider",
    type: "Select",
    options: ["OpenAI", "OpenRouter", "Gemini", "Anthropic", "GLM"],
    required: true,
  },
  { name: "model", label: "Model identifier", type: "Data", required: true },
  {
    name: "api_key",
    label: "API key (leave blank to keep saved key)",
    type: "Password",
  },
  { name: "enabled", label: "Enabled", type: "Check" },
];
async function load(after = null) {
  const result = await coreApi("automation.settings.providers", { after });
  rows.value = result.items;
  next.value = result.next;
}
function edit(row) {
  editing.value = row?.name || null;
  draft.value = row
    ? {
        provider: row.provider,
        model: row.model,
        enabled: row.enabled,
        api_key: "",
      }
    : { provider: "OpenAI", model: "", enabled: 0, api_key: "" };
}
async function save() {
  await coreApi(
    "automation.settings.save_provider",
    { ...draft.value, name: editing.value },
    true,
  );
  draft.value = null;
  notice.value = "Provider saved";
  await load();
}
onMounted(() => run(() => load()));
</script>
<template>
  <section class="workflow-card space-y-4">
    <div class="flex flex-wrap gap-3 items-center">
      <h2 class="text-lg font-medium">AI providers</h2>
      <Button
        label="Add AI provider"
        :disabled="busy"
        @click="edit(null)"
      /><Button
        label="First providers"
        :disabled="busy"
        @click="run(() => load())"
      />
    </div>
    <p class="text-sm text-ink-gray-5">
      Use the model identifier enabled for your provider account. Keys are
      stored encrypted and are never returned to the browser.
    </p>
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="space-y-2">
      <button
        v-for="row in rows"
        :key="row.name"
        class="w-full text-left rounded border p-3 hover:bg-surface-gray-2"
        :disabled="busy"
        @click="edit(row)"
      >
        {{ row.provider }} · {{ row.model }}
        <span class="text-xs">{{ row.enabled ? "Enabled" : "Disabled" }}</span>
      </button>
    </div>
    <Button
      v-if="next"
      label="Next providers"
      :disabled="busy"
      @click="run(() => load(next))"
    /><RelayForm
      v-if="draft"
      v-model="draft"
      :fields="fields"
      :busy="busy"
      label="Save AI provider"
      @submit="run(save)"
      ><template #actions
        ><Button
          label="Cancel provider edit"
          :disabled="busy"
          @click="draft = null" /></template
    ></RelayForm>
  </section>
</template>
