<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

// A floating pill over the bubble; Escape or a click outside closes it.
const props = defineProps({ choices: Array, current: String, busy: Boolean })
const emit = defineEmits(['pick', 'close'])
const pill = ref(null), below = ref(false)
function outside(event) { if (!pill.value?.contains(event.target)) emit('close') }
function escape(event) { if (event.key === 'Escape') emit('close') }
onMounted(() => {
  const thread = pill.value.closest('.message-thread')
  below.value = !!thread && pill.value.parentElement.getBoundingClientRect().top - thread.getBoundingClientRect().top < 56
  pill.value.querySelector('button')?.focus()
  document.addEventListener('pointerdown', outside, true)
  document.addEventListener('keydown', escape)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', outside, true)
  document.removeEventListener('keydown', escape)
})
</script>

<template>
  <div ref="pill" class="reaction-pill" :class="{ 'is-below': below }" role="group" aria-label="Choose reaction">
    <button v-for="emoji in choices" :key="emoji" type="button" :class="{ 'is-current': emoji === current }" :aria-pressed="emoji === current"
      :aria-label="'React ' + emoji" :disabled="busy" @click="emit('pick', emoji)">{{ emoji }}</button>
    <button v-if="props.current" type="button" class="reaction-remove" :disabled="busy" @click="emit('pick', '')">Remove reaction</button>
  </div>
</template>

<style scoped>
.reaction-pill { position:absolute; bottom:calc(100% + 4px); right:8px; z-index:6; display:flex; align-items:center; gap:2px; padding:4px 6px; border:1px solid var(--relay-stroke, var(--outline-gray-2)); border-radius:999px; background:var(--surface-modal, var(--surface-white)); box-shadow:var(--relay-shadow-2, 0 4px 16px #0002); animation:relay-pop var(--relay-fast, 120ms) ease; }
:global(.conversation-bubble:not(.ml-auto)) > .reaction-pill { right:auto; left:8px; }
.reaction-pill.is-below { bottom:auto; top:calc(100% + 4px); }
.reaction-pill button { display:grid; place-items:center; min-width:34px; min-height:34px; padding:0; border-radius:999px; font-size:20px; line-height:1; }
.reaction-pill button:hover:not(:disabled), .reaction-pill button:focus-visible { background:var(--relay-hover, var(--surface-gray-2)); outline:0; }
.reaction-pill button.is-current { background:var(--surface-blue-1, #e6f0ff); }
.reaction-pill .reaction-remove { padding:0 10px; font-size:12px; white-space:nowrap; color:var(--ink-gray-6); }
</style>
