<script setup>
import { ref } from "vue";

const props = defineProps({
  title: String,
  description: String,
  collapsible: Boolean,
  collapsed: Boolean,
});
const closed = ref(props.collapsed);
</script>

<template>
  <section class="frappe-form-section" :class="{ 'is-collapsed': closed }">
    <button v-if="title && collapsible" type="button" class="frappe-section-head" :aria-expanded="!closed" @click="closed = !closed">
      <span><strong>{{ title }}</strong><small v-if="description">{{ description }}</small></span><i>›</i>
    </button>
    <header v-else-if="title" class="frappe-section-head"><span><strong>{{ title }}</strong><small v-if="description">{{ description }}</small></span></header>
    <div v-show="!closed" class="frappe-section-content"><slot /></div>
  </section>
</template>
