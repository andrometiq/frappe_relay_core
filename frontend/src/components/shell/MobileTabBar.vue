<script setup>
import { computed, inject, nextTick, ref, watch } from 'vue'
import { FeatherIcon } from '@relay/ui'
import { splitMobileNav } from '../../services/mobileNav'
import { countLabel } from '../../services/queueCounts'
import { defaultMedium } from '../../services/enabledChannels'
import { useQueueCounts } from '../../composables/useQueueCounts'

const props = defineProps({ items: { type: Array, required: true }, sections: { type: Array, default: () => [] }, view: String, section: String })
const emit = defineEmits(['navigate', 'section'])
const open = defineModel('open', { type: Boolean, default: false })
const split = computed(() => splitMobileNav(props.items))
const sheet = ref(null)
const tabLabels = { Messages: 'Inbox' }
const capabilities = inject('relayCapabilities')
const { counts } = useQueueCounts(computed(() => defaultMedium(capabilities.value)))
const badge = computed(() => countLabel(counts.value.unread))
function go(name) {
  open.value = false
  emit('navigate', name)
}
function goSection(name) {
  open.value = false
  emit('section', name)
}
watch(open, async value => {
  if (!value) return
  await nextTick()
  sheet.value?.querySelector('button, a[href]')?.focus()
})
</script>

<template>
  <nav class="mobile-tabbar" aria-label="Relay sections">
    <button v-for="item in split.tabs" :key="item.name" type="button" class="mobile-tab" :class="{ active: view === item.name }"
      :aria-current="view === item.name ? 'page' : undefined" @click="go(item.name)">
      <span class="mobile-tab-icon"><FeatherIcon :name="item.icon" :size="20" />
        <span v-if="item.name === 'Messages' && badge" class="mobile-tab-badge" :aria-label="`${badge} unread chats`">{{ badge }}</span></span>
      <span>{{ tabLabels[item.name] || item.label }}</span>
    </button>
    <button type="button" class="mobile-tab" :class="{ active: open || split.more.some(item => item.name === view) }"
      aria-haspopup="dialog" :aria-expanded="open" @click="open = !open">
      <span class="mobile-tab-icon"><FeatherIcon name="menu" :size="20" /></span><span>More</span>
    </button>
  </nav>
  <Transition name="relay-fade">
    <button v-if="open" type="button" class="mobile-sheet-backdrop" aria-label="Close menu" @click="open = false" />
  </Transition>
  <Transition name="relay-sheet">
    <div v-if="open" ref="sheet" class="mobile-sheet" role="dialog" aria-modal="true" aria-label="More pages" @keydown.esc="open = false">
      <span class="mobile-sheet-handle" aria-hidden="true" />
      <button v-for="item in split.more" :key="item.name" type="button" class="mobile-sheet-item" :class="{ active: view === item.name }"
        :aria-current="view === item.name ? 'page' : undefined" @click="go(item.name)">
        <span class="mobile-sheet-icon"><FeatherIcon :name="item.icon" :size="18" /></span><span>{{ item.label }}</span>
        <FeatherIcon name="chevron-right" :size="16" class="mobile-sheet-chevron" />
      </button>
      <template v-if="sections.length">
        <p class="mobile-sheet-group">WhatsApp</p>
        <button v-for="item in sections" :key="item.name" type="button" class="mobile-sheet-item" :class="{ active: section === item.name }"
          :aria-current="section === item.name ? 'page' : undefined" @click="goSection(item.name)">
          <span class="mobile-sheet-icon"><FeatherIcon :name="item.icon" :size="18" /></span><span>{{ item.label }}</span>
          <FeatherIcon name="chevron-right" :size="16" class="mobile-sheet-chevron" />
        </button>
      </template>
      <slot name="footer" />
    </div>
  </Transition>
</template>
