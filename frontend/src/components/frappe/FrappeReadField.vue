<script setup>
defineProps({ label: { type: String, required: true }, value: { default: "" }, wide: Boolean, multiline: Boolean });
</script>
<template><div class="frappe-read-field" :class="{ wide, multiline }"><span>{{ label }}</span><p>{{ value || "—" }}</p></div></template>
