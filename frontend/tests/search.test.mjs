import test from 'node:test'
import assert from 'node:assert/strict'
import {fuzzyMatch,arrayPageSource} from '../src/components/search.js'
import {createPageWindow} from '../src/components/pageWindow.js'
test('fuzzy search matches ordered missing letters and keeps word order',()=>{assert(fuzzyMatch('Asha Kumar','akmr'));assert(fuzzyMatch('Willow Packaging','wlpkg'));assert(!fuzzyMatch('Asha Kumar','zz'));assert(fuzzyMatch('Asha Kumar',''))})
test('local adapter respects reverse boundary and bounded page cache',async()=>{const rows=Array.from({length:1200},(_,i)=>({id:String(i+1),name:'Record '+(i+1)}));const source=arrayPageSource(()=>rows,r=>r.name);const reverse=await source({cursor:{before:'20'},limit:50});assert.equal(reverse.items.length,19);assert.equal(reverse.items.at(-1).id,'19');const cache=createPageWindow(source,200);await cache.load();for(let i=0;i<10;i++){await cache.load(cache.state.next,'after');assert(cache.state.items.length<=200)}assert(cache.state.previous);const first=Number(cache.state.items[0].id);await cache.load(cache.state.previous,'before');assert(Number(cache.state.items[0].id)<first);assert(cache.state.items.length<=200)})

test('production contact adapter sends search and cursors to server without local filtering',async()=>{
 const {contactPageSource}=await import('../src/components/search.js')
 const controller=new AbortController();let seen
 const page={items:[{id:'RELAY-CON-0000000002',display_name:'Asha'}],previous:null,next:null}
 const source=contactPageSource(async(url,options)=>{seen={url,options};return {ok:true,json:async()=>({message:page})}})
 assert.deepEqual(await source({query:'a% & தமிழ்',cursor:{after:'RELAY-CON-0000000001'},limit:999,signal:controller.signal}),page)
 const params=new URL(seen.url,'http://localhost').searchParams
 assert.equal(params.get('query'),'a% & தமிழ்');assert.equal(params.get('limit'),'50')
 assert.equal(params.get('after'),'RELAY-CON-0000000001');assert.equal(seen.options.signal,controller.signal)
 assert.equal(seen.options.credentials,'same-origin')
 await assert.rejects(contactPageSource(async()=>({ok:false}))({}),/Unable to load/)
})
