<script setup>
import { computed, inject, ref } from 'vue'
import PageSidebar from '../shell/PageSidebar.vue'
import { settingsRoute, settingsSections } from '../../services/settingsSections'

// The Settings sidebar around one settings page; Access shares it from its own route.
defineProps({ active: { type: String, required: true }, panel: Boolean })
const capabilities = inject('relayCapabilities', ref({}))
const sections = computed(() => settingsSections(capabilities.value))
const site = window.location.hostname
function open(item) { location.hash = settingsRoute(item.key) }
</script>

<template>
  <div class="relay-page settings-layout-page" :class="{ 'has-panel': panel }">
    <PageSidebar title="Settings" :subtitle="'Relay · ' + site" label="Settings pages" :sections="sections" :active="active" @select="open" />
    <slot />
  </div>
</template>
