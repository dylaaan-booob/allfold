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

test('source date labels remain provenance while journal events use three business labels',()=>{
  const {first,journal}=render({publication_type:'journal',publication_date:'2027',first_public_at:'2020-03',date_evidence:[
    {kind:'published',year:2027,provider:'crossref',source_label:'published-print',publication_type:'journal'},
    {kind:'published-online',year:2026,month:9,provider:'wos',source_label:'EA',publication_type:'journal'},
    {kind:'accepted',year:2026,month:8,provider:'translator-web',publication_type:'journal'},
    {kind:'preprint',year:2020,month:3,first_version:true,provider:'arxiv',publication_type:'preprint'},
  ]});
  assert.equal(first.textContent,'2020-03');
  assert.deepEqual(Array.from(journal.children,item=>item.textContent),[
    'Accepted · 2026-08 · translator-web','Published online · 2026-09 · wos','Published · 2027 · crossref']);
  assert.match(journal.children[2].title,/published-print/);
});
