<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { FeatherIcon } from '@relay/ui'
import { threadTabs } from '../../services/conversationThreads'
// One tab per thread: a contact endpoint on one of our channels. The tabs scroll sideways on a phone.
const props = defineProps({ threads: { type: Array, default: () => [] }, active: String, busy: Boolean, canStart: Boolean })
const emit = defineEmits(['select', 'start'])
const tabs = computed(() => threadTabs(props.threads))
const list = ref(null)
// A fade marks each edge with more tabs behind it; it follows scrolling and resizing, never a timer.
const more = ref({ start: false, end: false })
function measure() {
  const node = list.value
  if (!node) return
  more.value = { start: node.scrollLeft > 2, end: node.scrollLeft + node.clientWidth < node.scrollWidth - 2 }
}
let resizes
onMounted(() => { resizes = new ResizeObserver(measure); resizes.observe(list.value); measure() })
onBeforeUnmount(() => resizes?.disconnect())
// The open tab scrolls into view, so an unread tab past the edge of a phone screen is seen.
watch(() => [props.active, tabs.value.length], async () => {
  await nextTick()
  list.value?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
  measure()
}, { immediate: true })
function keydown(event) {
  const index = props.threads.findIndex(thread => thread.key === props.active)
  const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key]
  if (!step || index < 0) return
  event.preventDefault()
  const next = props.threads[(index + step + props.threads.length) % props.threads.length]
  emit('select', next)
  nextTick(() => list.value?.querySelector('[aria-selected="true"]')?.focus())
}
</script>

<template>
  <div class="thread-tabs" :class="{ 'has-more-start': more.start, 'has-more-end': more.end }">
    <div ref="list" class="thread-tab-list" role="tablist" aria-label="Conversations by channel" @keydown="keydown" @scroll.passive="measure">
      <button v-for="tab in tabs" :key="tab.thread.key" type="button" role="tab" class="thread-tab" :data-provider="tab.provider"
        :aria-selected="tab.thread.key === active" :tabindex="tab.thread.key === active ? 0 : -1" :disabled="busy && tab.thread.key !== active"
        :title="tab.title" @click="emit('select', tab.thread)">
        <FeatherIcon class="thread-tab-icon" :name="tab.icon" :size="14" aria-hidden="true" />
        <span class="thread-tab-provider">{{ tab.provider }}</span>
        <small v-if="tab.person" class="thread-tab-person">{{ tab.person }}</small>
        <small v-if="tab.endpoint" class="thread-tab-endpoint"><bdi>{{ tab.endpoint }}</bdi></small>
        <small v-if="tab.via" class="thread-tab-via">· {{ tab.via }}</small>
        <span v-if="tab.thread.unread" class="thread-tab-unread" :aria-label="`${tab.thread.unread} unread`">{{ tab.thread.unread > 99 ? '99+' : tab.thread.unread }}</span>
      </button>
    </div>
    <button v-if="canStart" type="button" class="thread-tab-new" aria-label="New conversation on another channel" title="New conversation on another channel"
      :disabled="busy" @click="emit('start')"><FeatherIcon name="plus" :size="16" /></button>
  </div>
</template>

<style scoped>
.thread-tabs { position:relative; display:flex; align-items:stretch; gap:4px; min-width:0; padding:0 12px; border-bottom:1px solid var(--relay-stroke); background:var(--relay-layer); }
.thread-tab-list { display:flex; flex:1; gap:2px; min-width:0; overflow-x:auto; overscroll-behavior-x:contain; scrollbar-width:none; scroll-snap-type:x proximity; }
.thread-tab-list::-webkit-scrollbar { display:none; }
.thread-tab { position:relative; display:inline-flex; flex:none; align-items:center; gap:5px; min-height:42px; padding:0 8px; border:0; border-bottom:2px solid transparent; background:none; color:var(--relay-ink-3); font-size:12.5px; font-weight:500; white-space:nowrap; scroll-snap-align:start; cursor:pointer; transition:color var(--relay-fast) var(--relay-ease), border-color var(--relay-fast) var(--relay-ease); }
.thread-tab:hover { color:var(--relay-ink); }
.thread-tab[aria-selected="true"] { color:var(--relay-ink); border-bottom-color:var(--relay-accent); }
.thread-tab:focus-visible { outline:2px solid var(--relay-accent); outline-offset:-2px; border-radius:6px 6px 0 0; }
.thread-tab:disabled { cursor:default; opacity:.6; }
.thread-tab small { color:var(--relay-ink-soft); font-size:11.5px; font-weight:400; }
/* A long address never widens a tab: it ends in an ellipsis and the tab's tooltip holds the full value. */
.thread-tab-endpoint, .thread-tab-person, .thread-tab-via { min-width:0; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.thread-tab-icon, .thread-tab-provider, .thread-tab-unread { flex:none; }
.thread-tab-list { mask-image:linear-gradient(to right, var(--thread-fade-start, #000), #000 24px, #000 calc(100% - 24px), var(--thread-fade-end, #000)); }
.has-more-start .thread-tab-list { --thread-fade-start:transparent; }
.has-more-end .thread-tab-list { --thread-fade-end:transparent; }
.thread-tab-person { color:var(--relay-ink-3) !important; font-weight:500 !important; }
.thread-tab[data-provider="WhatsApp"] .thread-tab-icon { color:var(--relay-whatsapp); }
.thread-tab[data-provider="Telegram"] .thread-tab-icon { color:var(--relay-telegram); }
.thread-tab[data-provider="Email"] .thread-tab-icon { color:var(--relay-email); }
.thread-tab-unread { min-width:18px; height:16px; padding:0 5px; border-radius:9px; background:var(--relay-accent); color:var(--relay-accent-ink); font-size:10.5px; font-weight:600; line-height:16px; text-align:center; animation:thread-pop var(--relay-normal) var(--relay-ease); }
.thread-tab-new { display:grid; flex:none; place-items:center; width:40px; min-height:42px; border:0; border-radius:6px; background:none; color:var(--relay-ink-3); cursor:pointer; }
.thread-tab-new:hover { background:var(--relay-hover); color:var(--relay-ink); }
@keyframes thread-pop { from { transform:scale(.6); opacity:0; } to { transform:none; opacity:1; } }
@media (max-width:768px) {
  .thread-tabs { padding:0 4px 0 8px; }
  .thread-tab { min-height:44px; }
  .thread-tab-endpoint, .thread-tab-person, .thread-tab-via { max-width:120px; }
}
@media (prefers-reduced-motion:reduce) { .thread-tab-unread { animation:none; } }
</style>
