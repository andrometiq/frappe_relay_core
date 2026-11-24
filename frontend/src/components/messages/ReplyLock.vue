<script setup>
import { FeatherIcon } from '@relay/ui'
// One line over the composer: where this reply goes. The thread fixes it, so there is nothing to choose.
defineProps({ lock: { type: Object, required: true } })
</script>

<template>
  <p class="reply-lock" :data-provider="lock.provider" role="note" :aria-label="`${lock.verb} ${lock.provider} to ${lock.to}${lock.from ? ' from ' + lock.from : ''}`">
    <FeatherIcon class="reply-lock-icon" :name="lock.icon" :size="14" aria-hidden="true" />
    <span>{{ lock.verb }} <strong>{{ lock.provider }}</strong> to <bdi>{{ lock.to }}</bdi><template v-if="lock.from"> from <strong><bdi>{{ lock.from }}</bdi></strong></template><template v-if="lock.note"> · {{ lock.note }}</template></span>
  </p>
</template>

<style scoped>
.reply-lock { display:flex; align-items:center; gap:6px; min-width:0; margin:0; padding:8px 14px 2px; color:var(--relay-ink-3, var(--ink-gray-5)); font-size:12px; line-height:1.35; }
.reply-lock > span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.reply-lock strong { color:var(--relay-ink, var(--ink-gray-8)); font-weight:600; }
.reply-lock-icon { flex:none; }
.reply-lock[data-provider="WhatsApp"] .reply-lock-icon { color:var(--relay-whatsapp, #1fa855); }
.reply-lock[data-provider="Telegram"] .reply-lock-icon { color:var(--relay-telegram, #229ed9); }
.reply-lock[data-provider="Email"] .reply-lock-icon { color:var(--relay-email, #e5484d); }
@media (max-width:768px) { .reply-lock { padding:6px 12px 0; } }
</style>
