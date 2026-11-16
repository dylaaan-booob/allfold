'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process'),path=require('node:path');
const {validDOI,articleURL}=require('../src/browser/article-identity.cjs');
test('native DOI normalization matches shared Python identifiers including Unicode casefold',()=>{
  const inputs=[' DOI: 10.5555/TARGET ','https://dx.doi.org/10.5555/Name','10.5555/Straße','10.5555/Σς','10.5555/ﬃ','10.5555/ı','10.5555/Ꭰꭰ','ISSN 1234-5678','10.55/no','10.5555/white space'];
  const python=process.env.ALLFOLD_SOLVER_TEST_PYTHON || path.resolve(__dirname,'../../.venv/bin/python');
  const result=spawnSync(python,['-c','import json,sys; from allfold.identifiers import valid_doi; print(json.dumps([valid_doi(x) for x in json.loads(sys.argv[1])]))',JSON.stringify(inputs)],
    {env:{...process.env,PYTHONPATH:path.resolve(__dirname,'../../src')},encoding:'utf8'});
  assert.equal(result.status,0,result.stderr);assert.deepEqual(inputs.map(validDOI),JSON.parse(result.stdout));
});
test('article URL validation preserves relative-route evidence and refuses unsafe entries',()=>{
  assert.equal(articleURL('https://journal.example/#/article/one').href,'https://journal.example/#/article/one');
  for(const value of ['javascript:alert(1)','file:///private/data','https://user:secret@journal.example/article','relative-path'])
    assert.equal(articleURL(value),null);
});
