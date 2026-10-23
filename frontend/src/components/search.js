// Ordered-character matching: "akmr" matches "Asha Kumar".
export function fuzzyMatch(text, query) {
 const value=String(text??'').normalize('NFKD').toLowerCase()
 const needle=String(query??'').normalize('NFKD').toLowerCase().trim()
 let at=0
 for(const character of needle){at=value.indexOf(character,at);if(at<0)return false;at++}
 return true
}
// Preview/local collections only. Production adapters should search and page on the server.
export function arrayPageSource(getRows, text=row=>Object.values(row).join(' ')) {
 return async({cursor,limit=50,query='',signal})=>{
  if(signal?.aborted)throw new DOMException('Aborted','AbortError')
  const rows=getRows().filter(row=>fuzzyMatch(text(row),query));let start=0
  if(cursor?.after){const index=rows.findIndex(row=>String(row.id)===String(cursor.after));start=index<0?0:index+1}
  if(cursor?.before){const index=rows.findIndex(row=>String(row.id)===String(cursor.before));start=Math.max(0,index-limit)}
  const end=cursor?.before?Math.max(0,rows.findIndex(row=>String(row.id)===String(cursor.before))):start+limit
  const items=rows.slice(start,end)
  return {items,previous:start&&items.length?{before:items[0].id}:null,next:start+items.length<rows.length&&items.length?{after:items.at(-1).id}:null}
 }
}

// Frappe production page source. The server owns filtering, permissions and cursors.
export function contactPageSource(request = fetch) {
 return async ({cursor,limit=50,query='',signal}) => {
  const params=new URLSearchParams({query,limit:String(Math.min(limit,50))})
  if(cursor?.before)params.set('before',cursor.before)
  if(cursor?.after)params.set('after',cursor.after)
  const response=await request(`/api/method/relay_core.api.contacts?${params}`,{signal,credentials:'same-origin',headers:{Accept:'application/json'}})
  if(!response.ok)throw new Error('Unable to load contacts')
  const body=await response.json()
  if(!body.message || !Array.isArray(body.message.items))throw new Error('Invalid contact page')
  return body.message
 }
}
