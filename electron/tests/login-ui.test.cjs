'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {taskUI}=require('./task-ui-fixture.cjs');

test('Login starts explicitly and opens the Page that belongs to the waiting task',async()=>{
  const idle={active:false,phase:'idle',carsi:{status:'Not prepared'},services:[{
    id:'manual-a',name:'Manual A',access_method:'manual',access_url:'https://example.test/',preparation:{status:'Not prepared'},
  }]};
  const running={...idle,active:true,phase:'preparing',workflow_id:'login-a',services:[{
    ...idle.services[0],preparation:{status:'Preparing',waiting_for_user:true,page_id:9,workflow_id:'login-a',task_id:'manual-task'},
  }]};
  const ui=await taskUI('login.js',{page:'login',request:async route=>route.endsWith('/start')?running:route.endsWith('/cancel')?
    {...idle,phase:'canceled',workflow_id:'login-a'}:idle});
  const row=ui.get('login-services').children[0],visit=row.children.find(node=>node.textContent==='Visit');
  await visit.emit('click');
  assert.equal(ui.calls.find(([path])=>path==='/api/login/start')?.[1].service_id,'manual-a');
  const view=ui.get('login-services').children[0].children.find(node=>node.textContent==='查看任务页面');
  await view.emit('click');
  assert.deepEqual({...ui.presentations[0]},{pageId:9,workflowId:'login-a',taskId:'manual-task'});
  await ui.get('login-cancel').emit('click');
  assert.equal(ui.calls.find(([path])=>path==='/api/login/cancel')?.[1].workflow_id,'login-a');
});

test('Login reads the active task after an ambiguous start response without replaying',async()=>{
  const idle={active:false,phase:'idle',carsi:{},services:[{id:'service-a',name:'Service A',access_method:'carsi'}]};
  let state=idle;
  const ui=await taskUI('login.js',{page:'login',request:async route=>{
    if(route.endsWith('/start')){
      state={...idle,active:true,phase:'carsi',workflow_id:'login-a'};
      throw Error('Response lost');
    }
    return state;
  }});
  await ui.get('login-start').emit('click');
  assert.equal(ui.calls.filter(([route])=>route.endsWith('/start')).length,1);
  assert.equal(ui.calls.filter(([route])=>route.endsWith('/state')).length,2);
  assert.equal(ui.get('login-start').disabled,true);
  assert.equal(ui.get('login-cancel').hidden,false);
});
