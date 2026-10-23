<script setup>
import { computed, ref, watch } from "vue";
import { FormControl, Button, ErrorMessage } from "@relay/ui";
import RelaySelect from "../RelaySelect.vue";
const props = defineProps({
  node: Object,
  catalog: Array,
  answers: Array,
  disabled: Boolean,
});
const emit = defineEmits(["validity"]);
props.node.arguments ||= {};
const errors = ref({}),
  raw = ref({});
const definition = computed(() =>
  props.catalog.find((row) => row.key === props.node.action),
);
const fields = computed(() =>
  Object.entries(definition.value?.parameters?.properties || {}).map(
    ([name, schema]) => ({
      name,
      ...schema,
      required: (definition.value.parameters.required || []).includes(name),
    }),
  ),
);
function changed() {
  props.node.arguments = {};
  errors.value = {};
  raw.value = {};
  check();
}
function isReference(name) {
  const value = props.node.arguments?.[name];
  return (
    value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    Object.keys(value).length === 1 &&
    "var" in value
  );
}
function mode(name, value) {
  delete errors.value[name];
  delete raw.value[name];
  if (value === "answer") props.node.arguments[name] = { var: "" };
  else delete props.node.arguments[name];
  check();
}
function put(field, value) {
  try {
    if (["object", "array", "json"].includes(field.type)) {
      raw.value[field.name] = value;
      props.node.arguments[field.name] = JSON.parse(value);
    } else if (["number", "integer"].includes(field.type)) {
      if (value === "") delete props.node.arguments[field.name];
      else {
        const number = Number(value);
        if (
          !Number.isFinite(number) ||
          (field.type === "integer" && !Number.isInteger(number))
        )
          throw Error("Enter a valid " + field.type);
        props.node.arguments[field.name] = number;
      }
    } else props.node.arguments[field.name] = value;
    delete errors.value[field.name];
  } catch (e) {
    errors.value[field.name] = ["object", "array", "json"].includes(field.type)
      ? "Enter valid JSON for this structured field."
      : e.message;
  }
  check();
}
function check() {
  const values = props.node.arguments || {};
  const valid =
    !!definition.value &&
    !Object.keys(errors.value).length &&
    fields.value.every(
      (f) =>
        (!f.required || (f.name in values && values[f.name] !== "")) &&
        (!isReference(f.name) ||
          props.answers.some((a) => a.value === values[f.name].var)),
    );
  emit("validity", valid);
}
watch(() => props.node.action, check);
watch(() => props.catalog, check, { immediate: true });
</script>
<template>
  <section class="space-y-3" aria-label="Business action fields">
    <RelaySelect
      v-model="node.action"
      label="Business action"
      :options="catalog.map((row) => ({ value: row.key, label: row.label }))"
      :disabled="disabled"
      @update:model-value="changed"
    />
    <p v-if="!catalog.length" class="text-sm text-ink-gray-5">
      No business actions are registered on this site. Install the business
      adapter in Desk before using this step.
    </p>
    <p v-else-if="node.action && !definition" class="text-sm text-red-600">
      This saved action is no longer registered. Choose an available action
      before saving.
    </p>
    <p v-if="definition?.description" class="text-sm text-ink-gray-5">
      {{ definition.description }}
    </p>
    <div
      v-for="field in fields"
      :key="field.name"
      class="rounded border border-outline-gray-2 p-3 space-y-2"
    >
      <div class="flex justify-between gap-2">
        <h4 class="text-sm font-medium">
          {{ field.title || field.name }}{{ field.required ? " *" : "" }}
        </h4>
        <Button
          v-if="!field.required && field.name in node.arguments"
          label="Clear field"
          :disabled="disabled"
          @click="
            delete node.arguments[field.name];
            delete errors[field.name];
            delete raw[field.name];
            check();
          "
        />
      </div>
      <RelaySelect
        :model-value="isReference(field.name) ? 'answer' : 'value'"
        label="Value source"
        :options="[
          { value: 'value', label: 'Fixed value' },
          { value: 'answer', label: 'Collected answer' },
        ]"
        :disabled="disabled"
        @update:model-value="mode(field.name, $event)"
      />
      <RelaySelect
        v-if="isReference(field.name)"
        :model-value="node.arguments[field.name].var"
        :label="field.title || field.name"
        :options="answers"
        :disabled="disabled"
        @update:model-value="
          node.arguments[field.name] = { var: $event };
          check();
        "
      />
      <RelaySelect
        v-else-if="field.enum"
        :label="field.title || field.name"
        :model-value="node.arguments[field.name] ?? ''"
        :options="field.enum.map((value) => ({ value, label: String(value) }))"
        :disabled="disabled"
        @update:model-value="put(field, $event)"
      />
      <FormControl
        v-else-if="field.type === 'boolean'"
        type="checkbox"
        :label="field.title || field.name"
        :model-value="node.arguments[field.name] === true"
        :disabled="disabled"
        @update:model-value="put(field, $event)"
      />
      <FormControl
        v-else
        :type="
          ['object', 'array'].includes(field.type)
            ? 'textarea'
            : field.enum
              ? 'select'
              : ['number', 'integer'].includes(field.type)
                ? 'number'
                : 'text'
        "
        :label="field.title || field.name"
        :options="field.enum"
        :model-value="
          raw[field.name] ??
          (['object', 'array'].includes(field.type)
            ? JSON.stringify(
                node.arguments[field.name] ??
                  (field.type === 'array' ? [] : {}),
                null,
                2,
              )
            : (node.arguments[field.name] ?? ''))
        "
        :disabled="disabled"
        @update:model-value="put(field, $event)"
      />
      <p v-if="field.description" class="text-xs text-ink-gray-5">
        {{ field.description }}
      </p>
      <ErrorMessage :message="errors[field.name]" />
    </div>
  </section>
</template>
