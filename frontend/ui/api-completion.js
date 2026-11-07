(() => {
  const $=id=>document.getElementById(id),dialog=$('api-completion-dialog');
  let task=null,timer=null,submitting=false,restored=false,needsRefresh=false;
  const active=()=>submitting || ['Running','Cancelling'].includes(task?.phase);
  const labels={updated:'已更新',unchanged:'无新增内容',excluded:'已排除',failed:'失败',cancelled:'已取消'};
  function render(){
    const papers=new Map((window.allfoldCompletionPapers?.().papers || []).map(p=>[p.id,p]));
    const counts={};for(const result of task?.results || [])counts[result.status]=(counts[result.status] || 0)+1;
    const sourceProblems=task?.results?.some(result=>(result.lookups || []).some(lookup=>['failed','identity_mismatch'].includes(lookup.status)));
    const phase=task?.phase==='Partial'?(counts.failed?'部分 Paper 处理失败':sourceProblems?'Paper 已处理，部分来源查询异常':'Paper 已处理，部分写入需检查'):task?.phase;
    $('api-completion-status').textContent=task?.message || (task && task.phase!=='Idle'
      ? `${phase} · ${task.processed} / ${task.total} · ${Object.entries(counts).map(([key,count])=>`${labels[key]} ${count}`).join(' · ')}${task.activity?.label?' · '+task.activity.label:''}`:'');
    $('api-completion-results').replaceChildren(...(task?.results || []).map(result=>{
      const row=document.createElement('li'),summary=document.createElement('details'),heading=document.createElement('summary');
      const firstPublic={recorded:'首版日期已记录',no_association:'尚无预印本关联',known_unresolved:'已知预印本首版尚未确定',conflict:'首版日期证据冲突',failed:'首版日期查询失败',cancelled:'首版日期查询已取消'}[result.first_public_status];
      heading.textContent=[papers.get(result.paper_id)?.title || result.paper_id,labels[result.status] || result.status,firstPublic].filter(Boolean).join(' · ');
      const detail=document.createElement('p'),lookups={};
      for(const lookup of result.lookups || [])lookups[lookup.status]=(lookups[lookup.status] || 0)+1;
      const lookupLabels={no_match:'无匹配',failed:'请求失败',identity_mismatch:'身份不匹配',cancelled:'取消',evidence:'取得证据'};
      detail.textContent=[result.message,result.warning,result.first_public_recorded && result.first_public_status!=='recorded'?'已保存的 First public 保留':null,...Object.entries(lookups).map(([key,count])=>`${lookupLabels[key]} ${count}`),...(result.issues || []).map(item=>`${item.provider}: ${item.message}`)].filter(Boolean).join(' · ');
      summary.append(heading,detail);row.append(summary);return row;
    }));
    $('api-completion-start').disabled=active() || !$('api-completion-papers').querySelector('input:checked');
    $('api-completion-cancel').hidden=!active();$('api-completion-cancel').disabled=submitting || task?.phase==='Cancelling';
    for(const input of $('api-completion-papers').querySelectorAll('input'))input.disabled=active();
  }
  function select(){
    if(active())return;
    const state=window.allfoldCompletionPapers?.() || {papers:[]};
    $('api-completion-papers').replaceChildren(...state.papers.filter(p=>p.status!=='rejected').map(paper=>{
      const label=document.createElement('label'),input=document.createElement('input');input.type='checkbox';input.value=paper.id;input.checked=paper.id===state.current;
      label.append(input,document.createTextNode(paper.title));return label;
    }));
  }
  async function poll(){
    clearTimeout(timer);
    try{
      task=await uiNext.request('/api/papers/api-completion/state');render();
      if(active()){needsRefresh=true;timer=setTimeout(()=>void poll(),700);}
      else if(needsRefresh && ['Completed','Partial','Failed','Cancelled'].includes(task.phase)){
        needsRefresh=false;await window.allfoldRefreshWorkspace?.();
      }
    }catch(error){$('api-completion-status').textContent=error.message;timer=setTimeout(()=>void poll(),1500);}
  }
  for(const id of ['api-completion-open','array-api-completion-open'])$(id).addEventListener('click',()=>{select();render();dialog.showModal();});
  $('api-completion-papers').addEventListener('change',render);
  $('api-completion-close').addEventListener('click',()=>dialog.close());
  $('api-completion-start').addEventListener('click',async()=>{
    const paper_ids=[...$('api-completion-papers').querySelectorAll('input:checked')].map(input=>input.value);
    if(active() || !paper_ids.length)return;
    submitting=true;render();
    try{
      if(window.allfoldAutosave && !await window.allfoldAutosave.flush())throw new Error('请先保存配置再补全');
      task=await uiNext.request('/api/papers/api-completion/start',{paper_ids});
      needsRefresh=true;
      submitting=false;render();void poll();
    }catch(error){submitting=false;render();$('api-completion-status').textContent=error.message;}
  });
  $('api-completion-cancel').addEventListener('click',async()=>{
    try{await uiNext.request('/api/papers/api-completion/cancel',{request_id:task?.request_id});void poll();}
    catch(error){$('api-completion-status').textContent=error.message;}
  });
  window.addEventListener('workspace-data-changed',()=>{if(!active()){select();render();}if(!restored){restored=true;void poll();}});
  window.addEventListener('workspace-reset',()=>{clearTimeout(timer);task=null;needsRefresh=false;select();render();});
  window.addEventListener('pagehide',()=>clearTimeout(timer));
  window.allfoldApiCompletion={active};
})();
