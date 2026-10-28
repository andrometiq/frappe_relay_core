<script setup>
import { recordTitle } from '../../services/recordTitle'
import LoadingRows from "../LoadingRows.vue";
import WorkspaceState from "../WorkspaceState.vue";

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
const emit = defineEmits(["open"]);
const grid = {
  get value() {
    return {
      gridTemplateColumns: props.columns
        .map((column) => column.width || "minmax(120px,1fr)")
        .join(" "),
    };
  },
};
</script>

<template>
  <section class="frappe-list-view" :aria-label="title">
    <header class="frappe-list-toolbar">
      <p v-if="description">{{ description }}</p>
      <div class="frappe-list-actions"><slot name="actions" /></div>
    </header>
    <div v-if="$slots.filters" class="frappe-list-filters"><slot name="filters" /></div>
    <div class="frappe-list-scroll">
      <div class="frappe-list-table" role="table" :aria-label="label">
        <div class="frappe-list-row frappe-list-row-head" role="row" :style="grid.value">
          <span v-for="column in columns" :key="column.key" role="columnheader">{{ column.label }}</span>
        </div>
        <button v-for="item in items" :key="item.id || item.name" type="button" class="frappe-list-row" role="row" :style="grid.value" @click="emit('open', item)">
          <span v-for="column in columns" :key="column.key" role="cell" :data-label="column.label">
            <slot :name="`cell-${column.key}`" :item="item"><span :title="String(column.key === 'name' ? recordTitle(item) : item[column.key] ?? '')">{{ column.key === 'name' ? recordTitle(item) : item[column.key] }}</span></slot>
          </span>
        </button>
      </div>
      <LoadingRows v-if="busy && !items.length" label="Loading records…" :count="6" />
      <div v-if="loadingMore" class="frappe-list-loading" role="status">Loading more…</div>
      <WorkspaceState v-else-if="!items.length && !busy" :title="emptyTitle" :description="emptyDescription" icon="file-text"><slot name="empty-action" /></WorkspaceState>
      <footer v-if="$slots.footer" class="frappe-list-footer"><slot name="footer" /></footer>
    </div>
  </section>
</template>
