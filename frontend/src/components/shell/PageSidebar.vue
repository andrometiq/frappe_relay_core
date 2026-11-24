<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { FeatherIcon } from '@relay/ui'
import { useMobileLayout } from '../../composables/useMobileLayout'

// A page's own section sidebar: views, filters and links. Phones show the open view as a button that opens the list as a sheet.
const props = defineProps({ title: String, subtitle: String, sections: { type: Array, default: () => [] }, active: String, label: String })
const emit = defineEmits(['select'])
const isMobile = useMobileLayout()
const open = ref(false), sheet = ref(null)
const current = computed(() => props.sections.flatMap(section => section.items).find(item => item.key === props.active))
function choose(item) {
  if (item.static) return
  open.value = false
  emit('select', item)
}
watch(open, async value => {
  if (!value) return
  await nextTick()
  sheet.value?.querySelector('[aria-current=page], button')?.focus()
})
</script>

<template>
  <button v-if="isMobile" type="button" class="page-side-picker" aria-haspopup="dialog" :aria-expanded="open" @click="open = true">
    <FeatherIcon v-if="current?.icon" :name="current.icon" :size="16" /><span v-else-if="current?.dot" class="page-side-dot" :style="{ background: current.dot }" />
    <span class="page-side-picker-label">{{ current?.label || label || title }}</span>
    <span v-if="current?.count != null" class="page-side-count">{{ current.count }}</span>
    <FeatherIcon name="chevron-down" :size="16" />
  </button>
  <Transition name="relay-fade">
    <button v-if="isMobile && open" type="button" class="section-sidebar-backdrop" :aria-label="`Close ${title}`" @click="open = false" />
  </Transition>
  <Transition :name="isMobile ? 'relay-slide' : ''">
    <aside v-if="!isMobile || open" ref="sheet" class="page-side" :class="{ 'is-sheet': isMobile }" :aria-label="label || title"
      :role="isMobile ? 'dialog' : undefined" :aria-modal="isMobile || undefined" @keydown.esc="open = false">
      <header class="page-side-head">
        <div><h2>{{ title }}</h2><small v-if="subtitle">{{ subtitle }}</small></div>
        <slot name="actions" />
        <button v-if="isMobile" type="button" class="section-sidebar-close" :aria-label="`Close ${title}`" @click="open = false"><FeatherIcon name="x" /></button>
      </header>
      <slot name="top" />
      <nav class="page-side-sections">
        <div v-for="section in sections" :key="section.key" class="page-side-section">
          <h3 v-if="section.title">{{ section.title }}</h3>
          <component :is="item.static ? 'div' : 'button'" v-for="item in section.items" :key="item.key" :type="item.static ? undefined : 'button'"
            class="page-side-item" :class="{ active: item.key === active, static: item.static }" :aria-current="item.key === active ? 'page' : undefined"
            :title="item.title || item.label" @click="choose(item)">
            <FeatherIcon v-if="item.icon" :name="item.icon" :size="16" :class="item.tone ? 'tone-' + item.tone : ''" />
            <span v-else-if="item.dot" class="page-side-dot" :style="{ background: item.dot }" />
            <span class="page-side-label">{{ item.label }}</span>
            <span v-if="item.count != null" class="page-side-count" :class="{ strong: item.strong && item.count }">{{ item.count }}</span>
          </component>
        </div>
      </nav>
    </aside>
  </Transition>
</template>
