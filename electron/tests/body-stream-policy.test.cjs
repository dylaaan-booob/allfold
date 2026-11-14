'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {publicAddress}=require('../src/workflows/body-stream.cjs');
test('Session stream preserves exact public DNS boundaries and global exceptions',()=>{
  for(const address of ['198.51.1.1','203.0.114.1','8.8.8.8','192.0.0.9','192.0.0.10','2001:4860::1',
    '2001:1::1','2001:20::1','::ffff:8.8.8.8'])assert.equal(publicAddress(address),true,address);
  for(const address of ['127.0.0.1','10.0.0.1','100.64.0.1','198.51.100.1','203.0.113.1','100::1',
    '2001::1','2001:10::1','2001:db8::1','fe80::1','fd00::1','::ffff:127.0.0.1'])assert.equal(publicAddress(address),false,address);
});
