<script setup>
import { FeatherIcon } from '@relay/ui'
import { useLoadMore } from '../../composables/useLoadMore'
import { recordTitle } from '../../services/recordTitle'
import { computed, ref, watch, onBeforeUnmount, useId, nextTick } from 'vue'
const props = defineProps({field:Object, modelValue:[String,Object,Array], multiple:Boolean})
const emit = defineEmits(['update:modelValue'])
const id = useId(), query = ref(''), options = ref([]), open = ref(false), loading = ref(false), error = ref(''), active = ref(-1)
const labels = new Map()
// Results float above every container, so a dialog or card never clips them.
const input = ref(null), results = ref(null), place = ref({})
function position() {
  const box = input.value?.getBoundingClientRect()
  if (!box) return
  const below = innerHeight - box.bottom, up = below < 220 && box.top > below
  place.value = {left: box.left + 'px', width: box.width + 'px', maxHeight: Math.min(260, (up ? box.top : below) - 12) + 'px',
    ...(up ? {bottom: innerHeight - box.top + 4 + 'px'} : {top: box.bottom + 4 + 'px'})}
}
function onScroll(event) {
  if (results.value?.contains(event.target)) return
  close()
}
watch(open, value => {
  if (typeof window === 'undefined') return
  const method = value ? 'addEventListener' : 'removeEventListener'
  window[method]('scroll', onScroll, true); window[method]('resize', position)
  if (value) nextTick(position)
})
const inside = (event, target) => event.currentTarget.contains(target) || results.value?.contains(target)
let timer, controller, generation = 0, composing = false
const normalize = item => typeof item === 'string' ? {value:item,label:recordTitle(item)} : {...item,label:recordTitle(item)}
const selected = computed(() => (props.multiple ? props.modelValue || [] : [props.modelValue]).filter(Boolean).map(v => typeof v === 'object' ? v.value : v))
const display = value => recordTitle(labels.get(value) || (props.field.options || []).map(normalize).find(row => row.value === value)?.label || value, 'Saved selection')
function cancel() {clearTimeout(timer); controller?.abort(); ++generation; loading.value=false}
function close() {open.value=false;cancel();options.value=[];active.value=-1}
async function search() {
  cancel()
  if (!open.value || props.field.readOnly) return
  const current = generation
  controller = new AbortController()
  loading.value=true; error.value=''
  try {
    const result = props.field.search
      ? await props.field.search(query.value, controller.signal)
      : (props.field.options || []).map(normalize).filter(o => o.label.toLowerCase().includes(query.value.toLowerCase())).slice(0, props.field.loadMore ? undefined : 30)
    if (current !== generation || !open.value) return
    options.value=(Array.isArray(result) ? result : result.items || []).slice(0, props.field.loadMore ? undefined : 30).map(normalize)
    for (const row of options.value) labels.set(row.value,recordTitle(row))
    // Only selected labels survive searches: memory does not grow with the directory.
    const keep = new Set([...selected.value,...options.value.map(o=>o.value)])
    for (const key of labels.keys()) if (!keep.has(key)) labels.delete(key)
    active.value=options.value.length ? 0 : -1
  } catch(e) {if(current===generation && e.name!=='AbortError') error.value=props.field.errorMessage || e.message || 'Search failed. Try again.'}
  finally {if(current===generation) loading.value=false}
}
function schedule(event) {if(composing || event?.isComposing)return;open.value=true;cancel();options.value=[];active.value=-1;timer=setTimeout(search,300)}
function focus() {if(props.field.readOnly)return;open.value=true;search()}
function choose(row) {
  if(props.field.readOnly)return
  labels.set(row.value,recordTitle(row))
  emit('update:modelValue',props.multiple ? [...new Set([...selected.value,row.value])] : row.value)
  query.value='';close()
}
function remove(value) {if(!props.field.readOnly)emit('update:modelValue',props.multiple ? selected.value.filter(v=>v!==value) : '')}
function compositionStart() {composing=true;cancel();options.value=[];active.value=-1}
function compositionEnd() {composing=false;schedule()}
function keydown(event) {
  if(composing || event.isComposing || event.keyCode===229)return
  if(event.key==='Escape'){event.preventDefault();close()}
  if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();if(!open.value){focus();return}active.value=Math.max(0,Math.min(options.value.length-1,active.value+(event.key==='ArrowDown'?1:-1)))}
  if(event.key==='Enter' && open.value){event.preventDefault();if(!event.repeat && options.value[active.value])choose(options.value[active.value])}
}
watch(()=>props.field.search,()=>{close();query.value=''})
watch(()=>props.field.readOnly,value=>{if(value)close()})
watch(()=>props.field.initialOptions,rows=>{
  for(const row of rows||[]){const option=normalize(row);labels.set(option.value,option.label)}
},{immediate:true,deep:true})
watch(() => props.field.options, () => { if (open.value && !props.field.search) search() })
async function loadMore() {
  const current = generation
  loading.value = true
  try {
    const rows = await props.field.loadMore(query.value, controller?.signal)
    if (current !== generation || !open.value || !props.field.search || !Array.isArray(rows)) return
    const known = new Set(options.value.map(row => row.value))
    options.value = [...options.value, ...rows.map(normalize).filter(row => !known.has(row.value))]
    for (const row of options.value) labels.set(row.value, row.label)
  } catch(e) { if (current === generation && e.name !== 'AbortError') error.value = props.field.errorMessage || e.message }
  finally { if (current === generation) loading.value = false }
}
const moreSentinel = useLoadMore({ loading: () => loading.value || props.field.loading, hasMore: () => open.value && props.field.hasMore, error: () => error.value || props.field.error, load: loadMore })
onBeforeUnmount(() => {
  cancel()
  window.removeEventListener('scroll', onScroll, true)
  window.removeEventListener('resize', position)
})
</script>
<template>
  <div class="remote-choice" @focusout="event => {if(!inside(event, event.relatedTarget))close()}">
    <label v-if="field.label" :for="id">{{field.label}}<span v-if="field.required"> *</span></label>
    <div v-if="selected.length" class="choice-selected">
      <span v-for="value in selected" :key="value" class="choice-chip">{{display(value)}}<button type="button" :aria-label="'Remove '+display(value)" :disabled="field.readOnly" @click="remove(value)">×</button></span>
    </div>
    <input ref="input" :id="id" v-model="query" role="combobox" autocomplete="off" :maxlength="field.maxLength || 80" :aria-expanded="open" :aria-controls="id+'-options'" :aria-activedescendant="open&&active>=0?id+'-'+active:undefined" :disabled="field.readOnly" :placeholder="field.placeholder || 'Type to search…'" @focus="focus" @input="schedule" @compositionstart="compositionStart" @compositionend="compositionEnd" @keydown="keydown" />
    <Teleport to="body">
    <div v-if="open" ref="results" class="choice-results" :style="place" @mousedown.prevent>
      <p v-if="loading || field.loading" role="status">Searching…</p>
      <p v-if="error" role="alert">{{error}}</p>
      <ul :id="id+'-options'" role="listbox" :aria-multiselectable="multiple || undefined">
        <li v-for="(option,index) in options" :id="id+'-'+index" :key="option.value" role="option" :aria-selected="selected.includes(option.value)" :class="{active:index===active}" @mousedown.prevent="choose(option)"><FeatherIcon v-if="option.icon" :name="option.icon" :size="16" aria-hidden="true" class="choice-icon" />{{option.label}}<small v-if="option.description && option.description!==option.label" class="block text-xs text-ink-gray-5">{{option.description}}</small><span v-if="selected.includes(option.value)"> ✓</span></li>
      </ul>
      <p v-if="!loading&&!field.loading&&!error&&!options.length">No results found.</p>
      <div v-if="field.hasMore" ref="moreSentinel" class="h-px" aria-hidden="true" />
      <p v-if="!field.loadMore && options.length===30" class="choice-hint">Showing 30 matches. Refine your search.</p>
    </div>
    </Teleport>
  </div>
