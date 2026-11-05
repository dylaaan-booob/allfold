// A single public target preference shares Settings autosave and revision checks.
const host=document.getElementById('kept-zotero-target');
if(host) {
  const library=host.querySelector('[data-zotero-library]'),collection=host.querySelector('[data-zotero-collection]'),status=host.querySelector('[data-zotero-status]');
  const refresh=host.querySelector('[data-zotero-refresh]'),authorize=host.querySelector('[data-zotero-authorize]');
  let discovery=null,busy=false;
  const messages={authorization_denied:'已拒绝 Zotero 授权；如需导入，请重新授权并选择 Always Allow。',unsupported_version:'需要 Zotero 10.0.6 或更新版本。',authorization_required:'请授权 Zotero 并选择 Always Allow。',always_allow_required:'一次性 Allow 无法用于完整导入，请重新授权并选择 Always Allow。',access_denied:'Zotero 拒绝访问；检查 Local API 开关与 Library 权限。',server_id_mismatch:'Zotero 实例已变化，请刷新并重新选择目标。',target_missing:'Library 或 Collection 已不存在，请重新选择。',rate_limited:'Zotero 授权请求过于频繁，请稍后重试。',connection_lost:'无法连接 Zotero Desktop。',runtime_unavailable:'Electron 未连接。',encryption_unavailable:'系统安全存储不可用，未保存授权。',task_active:'当前任务仍在运行，请等待结果。',key_store_unreadable:'无法读取安全存储中的授权，请检查系统安全存储。'};
  const selected=()=>window.allfoldZoteroPreference?.value;
  const option=(value,text)=>{const row=document.createElement('option');row.value=value;row.textContent=text;return row;};
  function render() {
    const target=selected();
    if(discovery && target && target.server_id!==discovery.server_id)status.textContent=messages.server_id_mismatch;
    const libraries=discovery?.libraries || [];
    library.replaceChildren(option('','选择 Library'),...libraries.map(row=>option(row.type+':'+row.id,row.name)));
    const id=target?target.library_type+':'+target.library_id:'';
    if(target && !libraries.some(row=>row.type+':'+row.id===id))library.append(option(id,(target.library_type==='user'?'My Library':'Group '+target.library_id)+' · '+target.server_id));
    library.value=id;
    const current=libraries.find(row=>row.type+':'+row.id===id);
    collection.replaceChildren(option('','Library root'),...(current?.collections || []).map(row=>option(row.key,row.path)));
    if(target?.collection_key && !current?.collections?.some(row=>row.key===target.collection_key))collection.append(option(target.collection_key,target.collection_key));
    collection.value=target?.collection_key || '';
    library.disabled=busy || !discovery;collection.disabled=busy || !current;
    refresh.disabled=authorize.disabled=busy;
  }
  async function request(operation) {
    if(busy)return;busy=true;render();
    try {
      const result=await uiNext.request('/api/ui-next/zotero',{operation});
      if(!result.ok)throw Object.assign(Error(),{code:result.error});
      if(operation==='authorize') {status.textContent='已授权。刷新后选择 Library / Collection。';}
      else {discovery=result;status.textContent=result.authorized?'已连接 Zotero。Group 的条目与文件权限将在写入时核验。':'已连接 Zotero，请授权并选择 Always Allow。';}
    } catch(error){status.textContent=messages[error.code || error.state?.error] || error.message || 'Zotero 操作失败。';}
    finally{busy=false;render();}
  }
  async function save() {
    const parts=library.value.split(':');if(parts.length!==2 || !discovery)return;
    const target={server_id:discovery.server_id,library_type:parts[0],library_id:parts[1],collection_key:collection.value || null};
    busy=true;render();
    try {if(!await window.allfoldZoteroPreference?.set(target))throw Error('目标尚未保存，请核对 Settings 保存状态。');status.textContent='目标已保存；已开始的批次保留原目标。';}
    catch(error){status.textContent=error.message;}finally{busy=false;render();window.dispatchEvent(new Event('zotero-target-changed'));}
  }
  library.addEventListener('change',()=>{collection.value='';void save();});
  collection.addEventListener('change',()=>void save());
  refresh.addEventListener('click',()=>void request('targets'));authorize.addEventListener('click',()=>void request('authorize'));
  window.addEventListener('settings-saved',render);window.addEventListener('settings-loaded',render);window.addEventListener('kept-settings-mount',render);
  status.textContent='选择本配置的 Zotero 目标；首次使用请 Refresh 与 Authorize。';render();
}
