'use strict';
const {app,safeStorage}=require('electron');
const fs=require('node:fs/promises');
const path=require('node:path');
const {randomBytes,createHash}=require('node:crypto');

const filename=()=>path.join(app.getPath('userData'),'xmu-cas-credentials.bin');
const codes=new Set(['cas_encryption_unavailable','cas_store_unreadable','cas_store_write_failed',
  'cas_store_clear_failed','cas_credentials_required','cas_invalid_credentials',
  'cas_revision_conflict','cas_store_busy','cas_task_active']);
let mutation=Promise.resolve();
const revision=encrypted=>encrypted?createHash('sha256').update(encrypted).digest('hex'):'missing';
function mutate(action) {
  const result=mutation.then(action);mutation=result.catch(()=>{});return result;
}
async function encryptedStore() {
  try {return await fs.readFile(filename());}
  catch(error) {if(error.code==='ENOENT')return null;throw failure('cas_store_unreadable');}
}
function verifyRevision(expected,encrypted) {
  if(typeof expected!=='string' || expected!==revision(encrypted))throw failure('cas_revision_conflict');
}
function failure(code) {return Object.assign(new Error(code),{code});}
function casErrorCode(error) {return codes.has(error?.code)?error.code:'cas_store_unavailable';}
async function encryptionAvailable() {
  try {
    if(await safeStorage.isAsyncEncryptionAvailable())return;
  } catch (_) {}
  throw failure('cas_encryption_unavailable');
}
async function decryptCredentials(encrypted) {
  if(!encrypted)return null;
  await encryptionAvailable();
  try {
    const {result}=await safeStorage.decryptStringAsync(encrypted);
    const credentials=JSON.parse(result);
    if(typeof credentials?.username!=='string' || !credentials.username.trim()
      || typeof credentials.password!=='string' || !credentials.password)throw failure('cas_store_unreadable');
    return {username:credentials.username,password:credentials.password};
  } catch (_) {throw failure('cas_store_unreadable');}
}
async function readCASCredentials() {return decryptCredentials(await encryptedStore());}
async function casStatus() {
  const encrypted=await encryptedStore(),credentials=await decryptCredentials(encrypted);
  return {ok:true,configured:!!credentials,username:credentials?.username || '',revision:revision(encrypted)};
}
function saveCASCredentials(value) {return mutate(()=>saveCredentials(value));}
async function saveCredentials(value) {
  if(!value || typeof value.username!=='string' || !value.username.trim() || typeof value.password!=='string')
    throw failure('cas_invalid_credentials');
  const username=value.username.trim();
  const previous=await encryptedStore();verifyRevision(value.expected_revision,previous);
  const password=value.password || (await decryptCredentials(previous))?.password;
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
    verifyRevision(value.expected_revision,await encryptedStore());
    await fs.rename(temporary,target);
  } catch (error) {if(error.code==='cas_revision_conflict')throw error;throw failure('cas_store_write_failed');}
  finally {if(created)await fs.unlink(temporary).catch(()=>{});}
  return {ok:true,configured:true,username,revision:revision(encrypted)};
}
function clearCASCredentials(value) {return mutate(()=>clearCredentials(value));}
async function clearCredentials(value) {
  verifyRevision(value?.expected_revision,await encryptedStore());
  try {await fs.unlink(filename());}
  catch(error) {if(error.code!=='ENOENT')throw failure('cas_store_clear_failed');}
  return {ok:true,configured:false,username:'',revision:'missing'};
}
module.exports={readCASCredentials,casStatus,saveCASCredentials,clearCASCredentials,casErrorCode};
