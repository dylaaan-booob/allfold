'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function render(paper){
  const createElement=tagName=>({tagName,children:[],append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=nodes;}});
  const context={window:{},URL,document:{createElement}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/ui/paper-dates.js'),'utf8'),context);
  const fields=['ordinary','preprint'].map(dateSet=>({dataset:{dateSet}})),list=createElement('ol');
  context.window.allfoldPaperDates.render(paper,{querySelectorAll:()=>fields},list);
  return {dates:fields.map(field=>field.textContent),rows:list.children};
}
test('Reader renders the ordinary date set independently from verified Preprint',()=>{
  assert.deepEqual(render({publication_date:'2030',ordinary_dates:['2027-04-03','2026-03','2027-04-03'],first_public_at:'2026-03'}).dates,['2026-03 · 2027-04-03','2026-03']);
  assert.deepEqual(render({publication_date:'2026',preprints:[{provider:'arxiv',identifier:'2204.12345',date:'2022-04',version:'v2',first_version:false}]}).dates,['—','—']);
});
test('Info retains Preprint version proof and refuses unsafe source links',()=>{
  const {rows}=render({preprints:[{provider:'europe_pmc',identifier:'PPR1234',date:'2022-04-03',version:'v1',version_family:'family-a',first_version:true,url:'https://europepmc.org/article/PPR/PPR1234'},
    {provider:'crossref',identifier:'10.5555/preprint',date:null,first_version:false,url:'https://user:secret@example.test/preprint'}]});
  assert.match(rows[0].children[0].textContent,/2022-04-03 · europe_pmc · PPR1234 · Version v1 · Family family-a · First version: true/);
  assert.equal(rows[0].children[1].href,'https://europepmc.org/article/PPR/PPR1234');
  assert.equal(rows[0].children[1].rel,'noopener noreferrer');assert.equal(rows[1].children.length,1);
  assert.deepEqual(render(null).dates,['—','—']);
});
