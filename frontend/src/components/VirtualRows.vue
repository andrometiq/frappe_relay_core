<script setup>
import {ref,computed,watch,onMounted,onBeforeUnmount} from 'vue'
const props=defineProps({items:{type:Array,required:true},rowHeight:{type:Number,default:124},label:{type:String,default:'Records'}})
const root=ref(null),top=ref(0),height=ref(600)
const first=computed(()=>Math.max(0,Math.floor(top.value/props.rowHeight)-4))
const end=computed(()=>Math.min(props.items.length,first.value+Math.ceil(height.value/props.rowHeight)+8))
const rows=computed(()=>props.items.slice(first.value,end.value))
watch(()=>props.items,()=>{if(first.value>=props.items.length){top.value=0;if(root.value)root.value.scrollTop=0}})
let observer
onMounted(()=>{observer=new ResizeObserver(([e])=>height.value=e.contentRect.height);observer.observe(root.value)})
onBeforeUnmount(()=>observer?.disconnect())
</script>
<template><div ref="root" class="virtual-rows" :aria-label="label" @scroll.passive="top=$event.target.scrollTop"><div :style="{height:items.length*rowHeight+'px',position:'relative'}"><div v-for="(item,i) in rows" :key="item.id" :style="{position:'absolute',top:(first+i)*rowHeight+'px',height:rowHeight+'px',width:'100%',overflow:'hidden'}"><slot :item="item"/></div></div><p v-if="!items.length" class="p-5 text-sm">No matching records</p></div></template>
<style scoped>.virtual-rows{overflow:auto;min-height:0;height:100%;overflow-anchor:none}</style>
