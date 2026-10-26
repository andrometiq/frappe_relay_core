<script setup>
import { computed, ref, onBeforeUnmount } from 'vue'
import { coreApi } from '../../services/coreApi'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
import { avatarInitials, avatarTone } from '@relay/ui'
const props=defineProps({message:String,readers:{type:Array,default:()=>[]}})
const open=ref(false),trigger=ref(null),panel=ref(null),position=ref({}),coverage=ref(null),error=ref(''),loading=ref(false)
let generation=0
const readers=computed(()=>[...new Map(props.readers.filter(r=>r.user).map(r=>[r.user,r])).values()])
const seen=computed(()=>[...new Map([...(coverage.value?.read_by||[]),...readers.value].map(r=>[r.user,r])).values()])
const waiting=computed(()=>(coverage.value?.unread_by||[]).filter(r=>!seen.value.some(v=>v.user===r.user)))
const name=r=>r.full_name||r.display_name||'Team member'
const initials=r=>avatarInitials(name(r))
function avatar(r){const s=r.user_image||'';return /^https?:\/\//i.test(s)||(/^\/(?!\/)/.test(s))?s:''}
function label(r){const value=r.last_read_at||r.read_at;if(!value)return name(r);const date=new Date(value);return Number.isNaN(date.getTime())?name(r):name(r)+' · '+date.toLocaleString()}
async function load(){const ticket=++generation;loading.value=true;error.value='';try{const result=await coreApi('message_reads.coverage',{message:props.message});if(ticket===generation)coverage.value=result}catch(e){if(ticket===generation)error.value=e.message}finally{if(ticket===generation)loading.value=false}}
function outside(e){if(!panel.value?.contains(e.target)&&!trigger.value?.contains(e.target))close()}
function keydown(e){if(e.key==='Escape'){close();trigger.value?.focus()}}
function close(){open.value=false;++generation;document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',keydown);window.removeEventListener('resize',close)}
function toggle(){
 if(open.value){close();return}
 const rect=trigger.value.getBoundingClientRect(),width=Math.min(280,innerWidth-28),above=Math.max(0,rect.top-10),belowSpace=Math.max(0,innerHeight-rect.bottom-10),below=belowSpace>=180||belowSpace>=above
 position.value={left:Math.max(8,Math.min(innerWidth-width-8,rect.right-width))+'px',top:(below?rect.bottom+6:rect.top-6)+'px',maxHeight:Math.max(110,Math.min(270,(below?belowSpace:above)-6))+'px',transform:below?'none':'translateY(-100%)'}
 open.value=true;coverage.value=null;load()
 document.addEventListener('pointerdown',outside);document.addEventListener('keydown',keydown);window.addEventListener('resize',close)
}
useRealtimeRefresh([],['reads'],()=>open.value?load():undefined)
onBeforeUnmount(close)
</script>
<template>
 <div v-if="readers.length" class="message-readers" @pointerdown.stop>
  <button ref="trigger" type="button" class="reader-summary" aria-label="Open team read details" :aria-expanded="open" @click.stop="toggle">
   <span class="reader-stack" aria-hidden="true"><span v-for="reader in readers.slice(0,2)" :key="reader.user" class="reader-avatar" :class="avatarTone(name(reader))"><img v-if="avatar(reader)" :src="avatar(reader)" alt="" /><em v-else>{{initials(reader)}}</em></span></span>
   <span class="read-coverage" :class="{complete:coverage?.complete}"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m18 6-7 7-3-3M22 10l-7 7-3-3M2 14l3 3 3-3" /></svg>Seen by {{readers.length}}</span>
  </button>
 </div>
 <Teleport to="body"><div v-if="open" ref="panel" class="reader-panel" :style="position" role="dialog" aria-label="Team read details" @pointerdown.stop>
  <strong>Read by</strong><p v-if="error" role="alert">{{error}}</p>
  <ul><li v-for="reader in seen" :key="reader.user"><span class="reader-avatar" :class="avatarTone(name(reader))"><img v-if="avatar(reader)" :src="avatar(reader)" alt="" /><em v-else>{{initials(reader)}}</em></span><span :title="label(reader)">{{label(reader)}}</span></li></ul>
  <small v-if="loading">Loading read details…</small><small v-if="coverage?.more">Showing the most recent 100 readers.</small>
  <template v-if="waiting.length"><strong>Waiting on</strong><ul><li v-for="reader in waiting" :key="reader.user"><span class="reader-avatar" :class="avatarTone(name(reader))"><img v-if="avatar(reader)" :src="avatar(reader)" alt="" /><em v-else>{{initials(reader)}}</em></span><span>{{name(reader)}}</span></li></ul></template>
 </div></Teleport>
</template>
<style scoped>
.message-readers{position:absolute;right:7px;top:calc(100% + 3px);z-index:3}
.reader-summary{display:flex;align-items:center;gap:5px;min-height:26px;padding:2px 7px 2px 4px;border-radius:999px;flex-direction:row-reverse;cursor:pointer;border:0;background:transparent}
.reader-stack{display:flex;padding-left:4px}.reader-avatar{display:grid;place-items:center;width:22px;height:22px;margin-left:-5px;border-radius:50%;flex:0 0 auto;overflow:hidden;border:1.5px solid var(--relay-layer-strong);background:var(--relay-tone,#5b6b7f);color:#fff}
.reader-avatar img{width:100%;height:100%;object-fit:cover}.reader-avatar em{font-size:10px;font-style:normal;font-weight:600;letter-spacing:-.02em}
.read-coverage{display:inline-flex;align-items:center;gap:3px;font-size:12px;font-weight:400;white-space:nowrap;@apply text-ink-gray-5}.read-coverage.complete{@apply text-ink-blue-2}
.reader-summary:focus-visible{outline:2px solid var(--outline-blue-1);outline-offset:2px}
.reader-panel{position:fixed;z-index:10050;width:min(280px,calc(100vw - 28px));display:grid;gap:8px;padding:11px;overflow-y:auto;border-radius:var(--relay-radius);box-shadow:var(--relay-shadow);font-size:12px;@apply border border-outline-gray-2 bg-surface-white text-ink-gray-9}
.reader-panel strong{font-size:12px;text-transform:uppercase;letter-spacing:.05em}.reader-panel ul{display:grid;gap:7px;margin:0;padding:0;list-style:none}.reader-panel li{display:flex;align-items:center;gap:7px;min-width:0}.reader-panel li>span:last-child{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.reader-panel .reader-avatar{margin-left:0}.reader-panel small{@apply text-ink-gray-5}
</style>
