<script setup>
import {computed} from 'vue'
import PagedRows from './PagedRows.vue'
const props=defineProps({columns:{type:Array,required:true},fetchPage:{type:Function,required:true},query:String,revision:[String,Number],label:{default:'Records'},rowHeight:{default:48}})
const grid=computed(()=>({display:'grid',gridTemplateColumns:props.columns.map(c=>c.width||'minmax(140px,1fr)').join(' ')}))
</script>
<template><div class="relay-table border border-outline-gray-2 rounded-lg overflow-x-auto bg-surface-white" role="table" :aria-label="label"><div class="relay-table-inner" :style="{minWidth:columns.reduce((n,c)=>n+(c.minWidth||140),0)+'px'}"><div role="row" class="border-b border-outline-gray-2 bg-surface-gray-1 shrink-0" :style="grid"><div v-for="column in columns" :key="column.key" role="columnheader" class="px-4 py-3 text-xs font-medium text-ink-gray-5">{{column.label}}</div></div><PagedRows :fetch-page="fetchPage" :query="query" :revision="revision" :row-height="rowHeight" :label="label+' rows'"><template #default="{item}"><div role="row" class="h-full border-b border-outline-gray-1 items-center" :style="grid"><div v-for="column in columns" :key="column.key" role="cell" class="px-4 text-sm min-w-0 truncate"><slot :name="column.key" :item="item"><span :title="String(item[column.key]??'')">{{item[column.key]}}</span></slot></div></div></template></PagedRows></div></div></template>
<style scoped>.relay-table{height: min(65vh,650px);min-height:250px}.relay-table-inner{display:flex;flex-direction:column;height:100%}</style>
