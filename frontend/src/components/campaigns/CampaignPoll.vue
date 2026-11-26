<script setup>
import { computed, ref, watch } from 'vue';
import { Button, FormControl, TextInput } from '@relay/ui';
import RelaySelect from '../RelaySelect.vue';
import { pollOptions } from '../../services/campaignProgress';

const props = defineProps({ campaign: Object, busy: Boolean });
const emit = defineEmits(['save']);
const poll = computed(() => props.campaign.poll);
const editable = computed(() => props.campaign.status === 'Draft');
const optIn = ref(''), optOut = ref(''), question = ref(''), options = ref(''), thanks = ref('');
watch(() => [props.campaign.name, poll.value?.question], () => {
  optIn.value = poll.value.opt_in || ''; optOut.value = poll.value.opt_out || ''; question.value = poll.value.question || '';
  options.value = (poll.value.options || []).join('\n'); thanks.value = poll.value.thanks || '';
}, { immediate: true });
watch(optIn, (value) => { if (optOut.value === value) optOut.value = ''; });
const buttonOptions = computed(() => (poll.value.buttons || []).map((text) => ({ value: text, label: text })));
const optOutOptions = computed(() => [{ value: '', label: 'None' }, ...buttonOptions.value.filter((row) => row.value !== optIn.value)]);
const choices = computed(() => pollOptions(options.value));
// Meta allows 20 characters on a reply button (up to 3 options) and 24 on a list row (4 to 10 options).
const limit = computed(() => choices.value.length <= 3 ? 20 : 24);
const problems = computed(() => [
  !optIn.value && 'choose the button that opens the poll',
  !question.value.trim() && 'add the question',
  (choices.value.length < 2 || choices.value.length > 10) && 'add 2 to 10 options',
  choices.value.some((option) => option.length > limit.value) && `keep each option to ${limit.value} characters`,
].filter(Boolean));
const missingList = new Intl.ListFormat('en', { type: 'conjunction' });
const total = (row) => row.confirmed + row.pending;
function save() {
  emit('save', { opt_in: optIn.value, opt_out: optOut.value, question: question.value.trim(), options: choices.value, thanks: thanks.value.trim() });
}
</script>

<template>
  <section class="poll" aria-label="Poll">
    <template v-if="editable">
      <p class="poll-hint">When a person taps the opt-in button, Relay sends the question with the options as buttons. After a pick, Relay asks Confirm or Change. A confirmed answer is final. The opt-out button opts the number out of campaigns.</p>
      <div class="poll-grid">
        <RelaySelect v-model="optIn" label="Opt-in button" :options="buttonOptions" />
        <RelaySelect v-model="optOut" label="Opt-out button (optional)" :options="optOutOptions" />
      </div>
      <FormControl v-model="question" type="textarea" :rows="2" label="Question" maxlength="1024" />
      <FormControl v-model="options" type="textarea" :rows="4" label="Options, one per line" placeholder="Small&#10;Large" />
      <p class="poll-hint">2 to 10 options. Up to 3 options show as buttons of 20 characters; 4 to 10 show as a list of 24 characters.</p>
      <label class="poll-field"><span>Thank-you message</span><TextInput v-model="thanks" maxlength="1024" placeholder="Thank you, your response is recorded." /></label>
      <div class="poll-save">
        <Button label="Save poll" variant="solid" :loading="busy" :disabled="problems.length > 0" @click="save" />
        <p v-if="problems.length" class="poll-hint" role="status">To save the poll, {{ missingList.format(problems) }}.</p>
        <p v-else-if="!poll.question" class="poll-hint" role="status">Save the poll before you start sending.</p>
      </div>
    </template>
    <template v-else>
      <p class="poll-question">{{ poll.question }}</p>
      <p class="poll-hint">Opt-in button: {{ poll.opt_in }}<template v-if="poll.opt_out"> · Opt-out button: {{ poll.opt_out }}</template></p>
    </template>
    <table v-if="poll.question">
      <caption class="sr-only">Poll answers</caption>
      <thead><tr><th scope="col">Option</th><th scope="col">Confirmed</th><th scope="col">Not confirmed</th><th scope="col">Total</th></tr></thead>
      <tbody>
        <tr v-for="row in poll.results" :key="row.label"><td>{{ row.label }}</td><td>{{ row.confirmed }}</td><td>{{ row.pending }}</td><td>{{ total(row) }}</td></tr>
      </tbody>
    </table>
    <p v-if="poll.question" class="poll-hint" role="status">Opened the poll, no pick yet: {{ poll.waiting }} · Opted out: {{ poll.opted_out }}</p>
  </section>
</template>

<style scoped>
.poll { display: grid; gap: 12px; min-width: 0; color: var(--ink-gray-8); font-size: 13px; }
.poll-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; }
.poll-field { display: grid; gap: 6px; color: var(--ink-gray-6); }
.poll-save { display: grid; gap: 8px; justify-items: start; }
.poll-hint { color: var(--ink-gray-5); overflow-wrap: anywhere; }
.poll-question { font-weight: 600; overflow-wrap: anywhere; }
.poll table { width: 100%; table-layout: fixed; border-collapse: collapse; }
.poll th, .poll td { padding: 8px 6px; border-bottom: 1px solid var(--outline-gray-2); text-align: left; overflow-wrap: anywhere; }
.poll th:first-child { width: 40%; }
@media (max-width: 768px) { .poll-grid { grid-template-columns: 1fr; } }
</style>
