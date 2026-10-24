<script setup>
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import RemoteLinkField from "../fields/RemoteLinkField.vue";
import { ref, computed, onMounted, watch } from "vue";
import { Dialog, Button, FormControl, ErrorMessage } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
import { randomUUID } from "../../services/crypto.js";
import { coreApi } from "../../services/coreApi";
const props = defineProps({ contact: String, initialCase: String });
const emit = defineEmits(["close"]);
const shown = ref(true),
  rows = ref([]),
  next = ref(null),
  busy = ref(false),
  error = ref(""),
  record = ref(null),
  values = ref({}),
  stage = ref(""),
  raw = ref({}),
  fieldErrors = ref({});
watch(shown, (v) => {
  if (!v) emit("close");
});
const updatesAvailable=ref(false);
let refreshDeferred=false;
async function changed(){
 if(busy.value){refreshDeferred=true;return}
 if(record.value){updatesAvailable.value=true;return}
 await load();
}
useRealtimeRefresh([],['cases'],changed);
watch(busy,value=>{if(!value&&refreshDeferred){refreshDeferred=false;changed()}});
const fields = computed(() => {
  const schema = record.value?.definition.fields || {};
  const properties = Object.assign(
    Object.create(null),
    schema.properties || {},
  );
  for (const name of Object.keys(record.value?.field_values || {})) {
    if (!Object.hasOwn(properties, name))
      properties[name] =
        typeof schema.additionalProperties === "object"
          ? schema.additionalProperties
          : { type: "json" };
  }
  return Object.entries(properties).map(([name, schema]) => ({
    name,
    ...schema,
  }));
});
const typeRows = ref([]),
  newType = ref(""),
  newTitle = ref(""),
  requestKey = ref("");
