import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { ref, computed } from 'vue'
import { businessScope } from '../src/services/businessScope.js'
import { coreApi } from '../src/services/coreApi.js'

const components = [
  ['InternalNotes', 'submit', 'body.value = "Quantity 30, total 1500";', 'collaboration.add'],
  ['ConversationCases', 'save', 'record.value = {isNew:true,definition:{fields:{properties:{}},stages:[]}}; newType.value="Orders";newTitle.value="Order follow-up"; values.value={quantity:30};', 'cases.create_manual'],
  ['ConversationTopics', 'save', 'edit();draft.value.title="Order follow-up";', 'topics.save'],
]
for (const [component, action, setup, method] of components) {
  const script = (await readFile(new URL(`../src/components/messages/${component}.vue`, import.meta.url), 'utf8'))
    .split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
  for (const business of ['Customer', 'Supplier']) test(`${component} sends ${business} scope in the real HTTP request`, async () => {
    const calls = []
    const previousFetch = globalThis.fetch, previousWindow = globalThis.window
    globalThis.window = { frappe: { csrf_token: 'local-only' } }
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options })
      return { ok: true, status: 200, json: async () => ({message: {items:[],field_values:{quantity:30},definition:{fields:{properties:{}},stages:[]}}}) }
    }
    const props = {contact:'shared-contact',businessDoctype:business,businessName:`Sim ${business}`,messages:[]}
    const args = {ref,computed,watch:()=>{},onMounted:()=>{},onBeforeUnmount:()=>{},defineProps:()=>props,defineEmits:()=>()=>{},
      useRealtimeRefresh:()=>{},businessScope,coreApi,randomUUID:()=> 'local-request',stableSubmission:(_kind,_data,send)=>send('local-request')}
    try {
      const run = new Function(...Object.keys(args), script + `\nreturn async()=>{${setup} await ${action}();return error.value}`)(...Object.values(args))
      assert.equal(await run(), '')
      const request = calls.find(call => call.url === `/api/method/relay_core.${method}`)
      assert.equal(request.options.method, 'POST')
      const body = JSON.parse(request.options.body)
      assert.deepEqual(businessScope(props), method === 'topics.save'
        ? {business_doctype:body.values.business_doctype,business_name:body.values.business_name}
        : {business_doctype:body.business_doctype,business_name:body.business_name})
    } finally { globalThis.fetch=previousFetch;globalThis.window=previousWindow }
  })
}
