'use strict';

(() => {
  const root=document.getElementById('paper-preprint-lookup');
  const start=document.getElementById('preprint-lookup-start');
  const cancel=document.getElementById('preprint-lookup-cancel');
  const status=document.getElementById('preprint-lookup-status');
  const requests=new Map();
  let paper=null;
  const key=(workspace,id)=>`${workspace}/${id}`;
  const endpoint=id=>`/api/papers/${encodeURIComponent(id)}/preprint-lookup`;
  const active=task=>['Starting','Running','Cancelling'].includes(task?.phase) || task?.cleaning_up===true;
  const current=()=>requests.get(key(uiNext.libraryIdentity,paper?.id));
  const valid=operation=>operation.epoch===uiNext.workspaceEpoch && operation.workspace_id===uiNext.libraryIdentity &&
    requests.get(key(operation.workspace_id,operation.paperId))===operation;

  function render(){
    const task=current();
    root.hidden=!paper?.metadata_present || paper.excluded;
    start.disabled=!paper?.preprint_lookup_available || active(task) || paper?.cleanup_pending===true || ['queued','running'].includes(paper?.collection_status);
    cancel.hidden=!task?.request_id || !['Running','Cancelling'].includes(task.phase);
    cancel.disabled=task?.phase==='Cancelling';
    status.textContent=!paper ? '' : !paper.preprint_lookup_available ? '需要有效的正式论文 DOI。' : task?.message || '';
    status.hidden=!status.textContent;
  }

  async function poll(operation){
    if(!valid(operation))return;
    try{
      const result=await uiNext.request(`${endpoint(operation.paperId)}/state?workspace_id=${encodeURIComponent(operation.workspace_id)}&request_id=${encodeURIComponent(operation.request_id)}`);
      if(!valid(operation) || result.workspace_id!==operation.workspace_id)return;
      if(result.phase==='Idle' && !result.request_id){
        Object.assign(operation,result,{message:'查询已结束或已失效。'});render();
        await window.allfoldRefreshWorkspace();return;
      }
      if(result.request_id!==operation.request_id)return;
      Object.assign(operation,result);
      if(result.phase==='Failed')operation.message=`查询失败：${result.message}`;
      render();
      if(!active(operation))await window.allfoldRefreshWorkspace();
    }catch(error){
      if(!valid(operation))return;
      if(!error.stale)operation.message=error.message;render();
    }
    if(valid(operation) && active(operation))operation.timer=setTimeout(()=>void poll(operation),700);
  }

  start.addEventListener('click',async()=>{
    if(start.disabled)return;
    const operation={paperId:paper.id,workspace_id:uiNext.libraryIdentity,epoch:uiNext.workspaceEpoch,phase:'Starting',message:'正在准备查询…'};
    requests.set(key(operation.workspace_id,operation.paperId),operation);render();
    try{
      if(window.allfoldAutosave && !await window.allfoldAutosave.flush())throw new Error('请先保存配置再查询。');
      if(!valid(operation))return;
      const result=await uiNext.request(`${endpoint(operation.paperId)}/start`,{workspace_id:operation.workspace_id});
      if(!valid(operation) || result.workspace_id!==operation.workspace_id)return;
      Object.assign(operation,result);render();void poll(operation);
    }catch(error){
      if(!valid(operation))return;
      operation.phase='Failed';operation.message=`查询失败：${error.message}`;render();
    }
  });

  cancel.addEventListener('click',async()=>{
    const operation=current();
    if(!operation || operation.phase!=='Running')return;
    operation.phase='Cancelling';render();
    try{
      await uiNext.request(`${endpoint(operation.paperId)}/cancel`,{request_id:operation.request_id,workspace_id:operation.workspace_id});
    }catch(error){
      if(valid(operation) && operation.phase==='Cancelling'){
        operation.phase='Running';operation.message=error.message;render();
      }
    }
  });

  async function restore(id){
    const workspace=uiNext.libraryIdentity,epoch=uiNext.workspaceEpoch;
    try{
      const result=await uiNext.request(`${endpoint(id)}/state?workspace_id=${encodeURIComponent(workspace)}`);
      if(epoch!==uiNext.workspaceEpoch || workspace!==uiNext.libraryIdentity || result.workspace_id!==workspace ||
        requests.has(key(workspace,id)) || !active(result) || !result.request_id)return;
      const operation={paperId:id,epoch,...result};
      requests.set(key(workspace,id),operation);render();void poll(operation);
    }catch{} // Explicit Start reports service errors; navigation never cancels a request.
  }

  window.allfoldPreprintLookup={select(next){
    const changed=paper?.id!==next?.id;
    paper=next;render();
    if(changed && paper?.preprint_lookup_available && !current())void restore(paper.id);
  }};
  function clear(){for(const task of requests.values())clearTimeout(task.timer);requests.clear();}
  window.addEventListener('workspace-reset',()=>{clear();paper=null;render();});
  window.addEventListener('pagehide',clear);
})();
