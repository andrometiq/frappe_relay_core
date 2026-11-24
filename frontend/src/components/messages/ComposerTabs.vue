<script setup>
// The composer's three ways to write: a reply to the customer, an internal note for the team, or an approved template.
defineProps({ mode: { type: String, default: 'reply' }, template: Boolean, disabled: Boolean })
const emit = defineEmits(['mode', 'template'])
</script>

<template>
  <div class="composer-tabs" role="group" aria-label="Write">
    <button type="button" class="hit-zone" :aria-pressed="mode !== 'note'" :disabled="disabled" @click="emit('mode', 'reply')">Reply</button>
    <button type="button" class="hit-zone" :aria-pressed="mode === 'note'" :disabled="disabled" @click="emit('mode', 'note')">Internal note</button>
    <button v-if="template" type="button" class="hit-zone" :disabled="disabled" @click="emit('template')">Template</button>
  </div>
</template>

<style scoped>
.composer-tabs { display:flex; flex:none; gap:2px; padding:6px 8px; border-bottom:1px solid var(--relay-stroke); }
.composer-tabs button { height:24px; padding:0 10px; border-radius:5px; color:var(--relay-ink-3); font-size:12.5px; font-weight:500; white-space:nowrap; }
.composer-tabs button:hover:not(:disabled) { color:var(--relay-ink); }
.composer-tabs button[aria-pressed=true] { background:var(--relay-hover); color:var(--relay-ink); }
.composer-tabs button:disabled { cursor:not-allowed; opacity:.55; }
.composer-tabs button:focus-visible { outline:2px solid var(--relay-accent); outline-offset:-2px; }
</style>
