<script setup>
import { FeatherIcon } from "@relay/ui";

const props = defineProps({
  title: { type: String, required: true },
  description: String,
  label: { type: String, default: "Records" },
  columns: { type: Array, required: true },
  items: { type: Array, default: () => [] },
  busy: Boolean,
  loadingMore: Boolean,
  emptyTitle: { type: String, default: "No records found" },
  emptyDescription: String,
});
const emit = defineEmits(["open", "near-end"]);
const grid = {
  get value() {
    return {
      gridTemplateColumns: props.columns
        .map((column) => column.width || "minmax(120px,1fr)")
        .join(" "),
    };
  },
};
function onScroll(event) {
  const element = event.currentTarget;
  if (element.scrollHeight - element.scrollTop - element.clientHeight < 260)
    emit("near-end");
}
</script>

<template>
  <section class="frappe-list-view">
    <header class="frappe-list-toolbar">
      <div><h2>{{ title }}</h2><p v-if="description">{{ description }}</p></div>
      <div class="frappe-list-actions"><slot name="actions" /></div>
    </header>
    <div v-if="$slots.filters" class="frappe-list-filters"><slot name="filters" /></div>
    <div class="frappe-list-scroll" @scroll.passive="onScroll">
      <div class="frappe-list-table" role="table" :aria-label="label">
        <div class="frappe-list-row frappe-list-row-head" role="row" :style="grid.value">
          <span v-for="column in columns" :key="column.key" role="columnheader">{{ column.label }}</span>
        </div>
        <button v-for="item in items" :key="item.id || item.name" type="button" class="frappe-list-row" role="row" :style="grid.value" @click="emit('open', item)">
          <span v-for="column in columns" :key="column.key" role="cell" :data-label="column.label">
            <slot :name="`cell-${column.key}`" :item="item"><span :title="String(item[column.key] ?? '')">{{ item[column.key] }}</span></slot>
          </span>
        </button>
      </div>
      <div v-if="busy" class="frappe-list-loading" role="status">Loading records…</div>
      <div v-if="loadingMore" class="frappe-list-loading" role="status">Loading more…</div>
      <div v-else-if="!items.length && !busy" class="frappe-empty-state">
        <span class="frappe-empty-icon"><FeatherIcon name="file-text" :size="28" /></span>
        <h3>{{ emptyTitle }}</h3><p v-if="emptyDescription">{{ emptyDescription }}</p><slot name="empty-action" />
      </div>
    </div>
    <footer v-if="$slots.footer" class="frappe-list-footer"><slot name="footer" /></footer>
  </section>
</template>
