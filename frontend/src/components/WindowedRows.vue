<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { anchoredScrollTop, rowWindow } from './windowedRows'
// Renders only the rows in view and a few around them, as Vue rows so transitions, focus and hover keep working.
// Every row has one height, measured from a rendered row. The default slot gets the rows to render and `animate`,
// which is false when the change came from a scroll or kept the reader in place.
const props = defineProps({ items: { type: Array, required: true }, itemKey: { type: String, default: 'name' },
  estimate: { type: Number, default: 80 }, overscan: { type: Number, default: 6 } })
const scroller = ref(null), windowBox = ref(null)
const scrollTop = ref(0), viewportHeight = ref(0), measured = ref(0), animate = ref(true)
const rowHeight = computed(() => measured.value || props.estimate)
const range = computed(() => rowWindow({ count: props.items.length, rowHeight: rowHeight.value, scrollTop: scrollTop.value,
  viewportHeight: viewportHeight.value, overscan: props.overscan }))
const start = computed(() => range.value.start), end = computed(() => range.value.end)
const shown = computed(() => props.items.slice(start.value, end.value))
defineExpose({ scroller })

function scrollTo(value) {
  scrollTop.value = value
  nextTick(() => { if (scroller.value && scroller.value.scrollTop !== value) scroller.value.scrollTop = value })
}
// A hidden list (a phone showing a chat) has no height; its last offset is kept for when it shows again.
function onScroll() {
  if (!scroller.value.clientHeight) return
  scrollTop.value = scroller.value.scrollTop
  animate.value = false
}
function measure() {
  const row = [...(windowBox.value?.children || [])].find(child => child.offsetHeight)
  const height = row?.getBoundingClientRect().height, previous = measured.value
  if (!height || Math.abs(height - previous) < 0.5) return
  measured.value = height
  if (previous && scrollTop.value) scrollTo(scrollTop.value * height / previous)
}
watch(shown, measure, { flush: 'post' })
// Rows that arrive above the reader move the offset down by their height, so the rows in view do not jump.
watch(() => props.items, (items, previous) => {
  const target = anchoredScrollTop({ scrollTop: scrollTop.value, rowHeight: rowHeight.value, previous: previous || [], next: items,
    key: row => row[props.itemKey] })
  const limited = Math.min(target, Math.max(0, items.length * rowHeight.value - viewportHeight.value))
  animate.value = target === scrollTop.value
  if (limited !== scrollTop.value) scrollTo(limited)
})
let observer
onMounted(() => {
  viewportHeight.value = scroller.value.clientHeight
  observer = new ResizeObserver(() => {
    const node = scroller.value, height = node.clientHeight
    if (height && !viewportHeight.value && scrollTop.value) node.scrollTop = scrollTop.value
    viewportHeight.value = height
    measure()
  })
  observer.observe(scroller.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>
<template>
  <div ref="scroller" class="windowed-rows" @scroll.passive="onScroll">
    <div ref="windowBox" :style="{ paddingTop: start * rowHeight + 'px', paddingBottom: (items.length - end) * rowHeight + 'px' }">
      <slot :rows="shown" :animate="animate" />
    </div>
    <slot name="after" />
  </div>
</template>

<style scoped>
/* The list keeps the reader's rows in place itself; browser scroll anchoring would move them twice. */
.windowed-rows { overflow-anchor:none; }
</style>
