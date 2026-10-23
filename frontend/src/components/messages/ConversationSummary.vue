<script setup>
import { ref, watch, onBeforeUnmount } from "vue";
import { Button, ErrorMessage } from "@relay/ui";
import { useRealtimeRefresh } from "../../composables/useRealtimeRefresh";
import RelaySelect from "../RelaySelect.vue";
import { coreApi } from "../../services/coreApi";
import { stableSubmission } from "../../services/submission";
const props = defineProps({ contact: String, businessDoctype: String, businessName: String });
const emit = defineEmits(["close", "open"]);
const channels = ref([]),
  channel = ref(""),
  period = ref("30"),
  summary = ref(null),
  busy = ref(false),
  error = ref("");
let generation = 0, readGeneration=0, deferredRefresh=false;
const scope = () => props.businessName
  ? { business_doctype: props.businessDoctype, business_name: props.businessName }
  : { contact: props.contact };
async function load() {
  const current = generation;
  const [choices, latest] = await Promise.all([
    coreApi("summaries.options", scope()),
    coreApi("summaries.latest", scope()),
  ]);
  if (current !== generation) return;
  channels.value = choices;
  channel.value = choices[0]?.value || "";
  summary.value = latest.summary;
}
async function refreshSummary() {
  if(busy.value){deferredRefresh=true;return}
  const current=generation,request=++readGeneration;
  try {
    const result=summary.value
      ? await coreApi('summaries.read',{name:summary.value.name})
      : (await coreApi('summaries.latest',scope())).summary;
    if(current!==generation||request!==readGeneration)return;
    summary.value=result;error.value='';
  } catch(e){if(current===generation&&request===readGeneration)error.value=e.message}
}
useRealtimeRefresh(['Relay Conversation Summary'],['reports'],refreshSummary);
watch(busy,value=>{if(!value&&deferredRefresh){deferredRefresh=false;refreshSummary()}});
async function run(fn) {
  if (busy.value) return;
  const current = generation;
  busy.value = true;
  error.value = "";
  try {
    await fn();
  } catch (e) {
    if (current === generation) error.value = e.message;
  } finally {
    if (current === generation) busy.value = false;
  }
}
async function generate() {
  ++readGeneration;
  const current = generation;
  await run(async () => {
    const payload = {
      ...scope(),
      channel: channel.value,
      period: period.value,
    };
    const result = await stableSubmission("relay-summary", payload, (key) =>
      coreApi("summaries.generate", { ...payload, request_key: key }, true),
    );
    if (current !== generation) return;
    summary.value = result;
  });
}
watch(
  () => [props.contact, props.businessDoctype, props.businessName],
  () => {
    ++generation;++readGeneration;deferredRefresh=false;
    summary.value = null;
    channels.value = [];
    busy.value = false;
    run(load);
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  ++generation;++readGeneration;
});
</script>
<template>
  <aside class="conversation-summary" aria-label="Conversation summary">
    <header>
      <h2>Conversation summary</h2>
      <Button icon="x" label="Close summary" @click="emit('close')" />
    </header>
    <div class="summary-content">
      <ErrorMessage :message="error" />
      <form v-if="channels.length" @submit.prevent="generate">
        <RelaySelect
          label="Channel"
          v-model="channel"
          :options="channels"
        /><RelaySelect
          label="Period"
          v-model="period"
          :options="[
            { value: '7', label: 'Last 7 days' },
            { value: '30', label: 'Last 30 days' },
            { value: '90', label: 'Last 90 days' },
            { value: 'all', label: 'All available history' },
          ]"
        /><Button
          label="Generate summary"
          variant="solid"
          type="submit"
          :disabled="busy || ['Pending', 'Running'].includes(summary?.status)"
        />
      </form>
      <p v-else-if="!busy" class="summary-empty">
        Conversation summaries are not enabled for this business’s WhatsApp channel. An
        administrator can enable them in the AI policy in Frappe Desk.
      </p>
      <template v-if="summary"
        ><p class="summary-meta">
          {{ summary.message_count }} messages ·
          {{
            summary.period === "all"
              ? "All history"
              : "Last " + summary.period + " days"
          }}
          · {{ summary.creation }}
        </p>
        <p v-if="summary.truncated" class="summary-meta">
          This summary covers a limited recent window, up to 200 messages.
          Earlier history is not included.
        </p>
        <p v-if="summary.stale" role="status">
          A source message changed. Generate a new summary to see the current
          conversation.
        </p>
        <p
          v-else-if="['Pending', 'Running'].includes(summary.status)"
          role="status"
        >
          Preparing your summary…
        </p>
        <p v-else-if="summary.status === 'Failed'" role="status">
          {{ summary.reason }}
        </p>
        <template v-else-if="summary.result"
          ><p class="summary-overview">{{ summary.result.overview }}</p>
          <section v-if="summary.result.action_items.length">
            <h3>Suggested action items</h3>
            <ul>
              <li
                v-for="(item, index) in summary.result.action_items"
                :key="index"
              >
                {{ item }}
              </li>
            </ul>
          </section>
          <section v-if="summary.result.topics.length">
            <h3>Topics</h3>
            <article
              v-for="(topic, index) in summary.result.topics"
              :key="index"
            >
              <h4>{{ topic.title }}</h4>
              <Button
                v-for="(message, i) in topic.messages"
                :key="message"
                :label="'View source ' + (i + 1)"
                @click="emit('open', message)"
              />
            </article>
          </section>
          <p class="summary-meta">
            AI-generated. Review the linked messages before acting. Suggested
            actions have not been executed.
          </p></template
        ></template
      >
    </div>
  </aside>
</template>
<style scoped>
.conversation-summary {
  position: absolute;
  inset: 0 0 0 auto;
  width: 380px;
  max-width: 100%;
  z-index: 21;
  @apply bg-surface-white text-ink-gray-8;
  @apply border-l border-outline-gray-2;
  box-shadow: -10px 0 35px #0000000a;
  display: flex;
  flex-direction: column;
}
.conversation-summary header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px;
  @apply border-b border-outline-gray-2;
}
.conversation-summary h2 {
  font-size: 15px;
  font-weight: 600;
}
.summary-content {
  padding: 18px;
  overflow: auto;
  min-height: 0;
}
.summary-content form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 22px;
}
.summary-meta,
.summary-empty {
  font-size: 12px;
  @apply text-ink-gray-5;
  line-height: 1.5;
  margin: 12px 0;
}
.summary-overview {
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
}
.summary-content section {
  margin-top: 20px;
}
.summary-content h3 {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
}
.summary-content h4 {
  font-size: 13px;
  margin-bottom: 6px;
}
.summary-content li {
  font-size: 13px;
  line-height: 1.6;
  margin: 6px 0;
}
.summary-content ul {
  list-style: disc;
  padding-left: 18px;
}
.summary-content article {
  padding: 10px 0;
  @apply border-b border-outline-gray-2;
}
.summary-content article button {
  margin: 3px;
}
</style>
