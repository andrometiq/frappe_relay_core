import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {ref,computed,watch,nextTick} from 'vue'
import {attachmentMaxBytes,sizeError,sizeLabel} from '../src/components/messages/attachmentFormats.js'
import {headerChannelKind} from '../src/services/templateMedia.js'
import {whatsappCapabilities} from './channelCapabilities.js'
const source=(await readFile(new URL('../src/components/whatsapp/TemplateEditor.vue',import.meta.url),'utf8')).split('<script setup>')[1].split('</script>')[0].replace(/^import [\s\S]*?from ["'][^"']+["'];/gm,'')
const make=new Function('ref','computed','watch','inject','headerChannelKind','attachmentMaxBytes','sizeError','sizeLabel','defineProps','defineEmits','coreApi','templateForm','templateSampleFields','FileReader',source+'\nreturn {uploadSample,form,busy,error,sampleName};')
class Reader {readAsDataURL(){this.result='data:application/pdf;base64,JVBERi0xLjc=';this.onload()}}
function setup(api){return make(ref,computed,watch,()=>ref(whatsappCapabilities),headerChannelKind,attachmentMaxBytes,sizeError,sizeLabel,()=>({enabled:true}),()=>()=>{},api,()=>({header_type:'DOCUMENT',header_media_example:'old-handle'}),()=>[],Reader)}
test('sample upload returns handle and changing header invalidates it',async()=>{
 const calls=[];const state=setup(async(...args)=>{calls.push(args);return {handle:'new-handle'}})
 await state.uploadSample({target:{files:[{name:'sample.pdf',type:'application/pdf',size:8}],value:'file'}})
 assert.equal(state.form.value.header_media_example,'new-handle')
 assert.equal(calls[0][1].operation,'templates.media_upload')
 assert.equal(calls[0][1].arguments.content_base64,'JVBERi0xLjc=')
 state.form.value.header_type='IMAGE';await nextTick()
 assert.equal(state.form.value.header_media_example,'')
})
test('failed or invalid replacement preserves prior sample',async()=>{
 let calls=0;const state=setup(async()=>{calls++;throw Error('Upload unavailable')})
 for(const size of [8,whatsappCapabilities.max_file_bytes+1])await state.uploadSample({target:{files:[{name:'sample.pdf',type:'application/pdf',size}],value:''}})
 assert.equal(calls,1);assert.equal(state.form.value.header_media_example,'old-handle');assert.equal(state.busy.value,false);assert.ok(state.error.value)
})
