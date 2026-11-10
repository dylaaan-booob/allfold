'use strict';

// Serialize only fixture state; evaluating this observer never starts an operation.
function rendererDiagnostics(expectedPaperId=null) {
  const element=id=>document.getElementById(id);
  const candidates=window.inboxKept?.candidates?.().map(entry=>entry.paper.id) || [];
  const dialog=id=>{
    const node=element(id);
    return node?{open:node.open,hidden:node.hidden,visibility:getComputedStyle(node).visibility}:null;
  };
  return {
    workspace:window.workspaceNavigation?.current(),
    layout:element('selected-view')?.dataset.workspaceLayout,
    documentFocused:document.hasFocus(),activeElement:document.activeElement?.id,
    workspaceReady:window.uiWorkspace?.ready(),
    workspaceBusy:window.inboxKept?.busy(),workspaceAvailable:window.inboxKept?.available(),
    navigationBusy:window.workspaceArray?.navigationBusy(),workflowBusy:window.workspaceArray?.workflowBusy(),
    runActive:window.uiRun?.active(),runDialog:dialog('run-view'),importConfirmation:dialog('kept-confirm'),
    runCancelDisabled:element('run-wos-cancel')?.disabled,keptCancelDisabled:element('kept-leave')?.disabled,
    candidateIds:candidates,expectedPaperId,
    targetPaperLoaded:expectedPaperId===null?null:candidates.includes(expectedPaperId),
    readerPaperId:element('paper-detail')?.dataset.paperId,
    browserVisible:window.allfoldWorkbench?.visible(),
    nativeBody:element('browser-body')?.getBoundingClientRect().toJSON(),
    notice:element('app-notice-summary')?.textContent,
  };
}

async function fixtureDiagnostics(win,browser,{expectedPaperId=null,workspaceReads,requests}) {
  let renderer;
  try {
    renderer=await win.webContents.executeJavaScript(`(${rendererDiagnostics.toString()})(${JSON.stringify(expectedPaperId)})`);
  }catch(error){renderer={unavailable:error.message};}
  const presentation=browser?.presentation;
  return {
    renderer,workspaceReads,recentRequests:requests.slice(-12).map(request=>request.route),
    native:{visible:presentation?.visible,suspended:presentation?.suspended,
      sequence:presentation?.sequence,bounds:presentation?.bounds,
      selected:presentation?.selected?.id,mounted:presentation?.mounted?.id},
  };
}

module.exports={fixtureDiagnostics};
