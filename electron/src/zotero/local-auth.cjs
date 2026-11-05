'use strict';
const fs=require('node:fs/promises'),path=require('node:path');
const {randomBytes}=require('node:crypto');
const failure=code=>Object.assign(Error(code),{code});
function createKeyStore({safeStorage,filename}) {
  const available=async()=>{if(!await safeStorage.isAsyncEncryptionAvailable())throw failure('encryption_unavailable');};
  return {
    async read() {
      let encrypted;try{encrypted=await fs.readFile(filename);}catch(error){if(error.code==='ENOENT')return null;throw failure('key_store_unreadable');}
      await available();
      try {const value=JSON.parse((await safeStorage.decryptStringAsync(encrypted)).result);
        if(typeof value.server_id!=='string'||typeof value.key!=='string'||!/^[A-Za-z0-9]{32}$/.test(value.key))throw Error();return value;
      }catch{throw failure('key_store_unreadable');}
    },
    async write(value) {
      await available();let encrypted;try{encrypted=await safeStorage.encryptStringAsync(JSON.stringify(value));}catch{throw failure('encryption_unavailable');}
      const temporary=filename+'.'+randomBytes(12).toString('hex')+'.tmp';
      try{await fs.mkdir(path.dirname(filename),{recursive:true});await fs.writeFile(temporary,encrypted,{flag:'wx',mode:0o600});await fs.rename(temporary,filename);}
      catch{throw failure('key_store_write_failed');}finally{await fs.unlink(temporary).catch(()=>{});}
    },
  };
}
let singleton;
const keyStore={read:()=>getStore().read(),write:value=>getStore().write(value)};
function getStore(){if(!singleton){const {app,safeStorage}=require('electron');singleton=createKeyStore({safeStorage,filename:path.join(app.getPath('userData'),'zotero-local-key.bin')});}return singleton;}
module.exports={keyStore,createKeyStore};
