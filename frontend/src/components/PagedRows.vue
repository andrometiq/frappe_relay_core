<script setup>
import { useLoadMore } from '../composables/useLoadMore'
import {ref,watch,nextTick,onMounted,onBeforeUnmount} from 'vue'
import {Button} from '@relay/ui'
import FrappeRows from './FrappeRows.vue'
import {createPageWindow} from './pageWindow'
const props=defineProps({fetchPage:{type:Function,required:true},query:{default:''},revision:{default:''},rowHeight:{default:76},label:{default:'Records'}})
const root=ref(),items=ref([]),previous=ref(null),next=ref(null),busy=ref(false),error=ref('')
let generation=0,timer
const cache=createPageWindow(args=>props.fetchPage({...args,query:props.query}),200)
async function load(direction='reset'){
 if(busy.value&&direction!=='reset')return
 const ticket=++generation;busy.value=true;error.value=''
 const element=root.value?.element,old=items.value,anchor=old[Math.floor((element?.scrollTop||0)/props.rowHeight)],oldIndex=anchor?old.indexOf(anchor):0,oldTop=element?.scrollTop||0
 try{const state=await cache.load(direction==='before'?previous.value:direction==='after'?next.value:null,direction);if(ticket!==generation)return;items.value=state.items;previous.value=state.previous;next.value=state.next;await nextTick();if(element){const newIndex=anchor?items.value.findIndex(x=>x.id===anchor.id):-1;element.scrollTop=direction==='reset'?0:newIndex>=0?Math.max(0,oldTop+(newIndex-oldIndex)*props.rowHeight):direction==='before'?0:Math.max(0,element.scrollHeight-element.clientHeight)}}catch(e){if(ticket===generation&&e.name!=='AbortError')error.value=e.message}finally{if(ticket===generation)busy.value=false}
}

watch(()=>[props.query,props.revision],()=>{clearTimeout(timer);++generation;previous.value=null;next.value=null;busy.value=true;timer=setTimeout(()=>load(),300)})
onMounted(()=>load())
onBeforeUnmount(()=>{generation++;clearTimeout(timer);cache.dispose()})
defineExpose({reload:()=>load()})
const earlier = useLoadMore({ loading: busy, hasMore: previous, error, load: () => load('before') })
const later = useLoadMore({ loading: busy, hasMore: next, error, load: () => load('after') })
</script>
<template><div class="flex flex-col min-h-0 h-full"><FrappeRows ref="root" :items="items" :row-height="rowHeight" :label="label"><template #default="{item}"><div class="relative h-full"><div v-if="previous && item === items[0]" ref="earlier" class="absolute top-0 left-0 w-full h-px" aria-hidden="true" /><slot :item="item"/><div v-if="next && item === items.at(-1)" ref="later" class="absolute bottom-0 left-0 w-full h-px" aria-hidden="true" /></div></template></FrappeRows><div v-if="busy" role="status" class="px-3 py-1 text-xs text-ink-gray-5">Loading…</div><div v-else-if="error" role="alert" class="p-4 text-red-600">{{error}} <Button label="Retry" @click="load()"/></div><p v-else-if="!items.length" class="p-6 text-center text-sm text-ink-gray-5">No matching records</p></div></template>
