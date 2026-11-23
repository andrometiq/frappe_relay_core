<script setup>
import { computed } from 'vue'
import { FeatherIcon } from '@relay/ui'
import { endpointLabel, hasManyPeople, ourChannel, providerIcon } from '../../services/conversationThreads'
// The details panel's channel list: every endpoint of the record or chat, each on its own thread.
const props = defineProps({ threads: { type: Array, default: () => [] }, active: String, busy: Boolean, record: Object })
const emit = defineEmits(['select'])
const manyPeople = computed(() => hasManyPeople(props.threads))
</script>

<template>
  <section v-if="threads.length" class="thread-details" aria-label="Channels">
    <h3>Channels</h3>
    <button v-for="thread in threads" :key="thread.key" type="button" class="thread-detail" :data-provider="thread.provider"
      :aria-current="thread.key === active ? 'true' : undefined" :disabled="busy" @click="emit('select', thread)">
      <FeatherIcon class="thread-detail-icon" :name="providerIcon(thread.provider)" :size="15" aria-hidden="true" />
      <span class="thread-detail-copy">
        <strong><bdi>{{ endpointLabel(thread.endpoint, thread.provider) || thread.provider }}</bdi></strong>
        <small>{{ thread.provider }}<template v-if="manyPeople"> · {{ thread.contact_label }}</template><template v-if="ourChannel(thread)"> · to {{ ourChannel(thread) }}</template></small>
      </span>
      <span v-if="thread.unread" class="thread-detail-unread" :aria-label="`${thread.unread} unread`">{{ thread.unread }}</span>
    </button>
  </section>
  <section v-if="record" class="thread-details" aria-label="Record">
    <h3>Record</h3>
    <p class="thread-record"><FeatherIcon name="file-text" :size="15" aria-hidden="true" /><span><strong>{{ record.title }}</strong><small>{{ record.doctype }}<template v-if="record.title !== record.name"> · {{ record.name }}</template></small></span></p>
  </section>
</template>

<style scoped>
.thread-details { display:flex; flex-direction:column; gap:2px; padding:12px 16px; border-bottom:1px solid var(--relay-stroke); }
.thread-details h3 { margin:0 0 6px; color:var(--relay-ink-soft); font-size:11.5px; font-weight:600; }
.thread-detail { display:flex; align-items:center; gap:10px; min-height:44px; padding:4px 8px; margin:0 -8px; border:0; border-radius:6px; background:none; color:inherit; text-align:left; cursor:pointer; }
.thread-detail:hover { background:var(--relay-hover); }
.thread-detail[aria-current="true"] { background:var(--relay-accent-soft); }
.thread-detail-icon { flex:none; }
.thread-detail[data-provider="WhatsApp"] .thread-detail-icon { color:var(--relay-whatsapp); }
.thread-detail[data-provider="Telegram"] .thread-detail-icon { color:var(--relay-telegram); }
.thread-detail[data-provider="Email"] .thread-detail-icon { color:var(--relay-email); }
.thread-detail-copy, .thread-record span { display:flex; flex:1; flex-direction:column; min-width:0; }
.thread-detail-copy strong, .thread-record strong { overflow:hidden; font-size:13px; font-weight:600; text-overflow:ellipsis; white-space:nowrap; }
.thread-detail-copy small, .thread-record small { overflow:hidden; color:var(--relay-ink-3); font-size:12px; text-overflow:ellipsis; white-space:nowrap; }
.thread-detail-unread { min-width:18px; height:18px; padding:0 5px; border-radius:9px; background:var(--relay-accent); color:var(--relay-accent-ink); font-size:11px; font-weight:600; line-height:18px; text-align:center; }
.thread-record { display:flex; align-items:center; gap:10px; margin:0; color:inherit; }
</style>
