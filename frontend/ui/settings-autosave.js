// Serial ordinary-field patches. Controllers retain ownership of DOM and secrets.
const copy=value=>structuredClone(value);
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const changes=(saved,values)=>Object.fromEntries(Object.entries(values).filter(([key,value])=>!same(value,saved[key])));
export function createAutosave({write,onSaved=()=>{},onRestore=()=>{},onState=()=>{},storage=null,key='',delay=450,retryDelay=1200}) {
  let baseline=null,values=null,status='Saved',inflight=null,timer=null,disposed=false,paused=false,submittedValues=null,storageError='';
  function persist() {
    if(!storage || !key || !baseline)return;
    try {
      if(dirty() || submittedValues)storage.setItem(key,JSON.stringify({base:baseline.base,saved:baseline.values,values,pendingKeys:submittedValues?Object.keys(changes(baseline.values,submittedValues)):[]}));
      else storage.removeItem(key);
      storageError='';
    } catch {storageError='本地恢复存储不可用；关闭前请提交或保留窗口。';}
  }
  const dirty=()=>!!baseline && Object.keys(changes(baseline.values,values)).length>0;
  function emit() {onState({status,dirty:dirty() || !!submittedValues,busy:!!inflight,storageError});}
  function schedule(wait=delay) {
    clearTimeout(timer);
    if(!disposed && !paused)timer=setTimeout(()=>{timer=null;void flush();},wait);
  }
  function initialize(data,{restore=true}={}) {
    clearTimeout(timer);paused=false;submittedValues=null;baseline=copy(data);values=copy(data.values);status='Saved';
    if(restore && storage && key)try {
      const restored=JSON.parse(storage.getItem(key));
      if(restored?.base && restored?.saved && restored?.values) {
        // Restoration copies only keys supplied by the ordinary-field adapter.
        const retained=changes(restored.saved,restored.values);
        for(const field of restored.pendingKeys || [])if(Object.hasOwn(restored.values,field))retained[field]=restored.values[field];
        for(const field of Object.keys(values))if(Object.hasOwn(retained,field))values[field]=copy(retained[field]);
        status=same(restored.base,baseline.base)?(dirty()?'Pending':'Saved'):'Conflict';
        onRestore(copy(values));
      }
    } catch {storageError='恢复草稿无法读取；关闭前请检查配置。';}
    persist();emit();if(dirty() && status==='Pending')schedule();
  }
  function edit(next,{immediate=false}={}) {
    if(!baseline)return;
    values=copy(next);
    if(status!=='Conflict' && status!=='Partial')status=inflight || submittedValues || dirty()?'Pending':'Saved';
    persist();emit();
    if(!['Conflict','Partial'].includes(status) && (dirty() || submittedValues))schedule(immediate?0:delay);
  }
  async function send() {
    const submitted=copy(values),patch=changes(baseline.values,submitted),base=copy(baseline.base);
    submittedValues=submitted;status='Saving';persist();emit();
    let result;
    try {result=await write({base,changes:patch});}
    catch {status='Failed';persist();emit();return false;}
    if(!result.saved) {
      status=result.outcome==='TASK_ACTIVE'?'Pending':result.outcome==='REVISION_CONFLICT'?'Conflict':result.outcome==='PARTIAL_SAVE'?'Partial':'Failed';
      persist();emit();if(result.outcome==='TASK_ACTIVE')schedule(retryDelay);
      return false;
    }
    // The acknowledged request owns only the exact values it sent. Edits made
    // while it was in flight survive the new canonical baseline and revisions.
    const latest=copy(values);
    baseline={base:copy(result.base),values:copy(result.values)};
    values=copy(result.values);
    for(const field of Object.keys(latest))if(!same(latest[field],submitted[field]))values[field]=latest[field];
    submittedValues=null;status=dirty()?'Pending':'Saved';persist();onSaved(result,copy(values));emit();return true;
  }
  async function flush() {
    clearTimeout(timer);timer=null;
    if(!baseline || disposed || paused || ['Conflict','Partial'].includes(status))return false;
    if(inflight){const ok=await inflight;if(!ok)return false;}
    while(dirty() || submittedValues) {
      if(paused)return false;
      if(inflight){if(!await inflight)return false;continue;}
      const request=send();inflight=request;emit();
      let ok;try{ok=await request;}finally{if(inflight===request)inflight=null;emit();}
      if(!ok)return false;
    }
    return true;
  }
  function rebase(data) {
    if(inflight)return false;
    const retained=changes(baseline.values,values);
    submittedValues=null;baseline=copy(data);values=copy(data.values);
    for(const field of Object.keys(values))if(Object.hasOwn(retained,field))values[field]=copy(retained[field]);
    status=dirty()?'Pending':'Saved';persist();onRestore(copy(values));emit();return true;
  }
  return {initialize,edit,flush,rebase,retry:flush,get dirty(){return dirty() || !!submittedValues;},get busy(){return !!inflight;},get status(){return status;},
    async pause(){paused=true;clearTimeout(timer);if(inflight)await inflight;},resume(){paused=false;if(dirty() && !['Conflict','Partial'].includes(status))schedule();},dispose(){disposed=true;clearTimeout(timer);}};
}
