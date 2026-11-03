'use strict';
// Descriptive runtime metadata only. None of these fields grant page or credential authority.
function operationAssociation(data={}) {
  const scope=data.service_scope;
  if(scope!=null && (!scope || typeof scope!=='object'
    || !['scope_id','config_revision','user_state_revision'].every(key=>typeof scope[key]==='string' && /^[a-f0-9]{64}$/.test(scope[key]))))
    throw Error('Invalid browser Service scope');
  const service=data.service_id ?? null;
  if(service!==null && (!scope || typeof service!=='string' || !/^svc_[a-f0-9]{32}$/.test(service)))
    throw Error('Invalid browser Service identity');
  const identifier=value=>{
    if(value==null)return null;
    if(typeof value!=='string' || !/^[a-zA-Z0-9_-]{1,128}$/.test(value))throw Error('Invalid browser task identity');
    return value;
  };
  return Object.freeze({request_id:identifier(data.request_id),task_id:identifier(data.task_id ?? data.request_id),
    workflow_id:identifier(data.workflow_id ?? data.task_id ?? data.request_id),parent_task_id:identifier(data.parent_task_id),
    service_scope:scope?Object.freeze(Object.fromEntries(['scope_id','config_revision','user_state_revision'].map(key=>[key,scope[key]]))):null,
    service_id:service,paper_id:identifier(data.paper_id)});
}
module.exports={operationAssociation};
