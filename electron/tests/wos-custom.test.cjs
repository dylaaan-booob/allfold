'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const {pageStep,SELECTORS}=require('../src/workflows/page-actions.cjs');

// Synthetic controls matching the live WoS Core Collection editor inspected on
// 2026-11-07. No account page, exported record, or generated Angular ID is stored.
const wanted=[
  'authorTitleSource_AUTHORS','authorTitleSource_TITLE','authorTitleSource_SOURCE',
  'authorTitleSource_ISSN','authorTitleSource_PMID','abstractKeywordAddress_ABSTRACT',
  'abstractKeywordAddress_DOCTYPE','abstractKeywordAddress_KEYWORDS',
];
const other=[
  'authorTitleSource_CONFERENCE_INFO','authorTitleSource_CITTIMES','authorTitleSource_AUTHORSIDENTIFIERS',
  'abstractKeywordAddress_ADDRS','abstractKeywordAddress_AFFILIATIONS','abstractKeywordAddress_JCR_CATEGORY',
  'abstractKeywordAddress_SUBJECT_CATEGORY','abstractKeywordAddress_WOS_EDITIONS',
  'citedRefUse_CITREF','citedRefUse_CITREFC','citedRefUse_USAGEIND','citedRefUse_HOT_PAPER','citedRefUse_HIGHLY_CITED',
  'fundingOther_FUNDING','fundingOther_PUBINFO','fundingOther_OPEN_ACCESS','fundingOther_PAGEC',
  'fundingOther_SABBR','fundingOther_IDS','fundingOther_LANG',
];
function fixture(initial=[]) {
  const visible=()=>[{}];
  let editor=true,menu=false,selected='Author, Title, Source',exports=0;
  class Input {
    constructor(name,value='') {this.name=name;this._value=value;this.checked=false;this.indeterminate=false;this.disabled=false;this.readOnly=false;this.clicks=0;this.attributes={};this.getClientRects=visible;}
    get value(){return this._value;}
    set value(value){this._value=value;}
    getAttribute(key){return key==='aria-label'?this.name:this.attributes[key] || null;}
    dispatchEvent(){}
    click(){this.clicks++;this.checked=!this.checked;}
  }
  const fields=[...wanted,...other].map(name=>{const input=new Input(name);input.checked=initial.includes(name);return input;});
  const group=new Input('authorTitleSource');group.indeterminate=true;
  const radio=new Input('range');radio.checked=true;
  const first=new Input('first','1'),last=new Input('Input ending record range. A maximum of 1000 records can be exported at one time.','2');
  const save={getClientRects:visible,innerText:'Save selections',getAttribute:()=>null,click(){editor=false;selected=`Custom selection (${fields.filter(i=>i.checked).length})`;}};
  const edit={getClientRects:visible,innerText:'Edit',getAttribute:()=>null,click(){editor=true;menu=false;}};
  const combo={getClientRects:visible,get innerText(){return selected;},getAttribute:()=>null,click(){menu=true;}};
  const exportButton={getClientRects:visible,getAttribute:()=>null,click(){exports++;}};
  // The real Angular host uses display:contents, so only its modal ancestor has a box.
  const custom={getClientRects:()=>[],closest:()=>({getClientRects:visible}),
    querySelectorAll:selector=>selector==='input[type="checkbox"][aria-label]'?[group,...fields]:selector==='button'?[save]:[]};
  const content={getClientRects:visible,querySelectorAll:selector=>selector===SELECTORS.editContent?[edit]:[]};
  const dialog={getClientRects:visible,querySelectorAll:selector=>({
    [SELECTORS.first]:[first],[SELECTORS.last]:[last],[SELECTORS.range]:[radio],
    '[role="combobox"]':[combo],'wos-select button[role="combobox"]':[combo],[SELECTORS.export]:[exportButton],
  }[selector] || [])};
  const context=vm.createContext({Date,Set,Event:class{},HTMLInputElement:Input,HTMLTextAreaElement:Input,
    location:{pathname:'/wos/woscc/summary/synthetic'},getComputedStyle:()=>({visibility:'visible'}),
    document:{body:{innerText:''},querySelectorAll:selector=>selector===SELECTORS.customDialog?(editor?[custom]:[]):
      selector===SELECTORS.content?(menu?[content]:[]):selector===SELECTORS.dialog?[dialog]:[]}});
  const run=(op,args={})=>JSON.parse(JSON.stringify(vm.runInContext('('+pageStep.toString()+')(...'+JSON.stringify([op,args,SELECTORS,Date.now()+3000])+')',context)));
  return {fields,group,first,last,radio,run,get exports(){return exports;},
    reopen(){editor=true;},close(){editor=false;},setLabel(value){selected=value;}};
}

