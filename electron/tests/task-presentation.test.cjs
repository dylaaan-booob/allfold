'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {taskUI}=require('./task-ui-fixture.cjs');
function runData(status='RUNNING',provider='integrated') {return {snapshot:{status,provider,task_id:'run-1',waiting_for_user:provider==='wos'},progress:{stage_label:'Retrieving papers',elapsed_text:'2s',announcement_message:'Waiting for source'},result_summary:{status:'completed'},providers:{wos:{snapshot:{status:'IDLE'}}}};}
test('inline Run polls and refreshes results without constructing a player or returning from another workspace',async()=>{
  let state=runData();
  const ui=await taskUI('run.js',{request:async()=>state});
  await ui.window.uiRun.start('integrated');await ui.settle();
  assert.equal(ui.get('run-view').open,false);
  assert.equal(ui.stats().visuals,0);
  assert.match(ui.get('run-inline').textContent || ui.get('run-stage').textContent,/Retrieving/);
  ui.setPage('journals');state=runData('FINISHED');await ui.tick();
  assert.equal(ui.window.uiRun.active(),false);assert.equal(ui.stats().prepares,1);
  assert.equal(ui.page(),'journals');assert.equal(ui.stats().opens,0);
});
function keptState(phase='waiting_for_user',changes={}) {return {workflow_id:'workflow-1',generation:7,phase,active:['preparing','waiting_for_user','transition','importing','stopping'].includes(phase),can_continue:phase==='waiting_for_user',can_cancel:!['completed','stopping','idle'].includes(phase),waiting_for_login:false,settings:{display_name:'Synthetic researcher',auto_import_after_preparation:false},preparation:{services:[],manual_services:[],results:[]},message:'Review access before import',...changes};}
test('fullscreen Run waits for its workspace owner and restores the same task without a new start',async()=>{
  const running=runData('RUNNING','wos');running.providers.wos={snapshot:running.snapshot};
  const ui=await taskUI('run.js',{inline:false,page:'workspace',request:async()=>running});
  ui.window.uiRunPage.open=()=>false;
  await ui.window.uiRun.start('wos');await ui.settle();
  assert.equal(ui.window.uiRun.active(),false);assert.equal(ui.get('run-view').open,false);
  ui.window.uiRunPage.open=()=>{ui.setPage('run');return true;};
  ui.window.dispatchEvent({type:'inbox-ready'});await ui.settle();
  assert.equal(ui.window.uiRun.active(),true);assert.equal(ui.page(),'run');assert.equal(ui.get('run-view').open,true);
  assert.equal(ui.calls.filter(([url,body])=>url==='/api/ui-next/run-wos' && body!==undefined).length,1);
});
test('inline Kept recovers from Archive into visible controls and retains identity through continue, cancel and settlement',async()=>{
  let state=keptState('waiting_for_user',{preparation_task_id:'prepare-1'});
  const ui=await taskUI('kept.js',{inline:true,archiveDisabled:false,layout:'archive',page:'workspace',request:async(path,body)=>{
    if(path.includes('clips.json'))return {};
    if(path.endsWith('/continue'))state=keptState('importing',{import_started:true});
    if(path.endsWith('/cancel'))state=keptState('stopping',{can_cancel:false});
    if(path.endsWith('/acknowledge'))return {};
    return state;
  }});
  assert.equal(ui.get('kept-flow').open,false);assert.equal(ui.stats().visuals,0);
  assert.equal(ui.page(),'kept');
  assert.equal(ui.get('selected-view').dataset.workspaceLayout,'archive');
  assert.equal(ui.get('kept-view').dataset.status,'candidates');
  assert.equal(ui.get('array-import-profile').hidden,false);assert.equal(ui.get('kept-inline').hidden,false);
  assert.equal(ui.get('kept-flow-actions').parentElement,ui.get('kept-inline'));
  assert.equal(ui.get('kept-continue').hidden,false);assert.equal(ui.get('kept-leave').disabled,false);
  assert.equal(ui.window.workspaceArray.workflowBusy(),true);assert.equal(ui.window.workspaceArray.navigationBusy(),false);
  assert.equal(ui.calls.some(([url])=>url.endsWith('/start') || url.endsWith('/continue')),false);
  const taskPageButton=ui.get('kept-flow-actions').children.find(node=>node.textContent==='查看任务页面');
  assert.equal(taskPageButton.hidden,false);await taskPageButton.emit('click');
  assert.deepEqual(JSON.parse(JSON.stringify(ui.presentations)),[{workflowId:'workflow-1',source:'kept',taskId:'prepare-1'}]);
  await ui.get('kept-continue').emit('click');
  const continuation=ui.calls.find(([url])=>url.endsWith('/continue'));
  assert.deepEqual(JSON.parse(JSON.stringify(continuation[1])),{workflow_id:'workflow-1',generation:7});
  await ui.get('kept-leave').emit('click');
  assert.deepEqual(JSON.parse(JSON.stringify(ui.calls.find(([url])=>url.endsWith('/cancel'))[1])),{workflow_id:'workflow-1',generation:7});
  assert.equal(ui.get('kept-leave').disabled,true);
  await ui.get('workspace-archive').emit('click');ui.setPage('settings');await ui.tick();await ui.get('run-view').emit('close');
  assert.equal(ui.page(),'settings');assert.equal(ui.get('selected-view').dataset.workspaceLayout,'archive');
  state=keptState('completed',{import_started:true,navigation:'kept',batch:{total:1,results:[{paper_id:'paper-1',outcome:'exported',parent_outcome:'confirmed',reason:'Imported'}]}});await ui.tick();
  assert.ok(ui.calls.some(([url])=>url.endsWith('/acknowledge')));assert.equal(ui.window.workspaceArray.workflowBusy(),false);
  assert.equal(ui.get('kept-record-count').textContent,'1 / 1');assert.equal(ui.page(),'settings');assert.equal(ui.stats().visuals,0);
});
test('restored inline Run WoS opens its existing task page and cancels with the restored task identity',async()=>{
  const wos=runData('RUNNING','wos');
  const ui=await taskUI('run.js',{ready:true,request:async path=>path==='/api/ui-next/run'?{...runData('IDLE'),providers:{wos:{snapshot:wos.snapshot}}}:wos});
  assert.equal(ui.get('run-view').open,false);assert.equal(ui.stats().visuals,0);
  const button=ui.get('run-status-area').children.find(node=>node.textContent==='查看任务页面');
  assert.equal(button.hidden,false);await button.emit('click');
  assert.deepEqual(JSON.parse(JSON.stringify(ui.presentations)),[{workflowId:'run-1',source:'run'}]);
  await ui.get('run-wos-cancel').emit('click');
  assert.deepEqual(JSON.parse(JSON.stringify(ui.calls.find(([path])=>path.endsWith('/cancel'))[1])),{task_id:'run-1'});
  assert.equal(ui.calls.filter(([path,body])=>path==='/api/ui-next/run-wos' && body).length,0);
});
test('Kept inline login and manual gates obey server permission flags and never auto-continue from animation settings',async()=>{
  let state=keptState('waiting_for_user',{waiting_for_login:true,can_continue:false,settings:{auto_import_after_preparation:true},preparation:{services:[],manual_services:[{id:'manual',name:'Manual service'}],results:[]}});
  const ui=await taskUI('kept.js',{request:async path=>path.includes('clips.json')?{}:state});
  assert.equal(ui.get('kept-continue').hidden,true);await ui.get('kept-continue').emit('click');
  assert.equal(ui.calls.some(([path])=>path.endsWith('/continue')),false);
  assert.equal(ui.get('kept-phase').textContent,'等待机构登录');
  const button=ui.get('kept-flow-actions').children.find(node=>node.textContent==='查看任务页面');await button.emit('click');
  assert.equal(ui.presentations[0].workflowId,'workflow-1');
  state={...state,waiting_for_login:false,can_continue:true};await ui.tick();
  assert.equal(ui.get('kept-phase').textContent,'等待确认');assert.equal(ui.get('kept-continue').hidden,false);
  assert.equal(ui.calls.some(([path])=>path.endsWith('/continue')),false);
});
test('fullscreen Kept keeps its player while controls and terminal acknowledgement use backend snapshots',async()=>{
  let state=keptState();
  const ui=await taskUI('kept.js',{inline:false,request:async path=>path.includes('clips.json')?{}:state});
  assert.equal(ui.get('kept-flow').open,true);assert.equal(ui.stats().visuals,1);assert.equal(ui.window.workspaceArray.navigationBusy(),true);
  state=keptState('completed',{navigation:'kept'});await ui.tick();
  // The player double never finishes a clip. Acknowledgement and results still settle.
  assert.ok(ui.calls.some(([path])=>path.endsWith('/acknowledge')));
});
test('display preference changes apply on the next Run and do not cancel the current task',async()=>{
  let state=runData();
  const ui=await taskUI('run.js',{request:async()=>state,reduced:true});
  await ui.window.uiRun.start('integrated');ui.setInline(false);
  ui.window.dispatchEvent({type:'ui-preferences-changed',detail:{name:'fullscreenDisabled',value:false}});
  await ui.tick();assert.equal(ui.get('run-view').open,false);assert.equal(ui.window.uiRun.active(),true);
  state=runData('FINISHED');await ui.tick();state=runData();await ui.window.uiRun.start('integrated');await ui.settle();
  assert.equal(ui.get('run-view').open,true);assert.equal(ui.stats().visuals,1);
});
test('inline recovery is independent of the animation manifest and font scene readiness',async()=>{
  const ui=await taskUI('kept.js',{request:async path=>{
    if(path.includes('clips.json'))throw Error('Animation asset unavailable');
    return keptState('preparing',{can_continue:false});
  }});
  assert.equal(ui.window.workspaceArray.workflowBusy(),true);
  assert.equal(ui.get('kept-phase').textContent,'Preparation');
  assert.equal(ui.get('kept-flow').open,false);assert.equal(ui.stats().visuals,0);
});

test('Run waits for autosave and refuses to start when the draft is still pending',async()=>{
  const ui=await taskUI('run.js',{request:async()=>runData()});
  let settleSave;ui.window.allfoldAutosave={flush:()=>new Promise(resolve=>{settleSave=resolve;})};
  const first=ui.window.uiRun.start('integrated');await ui.settle();
  assert.equal(ui.calls.filter(([path,body])=>path==='/api/ui-next/run' && body).length,0);
  settleSave(false);await first;
  assert.equal(ui.calls.filter(([path,body])=>path==='/api/ui-next/run' && body).length,0);
  ui.window.allfoldAutosave.flush=async()=>true;
  await ui.window.uiRun.start('integrated');
  assert.equal(ui.calls.filter(([path,body])=>path==='/api/ui-next/run' && body).length,1);
});
