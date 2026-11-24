<script setup>
import { computed } from 'vue'
import { Avatar } from '@relay/ui'
import { userCard } from '../services/userProfiles'

// A colleague's avatar: their profile photo, display name and status dot.
const props = defineProps({ user: String, label: String, size: { type: String, default: 'md' } })
const card = computed(() => userCard(props.user))
const name = computed(() => card.value?.name || props.label || props.user || '')
const title = computed(() => [name.value, card.value?.status, card.value?.status_text].filter(Boolean).join(' · '))
</script>
<template><Avatar :label="name" :image="card?.image || undefined" :status="card?.status" :size="size" :title="title" /></template>
