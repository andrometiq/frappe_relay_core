<script setup>
import { computed, ref, watch } from 'vue'
import { Button, ErrorMessage, FeatherIcon, TextInput } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { useDebouncedSearch } from '../../composables/useDebouncedSearch'

// Tick the groups of a business type's first grouping field; the team sees every record in a ticked group.
const props = defineProps({ doctype: { type: String, required: true }, label: String, disabled: Boolean })
const values = defineModel({ type: Array, default: () => [] })
const query = ref(''), items = ref([]), next = ref(null), loading = ref(false), error = ref('')
const counts = ref({})
const picked = computed(() => values.value.reduce((total, value) => total + (counts.value[value] || 0), 0))
let generation = 0

async function load(append = false) {
  const request = append ? generation : ++generation
  loading.value = true; error.value = ''
  try {
    const result = await coreApi('business_groups.directory', { doctype: props.doctype, query: query.value, after: append ? next.value : undefined })
    if (request !== generation) return
    // A record without a group value cannot be given to a team as a group.
    const rows = (result.items || []).filter(row => row.value)
    items.value = append ? [...items.value, ...rows] : rows
    next.value = result.next
    for (const row of rows) counts.value[row.value] = row.record_count
  } catch (e) { if (request === generation) error.value = e.message }
  finally { if (request === generation) loading.value = false }
}
function toggle(value, checked) {
  values.value = checked ? [...values.value, value] : values.value.filter(item => item !== value)
}
useDebouncedSearch(query, () => load(), () => { ++generation })
watch(() => props.doctype, () => { query.value = ''; load() }, { immediate: true })
</script>

<template>
  <div class="team-groups-picker">
    <TextInput v-model="query" type="search" maxlength="80" placeholder="Search groups" aria-label="Search groups" :disabled="disabled"><template #prefix><FeatherIcon name="search" /></template></TextInput>
    <ul class="team-group-options" :aria-label="'Groups of ' + (label || doctype)">
      <li v-for="row in items" :key="row.value">
        <label><input type="checkbox" :checked="values.includes(row.value)" :disabled="disabled" @change="toggle(row.value, $event.target.checked)" /><span>{{ row.label }}</span><small>{{ row.record_count }}</small></label>
      </li>
    </ul>
    <p v-if="!loading && !items.length && !error" class="panel-hint">No groups match.</p>
    <Button v-if="next" variant="ghost" label="Show more groups" :loading="loading" @click="load(true)" />
    <ErrorMessage :message="error" />
    <p class="panel-hint">{{ values.length }} {{ values.length === 1 ? 'group' : 'groups' }}<template v-if="picked"> · {{ picked }} records</template> · new records in these groups join automatically</p>
  </div>
</template>

<style scoped>
.team-groups-picker { display:flex; flex-direction:column; gap:6px; padding:8px 10px; border:1px solid var(--relay-stroke); border-radius:6px; background:var(--relay-layer); }
.team-group-options { display:flex; flex-direction:column; max-height:240px; overflow:auto; }
.team-group-options label { display:flex; align-items:center; gap:10px; min-height:32px; font-size:13px; cursor:pointer; }
.team-group-options input { width:16px; height:16px; accent-color:var(--relay-accent); }
.team-group-options span { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.team-group-options small { color:var(--relay-ink-soft); font-size:12px; }
@media (max-width: 640px) { .team-group-options label { min-height:44px; } }
</style>
