<script setup>
import { nextTick, ref, watch } from 'vue'
import { FeatherIcon } from '@relay/ui'

// The pages of one rail group. Desktop shows it as a column; phones open it as a slide-over panel.
const props = defineProps({ group: { type: Object, required: true }, view: String, overlay: Boolean })
const emit = defineEmits(['navigate'])
const open = defineModel('open', { type: Boolean, default: false })
const panel = ref(null)

function go(name) {
  open.value = false
  emit('navigate', name)
}
watch(open, async value => {
  if (!value) return
  await nextTick()
  panel.value?.querySelector('[aria-current=page], button')?.focus()
})
</script>

<template>
  <Transition name="relay-fade">
    <button v-if="overlay && open" type="button" class="section-sidebar-backdrop" aria-label="Close pages" @click="open = false" />
  </Transition>
  <Transition :name="overlay ? 'relay-slide' : ''">
    <aside v-if="!overlay || open" ref="panel" class="section-sidebar" :class="{ 'is-overlay': overlay }" :aria-label="`${props.group.name} pages`"
      :role="overlay ? 'dialog' : undefined" :aria-modal="overlay || undefined" @keydown.esc="open = false">
      <header class="section-sidebar-head">
        <h2>{{ group.name }}</h2>
        <button v-if="overlay" type="button" class="section-sidebar-close" aria-label="Close pages" @click="open = false"><FeatherIcon name="x" /></button>
      </header>
      <nav class="section-sidebar-items">
        <button v-for="page in group.pages" :key="page.name" type="button" class="section-item" :class="{ active: view === page.name }"
          :aria-current="view === page.name ? 'page' : undefined" @click="go(page.name)">
          <FeatherIcon :name="page.icon" /><span>{{ page.label }}</span>
        </button>
      </nav>
    </aside>
  </Transition>
</template>
