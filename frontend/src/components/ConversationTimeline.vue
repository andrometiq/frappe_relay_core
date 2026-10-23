<script setup>
import {ref,computed,watch,nextTick} from 'vue'
import {Button} from '@relay/ui'
const props=defineProps({messages:{type:Array,default:()=>[]},conversation:String})
const viewport=ref(null), end=ref(0), expanded=ref(new Set()), positions=new Map()
let shifting=false
const nearBottom=ref(true)
const start=computed(()=>Math.max(0,end.value-80))
const visible=computed(()=>props.messages.slice(start.value,end.value))
const latest=computed(()=>end.value>=props.messages.length)
function remember(){if(viewport.value){positions.set(props.conversation,{end:end.value,top:viewport.value.scrollTop});if(positions.size>100)positions.delete(positions.keys().next().value)}}
async function reset(){const p=positions.get(props.conversation);end.value=p?.end||props.messages.length;expanded.value=new Set();await nextTick();if(viewport.value)viewport.value.scrollTop=p?.top??viewport.value.scrollHeight}
watch(()=>props.conversation,reset,{immediate:true})
watch(()=>props.messages.length,async(n,old)=>{if(end.value>=old&&nearBottom.value){end.value=n;await nextTick();if(viewport.value)viewport.value.scrollTop=viewport.value.scrollHeight}})
async function shift(delta){const el=viewport.value;if(!el||shifting)return;shifting=true;const children=[...el.querySelectorAll('[data-message]')];const anchor=delta<0?children[0]:children.at(-1);const id=anchor?.dataset.message;const before=anchor?.getBoundingClientRect().top;end.value=Math.min(props.messages.length,Math.max(80,end.value+delta));await nextTick();const after=[...el.querySelectorAll('[data-message]')].find(e=>e.dataset.message===id);if(after)el.scrollTop+=after.getBoundingClientRect().top-before;remember();shifting=false}
function scroll(){remember();const el=viewport.value;nearBottom.value=el.scrollHeight-el.scrollTop-el.clientHeight<40;if(el.scrollTop<30&&start.value>0)shift(-30);else if(el.scrollHeight-el.scrollTop-el.clientHeight<30&&!latest.value)shift(30)}
async function goLatest(){end.value=props.messages.length;await nextTick();viewport.value.scrollTop=viewport.value.scrollHeight;remember()}
function expand(id){const s=new Set(expanded.value);s.has(id)?s.delete(id):s.add(id);expanded.value=s}
</script>
<template><div ref="viewport" class="message-scroll" @scroll.passive="scroll"><Button v-if="start" label="Earlier messages" @click="shift(-30)"/><div v-for="(m,i) in visible" :key="m.id||start+i" :data-message="m.id||start+i" class="flex flex-col mb-5" :class="{'items-end':m.out}"><div class="text-xs text-ink-gray-5 mb-1">{{m.who}} · {{m.time}} <span class="channel-label" :data-channel="m.channel">{{m.channel}}</span></div><div class="message-body" :class="{outgoing:m.out,note:m.note}">{{m.text.length>700&&!expanded.has(start+i)?m.text.slice(0,700)+'…':m.text}}<Button v-if="m.text.length>700" :label="expanded.has(start+i)?'Collapse':'Expand'" variant="ghost" @click="expand(start+i)"/></div></div><Button v-if="!latest" label="Latest messages" @click="goLatest"/></div></template>
