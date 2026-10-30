<script setup>
import { FeatherIcon } from '@relay/ui'

/** A contact's mobile number and email, each marked with its own icon. */
defineProps({ phone: String, email: String, size: { type: Number, default: 12 } })
</script>
<template>
  <span v-if="phone" class="contact-endpoint" title="Mobile"><FeatherIcon name="phone" :size="size" /><span class="sr-only">Mobile:</span>{{ phone }}</span>
  <span v-if="email" class="contact-endpoint" title="Email"><FeatherIcon name="mail" :size="size" /><span class="sr-only">Email:</span>{{ email }}</span>
</template>

<style scoped>
.contact-endpoint { display:inline-flex; align-items:center; gap:3px; min-width:0; overflow-wrap:anywhere; }
.contact-endpoint > svg { flex:none; }
.contact-endpoint + .contact-endpoint { margin-left:8px; }
</style>
