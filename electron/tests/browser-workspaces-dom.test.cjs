'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const runFixture=require('./fixture-process.cjs');
test('shipped Workflows, Quick Open and grouped Browser work across workspaces and sizes',{timeout:180000},async t=>{
  for(const scrollbar of ['WhenScrolling','Always']){
    // Cocoa's argument-domain preference changes only this fixture process.
    const {stdout,stderr}=await runFixture(t,require('electron'),[path.join(__dirname,'browser-workspaces-dom.fixture.cjs'),'-AppleShowScrollBars',scrollbar],
      {timeout:85000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:'',
        ...(process.env.ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS?{ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS:path.join(process.env.ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS,scrollbar)}:{})}});
    assert.match(stdout+stderr,/BROWSER WORKSPACES DOM PASS/);
  }
});
