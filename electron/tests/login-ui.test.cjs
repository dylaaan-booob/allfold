'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {taskUI}=require('./task-ui-fixture.cjs');

test('Login starts explicitly and directs the waiting user to the Browser group',async()=>{
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
  const current=ui.get('login-services').children[0];
  assert.ok(current.children.some(node=>node.textContent==='请在 Browser 的对应分组完成验证'));
  assert.ok(!current.children.some(node=>node.textContent==='查看任务页面'));
  assert.equal(ui.get('login-confirm').hidden,true);
  await ui.get('login-cancel').emit('click');
  assert.equal(ui.calls.find(([path])=>path==='/api/login/cancel')?.[1].workflow_id,'login-a');
});

test('Login offers one explicit confirmation for a finished batch',async()=>{
  const services=['one','two'].map(id=>({id,name:id,access_method:'carsi',preparation:{status:'Failed'}}));
  let state={active:false,phase:'completed',workflow_id:'visit-a',confirmation_workflow_id:'login-a',carsi:{},services};
  const ui=await taskUI('login.js',{page:'login',request:async route=>{
    if(route.endsWith('/confirm'))state={...state,phase:'confirmed',confirmation_workflow_id:null,
      services:services.map(service=>({...service,preparation:{status:'Opened',reason:'manual_login_confirmed'}}))};
    return state;
  }});
  const confirm=ui.get('login-confirm');
  assert.equal(confirm.hidden,false);
  assert.ok(ui.get('login-services').children.every(row=>!row.children.some(node=>node.dataset.loginAction==='confirm')));
  await confirm.emit('click');
  const calls=ui.calls.filter(([route])=>route.endsWith('/confirm'));
  assert.equal(calls.length,1);
  assert.equal(calls[0][1].workflow_id,'login-a');
  assert.equal(confirm.hidden,true);
  assert.ok(ui.get('login-services').children.every(row=>row.children.some(node=>node.textContent==='Manually confirmed')));
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
