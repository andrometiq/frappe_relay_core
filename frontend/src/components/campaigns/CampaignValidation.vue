<script setup>
import { Button } from '@relay/ui';
defineProps({ campaign: Object, busy: Boolean });
defineEmits(['download']);
</script>

<template>
  <section class="validation" aria-label="Validation results">
    <p v-if="campaign.status === 'Importing'" role="status">Validating every row and file. Nothing is being sent.</p>
    <template v-else-if="campaign.validated">
      <p v-if="campaign.status === 'Draft'" role="status"><strong>{{ campaign.counts.total || 0 }} ready / {{ campaign.counts.skipped || 0 }} with errors</strong>. Rows with errors will be skipped.</p>
      <template v-if="campaign.error_rows?.length">
        <Button label="Download error report (.xlsx)" variant="outline" :disabled="busy" @click="$emit('download')" />
        <p>First {{ campaign.error_rows.length }} error rows. Download the report for all row errors.</p>
        <table>
          <caption class="sr-only">Rows with errors</caption>
          <thead><tr><th scope="col">Row</th><th scope="col">Mobile number</th><th scope="col">Reason</th></tr></thead>
          <tbody><tr v-for="row in campaign.error_rows" :key="row.sheet_row">
            <td>{{ row.sheet_row }}</td><td>{{ row.destination || 'Missing' }}</td><td>{{ row.reason }}</td>
          </tr></tbody>
        </table>
      </template>
      <ul v-if="campaign.file_issues?.length" aria-label="File errors">
        <li v-for="(issue, index) in campaign.file_issues" :key="index">{{ issue.filename }}: {{ issue.reason }}</li>
      </ul>
    </template>
    <p v-else role="status">Upload the sheet, then select Validate. Sending stays disabled until at least one row is ready.</p>
  </section>
</template>

<style scoped>
.validation { display: grid; gap: 12px; min-width: 0; color: var(--ink-gray-8); font-size: 13px; }
.validation > button { justify-self: start; min-height: 44px; }
.validation p, .validation li { overflow-wrap: anywhere; }
.validation table { width: 100%; table-layout: fixed; border-collapse: collapse; }
.validation th, .validation td { padding: 10px 6px; border-bottom: 1px solid var(--outline-gray-2); text-align: left; vertical-align: top; overflow-wrap: anywhere; }
.validation th:first-child { width: 15%; }
.validation th:nth-child(2) { width: 32%; }
.validation ul { list-style: disc; padding-left: 20px; }
@media (max-width: 480px) { .validation th, .validation td { padding: 10px 3px; } }
</style>
