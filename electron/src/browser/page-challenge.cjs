'use strict';
const {checkPage,cloudflareChallenge}=require('./browser-errors.cjs');

// One observer per physical Page. Business waits consume the same access facts,
// but neither own this observer nor lend it their deadlines or credentials.
class PageChallenge {
  constructor({tab,owner,probe,solve,changed,report}) {
    Object.assign(this,{tab,owner,probe,solve,changed,report});
    this.lifetime=new AbortController();this.state=null;this.active=null;this.reading=null;
    this.ownerCanceled=()=>{if(tab.resourceOwner===owner)void this.close();};
    owner?.signal?.addEventListener('abort',this.ownerCanceled,{once:true});
    if(owner?.signal?.aborted)this.ownerCanceled();
    this.schedule();
  }
  setState(value,kind=this.kind) {
    if(this.state===value && this.kind===kind)return;
    this.state=value;this.kind=kind;this.changed();
  }
  schedule() {
    if(this.lifetime.signal.aborted)return;
    clearTimeout(this.timer);
    this.timer=setTimeout(()=>{void this.read();},750);this.timer.unref?.();
  }
  async read() {
    if(this.reading || this.lifetime.signal.aborted)return;
    const contents=this.tab.view.webContents;
    if(contents.isDestroyed() || contents.isCrashed() || contents.isLoadingMainFrame()) {this.schedule();return;}
    this.reading=this.probe(this.lifetime.signal);
    try {this.observe(await this.reading);}catch(_) { /* Replaced Documents and transient probe errors are reobserved. */ }
    finally {this.reading=null;this.schedule();}
  }
  observe(doc) {
    if(this.lifetime.signal.aborted)return;
    let diagnostic;
    try{checkPage(doc.status,doc);}catch(error){diagnostic=error.diagnostic;}
    const cloudflare=cloudflareChallenge(doc) || doc.markers.cloudflareVisible;
    if(!cloudflare) {
      this.active?.controller.abort();
      if(diagnostic?.code==='verification_page' || doc.markers.login || doc.markers.mfa)this.setState('manual',
        doc.imperva?'imperva':doc.markers.mfa?'mfa':doc.markers.login?(this.tab.authContext?.institution?'institution':'login'):
          doc.markers.hcaptchaVisible?'hcaptcha':'verification');
      else if(diagnostic)this.setState('failed');
      else if(this.state)this.setState('recovered');
      return;
    }
    if(this.active || Date.now()<(this.nextObservation || 0))return;
    const controller=new AbortController(),entry={controller};this.active=entry;
    this.setState('waiting','cloudflare');
    entry.done=(async()=>{
      try {
        const result=await this.solve({signal:controller.signal,onProgress:progress=>{
          if(this.active!==entry || controller.signal.aborted)return;
          this.setState(progress.outcome==='clicked'?'handling':progress.reason==='checkbox_ambiguous'?'manual':'waiting');
        }});
        if(!controller.signal.aborted && result?.outcome==='failed')this.setState('failed');
      } catch(_) {
        if(!controller.signal.aborted){this.setState('failed');this.report();}
      } finally {if(this.active===entry){this.active=null;this.nextObservation=Date.now()+750;}}
    })();
  }
  cancel() {this.active?.controller.abort();}
  async close() {
    this.lifetime.abort();clearTimeout(this.timer);this.cancel();
    this.owner?.signal?.removeEventListener('abort',this.ownerCanceled);
    await Promise.allSettled([this.reading,this.active?.done]);
  }
}
module.exports={PageChallenge};
