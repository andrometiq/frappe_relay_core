<script setup>
import { computed } from 'vue'
import PrimeAvatar from 'primevue/avatar'
import { avatarInitials, avatarTone } from './avatarIdentity'
const sizes = { sm: 'relay-avatar--sm', md: 'relay-avatar--md', lg: 'relay-avatar--lg', xl: 'relay-avatar--xl' }
const props = defineProps({ label: { type: String, default: '' }, image: String, size: { type: String, default: 'md' }, shape: { type: String, default: 'circle' } })
const initials = computed(() => avatarInitials(props.label))
</script>
<template><PrimeAvatar :label="initials" :image="image" :shape="shape" :class="['relay-avatar', sizes[size], image ? '' : avatarTone(label)]" /></template>
