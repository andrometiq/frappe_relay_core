<script setup>
import PrimeTag from 'primevue/tag'
const themes = { gray: 'relay-badge--gray', blue: 'relay-badge--blue', red: 'relay-badge--red', green: 'relay-badge--green', amber: 'relay-badge--amber' }
defineProps({ label: { type: [String, Number], default: '' }, theme: { type: String, default: 'gray' } })
</script>
<template><PrimeTag :value="String(label)" :class="['relay-badge', themes[theme]]" /></template>
