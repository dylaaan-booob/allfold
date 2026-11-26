'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const runFixture=require('./fixture-process.cjs');
test('a timed-out fixture ends its owned descendants and releases captured output',{timeout:6000},async t=>{
  const source=`const {spawn}=require('node:child_process');
    process.on('SIGTERM',()=>{});
    const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'inherit'});
    console.log('owned descendant',child.pid);setInterval(()=>{},1000);`;
  const pending=runFixture(t,process.execPath,['-e',source],{detached:true,timeout:1000});
  let guard,descendant;
  pending.child.stdout.on('data',bytes=>{const match=String(bytes).match(/owned descendant (\d+)/);if(match)descendant=Number(match[1]);});
  try {
    await assert.rejects(Promise.race([pending,new Promise((_,reject)=>{guard=setTimeout(()=>reject(Error('fixture remained alive after its timeout')),3000);})]),
      error=>error.killed===true&&error.signal==='SIGKILL'&&/owned descendant/.test(error.stdout));
    assert.ok(descendant);
    const until=Date.now()+1000;
    while(Date.now()<until){try{process.kill(descendant,0);}catch(error){if(error.code==='ESRCH')break;throw error;}await new Promise(resolve=>setTimeout(resolve,10));}
    assert.throws(()=>process.kill(descendant,0),{code:'ESRCH'});
  }finally {
    clearTimeout(guard);
    for(const pid of [descendant,pending.child.pid].filter(Boolean))try{process.kill(pid,'SIGKILL');}catch(error){if(error.code!=='ESRCH')throw error;}
    await pending.catch(()=>{});
  }
});
