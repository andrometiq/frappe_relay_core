import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, createSSRApp, defineComponent, effectScope, h, ref, watch } from 'vue'
import * as Vue from 'vue'
import { compile } from '@vue/compiler-dom'
import { renderToString } from '@vue/server-renderer'
import { filterTemplates, templateSyncLabel } from '../src/services/templateList.js'

const workspaceSource = (await readFile(new URL('../src/composables/whatsapp/useWhatsAppTemplatesWorkspace.js', import.meta.url), 'utf8'))
  .replace(/^import .*\n/gm, '').replace('export function', 'function')
const makeWorkspace = new Function('computed','ref','onMounted','useRealtimeRefresh','coreApi','templateParameterDescriptors',workspaceSource+'\nreturn useWhatsAppTemplatesWorkspace();')
const component = await readFile(new URL('../src/components/whatsapp/WhatsAppTemplates.vue', import.meta.url), 'utf8')
const script = component.split('<script setup>')[1].split('</script>')[0].replace(/^import [\s\S]*?from ["'][^"']+["'];/gm, '')
const makeList = new Function('computed','ref','watch','onBeforeUnmount','inject','whatsappKey','filterTemplates','window','location',
  script+'\nreturn {query,status,category,language,filteredTemplates,templateCursor,syncStatus,nextTemplates,busy,loadingMore,templates,access,columns,statuses,creating,selectedTemplate,supported,refresh,openTemplate};')
const template = component.slice(component.indexOf('<template>') + '<template>'.length, component.lastIndexOf('</template>'))
const render = new Function('Vue', compile(template, {mode:'function',prefixIdentifiers:true}).code)(Vue)
const Empty = defineComponent({setup:() => () => null})
const List = defineComponent({props:['items'],setup:(props, {slots}) => () => h('section', [
  props.items.length ? h('p', props.items.map(item => item.name).join(', ')) : slots['empty-action']?.(),
  h('footer', slots.footer?.()),
])})

for (const query of ['quantity', 'missing']) test(`filtered templates can reach page two without scrolling (${query})`, async t => {
  const scope = effectScope();t.after(() => scope.stop())
  const calls = []; let finish
  const workspace = scope.run(() => makeWorkspace(computed,ref,()=>{},()=>{},async(method,values) => {
    calls.push({method,values})
    return new Promise(resolve => finish = resolve)
  },()=>[]))
  workspace.templates.value = [{id:'1',name:'first_page',status:'APPROVED',language:'en_US'}]
  workspace.templateCursor.value = 'page-2'
  const state = scope.run(() => makeList(computed,ref,watch,()=>{},key => key === 'workspace' ? workspace : ref({manage:false}),
    'workspace',filterTemplates,{addEventListener() {}},{hash:'#/whatsapp'}))
  state.query.value=query
  let loadMore
  const Button = defineComponent({props:['label','loading','disabled'],setup:(props, {attrs}) => () => {
    if (props.label === 'Load more templates') loadMore = attrs.onClick
    return h('button', {...attrs, disabled:props.disabled || props.loading}, props.label)
  }})
  const html = () => renderToString(createSSRApp({setup:()=>({...state,templateSyncLabel}), render, components:{Button,FrappeListView:List,TemplateEditor:Empty,FrappeFormView:Empty,
    FrappeFormSection:Empty,FrappeReadField:Empty,RelaySelect:Empty,TextInput:Empty,FeatherIcon:Empty,Badge:Empty}}))
  const empty = await html()
  assert.equal((empty.match(/Load more templates/g)||[]).length,2,'Empty state and footer both expose pagination')
  assert.equal(state.filteredTemplates.value.length,0)
  const loading=loadMore()
  assert.equal(calls.length,1);assert.deepEqual(calls[0].values.arguments,{after:'page-2'})
  assert.match(await html(),/disabled[^>]*>Load more templates/)
  await loadMore();assert.equal(calls.length,1,'Repeated clicks do not duplicate requests')
  finish({data:[{id:'2',name:'quantity_25',status:'APPROVED',language:'en_US'}],paging:{}})
  await loading
  assert.equal(state.filteredTemplates.value.length,query === 'quantity' ? 1 : 0)
  const exhausted = await html()
  assert.doesNotMatch(exhausted,/Load more templates/)
  if(query === 'quantity')assert.match(exhausted,/quantity_25/)
})
