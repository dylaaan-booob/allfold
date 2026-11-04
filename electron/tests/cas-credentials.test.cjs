'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),vm=require('node:vm');
function fixture(t) {
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-cas-'));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  const safeStorage={isAsyncEncryptionAvailable:async()=>true,
    encryptStringAsync:async value=>Buffer.from(value),
    decryptStringAsync:async value=>({result:value.toString()})};
  const module={exports:{}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/auth/cas-credentials.cjs'),'utf8'),{
    module,exports:module.exports,Buffer,require:name=>name==='electron'
      ? {app:{getPath:()=>directory},safeStorage}:require(name),
  });
  return {...module.exports,safeStorage,directory};
}
test('explicit CARSI replacement and clearing compare the displayed credential revision',async t=>{
  const api=fixture(t),initial=await api.casStatus();
  assert.equal(initial.revision,'missing');
  const saved=await api.saveCASCredentials({username:'fixture',password:'synthetic-password',expected_revision:initial.revision});
  assert.match(saved.revision,/^[0-9a-f]{64}$/);
  assert.equal((await api.casStatus()).revision,saved.revision);
  await assert.rejects(api.clearCASCredentials({expected_revision:'missing'}),error=>error.code==='cas_revision_conflict');
  assert.equal((await api.casStatus()).configured,true);
  await api.clearCASCredentials({expected_revision:saved.revision});
  assert.equal((await api.casStatus()).revision,'missing');
});
test('a credential mutation cannot overwrite an external revision arriving during encryption',async t=>{
  const api=fixture(t),initial=await api.casStatus();
  const original=api.safeStorage.encryptStringAsync;
  api.safeStorage.encryptStringAsync=async value=>{
    fs.writeFileSync(path.join(api.directory,'xmu-cas-credentials.bin'),JSON.stringify({username:'external',password:'external-fixture'}));
    return original(value);
  };
  await assert.rejects(api.saveCASCredentials({username:'fixture',password:'synthetic',expected_revision:initial.revision}),
    error=>error.code==='cas_revision_conflict');
  assert.equal((await api.casStatus()).username,'external');
  assert.deepEqual(fs.readdirSync(api.directory),['xmu-cas-credentials.bin']);
});
test('concurrent replacements cannot both consume the same displayed revision',async t=>{
  const api=fixture(t),initial=await api.casStatus();
  const results=await Promise.allSettled(['first','second'].map(username=>api.saveCASCredentials({
    username,password:'synthetic',expected_revision:initial.revision})));
  assert.equal(results[0].status,'fulfilled');assert.equal(results[1].reason.code,'cas_revision_conflict');
  assert.equal((await api.casStatus()).username,'first');
});
test('unreadable ciphertext reports its revision for an explicit complete replacement',async t=>{
  for(const cause of ['invalid-json','decryption-failed']){
    const api=fixture(t),target=path.join(api.directory,'xmu-cas-credentials.bin');
    fs.writeFileSync(target,'synthetic corrupt ciphertext');
    const decrypt=api.safeStorage.decryptStringAsync;
    if(cause==='decryption-failed')api.safeStorage.decryptStringAsync=async()=>{throw Error('synthetic decrypt failure');};
    const state=await api.casStatus();
    assert.equal(state.ok,false);assert.equal(state.error,'cas_store_unreadable');
    assert.equal(state.configured,false);assert.equal(state.username,'');
    assert.match(state.revision,/^[0-9a-f]{64}$/);
    await assert.rejects(api.saveCASCredentials({username:'fixture',password:'replacement',expected_revision:'missing'}),error=>error.code==='cas_revision_conflict');
    await assert.rejects(api.saveCASCredentials({username:'fixture',password:'',expected_revision:state.revision}),error=>error.code==='cas_store_unreadable');
    api.safeStorage.decryptStringAsync=decrypt;
    const saved=await api.saveCASCredentials({username:'fixture',password:'replacement',expected_revision:state.revision});
    assert.equal((await api.casStatus()).revision,saved.revision);
    assert.equal((await api.readCASCredentials()).password,'replacement');
  }
});
test('a credential file that cannot be read supplies no overwrite revision',async t=>{
  const api=fixture(t);fs.mkdirSync(path.join(api.directory,'xmu-cas-credentials.bin'));
  await assert.rejects(api.casStatus(),error=>error.code==='cas_store_unreadable');
  await assert.rejects(api.saveCASCredentials({username:'fixture',password:'replacement',expected_revision:'missing'}),error=>error.code==='cas_store_unreadable');
});