</template>
<style scoped>
.remote-choice{position:relative;min-width:0;display:grid;gap:6px;@apply text-base text-ink-gray-8}
.remote-choice>label{@apply text-xs text-ink-gray-5}
.remote-choice>input{width:100%;min-width:0;height:32px;border:1px solid var(--relay-stroke,var(--outline-gray-2));border-bottom-color:var(--relay-stroke-strong,var(--outline-gray-2));border-radius:6px;background:var(--relay-layer,var(--surface-white));padding:6px 9px;color:var(--ink-gray-8);font:inherit;outline:0}.remote-choice>input:focus{border-color:var(--outline-blue-2);background:var(--surface-white);box-shadow:0 0 0 2px color-mix(in srgb,var(--outline-blue-2) 18%,transparent)}
.choice-results{position:fixed;z-index:1200;max-height:260px;overflow:auto;@apply bg-surface-modal border border-outline-gray-modals rounded-lg shadow-lg p-1 text-ink-gray-8;animation:choice-appear 120ms ease-out}
.choice-results li,.choice-results p{@apply px-2 py-1.5;overflow-wrap:anywhere}
.choice-results li{@apply cursor-pointer rounded}
.choice-results li:hover,.choice-results li.active{@apply bg-surface-gray-3}
.choice-selected{display:flex;flex-wrap:wrap;gap:5px}
.choice-chip{display:flex;gap:6px;align-items:center;max-width:100%;overflow-wrap:anywhere;@apply bg-surface-gray-2 text-ink-gray-8 rounded px-2 py-0.5 text-sm}
.choice-chip button{@apply rounded text-ink-gray-5 hover:bg-surface-gray-3 hover:text-ink-gray-9 px-1 disabled:opacity-50}
.choice-icon{display:inline-block;vertical-align:middle;margin-right:6px}
.choice-hint{@apply text-xs text-ink-gray-5}
.choice-results [role=alert]{@apply text-ink-red-2}
@keyframes choice-appear{from{opacity:0;transform:translateY(-3px)}to{opacity:1;transform:translateY(0)}}
@media(max-width:768px){.choice-results li{min-height:44px;min-width:44px;padding:12px 8px}.choice-chip button{min-height:44px;min-width:44px}}
@media(prefers-reduced-motion:reduce){.choice-results{animation:none}}
</style>
