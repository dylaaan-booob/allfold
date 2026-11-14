'use strict';
const fs=require('node:fs'),path=require('node:path');
const same=(info,pair)=>Array.isArray(pair)&&pair.length===2&&info.dev===pair[0]&&info.ino===pair[1];
const failure=()=>Object.assign(Error('native-output'),{bodyLocal:true});
class NativeOutput {
  constructor(data) {
    this.root=data.workspace_root;this.proof=data.output;
    const p=this.proof;
    if(!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(data.paper_id)
      ||!Number.isSafeInteger(data.attempt)||data.attempt<1||!Number.isSafeInteger(data.deadline_ms)
      ||!path.isAbsolute(this.root)||path.normalize(this.root)!==this.root||!p||p.file!==null
      ||p.temporary!==`Documents/.downloads/${data.paper_id}.${data.attempt}.native/body.part`
      ||p.target!==`Documents/${data.paper_id}.pdf`)throw failure();
    this.filename=path.join(this.root,p.temporary);this.directory=path.dirname(this.filename);this.file=null;
    this.check();this.absent();
  }
  check() {
    try {
      let current=path.parse(this.root).root;
      for(const part of path.relative(current,this.root).split(path.sep).filter(Boolean)) {
        current=path.join(current,part);if(!fs.lstatSync(current).isDirectory())throw failure();
      }
      for(const [name,pair,privateDirectory] of [[this.root,this.proof.workspace],
        [path.join(this.root,'Documents'),this.proof.documents],[path.join(this.root,'Documents/.downloads'),this.proof.staging],
        [path.join(this.root,'Documents/.downloads/.cleanup'),this.proof.disposal,true],[this.directory,this.proof.native_directory,true]]) {
        const info=fs.lstatSync(name);
        if(!info.isDirectory()||!same(info,pair)||privateDirectory&&((info.mode&0o777)!==0o700||info.uid!==process.getuid()))throw failure();
      }
      if(fs.readdirSync(this.directory).some(name=>name!=='body.part'))throw failure();
    } catch(error){error.bodyLocal=true;throw error;}
  }
  absent() {
    this.check();
    try {fs.lstatSync(this.filename);}catch(error){if(error.code==='ENOENT')return;throw error;}
    throw failure();
  }
  capture({missing=false}={}) {
    this.check();
    let info;
    try {info=fs.lstatSync(this.filename);}catch(error){if(error.code==='ENOENT'&&missing)return null;throw failure();}
    if(!info.isFile()||info.nlink!==1||this.file&&!same(info,this.file))throw failure();
    // Chromium can briefly reserve a zero-length destination before moving its
    // already-open native file there. Observe a growing inode, or the actual
    // done object for an empty transfer; zero bytes remain a valid completion.
    if(missing&&!this.file&&info.size===0)return null;
    // Verify a no-follow descriptor against the observed entry. The private,
    // absent leaf is created by Chromium, rather than a path-sized placeholder.
    const fd=fs.openSync(this.filename,fs.constants.O_RDONLY|fs.constants.O_NONBLOCK|
      (process.platform==='darwin'?0x20000000:fs.constants.O_NOFOLLOW));
    try {
      const actual=fs.fstatSync(fd);
      if(!actual.isFile()||actual.nlink!==1||!same(actual,[info.dev,info.ino]))throw failure();
      this.check();if(!same(fs.lstatSync(this.filename),[actual.dev,actual.ino]))throw failure();
      this.file ??= [actual.dev,actual.ino];return {file:this.file,size:actual.size};
    }finally {fs.closeSync(fd);}
  }
}
module.exports={NativeOutput};
