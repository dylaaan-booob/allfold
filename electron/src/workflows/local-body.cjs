'use strict';
// Authenticated host capability only. No renderer IPC, Session, PDF read or watch.
const fs=require('node:fs');
const path=require('node:path');
const {checkCanceled}=require('../browser/browser-task.cjs');
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const pair=value=>Array.isArray(value)&&value.length===2&&value.every(n=>Number.isSafeInteger(n)&&n>=0);
const same=(info,expected)=>pair(expected)&&info.dev===expected[0]&&info.ino===expected[1];
function regular(info,expected){if(!info.isFile()||!same(info,expected))throw Error('body-changed');}

function capture(data,handles){
  const proof=data?.body,root=data?.workspace_root,parts=proof?.relative_path?.split('/');
  if(!['open','locate'].includes(data?.action)||!UUID.test(data?.workspace_id)||!UUID.test(data?.paper_id)||
    !Number.isSafeInteger(data?.body_generation)||data.body_generation<1||typeof root!=='string'||!path.isAbsolute(root)||
    root.split(path.sep).includes('..')||!parts||parts.length<2||parts[0]!=='Documents'||
    parts.some(part=>!part||['.','..'].includes(part)||/[\\:\u0000-\u001f]/.test(part))||
    !pair(proof.workspace)||!pair(proof.file)||!Array.isArray(proof.directories)||proof.directories.length!==parts.length-1||
    !proof.directories.every(pair))throw Error('invalid-body-capability');
  const directories=[];
  const directory=(name,expected)=>{
    const fd=fs.openSync(name,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);handles.push(fd);
    const info=fs.fstatSync(fd);
    if(!info.isDirectory()||expected&&!same(info,expected))throw Error('directory-changed');
    directories.push([name,[info.dev,info.ino]]);
  };
  let current=path.parse(root).root;directory(current);
  const components=root.slice(current.length).split(path.sep).filter(Boolean);
  for(const component of components){current=path.join(current,component);directory(current);}
  if(!same(fs.fstatSync(handles.at(-1)),proof.workspace))throw Error('workspace-changed');
  for(let index=0;index<parts.length-1;index++){current=path.join(current,parts[index]);directory(current,proof.directories[index]);}
  const filename=path.join(current,parts.at(-1));
  const verify=()=>{
    for(const [name,expected] of directories){const info=fs.lstatSync(name);if(!info.isDirectory()||!same(info,expected))throw Error('directory-changed');}
    let info;try{info=fs.lstatSync(filename);}catch(error){if(error.code==='ENOENT')return false;throw error;}
    regular(info,proof.file);return true;
  };
  if(!verify())return {filename,verify,present:false};
  const fd=fs.openSync(filename,fs.constants.O_RDONLY|fs.constants.O_NONBLOCK|fs.constants.O_NOFOLLOW);handles.push(fd);
  regular(fs.fstatSync(fd),proof.file);
  return {filename,verify,present:verify()};
}

async function executeLocalBody(data,{signal,shell,verifyAuthority}={}){
  const handles=[];let outcome='local_failure',closed=true;
  try{
    checkCanceled(signal);
    const body=capture(data,handles);
    if(!body.present)outcome='missing';
    else{
      if(typeof verifyAuthority!=='function')throw Error('authority-unavailable');
      await verifyAuthority({signal});
      checkCanceled(signal);
      if(!body.verify())outcome='missing';
      else if(data.action==='open'){
        const error=await shell.openPath(body.filename);
        // shell.openPath resolves to an error string instead of rejecting.
        if(error==='')outcome='opened';
      }else{
        shell.showItemInFolder(body.filename);
        // The API returns void; only issuance can be reported.
        outcome='locate_requested';
      }
    }
  }catch(_){outcome='local_failure';}
  finally{for(const fd of handles.reverse())try{fs.closeSync(fd);}catch(_){closed=false;}}
  return {outcome,resource_closed:closed};
}
module.exports={executeLocalBody};
