import {test} from 'node:test'
import assert from 'node:assert/strict'
import {validateFields} from '../src/components/formValidation.js'
const fields=[{name:'site',label:'Site URL',required:true,url:true}]
test('accepts HTTP and HTTPS site origins with custom hosts and ports',()=>{
 for(const site of ['http://relay.test:8002','http://localhost:8002','http://192.168.1.10:8002','https://erp.example.com','http://custom.example.com:8080/'])assert.deepEqual(validateFields(fields,{site}),{})
})
test('rejects malformed URLs, other protocols and non-origin URLs',()=>{
 for(const site of ['', 'relay.test:8002','ftp://relay.test','https://user:password@relay.test','http://relay.test/path','http://relay.test?query=1','http://relay.test#fragment','http://relay.test:99999'])assert.ok(validateFields(fields,{site}).site,site)
})
