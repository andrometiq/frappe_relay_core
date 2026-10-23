<script setup>
import { Button, ErrorMessage } from '@relay/ui'
import { useWhatsAppIdentity } from '../composables/useWhatsAppIdentity'
const { identity, busy, error, load } = useWhatsAppIdentity()
</script>
<template>
  <section class="space-y-2" aria-label="Sending number">
    <p v-if="busy" role="status">Reading WhatsApp identity…</p><ErrorMessage :message="error" />
    <template v-if="identity"><p><strong>Sending number:</strong> {{ identity.display_phone_number || 'Not returned by Hub metadata' }}</p><p v-if="identity.verified_name">Verified name: {{ identity.verified_name }}</p><p v-if="identity.quality_rating">Quality: {{ identity.quality_rating }}</p><p class="text-sm text-ink-gray-5">Metadata: {{ identity.status || 'Not available' }} · Last successful sync: {{ identity.updated || 'Never' }}</p></template>
    <Button label="Refresh number identity" :disabled="busy" @click="load" />
  </section>
</template>
