'use strict';
const test=require('node:test'),assert=require('node:assert/strict');

test('History does not restore retired Import or active Enrich projections',async()=>{
 const {renderHistoryRecord,filterHistoryRecords}=await import('../../frontend/ui/history-view.js');
 const retired=['import','kept','enrich'].map(kind=>({kind,task_id:kind,details:{zotero_keys:{parent_key:'PRIVATE'}}}));
 assert.deepEqual(retired.map(renderHistoryRecord),['','','']);assert.deepEqual(filterHistoryRecords(retired,''),[]);
});

test('history reuses Run status wording and distinguishes opened evidence from access confirmation',async()=>{
  const {renderHistoryRecord}=await import('../../frontend/ui/history-view.js');
  const run=renderHistoryRecord({kind:'run',provider:'crossref',task_id:'run_1',outcome:'partial',
    statistics:{created:2},details:{result_status:'incomplete'}});
  assert.match(run,/Crossref/);assert.match(run,/检索不完整/);
  const prep=renderHistoryRecord({kind:'prepare',task_id:'prep_1',outcome:'opened',statistics:{opened:1},
    details:{results:[{service_id:'svc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',outcome:'opened',reason:'target_opened',
      recovery:[{recovery_action:'resource_reentry',count:1,outcome:'recovered'}]}]}});
  assert.match(prep,/已打开/);assert.match(prep,/不代表订阅或下载已验证/);
  assert.match(prep,/重新访问 CARSI 资源 ×1 已恢复/);
});

test('history escapes record identity and only renders reviewed business fields',async()=>{
  const {renderHistoryRecord,historyIntegrityMessage}=await import('../../frontend/ui/history-view.js');
  const html=renderHistoryRecord({kind:'preprint',task_id:'<script>bad</script>',outcome:'completed',
    details:{saved_fields:['abstract','authors'],message:'PRIVATE_SENTINEL'},statistics:{arbitrary_secret:77}});
  assert.doesNotMatch(html,/<script>|PRIVATE_SENTINEL|arbitrary_secret/);
  assert.match(html,/摘要/);assert.match(html,/作者/);
  assert.match(historyIntegrityMessage({rotated_files:1,native:{status_known:true,incomplete:false}}),/不完整/);
});

test('interruption takes priority over a Run snapshot',async()=>{
 const {renderHistoryRecord}=await import('../../frontend/ui/history-view.js');
 const run=renderHistoryRecord({kind:'run',provider:'wos',task_id:'wos_1',outcome:'interrupted',details:{result_status:'failed',reason:'connection_lost'}});
 assert.match(run,/已中断/);assert.match(run,/连接中断/);
});

test('diagnostic download carries CSRF and does not turn JSON errors into ZIP downloads',async()=>{
  const {requestDiagnosticBundle}=await import('../../frontend/ui/history-view.js');
  let request;
  const zip=await requestDiagnosticBundle('task_1','csrf_1',async(path,options)=>{
    request={path,options};return new Response('zip',{headers:{'Content-Type':'application/zip'}});
  });
  assert.equal(await zip.text(),'zip');assert.equal(request.path,'/api/diagnostics/export');
  assert.deepEqual(JSON.parse(request.options.body),{csrf_token:'csrf_1',task_id:'task_1'});
  await assert.rejects(requestDiagnosticBundle(null,'csrf_1',async()=>new Response(
    JSON.stringify({message:'Task no longer retained'}),{status:409,headers:{'Content-Type':'application/json'}})),/Task no longer retained/);
});

test('reset scope descriptions have separate deletion boundaries',async()=>{
  const {resetImpact}=await import('../../frontend/ui/history-view.js');
  assert.match(resetImpact('workspace',{workspace:'/synthetic/workspace'}),/Paper/);
  assert.match(resetImpact('workspace',{workspace:'/synthetic/workspace'}),/日志保留/);
  assert.match(resetImpact('logs',{history_records:3}),/3/);
  assert.match(resetImpact('logs',{history_records:3}),/Workspace/);
  assert.doesNotMatch(resetImpact('logs',{history_records:3}),/输入|Type RESET/);
});

test('history filters by execution Service and exposes stable Paper identities and bounded Service totals',async()=>{
  const {filterHistoryRecords,renderHistoryRecord}=await import('../../frontend/ui/history-view.js');
  const a={kind:'run',task_id:'a',outcome:'partial',details:{batch_scope:'all',service_statistics:[
    {service_id:'svc_a',total:105,created:100}],results:[
    {paper_id:'paper-a',service_id:'svc_a',parent_outcome:'confirmed',pdf_outcome:'unverified',outcome:'confirmed'}]}};
  const b={kind:'prepare',task_id:'b',details:{batch_scope:'service',service_id:'svc_b'}};
  assert.deepEqual(filterHistoryRecords([a,b],'svc_a'),[a]);
  assert.deepEqual(filterHistoryRecords([a,b],'svc_b'),[b]);
  assert.equal(filterHistoryRecords([a,b],'').length,2);
  const html=renderHistoryRecord(a);
  assert.match(html,/All Services/);assert.match(html,/svc_a/);assert.match(html,/paper-a/);
  assert.match(html,/105/);assert.match(html,/新增 Paper 100/);
});

test('unified Run history presents selected sources and native batch hints',async()=>{
  const {renderHistoryRecord}=await import('../../frontend/ui/history-view.js');
  const html=renderHistoryRecord({kind:'run',provider:'integrated',task_id:'run-unified',outcome:'partial',
    details:{result_status:'incomplete',run_sources:[{provider:'wos',status:'partial',candidates:3,created:1,existing:2,problems:1}],
      wos_checks:{batches:2,completed_batches:1,journal_hints:1,date_hints:0,unmatched_records:1}}});
  assert.match(html,/3 candidates/);assert.match(html,/1 new \/ 2 existing/);assert.match(html,/WoS Export 1\/2/);
  assert.match(html,/1 期刊清单提示/);
});

test('Run results and History report foreground identity and registration without background totals',async()=>{
  const {renderHistoryRecord}=await import('../../frontend/ui/history-view.js');
  const {renderRunResult}=await import('../../frontend/ui/run-results.js');
  const statistics={identity_targets:2,identity_requests:3,collection_admitted:4,collection_reused:1,
    collection_registration_failed:1,excluded_papers:2,rebuilt_papers:1};
  const result={availability:'available',provider:'integrated',status:'completed',created_papers:4,existing_papers:1,
    details:{discovery_status:'complete'},journals:[],issues:[],statistics};
  for(const html of [renderRunResult(result),renderHistoryRecord({kind:'run',provider:'integrated',task_id:'run-registration',
    outcome:'completed',details:result.details,statistics})]){
    assert.match(html,/Collection admitted|已登记采集/);
    assert.match(html,/Registration failed|登记失败/);
    assert.doesNotMatch(html,/Completion|metadata completion|首版日期已记录/);
  }
});
