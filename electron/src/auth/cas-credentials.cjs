'use strict';
const {app,safeStorage}=require('electron');
const fs=require('node:fs/promises');
const path=require('node:path');
const {randomBytes}=require('node:crypto');

const filename=()=>path.join(app.getPath('userData'),'xmu-cas-credentials.bin');
const codes=new Set(['cas_encryption_unavailable','cas_store_unreadable','cas_store_write_failed',
  'cas_store_clear_failed','cas_credentials_required','cas_invalid_credentials']);
function failure(code) {return Object.assign(new Error(code),{code});}
function casErrorCode(error) {return codes.has(error?.code)?error.code:'cas_store_unavailable';}
async function encryptionAvailable() {
  try {
    if(await safeStorage.isAsyncEncryptionAvailable())return;
  } catch (_) {}
  throw failure('cas_encryption_unavailable');
}
async function readCASCredentials() {
  let encrypted;
  try {encrypted=await fs.readFile(filename());}
  catch(error) {if(error.code==='ENOENT')return null;throw failure('cas_store_unreadable');}
  await encryptionAvailable();
  try {
    const {result}=await safeStorage.decryptStringAsync(encrypted);
    const credentials=JSON.parse(result);
    if(typeof credentials?.username!=='string' || !credentials.username.trim()
      || typeof credentials.password!=='string' || !credentials.password)throw failure('cas_store_unreadable');
    return {username:credentials.username,password:credentials.password};
  } catch (_) {throw failure('cas_store_unreadable');}
}
async function casStatus() {
  const credentials=await readCASCredentials();
  return {ok:true,configured:!!credentials,username:credentials?.username || ''};
}
async function saveCASCredentials(value) {
  if(!value || typeof value.username!=='string' || !value.username.trim() || typeof value.password!=='string')
    throw failure('cas_invalid_credentials');
  const username=value.username.trim();
  const password=value.password || (await readCASCredentials())?.password;
  if(!password)throw failure('cas_credentials_required');
  await encryptionAvailable();
  let encrypted;
  try {encrypted=await safeStorage.encryptStringAsync(JSON.stringify({username,password}));}
  catch (_) {throw failure('cas_encryption_unavailable');}
  const target=filename(),temporary=target+'.'+randomBytes(12).toString('hex')+'.tmp';
  let created=false;
  try {
    const file=await fs.open(temporary,'wx',0o600);
    created=true;
    try {await file.writeFile(encrypted);} finally {await file.close();}
    await fs.rename(temporary,target);
  } catch (_) {throw failure('cas_store_write_failed');}
  finally {if(created)await fs.unlink(temporary).catch(()=>{});}
  return {ok:true,configured:true,username};
}
async function clearCASCredentials() {
  try {await fs.unlink(filename());}
  catch(error) {if(error.code!=='ENOENT')throw failure('cas_store_clear_failed');}
  return {ok:true,configured:false,username:''};
}
module.exports={readCASCredentials,casStatus,saveCASCredentials,clearCASCredentials,casErrorCode};
