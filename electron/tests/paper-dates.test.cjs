const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function render(paper) {
  const context = {window:{}, document:{createElement:()=>({})}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/ui/paper-dates.js'),'utf8'), context);
  const first={},journal={replaceChildren(...children){this.children=children;}};
  context.window.allfoldPaperDates.render(paper,first,journal);
  return {first,journal};
}

test('journal date view shows Published without inventing Accepted or precision',()=>{
  const {journal}=render({publication_type:'journal',publication_date:'2027',date_evidence:[]});
  assert.equal(journal.children.length,1);
  assert.equal(journal.children[0].textContent,'Published · 2027');
});

test('source date labels remain provenance while journal events use four independent labels',()=>{
  const {first,journal}=render({publication_type:'journal',publication_date:'2027',first_public_at:'2020-03',date_evidence:[
    {kind:'published',year:2027,provider:'crossref',source_label:'published-print',publication_type:'journal'},
    {kind:'published-online',year:2026,month:9,provider:'wos',source_label:'EA',publication_type:'journal'},
    {kind:'accepted',year:2026,month:8,provider:'translator-web',publication_type:'journal'},
    {kind:'received',year:2026,month:6,provider:'pubmed',source_label:'received',publication_type:'journal'},
    {kind:'preprint',year:2020,month:3,first_version:true,provider:'arxiv',publication_type:'preprint'},
  ]});
  assert.equal(first.textContent,'2020-03');
  assert.deepEqual(Array.from(journal.children,item=>item.textContent),[
    'Received · 2026-06 · pubmed','Accepted · 2026-08 · translator-web','Published online · 2026-09 · wos','Published · 2027 · crossref']);
  assert.match(journal.children[3].title,/published-print/);
});

test('equal business events share a row with every raw source label in the tooltip',()=>{
  const event={kind:'published',year:2026,month:3,provider:'crossref',record_id:'10.5555/main',version:'1',publication_type:'journal'};
  const evidence=[...['published','published-print','issued'].map(source_label=>({...event,source_label})),
    {...event,kind:'accepted',source_label:'accepted'}, {...event,month:4,source_label:'published'},
    {...event,provider:'europe_pmc',source_label:'pubYear'}, {...event,version:'2',source_label:'published'},
    {...event,record_id:'10.5555/other',source_label:'published'}];
  const {journal}=render({date_evidence:evidence});
  assert.equal(journal.children.length,6);
  const combined=journal.children.find(item=>item.title.includes('published-print'));
  assert.equal(combined.textContent,'Published · 2026-03 · crossref');
  assert.match(combined.title,/published-print/);
  assert.match(combined.title,/issued/);
  assert.match(combined.title,/ · published(?:\n|$)/);
  assert.ok(journal.children.some(item=>item.textContent==='Accepted · 2026-03 · crossref'));
  assert.ok(journal.children.some(item=>item.textContent==='Published · 2026-04 · crossref'));
  assert.ok(journal.children.some(item=>item.textContent==='Published · 2026-03 · europe_pmc'));
  assert.equal(evidence.length,8);
});