test('Custom selects exactly the eight business fields from arbitrary states and is idempotent',()=>{
  for(const initial of [[],[...wanted,...other],['authorTitleSource_TITLE','citedRefUse_HOT_PAPER']]) {
    const f=fixture(initial);
    assert.equal(f.run('configureCustom').verified,true);
    assert.deepEqual(f.fields.filter(i=>i.checked).map(i=>i.name).sort(),[...wanted].sort());
    const clicks=f.fields.map(i=>i.clicks);
    assert.equal(f.run('configureCustom').verified,true);
    assert.deepEqual(f.fields.map(i=>i.clicks),clicks,'a second application must not toggle choices');
    assert.equal(f.group.clicks,0,'mixed group controls are not leaf fields');
    assert.deepEqual(f.run('saveCustom'),{ok:true});
    f.reopen();assert.equal(f.run('verifyCustom').verified,true);
  }
});

test('eight selected fields is insufficient when their identities are wrong',()=>{
  const f=fixture([...wanted.slice(1),other[0]]);
  assert.equal(f.fields.filter(i=>i.checked).length,8);
  assert.deepEqual(f.run('verifyCustom'),{error:'export_content_unverified'});
  assert.deepEqual(f.run('saveCustom'),{error:'export_content_unverified'});
});

test('Custom fails closed on missing/duplicate controls or a selected disabled unwanted field',()=>{
  const missing=fixture(wanted);missing.fields.shift();
  assert.deepEqual(missing.run('configureCustom'),{error:'export_content_unverified'});
  const duplicate=fixture(wanted);duplicate.fields.push(duplicate.fields[0]);
  assert.deepEqual(duplicate.run('verifyCustom'),{error:'export_content_unverified'});
  const disabled=fixture([...wanted,other[0]]);disabled.fields.find(i=>i.name===other[0]).disabled=true;
  assert.deepEqual(disabled.run('configureCustom'),{error:'control_disabled'});
});

test('per-export limit comes from current range description and has no historical default',()=>{
  const f=fixture();f.close();
  assert.deepEqual(f.run('dialog'),{ready:true,limit:1000});
  f.last.name='Input ending record range. A maximum of 500 records can be exported at one time.';
  assert.deepEqual(f.run('dialog'),{ready:true,limit:500});
  f.last.name='Input ending record range.';f.last.attributes.max='9000';
  assert.deepEqual(f.run('dialog'),{error:'export_range_unverified'});
});

test('export needs a verified field set as well as current Custom content and range',()=>{
  const f=fixture(wanted);f.run('saveCustom');
  assert.deepEqual(f.run('export',{first:1,last:2}),{error:'export_content_unverified'});
  assert.equal(f.exports,0);
  f.setLabel('Full Record');
  assert.deepEqual(f.run('export',{first:1,last:2,customVerified:true}),{error:'export_content_unverified'});
  f.setLabel('Custom selection (8)');f.last.value='3';
  assert.deepEqual(f.run('export',{first:1,last:2,customVerified:true}),{error:'export_range_unverified'});
  f.last.value='2';
  f.last.name='A maximum of 1 records can be exported at one time.';
  assert.deepEqual(f.run('export',{first:1,last:2,customVerified:true}),{error:'export_range_unverified'});
  f.last.name='A maximum of 2 records can be exported at one time.';
  assert.deepEqual(f.run('export',{first:1,last:2,customVerified:true}),{ok:true});
  assert.equal(f.exports,1);
});
