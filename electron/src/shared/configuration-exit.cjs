'use strict';
function options(action,unknown=false) {
  return {type:'warning',title:'Allfold',
    message:unknown?'无法核对配置保存状态。': '仍有配置修改未落盘或正在提交。',
    detail:'普通配置草稿可在恢复后核对。未提交的凭据和 Workspace 路径修改不会进入恢复存储，继续后会丢失；尚在进行的原生写入会等待结算。',
    buttons:['继续编辑',action==='reload'?'仍然重新加载':'仍然退出'],defaultId:0,cancelId:0,noLink:true};
}
async function confirmConfigurationExit(hostWindow,dialog) {
  let pending,unknown=false;
  try {pending=await hostWindow.webContents.executeJavaScript('Boolean(window.allfoldAutosave?.dirty || window.allfoldAutosave?.busy)');}
  catch {pending=true;unknown=true;}
  if(!pending)return true;
  return (await dialog.showMessageBox(hostWindow,options('quit',unknown))).response===1;
}
function confirmBlockedUnload(hostWindow,dialog) {
  return dialog.showMessageBoxSync(hostWindow,options('reload'))===1;
}
module.exports={confirmConfigurationExit,confirmBlockedUnload};
