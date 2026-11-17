'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const runFixture=require('./fixture-process.cjs');
test('real task Browser keeps its Page through Focus, overlays, resize, zoom and mouse / keyboard input',{timeout:90000},async t=>{
  const {stdout,stderr}=await runFixture(t,require('electron'),[path.join(__dirname,'browser-presentation-dom.fixture.cjs')],
    {timeout:85000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout+stderr,/BROWSER PRESENTATION DOM PASS/);
});
