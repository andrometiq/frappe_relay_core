// A bounded cursor cache for API adapters. Fetchers must return ordered, unique
// records and opaque previous/next cursors; no total-size array is allocated.
export function createPageWindow(fetchPage, limit=200) {
  let generation=0, controller, state={items:[],previous:null,next:null}
  return {
    get state(){return state},
    async load(cursor=null,direction='reset') {
      const ticket=++generation
      controller?.abort();controller=new AbortController()
      const page=await fetchPage({cursor,signal:controller.signal,limit:50})
      if(ticket!==generation)return state
      const merged=direction==='before'?[...page.items,...state.items]:direction==='after'?[...state.items,...page.items]:page.items
      const seen=new Set();let items=merged.filter(x=>!seen.has(x.id)&&seen.add(x.id))
      // When trimming, the dropped boundary must be reloadable by record cursor.
      let previous=direction==='after'?state.previous:page.previous
      let next=direction==='before'?state.next:page.next
      if(items.length>limit){if(direction==='before'){items=items.slice(0,limit);next={after:items.at(-1).id}}else{items=items.slice(-limit);previous={before:items[0].id}}}
      state={items,previous,next};return state
    },
    dispose(){generation++;controller?.abort();state={items:[],previous:null,next:null}}
  }
}
