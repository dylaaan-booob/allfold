'use strict';
window.uiNext={
  data:null,
  csrf_token:null,
  workspaceEpoch:0,
  responseOrder:0,
  acceptedOrder:0,
  libraryIdentity:undefined,
  libraryRevision:-1,
  staleResponse() {const error=new Error('Workspace 响应已过期');error.stale=true;return error;},
  resetWorkspace() {
    this.workspaceEpoch++;this.data=null;this.libraryIdentity=undefined;
    this.libraryRevision=-1;this.acceptedOrder=0;
  },
  isCurrentEnvelope(value) {
    const revision=Number.isInteger(value?.revision)?value.revision:value?.snapshot_revision;
    return value?.workspace_id===this.libraryIdentity && revision===this.libraryRevision &&
      (!value.__allfoldResponseOrder || value.__allfoldResponseOrder>=this.acceptedOrder);
  },
  acceptEnvelope(value,epoch,order,projectsPapers=true) {
    if(epoch!==this.workspaceEpoch)throw this.staleResponse();
    const revision=Number.isInteger(value?.revision)?value.revision:value?.snapshot_revision;
    if(!Object.hasOwn(value || {},'workspace_id') || !Number.isInteger(revision))return;
    const identity=value.workspace_id;
    if(this.libraryIdentity!==undefined && this.libraryIdentity!==null && identity!==this.libraryIdentity)
      throw this.staleResponse();
    if(revision<this.libraryRevision || (revision===this.libraryRevision && order<this.acceptedOrder))throw this.staleResponse();
    this.libraryIdentity=identity;
    // Status and field reads carry a revision but do not apply Paper content.
    // Only a snapshot or Paper projection can supersede another projection.
    if(projectsPapers){this.libraryRevision=revision;this.acceptedOrder=order;}
    Object.defineProperty(value,'__allfoldResponseOrder',{value:order});
  },
  layout() {
    return this.layoutPromise ||= this.request(new URL('archive-layout.json', document.baseURI).href);
  },
  async request(path,body,options={}) {
    const epoch=this.workspaceEpoch,order=++this.responseOrder;
    if(body!==undefined && /^\/api\/(ui-next\/)?papers\//.test(path))body={workspace_id:this.libraryIdentity,...body};
    let response;
    try {
      response=await fetch(path,{
        cache:'no-store',...options,
        ...(body!==undefined?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf_token:this.csrf_token || this.data?.csrf_token,...body})}:{}),
      });
    } catch {
      throw new Error('无法连接 Allfold 服务，请确认应用仍在运行，然后刷新页面重试。');
    }
    let data;
    try{data=await response.json();}catch{throw new Error(`服务响应异常 (${response.status})，请确认 Web 服务仍在运行。`);}
    if(!response.ok){const error=new Error(data.message || data.error || `请求失败 (${response.status})`);error.state=data;throw error;}
    this.acceptEnvelope(data,epoch,order,path==='/api/ui-next/workspace' || Object.hasOwn(data || {},'paper'));
    return data;
  },
  async workspace(){
    const epoch=this.workspaceEpoch,data=await this.request('/api/ui-next/workspace');
    if(epoch!==this.workspaceEpoch)throw this.staleResponse();
    this.data=data;this.csrf_token=data.csrf_token;return data;
  },
  notice(message,details=[]) {
    document.getElementById('app-notice-popover').hidePopover();
    document.getElementById('app-notice').hidden=!message;
    document.getElementById('app-notice-summary').textContent=message;
    const disclosure=document.getElementById('app-notice-details');
    disclosure.hidden=!details.length;disclosure.open=false;
    document.getElementById('app-notice-messages').replaceChildren(...details.map(text=>{
      const line=document.createElement('p');line.textContent=text;return line;
    }));
  },
};
document.getElementById('message-close').addEventListener('click',()=>uiNext.notice(''));
document.getElementById('app-notice-popover').addEventListener('beforetoggle',event=>{
  if(event.newState!=='open')return;
  document.getElementById('app-notice-popover-summary').textContent=document.getElementById('app-notice-summary').textContent;
  document.getElementById('app-notice-popover-messages').replaceChildren(
    ...[...document.getElementById('app-notice-messages').children].map(line=>line.cloneNode(true)));
});
