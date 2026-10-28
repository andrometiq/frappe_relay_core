<script setup>
import { Badge, Button } from "@relay/ui";

defineProps({
  title: { type: String, required: true },
  breadcrumbs: { type: Array, default: () => [] },
  status: String,
  statusTheme: { type: String, default: "gray" },
  backLabel: { type: String, default: "Back" },
});
defineEmits(["back"]);
</script>

<template>
  <header class="frappe-page-head">
    <div class="frappe-page-title">
      <Button v-if="breadcrumbs.length" icon="chevron-left" variant="ghost" :aria-label="backLabel" @click="$emit('back')" />
      <div>
        <p v-if="breadcrumbs.length" class="frappe-breadcrumbs">
          <template v-for="(crumb, index) in breadcrumbs" :key="`${crumb}-${index}`">
            <button v-if="index < breadcrumbs.length - 1 || crumb !== title" type="button" @click="$emit('back')">{{ crumb }}</button>
            <span v-else>{{ crumb }}</span>
            <i v-if="index < breadcrumbs.length - 1">/</i>
          </template>
        </p>
        <div class="frappe-page-title-row">
          <h2>{{ title }}</h2><Badge v-if="status" :label="status" :theme="statusTheme" />
        </div>
      </div>
    </div>
    <div class="frappe-page-actions"><slot name="actions" /></div>
  </header>
</template>
