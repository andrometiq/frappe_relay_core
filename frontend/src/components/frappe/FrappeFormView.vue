<script setup>
import { computed } from "vue";
import FrappePageHeader from "./FrappePageHeader.vue";

const props = defineProps({
  title: { type: String, required: true },
  breadcrumbs: { type: Array, default: () => [] },
  status: String,
  statusTheme: { type: String, default: "gray" },
  tabs: { type: Array, default: () => ["Details"] },
  activeTab: { type: String, default: "Details" },
});
defineEmits(["back", "update:activeTab"]);
// The title already names the document, so the trail stops at its parent; one tab needs no tab bar.
const trail = computed(() => props.breadcrumbs.at(-1) === props.title ? props.breadcrumbs.slice(0, -1) : props.breadcrumbs);
</script>

<template>
  <article class="frappe-form-view">
    <FrappePageHeader :title="title" :breadcrumbs="trail" :status="status" :status-theme="statusTheme" @back="$emit('back')">
      <template #actions><slot name="actions" /></template>
    </FrappePageHeader>
    <nav v-if="tabs.length > 1" class="frappe-form-tabs" aria-label="Document sections">
      <button v-for="tab in tabs" :key="tab" type="button" :class="{ active: tab === activeTab }" @click="$emit('update:activeTab', tab)">{{ tab }}</button>
    </nav>
    <div class="frappe-form-layout">
      <main class="frappe-form-main"><slot /></main>
      <aside v-if="$slots.sidebar" class="frappe-form-sidebar"><slot name="sidebar" /></aside>
    </div>
  </article>
</template>
