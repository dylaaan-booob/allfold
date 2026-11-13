'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process'),path=require('node:path');
const {validDOI,articleIdentity}=require('../src/browser/article-identity.cjs');
test('native DOI normalization matches shared Python identifiers including Unicode casefold',()=>{
  const inputs=[' DOI: 10.5555/TARGET ','https://dx.doi.org/10.5555/Name','10.5555/Straße','10.5555/Σς','10.5555/ﬃ','10.5555/ı','10.5555/Ꭰꭰ','ISSN 1234-5678','10.55/no','10.5555/white space'];
  const python=process.env.ALLFOLD_SOLVER_TEST_PYTHON || path.resolve(__dirname,'../../.venv/bin/python');
  const result=spawnSync(python,['-c','import json,sys; from allfold.identifiers import valid_doi; print(json.dumps([valid_doi(x) for x in json.loads(sys.argv[1])]))',JSON.stringify(inputs)],
    {env:{...process.env,PYTHONPATH:path.resolve(__dirname,'../../src')},encoding:'utf8'});
  assert.equal(result.status,0,result.stderr);assert.deepEqual(inputs.map(validDOI),JSON.parse(result.stdout));
});
test('explicit DOI-free relations and fixed absence/overflow/conflict outcomes',()=>{
  const doc={url:'https://fixture.invalid/article/42'},probe={values:[],limited:false,multiple:false,article:true};
  assert.deepEqual(articleIdentity({},doc,probe),{outcome:'not_applicable',reason:'identity_missing'});
  assert.equal(articleIdentity({confirmed_article_url:doc.url},doc,probe).outcome,'confirmed');
  assert.equal(articleIdentity({confirmed_article_url:'https://fixture.invalid/article/43'},doc,probe).outcome,'not_applicable');
  assert.equal(articleIdentity({doi:'10.5555/a'},doc,{...probe,values:['10.5555/a','10.5555/b']}).outcome,'conflict');
  assert.equal(articleIdentity({doi:'10.5555/a'},doc,{...probe,values:['10.5555/a'],limited:true}).reason,'evidence_limit');
});

test('fragment article routes and complete DOI suffixes remain distinct identity facts',()=>{
  const probe={values:[],limited:false,multiple:false,article:true};
  const target={confirmed_article_url:'https://fixture.invalid/#/article/1'};
  assert.equal(articleIdentity(target,{url:'https://fixture.invalid/#/article/2'},probe).outcome,'not_applicable');
  const doc={url:'https://projecteuclid.org/journals/example/10.1214/aos/1176342506.full'};
  assert.equal(articleIdentity({doi:'10.1214/aos/1176342506'},doc,probe).outcome,'confirmed');
  assert.equal(articleIdentity({doi:'10.5555/target'},doc,{...probe,values:['10.5555/target']}).outcome,'conflict');
});

test('known IOP view routes do not become extra DOI suffix segments',()=>{
  const doi='10.1088/0022-3727/34/10/311';
  for(const ending of ['/meta','/meta/','/pdf','/']) {
    const doc={url:'https://iopscience.iop.org/article/'+doi+ending};
    const probe={values:[doi],limited:false,multiple:false,article:true};
    assert.equal(articleIdentity({doi},doc,probe).outcome,'confirmed');
    assert.equal(articleIdentity({doi:'10.5555/target'},doc,{...probe,values:['10.5555/target']}).outcome,'conflict');
  }
});
