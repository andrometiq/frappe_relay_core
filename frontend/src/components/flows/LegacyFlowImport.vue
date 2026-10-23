<script setup>
import { ref, watch } from "vue";
import { Dialog, Button, FormControl, ErrorMessage } from "@relay/ui";
import { coreApi } from "../../services/coreApi";
const emit = defineEmits(["close", "import"]);
const shown = ref(true),
  text = ref(""),
  preview = ref(null),
  busy = ref(false),
  error = ref("");
watch(shown,value=>{if(!value)emit('close')});
async function file(event) {
  const f = event.target.files?.[0];
  if (!f) return;
  if (f.size > 200000) {
    error.value = "Choose a graph smaller than 200 KB.";
    return;
  }
  text.value = await f.text();
  preview.value = null;
}
async function review() {
  busy.value = true;
  error.value = "";
  preview.value = null;
  try {
    if (text.value.length > 200000)
      throw Error("Graph exceeds 200,000 characters.");
    JSON.parse(text.value);
    preview.value = await coreApi(
      "flows.service.preview_legacy",
      { graph: text.value },
      true,
    );
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <Dialog
    v-model="shown"
    :options="{ title: 'Import legacy flow', size: 'xl' }"
    @after-leave="emit('close')"
    ><template #body-content
      ><div class="space-y-4">
        <p class="text-sm text-ink-gray-5">
          Upload or paste the old flow graph. Review the converted steps before
          opening a new draft.
        </p>
        <label class="block text-sm"
          >Graph JSON file<input
            type="file"
            accept="application/json,.json"
            :disabled="busy"
            class="block mt-2 max-w-full"
            @change="file"
        /></label>
        <FormControl
          v-model="text"
          label="Legacy graph JSON"
          type="textarea"
          :rows="6"
          :disabled="busy"
          @update:model-value="preview = null"
        />
        <Button
          label="Preview conversion"
          :loading="busy"
          :disabled="!text.trim()"
          @click="review"
        /><ErrorMessage :message="error" />
        <template v-if="preview"
          ><p class="font-medium text-sm">
            {{ preview.nodes.length }} steps ·
            {{ preview.triggers.length }} triggers
          </p>
          <ul class="list-disc pl-5 text-sm space-y-1">
            <li v-for="warning in preview.warnings" :key="warning">
              {{ warning }}
            </li>
          </ul>
          <p v-if="preview.missing_actions.length" class="text-sm text-red-600">
            Missing business actions: {{ preview.missing_actions.join(", ") }}
          </p>
          <div
            class="max-h-64 overflow-auto rounded border border-outline-gray-2"
          >
            <ol class="divide-y divide-outline-gray-1">
              <li
                v-for="(node, index) in preview.nodes"
                :key="node.id"
                class="p-2 text-sm break-words"
              >
                <span class="text-ink-gray-5"
                  >{{ index + 1 }} · {{ node.kind }}</span
                >
                <p>{{ node.title || node.text || node.action || node.id }}</p>
              </li>
            </ol>
          </div>
          <Button
            label="Open disabled draft"
            variant="solid"
            :disabled="preview.missing_actions.length > 0"
            @click="
              emit('import', preview);
              emit('close');
            "
        /></template>
        <Button
          label="Cancel import"
          :disabled="busy"
          @click="emit('close')"
        /></div></template
  ></Dialog>
</template>
