<script setup>
import { computed, ref, watch } from 'vue'
import { Avatar, Button, Dropdown, FeatherIcon } from '@relay/ui'
import ContactDetails from '../ContactDetails.vue'
import WorkspaceState from '../WorkspaceState.vue'
import { coreApi } from '../../services/coreApi'
import { linkedTitle } from '../../services/linkedTitle'

const props = defineProps({ title: String, contact: String, relayContact: String, primary: Object, channel: String, canOrganize: Boolean })
const emit = defineEmits(['close', 'cases', 'notes', 'assign', 'changed'])
const phone = ref(''), assignment = ref(null)
const assignee = computed(() => {
  if (!assignment.value) return ''
  const { assigned_to: user, team } = assignment.value
  return user ? linkedTitle('User', user, 'Assigned') : linkedTitle('Relay Team', team, 'Unassigned')
})
const menu = computed(() => [
  ...(props.canOrganize ? [{ label: 'Internal notes', icon: 'message-square', onClick: () => emit('notes') }] : []),
  ...(props.contact ? [{ label: 'Edit Contact in Desk', icon: 'external-link', onClick: () => { location.href = '/desk/contact/' + encodeURIComponent(props.contact) } }] : []),
])
watch(() => props.relayContact, async contact => {
  assignment.value = null
  if (!contact) return
  try { const state = await coreApi('inbox.read', { contact }); if (contact === props.relayContact) assignment.value = state.assignment || {} }
  catch { assignment.value = null }
}, { immediate: true })
</script>

<template>
  <section class="contact-info-page" aria-label="Contact info">
    <header class="contact-info-bar">
      <Button icon="arrow-left" variant="ghost" aria-label="Back to chat" title="Back to chat" @click="emit('close')" />
      <h2>Contact info</h2>
      <Dropdown v-if="menu.length" :options="menu"><Button icon="more-vertical" variant="ghost" aria-label="Contact actions" title="Contact actions" /></Dropdown>
    </header>
    <div class="contact-info-scroll">
      <div class="contact-info-hero">
        <Avatar :label="title" size="xl" aria-hidden="true" />
        <strong>{{ title }}</strong>
        <small v-if="phone || primary">{{ [phone, primary?.title].filter(Boolean).join(' · ') }}</small>
        <div class="contact-info-actions">
          <a v-if="phone" class="contact-info-action" :href="'tel:' + phone.replace(/[^0-9+]/g, '')"><FeatherIcon name="phone" :size="18" />Call</a>
          <button v-if="canOrganize" type="button" class="contact-info-action" @click="emit('cases')"><FeatherIcon name="bookmark" :size="18" />Ticket</button>
          <button v-if="canOrganize" type="button" class="contact-info-action" @click="emit('assign')"><FeatherIcon name="user" :size="18" />Assign</button>
        </div>
      </div>
      <ContactDetails v-if="contact" compact :contact="contact" :channel="channel" :assignee="assignee" @loaded="phone = $event.phone" @changed="emit('changed')" />
      <template v-else>
        <h4 class="info-group-title">Details</h4>
        <dl class="info-card">
          <div v-if="channel" class="info-kv"><dt>Channel</dt><dd>{{ channel }}</dd></div>
          <div v-if="assignee" class="info-kv"><dt>Assigned to</dt><dd>{{ assignee }}</dd></div>
        </dl>
        <WorkspaceState compact title="No linked Contact" description="This chat has no Frappe Contact yet, so it has no business links." icon="user" />
      </template>
    </div>
  </section>
</template>