async function begin() {
  await task(async () => {
    typeRows.value = await coreApi("cases.types", { contact: props.contact });
    newType.value = "";
    newTitle.value = "";
    requestKey.value = randomUUID();
    record.value = {
      isNew: true,
      definition: { fields: { properties: {} }, stages: [] },
    };
    values.value = {};
    fieldErrors.value = {};
    raw.value = {};
  });
}
function chooseType() {
  const type = typeRows.value.find((t) => t.name === newType.value);
  if (!type) return;
  setRecord({
    isNew: true,
    case_type: type.name,
    definition: type.definition,
    stage: type.definition.initial_stage,
    field_values: {},
    priority: type.definition.priority || "Normal",
  });
}
const stages = computed(() => {
  const all = record.value?.definition.stages || [];
  const current = all.find((s) => s.key === record.value?.stage);
  return all
    .filter(
      (s) =>
        s.key === current?.key ||
        !current?.next ||
        current.next.includes(s.key),
    )
    .map((s) => ({ value: s.key, label: s.label }));
});
const required = computed(
  () =>
    new Set([
      ...(record.value?.definition.fields.required || []),
      ...(record.value?.definition.stages.find((s) => s.key === stage.value)
        ?.required_fields || []),
    ]),
);
async function task(fn) {
  busy.value = true;
  error.value = "";
  try {
    await fn();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
async function load(more = false) {
  await task(async () => {
    const result = await coreApi("cases.directory", {
      contact: props.contact,
      ...(more ? { after: next.value } : {}),
    });
    rows.value = more ? [...rows.value, ...result.items] : result.items;
    next.value = result.next;updatesAvailable.value=false;
  });
}
function setRecord(value) {
  updatesAvailable.value=false;
  assignmentOpen.value=false;
  record.value = value;
  values.value = { ...value.field_values };
  stage.value = value.stage;
  raw.value = {};
  fieldErrors.value = {};
}
async function open(name) {
  await task(async () => setRecord(await coreApi("cases.read", { name })));
}
function put(field, value) {
  try {
    if (["object", "array", "json"].includes(field.type)) {
      raw.value[field.name] = value;
      values.value[field.name] = JSON.parse(value);
    } else if (["integer", "number"].includes(field.type)) {
      const number = Number(value);
      if (
        value === "" ||
        !Number.isFinite(number) ||
        (field.type === "integer" && !Number.isInteger(number))
      )
        throw Error();
      values.value[field.name] = number;
    } else values.value[field.name] = value;
    delete fieldErrors.value[field.name];
  } catch {
    fieldErrors.value[field.name] = "Enter a valid " + field.type + " value.";
  }
}
const assignees = ref([]),
  agent = ref(""),
  assignmentOpen = ref(false);
async function editAssignment() {
  await task(async () => {
    agent.value = record.value.assigned_to || "";
    assignmentOpen.value = true;
  });
}
async function assign() {
  await task(async () => {
    setRecord(
      await coreApi(
        "cases.assign",
        {
          name: record.value.name,
          user: agent.value,
          modified: record.value.modified,
        },
        true,
      ),
    );
    assignmentOpen.value = false;
  });
}
async function save() {
  await task(async () => {
    if (Object.keys(fieldErrors.value).length)
      throw Error("Correct the highlighted fields.");
    for (const name of required.value) {
      const v = values.value[name];
      if (v == null || (typeof v === "string" && !v.trim()))
        throw Error(
          "Complete " + name.replaceAll("_", " ") + " before changing stage.",
        );
    }
    const result = record.value.isNew
      ? await coreApi(
          "cases.create_manual",
          {
            case_type: newType.value,
            contact: props.contact,
            title: newTitle.value,
            field_values: values.value,
            request_key: requestKey.value,
          },
          true,
        )
      : await coreApi(
          "cases.move",
          {
            name: record.value.name,
            stage: stage.value,
            values: values.value,
            modified: record.value.modified,
          },
          true,
        );
    setRecord(result);
  });
}
onMounted(() => (props.initialCase ? open(props.initialCase) : load()));
</script>
<template>
  <Dialog v-model="shown" :options="{ title: 'Conversation cases', size: 'lg' }"
    ><template #body-content
      ><div class="space-y-4 break-words">
        <ErrorMessage :message="error" />
        <div v-if="updatesAvailable" role="status" class="rounded p-3 bg-surface-gray-2 text-ink-gray-7 space-y-2">
          <p>Cases may have changed. Your current edits have been kept.</p>
          <Button v-if="record && !record.isNew" label="Reload case and discard edits" :disabled="busy" @click="open(record.name)" />
        </div>
        <template v-if="record"
          ><Button
            label="Back to cases"
            :disabled="busy"
            @click="
              record = null;
              load();
            " />
          <h3 class="font-medium">{{ record.title }}</h3>
          <p class="text-sm text-ink-gray-5">
            {{ record.priority }} priority
          </p>
          <p v-if="!record.isNew" class="text-sm text-ink-gray-5">
            Assigned to {{ record.assigned_to || "Unassigned" }}
          </p>
          <Button
            v-if="record.can_assign && !record.isNew"
            label="Assign case"
            :disabled="busy"
            @click="editAssignment" />
          <div
            v-if="assignmentOpen && !record.isNew"
            class="flex gap-2 items-end"
          >
            <RemoteLinkField v-model="agent" :field="{label:'Case assignee',method:'cases.agents',params:{name:record.name},readOnly:busy}" /><Button label="Save assignment" :loading="busy" @click="assign" />
          </div>
          <form class="space-y-4" @submit.prevent="save">
            <template v-if="record.isNew"
              ><RelaySelect
                v-model="newType"
                label="Case type"
                :options="
                  typeRows.map((t) => ({ value: t.name, label: t.title }))
                "
                :disabled="busy"
                @update:model-value="chooseType"
              /><FormControl
                v-model="newTitle"
                label="Case title"
                :maxlength="140"
                :disabled="busy"
              />
              <p v-if="!typeRows.length" class="text-sm text-ink-gray-5">
                No case types are configured. Add a Relay Case Type in Desk.
              </p></template
            >
            <RelaySelect
              v-model="stage"
              label="Stage"
              :options="stages"
              v-if="!record.isNew"
              :disabled="busy"
            />
            <div v-for="field in fields" :key="field.name">
              <RelaySelect
                v-if="field.enum"
                :label="
                  (field.title || field.name.replaceAll('_', ' ')) +
                  (required.has(field.name) ? ' *' : '')
                "
                :model-value="values[field.name] ?? ''"
                :options="
                  field.enum.map((v) => ({ value: v, label: String(v) }))
                "
                :disabled="busy"
                @update:model-value="put(field, $event)"
              />
              <FormControl
                v-else
                :label="
                  (field.title || field.name.replaceAll('_', ' ')) +
                  (required.has(field.name) ? ' *' : '')
                "
                :type="
                  field.type === 'boolean'
                    ? 'checkbox'
                    : ['integer', 'number'].includes(field.type)
                      ? 'number'
                      : 'textarea'
                "
                :model-value="
                  raw[field.name] ??
                  (['object', 'array'].includes(field.type)
                    ? JSON.stringify(
                        values[field.name] ??
                          (field.type === 'array' ? [] : {}),
                        null,
                        2,
                      )
                    : (values[field.name] ?? ''))
                "
                :disabled="busy"
                @update:model-value="put(field, $event)"
              /><ErrorMessage :message="fieldErrors[field.name]" />
            </div>
            <p v-if="required.size" class="text-xs text-ink-gray-5">
              Fields marked * are required for this stage.
            </p>
            <Button
              :label="record.isNew ? 'Create case' : 'Save case'"
              :disabled="record.isNew && (!newType || !newTitle.trim())"
              variant="solid"
              type="submit"
              :loading="busy"
            /><Button
              v-if="!record.isNew"
              label="Reload case"
              :disabled="busy"
              @click="open(record.name)"
            /></form
        ></template>
        <template v-else
          ><Button label="New case" :disabled="busy" @click="begin" /><Button
            label="Refresh cases"
            :loading="busy"
            @click="load()" />
          <p v-if="!rows.length && !busy" class="text-sm text-ink-gray-5">
            No cases in this conversation yet.
          </p>
          <button
            v-for="row in rows"
            :key="row.name"
            class="block w-full text-left rounded-lg border border-outline-gray-2 p-3 hover:bg-surface-gray-1"
            :disabled="busy"
            @click="open(row.name)"
          >
            <span class="block font-medium text-sm">{{ row.title }}</span
            ><span class="text-xs text-ink-gray-5"
              >{{ row.priority }} · {{ row.stage.replaceAll("_", " ") }}</span
            ></button
          ><Button
            v-if="next"
            label="More cases"
            :loading="busy"
            @click="load(true)"
        /></template></div></template
  ></Dialog>
</template>
