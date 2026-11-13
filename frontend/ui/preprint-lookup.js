'use strict';

(() => {
  const root=document.getElementById('paper-preprint-lookup');
  const start=document.getElementById('preprint-lookup-start');
  const cancel=document.getElementById('preprint-lookup-cancel');
  const status=document.getElementById('preprint-lookup-status');
  let paper=null, task=null, timer=null;
  const endpoint=id=>`/api/papers/${encodeURIComponent(id)}/preprint-lookup`;
  const active=()=>['Starting','Running','Cancelling'].includes(task?.phase) || task?.cleaning_up===true;

  function render(){
    const current=task?.paperId===paper?.id ? task : null;
    root.hidden=!paper?.metadata_present || paper.excluded;
    start.disabled=!paper?.preprint_lookup_available || active();
    cancel.hidden=!current || !['Running','Cancelling'].includes(current.phase);
    cancel.disabled=current?.phase==='Cancelling';
    status.textContent=!paper ? '' : !paper.preprint_lookup_available ? '需要有效的正式论文 DOI。' :
      current?.message || (active() ? '另一篇 Paper 正在查询。' : '');
    status.hidden=!status.textContent;
  }

  async function poll(operation){
    if(task!==operation)return;
    try{
      const result=await uiNext.request(`${endpoint(operation.paperId)}/state?request_id=${encodeURIComponent(operation.request_id)}`);
      if(task!==operation)return;
      Object.assign(operation,result);
      if(result.phase==='Failed')operation.message=`查询失败：${result.message}`;
      render();
      if(!active()){
        await window.allfoldRefreshWorkspace();
      }
    }catch(error){
      if(task!==operation)return;
      if(!error.stale)operation.message=error.message;render();
    }
    if(task===operation && active())timer=setTimeout(()=>void poll(operation),700);
  }

  start.addEventListener('click',async()=>{
    if(start.disabled)return;
    const operation=task={paperId:paper.id,workspace_id:uiNext.libraryIdentity,phase:'Starting',message:'正在准备查询…'};
    render();
    try{
      if(window.allfoldAutosave && !await window.allfoldAutosave.flush())throw new Error('请先保存配置再查询。');
      if(task!==operation)return;
      if(paper?.id!==operation.paperId){
        task=null;render();return;
      }
      const result=await uiNext.request(`${endpoint(operation.paperId)}/start`,{workspace_id:operation.workspace_id});
      if(task!==operation)return;
      Object.assign(operation,result);render();void poll(operation);
    }catch(error){
      if(task!==operation)return;
      operation.phase='Failed';operation.message=`查询失败：${error.message}`;render();
    }
  });

  cancel.addEventListener('click',async()=>{
    const operation=task;
    if(operation?.paperId!==paper?.id || operation.phase!=='Running')return;
    operation.phase='Cancelling';render();
    try{
      await uiNext.request(`${endpoint(operation.paperId)}/cancel`,{request_id:operation.request_id,workspace_id:operation.workspace_id});
    }catch(error){
      if(task===operation && operation.phase==='Cancelling'){
        operation.phase='Running';operation.message=error.message;render();
      }
    }
  });

  async function restore(id){
    try{
      const result=await uiNext.request(`${endpoint(id)}/state`);
      if(paper?.id!==id || active() || task?.paperId===id || !['Running','Cancelling'].includes(result.phase))return;
      task={paperId:id,workspace_id:uiNext.libraryIdentity,...result};render();void poll(task);
    }catch{} // The next explicit Start reports service errors.
  }

  window.allfoldPreprintLookup={
    select(next){
      const changed=paper?.id!==next?.id;
      paper=next;render();
      if(changed && paper?.preprint_lookup_available && !active())void restore(paper.id);
    },
  };
  window.addEventListener('workspace-reset',()=>{
    clearTimeout(timer);paper=task=null;render();
  });
  window.addEventListener('pagehide',()=>clearTimeout(timer));
})();
