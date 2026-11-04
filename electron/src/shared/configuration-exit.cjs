'use strict';
function options(action,unknown=false) {
  return {type:'warning',title:'Allfold',
    message:unknown?'无法核对配置保存状态。': '仍有配置修改未落盘或正在提交。',
    detail:'已保留到本地的普通草稿可在恢复后核对。未成功保留的修改、未提交的凭据和 Workspace 路径修改继续后会丢失；退出会等待已开始的原生写入结算。',
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
