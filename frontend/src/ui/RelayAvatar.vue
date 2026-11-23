<script setup>
import { computed } from 'vue'
import { User } from '@lucide/vue'
import PrimeAvatar from 'primevue/avatar'
import { avatarInitials, avatarTone } from './avatarIdentity'
const sizes = { sm: 'relay-avatar--sm', md: 'relay-avatar--md', lg: 'relay-avatar--lg', xl: 'relay-avatar--xl' }
// A status adds a presence dot: Available, Busy, Away or Do not disturb.
const statuses = { Available: 'available', Busy: 'busy', Away: 'away', 'Do not disturb': 'dnd' }
const props = defineProps({ label: { type: String, default: '' }, image: String, size: { type: String, default: 'md' }, shape: { type: String, default: 'circle' }, status: String })
const initials = computed(() => avatarInitials(props.label))
</script>
<template><PrimeAvatar :label="image ? undefined : initials" :image="image" :shape="shape" :data-status="statuses[status]" :class="['relay-avatar', sizes[size], image ? '' : avatarTone(label)]"><template v-if="!image && !initials" #icon><User class="relay-avatar__person" :stroke-width="1.7" aria-hidden="true" /></template></PrimeAvatar></template>
<style scoped>
.relay-avatar__person { width:60%; height:60%; }
</style>
