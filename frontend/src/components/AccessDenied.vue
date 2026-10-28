<script setup>
import { computed } from 'vue'
import { deniedReason } from '../services/pageAccess'
import WorkspaceState from './WorkspaceState.vue'
const props = defineProps({ page: Object, capabilities: Object })
const reason = computed(() => deniedReason(props.page, props.capabilities))
</script>
<template>
  <WorkspaceState icon="lock" title="You cannot open this page" :description="reason || 'Ask your system administrator for access.'">
    <a class="relay-button relay-button--outline" href="#/messages">Go to Chats</a>
  </WorkspaceState>
</template>
