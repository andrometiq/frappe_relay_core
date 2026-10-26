<script setup>
import { ref } from 'vue'
import { Avatar, Button, FeatherIcon } from '@relay/ui'
import ContactDetails from '../ContactDetails.vue'
import WorkspaceState from '../WorkspaceState.vue'

defineProps({ title: String, contact: String, primary: Object, channel: String, canOrganize: Boolean })
const emit = defineEmits(['close', 'cases', 'notes'])
const phone = ref('')
</script>

<template>
  <section class="contact-info-page" aria-label="Contact info">
    <header class="contact-info-bar">
      <Button icon="arrow-left" variant="ghost" aria-label="Back to chat" title="Back to chat" @click="emit('close')" />
      <h2>Contact info</h2>
    </header>
    <div class="contact-info-scroll">
      <div class="contact-info-hero">
        <Avatar :label="title" size="xl" aria-hidden="true" />
        <strong>{{ title }}</strong>
        <small v-if="phone || primary">{{ [phone, primary?.title].filter(Boolean).join(' · ') }}</small>
        <div class="contact-info-actions">
          <a v-if="phone" class="contact-info-action" :href="'tel:' + phone.replace(/[^0-9+]/g, '')"><FeatherIcon name="phone" :size="18" />Call</a>
          <button v-if="canOrganize" type="button" class="contact-info-action" @click="emit('cases')"><FeatherIcon name="bookmark" :size="18" />Cases</button>
          <button v-if="canOrganize" type="button" class="contact-info-action" @click="emit('notes')"><FeatherIcon name="message-square" :size="18" />Notes</button>
        </div>
      </div>
      <dl v-if="channel" class="contact-info-facts"><div><dt>Channel</dt><dd>{{ channel }}</dd></div></dl>
      <ContactDetails v-if="contact" :contact="contact" @loaded="phone = $event.phone" />
      <WorkspaceState v-else compact title="No linked Contact" description="This chat has no Frappe Contact yet, so it has no business links." icon="user" />
    </div>
  </section>
</template>
