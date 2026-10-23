import { sha256Hex, randomUUID } from './crypto.js'
export async function stableSubmission(namespace, payload, submit) {
 const hash=sha256Hex(JSON.stringify(payload))
 const storage=namespace+'-'+hash
 let key=sessionStorage.getItem(storage)
 if(!key){key=randomUUID();sessionStorage.setItem(storage,key)}
 const result=await submit(key)
 sessionStorage.removeItem(storage)
 return result
}
