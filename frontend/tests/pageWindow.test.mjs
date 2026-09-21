import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createPageWindow} from '../src/components/pageWindow.js'
test('bounded traversal across a million records without allocating the dataset',async()=>{
 const cache=createPageWindow(async({cursor,limit})=>{const offset=cursor?.after?cursor.after+1:cursor?.before?Math.max(0,cursor.before-limit):cursor||0;return {items:Array.from({length:Math.min(limit,1000000-offset)},(_,i)=>({id:offset+i})),previous:offset?{before:offset}:null,next:offset+limit<1000000?{after:offset+limit-1}:null}})
 await cache.load();for(let i=0;i<30;i++)await cache.load(cache.state.next,'after')
 assert.equal(cache.state.items.length,200);assert.equal(cache.state.items.at(-1).id,1549)
 await cache.load(cache.state.previous,'before');assert.equal(cache.state.items[0].id,1300)
 await cache.load(999950);assert.equal(cache.state.items.at(-1).id,999999);assert.equal(cache.state.next,null)
})
test('late responses cannot overwrite the new query',async()=>{
 let finish;const cache=createPageWindow(({cursor})=>cursor==='old'?new Promise(r=>finish=r):Promise.resolve({items:[{id:2}],previous:null,next:null}))
 const old=cache.load('old');await cache.load('new');finish({items:[{id:1}]});await old;assert.equal(cache.state.items[0].id,2)
})
