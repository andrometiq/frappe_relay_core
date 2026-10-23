<script setup>
import { ref, onMounted } from "vue";
import { Button, FormControl, ErrorMessage, Badge, Dialog } from "@relay/ui";
import RelaySelect from "./RelaySelect.vue";
import { coreApi } from "../services/coreApi";
import { useTask } from "../composables/useTask";
const { busy, error, notice, run } = useTask();
const configured = ref(false),
  rows = ref([]),
  next = ref(""),
  draft = ref(null),
  jsonText = ref(""),
  validation = ref([]),
  confirm = ref(null);
const categories = [
  "SIGN_UP",
  "SIGN_IN",
  "APPOINTMENT_BOOKING",
  "LEAD_GENERATION",
  "CONTACT_US",
  "CUSTOMER_SUPPORT",
  "SURVEY",
  "OTHER",
].map((value) => ({ value, label: value.toLowerCase().replaceAll("_", " ") }));
const call = (operation, args = {}) =>
  coreApi("meta_flows.execute", { operation, arguments: args }, true);
async function load(after = "") {
  const result = await call("list", after ? { after } : {});
  rows.value = result.data || [];
  next.value = result.paging?.has_more
    ? result.paging?.cursors?.after || ""
    : "";
}
function fresh() {
  draft.value = {
    name: "",
    categories: ["OTHER"],
    status: "DRAFT",
    endpoint_uri: "",
  };
  jsonText.value = "";
  validation.value = [];
  error.value = "";
}
async function open(row) {
  draft.value = await call("get", { id: row.id });
  validation.value = draft.value.validation_errors || [];
  jsonText.value = "";
}
async function loadDefinition() {
  const result = await call("json", { id: draft.value.id });
  jsonText.value = result.flow_json
    ? JSON.stringify(result.flow_json, null, 2)
    : "";
  notice.value = result.flow_json
    ? "Current form definition loaded."
    : "This draft has no uploaded definition yet.";
}
async function save() {
  const value = draft.value;
  if (!value.name.trim()) throw Error("Enter a Flow name.");
  const result = await call(value.id ? "update" : "create", {
    ...(value.id ? { id: value.id } : {}),
    name: value.name,
    categories: value.categories,
    endpoint_uri: value.endpoint_uri || "",
  });
  if (!value.id) {
    if (!result.id)
      throw Error(
        "Creation was not confirmed. Refresh the list before trying again.",
      );
    value.id = result.id;
  }
  notice.value =
    "Flow saved as a draft. Upload its form definition before publishing.";
  await load();
}
async function upload() {
  let value;
  try {
    value = JSON.parse(jsonText.value);
  } catch {
    throw Error("Choose a valid Flow JSON file.");
  }
  if (!value || Array.isArray(value) || typeof value !== "object")
    throw Error("Flow JSON must be an object.");
  const result = await call("upload", { id: draft.value.id, flow_json: value });
  validation.value = result.validation_errors || [];
  notice.value = validation.value.length
    ? "Meta returned validation issues. Review them before publishing."
    : "Form definition uploaded.";
}
async function choose(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (file.size > 1048576) throw Error("Choose a JSON file up to 1 MiB.");
  jsonText.value = await file.text();
}
async function lifecycle() {
  const operation = confirm.value;
  confirm.value = null;
  await call(operation, { id: draft.value.id });
  notice.value =
    "Flow " +
    { publish: "published", deprecate: "retired", delete: "deleted" }[
      operation
    ] +
    ".";
  if (operation === "delete") draft.value = null;
  else await open(draft.value);
  await load();
}
onMounted(() =>
  run(async () => {
    configured.value = (await coreApi("meta_flows.workspace")).configured;
    if (configured.value) await load();
  }),
);
</script>
<template>
  <section class="space-y-5">
    <div class="flex flex-wrap items-center gap-2">
      <h2 class="text-xl font-semibold mr-auto">WhatsApp forms</h2>
      <Button
        label="Refresh"
        :disabled="busy || !configured"
        @click="run(() => load())"
      /><Button
        label="New form"
        :disabled="busy || !configured"
        @click="fresh"
      />
    </div>
    <p class="text-sm text-ink-gray-5">
      Manage forms that customers fill out inside WhatsApp. Drafts stay private
      until published.
    </p>
    <ErrorMessage :message="error" />
    <p v-if="notice" role="status" class="text-sm text-green-700">
      {{ notice }}
    </p>
    <p v-if="!configured && !busy" class="rounded-lg border p-5 text-sm">
      Connect a WhatsApp channel in Frappe Desk to manage forms.
    </p>
    <div
      v-if="configured"
      class="grid gap-5 lg:grid-cols-[minmax(220px,1fr)_minmax(0,2fr)]"
    >
      <div class="space-y-2">
        <p v-if="!rows.length && !busy" class="text-sm text-ink-gray-5">
          No WhatsApp forms yet.
        </p>
        <button
          v-for="row in rows"
          :key="row.id"
          class="w-full rounded-lg border p-3 text-left space-y-2"
          :class="{ 'bg-surface-gray-2': draft?.id === row.id }"
          :disabled="busy"
          @click="run(() => open(row))"
        >
          <span class="block font-medium break-words">{{ row.name }}</span
          ><Badge :label="row.status" /></button
        ><Button
          v-if="next"
          label="Next forms"
          :disabled="busy"
          @click="run(() => load(next))"
        />
      </div>
      <form
        v-if="draft"
        class="min-w-0 rounded-lg border p-4 space-y-4"
        @submit.prevent="run(save)"
      >
        <div class="flex justify-between gap-3">
          <h3 class="font-semibold">
            {{ draft.id ? "Form details" : "New form" }}
          </h3>
          <Badge :label="draft.status" />
        </div>
        <FormControl
          label="Name"
          v-model="draft.name"
          :disabled="busy || draft.status !== 'DRAFT'"
        />
        <RelaySelect
          label="Category"
          :model-value="draft.categories?.[0] || 'OTHER'"
          :options="categories"
          :disabled="busy || draft.status !== 'DRAFT'"
          @update:model-value="draft.categories = [$event]"
        />
        <FormControl
          label="Data endpoint (optional)"
          v-model="draft.endpoint_uri"
          placeholder="https://example.com/whatsapp/flow"
          :disabled="busy || draft.status !== 'DRAFT'"
        />
        <p class="text-xs text-ink-gray-5">
          A data endpoint is needed only when the form exchanges data with your
          server.
        </p>
        <Button
          v-if="draft.status === 'DRAFT'"
          label="Save draft"
          type="submit"
          :loading="busy"
        />
        <div
          v-if="draft.id && draft.status === 'DRAFT'"
          class="space-y-3 border-t pt-4"
        >
          <label class="block text-sm"
            >Form definition
            <input
              type="file"
              accept=".json,application/json"
              class="block mt-2 max-w-full text-sm"
              :disabled="busy"
              @change="run(() => choose($event))"
          /></label>
          <FormControl
            type="textarea"
            label="Flow JSON"
            v-model="jsonText"
            :disabled="busy"
            :rows="10"
            placeholder="Choose a JSON file or paste your form definition"
          />
          <Button
            label="Load current definition"
            :disabled="busy"
            @click="run(loadDefinition)"
          /><Button
            label="Upload definition"
            :disabled="busy || !jsonText.trim()"
            @click="run(upload)"
          />
        </div>
        <ul v-if="validation.length" class="space-y-2 text-sm text-red-700">
          <li v-for="(issue, index) in validation" :key="index">
            {{
              issue.error ||
              issue.message ||
              issue.error_type ||
              "Validation issue"
            }}
            {{ issue.line_start ? `(line ${issue.line_start})` : "" }}
          </li>
        </ul>
        <div v-if="draft.id" class="flex flex-wrap gap-2 border-t pt-4">
          <Button
            v-if="draft.status === 'DRAFT'"
            label="Publish"
            :disabled="busy || validation.length > 0"
            @click="confirm = 'publish'"
          /><Button
            v-if="draft.status === 'PUBLISHED'"
            label="Retire form"
            :disabled="busy"
            @click="confirm = 'deprecate'"
          /><Button
            v-if="draft.status === 'DRAFT'"
            label="Delete draft"
            theme="red"
            :disabled="busy"
            @click="confirm = 'delete'"
          />
        </div>
      </form>
      <p v-else class="text-sm text-ink-gray-5 p-5">
        Select a form to review it, or create a draft.
      </p>
    </div>
    <Dialog
      :model-value="!!confirm"
      @update:model-value="!$event && (confirm = null)"
      :options="{
        title:
          confirm === 'publish'
            ? 'Publish this form?'
            : confirm === 'delete'
              ? 'Delete this draft?'
              : 'Retire this form?',
      }"
      ><template #body-content
        ><p class="text-sm">
          {{
            confirm === "publish"
              ? "Publishing makes this version available to send. Its form definition can no longer be edited."
              : confirm === "delete"
                ? "This removes the draft from WhatsApp."
                : "Retired forms can no longer be sent to customers."
          }}
        </p>
        <Button
          class="mt-4"
          label="Confirm"
          :loading="busy"
          @click="run(lifecycle)" /></template
    ></Dialog>
  </section>
</template>
