'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {publicAddress}=require('../src/workflows/body-stream.cjs');
test('Session cooldown waits beyond 30 seconds when the real parent allows it',async()=>{
  const {BrowserCooldown}=require('../src/browser/browser-recovery.cjs');
  let now=1000;const waits=[];
  const gate=new BrowserCooldown({now:()=>now,pause:async(_signal,ms)=>{waits.push(ms);now+=ms;}});
  gate.observe('https://publisher.example.org/a',429,'120');
  await gate.wait('https://other.example.org/b',{deadline:200000});
  assert.deepEqual(waits,[]);
  await gate.wait('https://publisher.example.org/b',{deadline:200000});
  assert.deepEqual(waits,[120000]);
});
test('Session stream preserves exact public DNS boundaries and global exceptions',()=>{
  for(const address of ['198.51.1.1','203.0.114.1','8.8.8.8','192.0.0.9','192.0.0.10','2001:4860::1',
    '2001:1::1','2001:20::1','::ffff:8.8.8.8'])assert.equal(publicAddress(address),true,address);
  for(const address of ['127.0.0.1','10.0.0.1','100.64.0.1','198.51.100.1','203.0.113.1','100::1',
    '2001::1','2001:10::1','2001:db8::1','fe80::1','fd00::1','::ffff:127.0.0.1'])assert.equal(publicAddress(address),false,address);
});

test('publisher API secrets are fixed scoped headers, never arbitrary injection',()=>{
  const {credentialHeaders}=require('../src/workflows/body-stream.cjs');
  assert.deepEqual(credentialHeaders({kind:'elsevier',value:'fixture'},'https://api.elsevier.com/content/article/doi/10.5555/x'),{'X-ELS-APIKey':'fixture'});
  for(const url of ['https://attacker.example/content/article/x','http://api.elsevier.com/content/article/x',
    'https://api.elsevier.com/elsewhere','https://api.elsevier.com:444/content/article/x'])
    assert.throws(()=>credentialHeaders({kind:'elsevier',value:'fixture'},url));
  assert.throws(()=>credentialHeaders({kind:'cookie',value:'fixture'},'https://api.elsevier.com/content/article/x'));
  assert.throws(()=>credentialHeaders({kind:'elsevier',value:'a\r\nb'},'https://api.elsevier.com/content/article/x'));
});
