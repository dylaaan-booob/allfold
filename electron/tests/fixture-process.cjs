'use strict';
const {spawn}=require('node:child_process');
module.exports=(t,command,args,options={})=>{
  // Each fixture owns this process group, never another running Electron app.
  // execFile does not forward detached to spawn.
  const child=spawn(command,args,{...options,detached:true,killSignal:'SIGKILL',signal:t.signal});
  const stop=()=>{
    if(!child.pid)return;
    try{process.kill(-child.pid,'SIGKILL');}catch(error){if(error.code!=='ESRCH')throw error;}
  };
  child.once('exit',stop);
  const output={stdout:[],stderr:[]},length={stdout:0,stderr:0};let failure;
  const pending=new Promise((resolve,reject)=>{
    child.once('error',error=>{failure=error;stop();});
    // Stream diagnostic output even if the child never settles.
    for(const name of ['stdout','stderr'])child[name]?.on('data',bytes=>{
      length[name]+=bytes.length;
      if(length[name]>(options.maxBuffer??1024*1024)){
        failure=Error('Fixture '+name+' exceeded maxBuffer');stop();return;
      }
      output[name].push(bytes);if(name==='stdout')process.stdout.write(bytes);
    });
    child.once('close',(code,signal)=>{
      const result=Object.fromEntries(Object.entries(output).map(([name,chunks])=>[name,Buffer.concat(chunks).toString()]));
      if(failure||code!==0)reject(Object.assign(failure||Error('Fixture exited unsuccessfully'),result,{code,signal,killed:signal==='SIGKILL'}));
      else resolve(result);
    });
  });
  pending.child=child;
  return pending;
};
