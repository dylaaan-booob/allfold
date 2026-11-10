'use strict';
const {log,recoveryEvidence}=require('./logging.cjs');
const actions=require('../../../src/allfold/diagnostic_schema.json').fields.recovery_action.enum;
const outcomes={
  recovery_scheduled:'stopped',
  recovery_succeeded:'recovered',
  recovery_exhausted:'exhausted',
  service_cooldown_started:'stopped',
  service_cooldown_ended:'recovered',
};

function invocationRecovery() {
  const summaries=new Map();
  return {
    record(event,details) {
      const action=details.recovery_action,outcome=outcomes[event];
      if(!actions.includes(action) || !Object.hasOwn(outcomes,event))return;
      const evidence=recoveryEvidence(details);
      const previous=summaries.get(action);
      const count=Math.min(1000000,(previous?.count || 0)+Number(outcome==='stopped'));
      summaries.set(action,{recovery_action:action,count,outcome,first:previous?.first || evidence,last:evidence});
      log(outcome==='exhausted'?'warn':'info',event,details);
    },
    summary:()=>[...summaries.values()],
  };
}

module.exports={invocationRecovery};
