'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {createKeyStore}=require('../src/zotero/local-auth.cjs');
test('server-bound key persists only encrypted bytes with private mode and unavailable encryption never writes',async t=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'allfold-key-'));t.after(()=>fs.rm(root,{recursive:true,force:true}));
 const filename=path.join(root,'key.bin'),secret={server_id:'SERVERFIXTUR',key:'secret'.repeat(5)+'12'};
 const safeStorage={isAsyncEncryptionAvailable:async()=>true,encryptStringAsync:async value=>Buffer.from(value).map(v=>v^0x5a),decryptStringAsync:async bytes=>({result:Buffer.from(bytes).map(v=>v^0x5a).toString()})};
 const store=createKeyStore({safeStorage,filename});await store.write(secret);assert.deepEqual(await store.read(),secret);
 assert.ok(!(await fs.readFile(filename)).includes(Buffer.from(secret.key)));assert.equal((await fs.stat(filename)).mode&0o777,0o600);
 safeStorage.isAsyncEncryptionAvailable=async()=>false;await assert.rejects(store.write(secret),{code:'encryption_unavailable'});
 safeStorage.isAsyncEncryptionAvailable=async()=>true;safeStorage.decryptStringAsync=async()=>{throw Error('locked');};await assert.rejects(store.read(),{code:'key_store_unreadable'});
});
