import { recordTitle } from '../src/services/recordTitle.js'
import { useLoadMore } from '../src/composables/useLoadMore.js'
import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {computed,ref,watch} from 'vue'
const source=(await readFile(new URL('../src/components/fields/ChoiceField.vue',import.meta.url),'utf8'))
 .split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm,'')
const make=new Function('recordTitle','useLoadMore','computed','ref','watch','onBeforeUnmount','useId','defineProps','defineEmits',source+'\nreturn {focus,schedule,keydown,compositionStart,compositionEnd,query,close,loadMore,options,onScroll,open,results};').bind(null, recordTitle, useLoadMore)
for(const multiple of [false,true])test(`IME completion and Enter selection (${multiple?'multiple':'single'})`,async()=>{
 const queries=[],events=[]
 const props={multiple,modelValue:multiple?['existing']:'',field:{search:async q=>{queries.push(q);return [{value:'new',label:'தமிழ்'}]}}}
 const field=make(computed,ref,watch,()=>{},()=> 'test',()=>props,()=> (...args)=>events.push(args))
 const key=(extra={})=>({key:'Enter',preventDefault(){},...extra})
 field.focus();await new Promise(r=>setTimeout(r,0))
 field.keydown(key({isComposing:true}));field.keydown(key({keyCode:229}))
 assert.equal(events.length,0)
 field.compositionStart();field.query.value='த';field.schedule({isComposing:true})
 await new Promise(r=>setTimeout(r,350))
 assert.deepEqual(queries,[''],'No partial composition search')
 field.query.value='தமிழ்';field.compositionEnd()
 await new Promise(r=>setTimeout(r,350))
 assert.deepEqual(queries,['','தமிழ்'])
 field.keydown(key({repeat:true}));assert.equal(events.length,0)
 field.keydown(key())
 assert.deepEqual(events,[['update:modelValue',multiple?['existing','new']:'new']])
 field.close()
})

test('remote picker appends pages without duplicate values or losing captions', async () => {
 const props = {modelValue:'', field:{search:async () => [{value:'one',label:'Asha'}], loadMore:async () => [{value:'one',label:'Asha'},{value:'two',label:'Ravi'}]}}
 const field = make(computed,ref,watch,()=>{},()=> 'paging',()=>props,()=>()=>{})
 await field.focus(); await new Promise(resolve => setTimeout(resolve, 0))
 await field.loadMore()
 assert.deepEqual(field.options.value.map(row => row.label), ['Asha','Ravi'])
 field.close()
})


test('scrolling the page closes a floating picker but scrolling its own options does not', async () => {
 const props={modelValue:'',field:{options:['One','Two']}}
 const field=make(computed,ref,watch,()=>{},()=> 'scrolling',()=>props,()=>()=>{})
 field.focus();await new Promise(resolve=>setTimeout(resolve,0))
 const popup={};field.results.value={contains:target=>target===popup}
 field.onScroll({target:popup});assert.equal(field.open.value,true)
 field.onScroll({target:{}});assert.equal(field.open.value,false)
})
