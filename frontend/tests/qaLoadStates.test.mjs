import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref } from 'vue'

const source = readFileSync(new URL('../src/components/messages/StartConversation.vue', import.meta.url), 'utf8')
const destinations = source.slice(source.indexOf('const destinationsLoaded'), source.indexOf('async function loadRecords'))
function setup(coreApi) {
  return new Function('ref', 'coreApi', `
    const props = {businessName:'Local QA business'}, contact=ref('Local QA contact'), businessDoctype=ref('Customer'), businessName=ref(props.businessName), record=ref(''), endpoints=ref([]), endpoint=ref(''), error=ref('');
    const channelEnabled=()=>true; let generation=0;
    ${destinations}
    return {destinations, destinationsLoaded, endpoints, error};
  `)(ref, coreApi)
}
test('missing-number guidance appears only after a successful destination load', async () => {
  let fail = true
  const state = setup(async () => { if (fail) throw Error('Unavailable'); return [] })
  await state.destinations()
  assert.equal(state.destinationsLoaded.value, false)
  assert.equal(state.error.value, 'Unavailable')
  fail = false
  await state.destinations()
  assert.equal(state.destinationsLoaded.value, true)
  assert.equal(state.error.value, '')
  assert.deepEqual(state.endpoints.value, [])
})
test('a stale successful response cannot turn a failed current request into an empty result', async () => {
  let finish, calls=0
  const state=setup(() => ++calls === 1 ? new Promise(resolve => {finish=resolve}) : Promise.reject(Error('Offline')))
  const first=state.destinations()
  await state.destinations()
  finish([]); await first
  assert.equal(state.destinationsLoaded.value,false)
  assert.equal(state.error.value,'Offline')
})
test('delivery failures suppress the successful-empty state', () => {
  const template=readFileSync(new URL('../src/components/DeliveryWorkspace.vue', import.meta.url),'utf8')
  const condition=template.match(/<p v-if="([^"]+)"[^>]*>\s*No deliveries/)[1]
  const visible=new Function('rows','busy','error',`return ${condition}`)
  assert.equal(visible([],false,'Offline'),false)
  assert.equal(visible([],true,''),false)
  assert.equal(visible([],false,''),true)
  assert.equal(visible([{}],false,''),false)
})

test('network failure copy is neutral for readers as well as editors', async () => {
  const source=readFileSync(new URL('../src/services/coreApi.js',import.meta.url),'utf8').replace(/^import .*$/gm,'').replaceAll('export ', '')
  const request=new Function('fetch','serverError','invalidateReads',source+';return frappeRequest')(
    async()=>{throw Error('Offline')},()=>'',()=>{})
  await assert.rejects(request('relay_core.operations.recovery_status'), error => {
    assert.match(error.message,/Connection lost/)
    assert.doesNotMatch(error.message,/draft/)
    return true
  })
})

test('saved picker captions expose failed lookups and recover on retry', async () => {
  const source=readFileSync(new URL('../src/components/fields/EventPicker.vue',import.meta.url),'utf8')
  const load=source.slice(source.indexOf('async function loadCaptions'),source.indexOf('watch(['))
  let fail=true
  const state=new Function('ref','coreApi',`
    let generation=0;
    const props={modelValue:'private-id',method:'options',multiple:false},params=ref({kind:'doctype'}),captions=ref([]),error=ref(''),loading=ref(false),caption=row=>row;
    ${load}
    return {loadCaptions,captions,error};
  `)(ref,async()=>{if(fail)throw Error('Source DocType is not accessible');return {items:[{value:'private-id',label:'Customer'}]}})
  await state.loadCaptions()
  assert.equal(state.captions.value[0].label,'Unavailable selection')
  assert.equal(state.error.value,'Source DocType is not accessible')
  fail=false;await state.loadCaptions()
  assert.equal(state.captions.value[0].label,'Customer')
  assert.equal(state.error.value,'')
})
