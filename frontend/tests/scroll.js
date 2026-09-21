// Development-only browser fixture, excluded from the production entry point.
import {createApp,ref} from 'vue/dist/vue.esm-bundler.js'
import VirtualRows from '../src/components/VirtualRows.vue'
import ConversationTimeline from '../src/components/ConversationTimeline.vue'
import '../src/style.css'
createApp({components:{VirtualRows,ConversationTimeline},setup(){return {items:Array.from({length:2000},(_,i)=>({id:i,name:`Contact ${i}`})),messages:ref(Array.from({length:1000},(_,i)=>({id:i,who:'Sample',time:String(i),text:`Message ${i} `+'Sample text '.repeat(i%8+1)}))) }},template:'<div style="height:400px"><VirtualRows :items="items" :row-height="50"><template #default="{item}"><div class="test-row">{{item.name}}</div></template></VirtualRows></div><div style="height:400px;display:flex"><ConversationTimeline conversation="test" :messages="messages"/></div>'}).mount('#app')
