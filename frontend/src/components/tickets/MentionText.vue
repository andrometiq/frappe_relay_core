<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { coreApi } from '../../services/coreApi'
import { distinctPeople, insertMention, mentionListPlacement, mentionQuery } from '../../services/ticketForm'

// A text area where "@" mentions a colleague. Picked colleagues are kept by user with the label written in the text.
const props = defineProps({ id: String, disabled: Boolean, placeholder: String })
const text = defineModel({ type: String, default: '' })
const picked = defineModel('picked', { type: Map, default: () => new Map() })
const area = ref(null), list = ref(null), options = ref([]), active = ref(0), typed = ref(null), placement = ref({})
let timer, controller

function close() { clearTimeout(timer); controller?.abort(); options.value = []; typed.value = null }
// The list is fixed to the viewport so the dialog cannot clip it; a scroll outside the list closes it.
function scrolled(event) { if (options.value.length && !list.value?.contains(event.target)) close() }
onMounted(() => { window.addEventListener('scroll', scrolled, true); window.addEventListener('resize', close) })
onBeforeUnmount(() => { window.removeEventListener('scroll', scrolled, true); window.removeEventListener('resize', close); close() })
function lookup() {
  const found = mentionQuery(text.value, area.value.selectionStart)
  if (!found) { close(); return }
  typed.value = found
  clearTimeout(timer)
  timer = setTimeout(async () => {
    controller?.abort(); controller = new AbortController()
    try {
      options.value = distinctPeople(await coreApi('tickets.colleagues', { query: found.query, mention: 1 }, false, { signal: controller.signal })).slice(0, 8)
      active.value = 0
      placement.value = mentionListPlacement(area.value.getBoundingClientRect(), window.innerHeight)
    } catch { options.value = [] }
  }, 200)
}
function pick(option) {
  if (!typed.value) return
  const { start } = typed.value
  text.value = insertMention(text.value, start, area.value.selectionStart, option.label)
  picked.value = new Map(picked.value).set(option.value, option.label)
  close()
  const end = start + option.label.length + 2
  nextTick(() => { area.value?.focus(); area.value?.setSelectionRange(end, end) })
}
// A click on an option lands before the blur ends the list.
function blur() { setTimeout(close, 150) }
function keydown(event) {
  if (!options.value.length) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    active.value = (active.value + (event.key === 'ArrowDown' ? 1 : -1) + options.value.length) % options.value.length
  } else if (event.key === 'Enter' || event.key === 'Tab') {
    event.preventDefault(); pick(options.value[active.value])
  } else if (event.key === 'Escape') {
    event.stopPropagation(); close()
  }
}
</script>

<template>
  <div class="mention-text">
    <textarea :id="id" ref="area" v-model="text" rows="4" maxlength="4000" :placeholder="placeholder" :disabled="disabled"
      role="combobox" aria-autocomplete="list" :aria-expanded="options.length > 0" :aria-controls="id + '-people'"
      @input="lookup" @click="lookup" @keydown="keydown" @blur="blur" />
    <ul v-if="options.length" :id="id + '-people'" ref="list" class="mention-options" :style="placement" role="listbox" aria-label="Colleagues">
      <li v-for="(option, index) in options" :key="option.value" role="option" :aria-selected="index === active"
        :class="{ active: index === active }" @mousedown.prevent="pick(option)">{{ option.label }}<small v-if="option.description">{{ option.description }}</small></li>
    </ul>
  </div>
</template>

<style scoped>
.mention-text { position:relative; }
.mention-text textarea { width:100%; min-height:88px; padding:8px 10px; border:1px solid var(--relay-stroke); border-radius:6px; background:var(--relay-layer); color:var(--relay-ink); font:inherit; font-size:13.5px; resize:vertical; }
.mention-text textarea:focus-visible { outline:2px solid var(--relay-accent); outline-offset:-1px; }
.mention-options { position:fixed; z-index:1200; overflow:auto; padding:4px; border:1px solid var(--relay-stroke); border-radius:8px; background:var(--relay-layer); box-shadow:0 8px 24px rgba(0,0,0,.14); }
.mention-options li { display:flex; flex-direction:column; min-height:36px; justify-content:center; padding:4px 10px; border-radius:6px; font-size:13px; cursor:pointer; }
.mention-options li.active, .mention-options li:hover { background:var(--relay-accent-soft); }
.mention-options small { color:var(--relay-ink-soft); font-size:11.5px; }
@media (max-width: 640px) { .mention-options li { min-height:44px; } }
</style>
