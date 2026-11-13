'use strict';
const {BrowserFailure}=require('./browser-errors.cjs');
const {checkCanceled,timeoutFailure}=require('./browser-task.cjs');
const USER_PAGE_LIMIT=16;
function pageLimits(value={global_limit:16,service_limit:4}) {
  if(!value || !Number.isInteger(value.global_limit) || value.global_limit<4 || value.global_limit>64
    || !Number.isInteger(value.service_limit) || value.service_limit<3 || value.service_limit>16)
    throw Error('Invalid managed page limits');
  return Object.freeze({global_limit:value.global_limit,service_limit:value.service_limit});
}
// Reservations and physical resources share both dimensions. A reservation never creates a WebContents.
class PageBudget {
  constructor(limits) {this.limits=pageLimits(limits);this.reservations=new Set();this.claims=new Set();this.queue=[];this.closed=false;}
  usage(bucket,user=false) {
    let total=0,scoped=0;
    for(const claim of this.claims)if(claim.user===user){total++;if(claim.bucket===bucket)scoped++;}
    for(const ticket of this.reservations)if(ticket.user===user){total+=ticket.remaining;if(ticket.bucket===bucket)scoped+=ticket.remaining;}
    return {total,scoped};
  }
  tryAcquire(owner,bucket,count=1,user=false) {
    if(this.closed)throw new BrowserFailure('navigation','canceled');
    const used=this.usage(bucket,user);
    if(user?used.total+count>USER_PAGE_LIMIT:
      used.total+count>this.limits.global_limit || used.scoped+count>this.limits.service_limit)return null;
    const ticket={owner,bucket,user,remaining:count,revoked:false};
    ticket.split=()=>{
      if(ticket.revoked || !ticket.remaining)throw new BrowserFailure('navigation','page_capacity_changed');
      ticket.remaining--;if(!ticket.remaining)this.reservations.delete(ticket);
      // Transfer one reserved unit without changing either count.
      const child=this.tryAcquire(owner,bucket,1,user);
      if(!child)throw new BrowserFailure('navigation','page_capacity_changed');
      return child;
    };
    ticket.take=()=>{
      if(ticket.revoked || !ticket.remaining || this.closed)throw new BrowserFailure('navigation','page_capacity_changed');
      ticket.remaining--;if(!ticket.remaining)this.reservations.delete(ticket);
      const claim={owner,bucket,user};this.claims.add(claim);
      claim.release=()=>{if(this.claims.delete(claim))this.drain();};
      return claim;
    };
    ticket.release=()=>{ticket.remaining=0;ticket.revoked=true;this.reservations.delete(ticket);this.drain();};
    this.reservations.add(ticket);return ticket;
  }
  acquire(owner,bucket,{count=1,user=false,signal,deadline=Infinity,validate=()=>{}}={}) {
    checkCanceled(signal);validate();
    if(Date.now()>=deadline)return Promise.reject(timeoutFailure('navigation','page_admission'));
    const ticket=this.tryAcquire(owner,bucket,count,user);if(ticket)return Promise.resolve(ticket);
    return new Promise((resolve,reject)=>{
      const entry={owner,bucket,count,user,validate,signal,deadline,resolve,reject};
      const remove=()=>{const index=this.queue.indexOf(entry);if(index>=0)this.queue.splice(index,1);clearTimeout(entry.timer);signal?.removeEventListener('abort',entry.abort);};
      entry.finish=(error,ticket)=>{remove();error?reject(error):resolve(ticket);};
      entry.abort=()=>{try{checkCanceled(signal);}catch(error){entry.finish(error);}};
      if(Number.isFinite(deadline))entry.timer=setTimeout(()=>entry.finish(timeoutFailure('navigation','page_admission')),Math.max(1,deadline-Date.now()));
      signal?.addEventListener('abort',entry.abort,{once:true});this.queue.push(entry);
      if(signal?.aborted)entry.abort();
    });
  }
  drain() {
    for(const entry of [...this.queue]) {
      try {
        if(this.closed)throw new BrowserFailure('navigation','canceled');
        checkCanceled(entry.signal);entry.validate();
        if(Date.now()>=entry.deadline)throw timeoutFailure('navigation','page_admission');
        const ticket=this.tryAcquire(entry.owner,entry.bucket,entry.count,entry.user);
        if(ticket)entry.finish(null,ticket);
      }catch(error){entry.finish(error);}
    }
  }
  releaseUnused(owner) {for(const ticket of [...this.reservations])if(ticket.owner===owner)ticket.release();}
  update(limits) {
    this.limits=pageLimits(limits);
    // Old headroom is not permission to exceed a newly saved limit.
    for(const ticket of [...this.reservations])ticket.release();
    this.drain();return this.limits;
  }
  stop() {this.closed=true;for(const ticket of [...this.reservations])ticket.release();this.drain();}
}
module.exports={PageBudget,pageLimits,USER_PAGE_LIMIT};
