<script setup>
import { Button, ErrorMessage } from '@relay/ui'
import { useWhatsAppIdentity } from '../composables/useWhatsAppIdentity'
import { qualityBadge } from '../services/whatsappHealth'
const { identity, busy, error, load } = useWhatsAppIdentity()
</script>
<template>
  <section class="space-y-2" aria-label="Sending number">
    <p v-if="busy" role="status">Reading WhatsApp identity…</p><ErrorMessage :message="error" />
    <template v-if="identity"><p><strong>Number:</strong> {{ identity.display_phone_number || 'Not available yet. Select Sync now.' }}</p><p v-if="identity.verified_name">Business name: {{ identity.verified_name }}</p><p v-if="identity.display_phone_number">Quality: {{ qualityBadge(identity.quality_rating).label }}</p><p class="text-sm text-ink-gray-5">Last synced: {{ identity.updated || 'Never' }}</p></template>
    <Button variant="outline" icon-left="refresh-cw" label="Sync now" :loading="busy" @click="load" />
  </section>
</template>
