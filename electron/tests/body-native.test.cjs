'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
test('native body actions preserve original POST/navigation and first-response frame/popup output',{timeout:65000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-body-native-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-native.fixture.cjs'),profile,
    'attachment,inline,iframe,popup,cancel,interrupted,no-item,unrelated,sciencedirect'],
    {timeout:60000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/BODY NATIVE PASS/);assert.doesNotMatch(stderr,/Check failed/);t.diagnostic(stdout.trim());
});
test('ScienceDirect original HTML reader hands off once to its own same-PII CDN navigation',{timeout:45000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-native-reader-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-native.fixture.cjs'),profile,
    'sciencedirect-reader,sciencedirect-reader-self,sciencedirect-reader-wrong-pii,sciencedirect-reader-wrong-origin,sciencedirect-reader-wrong-source,sciencedirect-reader-twice,sciencedirect-reader-challenge,sciencedirect-reader-http-error,sciencedirect-reader-cancel'],
    {timeout:40000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/BODY NATIVE PASS/);assert.doesNotMatch(stderr,/Check failed/);t.diagnostic(stdout.trim());
});
test('native output replacement is refused and records the accepted Chromium cancellation race',{timeout:15000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-body-native-replacement-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  // A cancelled item can asynchronously delete the substituted pathname. The
  // accepted boundary asserts application refusal, never replacement survival.
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-native.fixture.cjs'),profile,'replace'],
    {timeout:10000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/BODY NATIVE PASS/);assert.doesNotMatch(stderr,/Check failed/);
  assert.match(stdout,/replacement_exists_at_terminal/);t.diagnostic(stdout.trim());
});
test('native popup completes after an unlinked empty destination reservation',{timeout:15000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-native-reservation-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-native.fixture.cjs'),profile,'popup-reservation'],
    {timeout:10000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/BODY NATIVE PASS/);assert.doesNotMatch(stderr,/Check failed|NATIVE OUTPUT FAILURE/);t.diagnostic(stdout.trim());
});
test('public native Download publishes original response through SQLite and Workspace',{timeout:65000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-public-native-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-native.fixture.cjs'),profile,'public'],
    {timeout:60000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/PUBLIC BODY NATIVE PASS/);assert.doesNotMatch(stderr,/Check failed/);t.diagnostic(stdout.trim());
});
