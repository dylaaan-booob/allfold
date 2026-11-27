'use strict';
const {checkCanceled,pause,timeoutFailure,waitFor}=require('./browser-task.cjs');

class ServiceEntryStarts {
  constructor({random=Math.random,pause:wait=pause,now=Date.now}={}) {
    this.random=random;
    this.pause=wait;
    this.now=now;
    this.tail=Promise.resolve();
  }
  async dispatch(start,{signal,deadline,first=false,validate}) {
    const preceding=this.tail;
    let release;
    const slot=new Promise(resolve=>{release=resolve;});
    this.tail=preceding.then(()=>slot);
    try {
      await waitFor(()=>preceding,signal,deadline);
      if(!first)await waitFor(()=>this.pause(signal,this.random()*1000),signal,deadline);
      checkCanceled(signal);
      if(this.now()>=deadline)throw timeoutFailure('preparation','request');
      validate();
      // start dispatches synchronously. Its navigation promise belongs to the caller.
      start();
    } finally {
      release();
    }
  }
}
module.exports={ServiceEntryStarts};
