<script setup>
import { computed, useId } from "vue";
const props = defineProps({
  label: String,
  options: { type: Array, default: () => [] },
  disabled: Boolean,
  hideLabel: Boolean,
});
const model = defineModel({ default: "" });
const id = useId();
const rows = computed(() =>
  props.options.map((o) =>
    typeof o === "string" ? { label: o, value: o } : o,
  ),
);
</script>
<template>
  <div class="space-y-1.5">
    <label :for="id" :class="hideLabel ? 'sr-only' : 'block text-xs text-ink-gray-5'">{{ label }}</label
    ><select
      :id="id"
      v-model="model"
      :disabled="disabled"
      class="w-full text-base rounded min-h-8 px-2 py-1 border border-transparent bg-surface-gray-2 text-ink-gray-8 focus:ring-2 focus:ring-outline-gray-3"
    >
      <option v-if="!rows.some((row) => row.value === '')" value="" disabled>Select option</option>
      <option v-for="row in rows" :key="row.value" :value="row.value">
        {{ row.label }}
      </option>
    </select>
  </div>
</template>
