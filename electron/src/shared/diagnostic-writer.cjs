'use strict';
// Synchronous bounded local transport. Every write opens, verifies and closes its file.
const fs=require('node:fs'),path=require('node:path');
const {randomBytes}=require('node:crypto');
const names=['events.0.jsonl','events.1.jsonl','events.2.jsonl','events.3.jsonl'];
const managed=new Set([...names,'integrity.json']);
function identity(stat){return {dev:stat.dev,ino:stat.ino};}
function same(a,b){return a?.dev===b?.dev && a?.ino===b?.ino;}
class DiagnosticWriter {
  constructor({root,scopeId,maxBytes=1024*1024,maxFiles=4}={}) {
    this.scopeId=scopeId;this.maxBytes=Math.min(1024*1024,Math.max(512,maxBytes));this.maxFiles=Math.min(4,Math.max(1,maxFiles));
    this.integrity={rotations:0,write_failures:0,omitted:0,incomplete:false};this.tokens=new Map();this.directories=[];this.files=new Map();
    try {
      if(!path.isAbsolute(root) || !/^[a-f0-9]{64}$/.test(scopeId))throw Error('invalid_target');
      this.root=path.resolve(root);this.directory=path.join(this.root,'scopes',scopeId,'electron');
      // Capture every ancestor, including existing parents, so replacement cannot redirect a writer.
      const chain=[];let current=this.directory;
      while(true){chain.unshift(current);const parent=path.dirname(current);if(parent===current)break;current=parent;}
      for(const directory of chain) {
        let stat;
        try {stat=fs.lstatSync(directory);}catch(error){if(error.code!=='ENOENT')throw error;fs.mkdirSync(directory,{mode:0o700});stat=fs.lstatSync(directory);}
        if(!stat.isDirectory() || stat.isSymbolicLink())throw Error('unsafe_directory');
        if(directory===this.root || directory.startsWith(this.root+path.sep)) {
          if(typeof process.getuid==='function' && stat.uid!==process.getuid())throw Error('foreign_directory');
          fs.chmodSync(directory,0o700);
        }
        this.directories.push({path:directory,...identity(stat)});
      }
      this.captureFiles();
      if(this.files.has('integrity.json')) {
        const old=JSON.parse(this.read('integrity.json'));
        for(const key of ['rotations','write_failures','omitted'])if(Number.isSafeInteger(old[key]) && old[key]>=0)this.integrity[key]=Math.min(old[key],2147483647);
        this.integrity.incomplete=old.incomplete===true || this.integrity.rotations>0 || this.integrity.write_failures>0;
      } else if(this.files.size) {
        // Retained events without their integrity record can follow interrupted or partial reset.
        this.integrity.incomplete=true;this.integrity.write_failures=1;
      }
      this.available=true;this.persistIntegrity();
    }catch(_){this.failure();}
  }
  checkDirectories() {
    for(const expected of this.directories) {
      const stat=fs.lstatSync(expected.path);
      if(!stat.isDirectory() || stat.isSymbolicLink() || !same(stat,expected))throw Error('directory_replaced');
    }
  }
  fileStat(name) {
    const stat=fs.lstatSync(path.join(this.directory,name));
    if(!stat.isFile() || stat.isSymbolicLink() || stat.nlink!==1
      || (typeof process.getuid==='function' && stat.uid!==process.getuid()))throw Error('unsafe_file');
    return stat;
  }
  captureFiles() {
    this.checkDirectories();this.files.clear();
    for(const name of fs.readdirSync(this.directory)) {
      if(!managed.has(name))throw Error('unexpected_file');
      const stat=this.fileStat(name);
      if(stat.size>(name==='integrity.json'?4096:this.maxBytes))throw Error('oversized_file');
      fs.chmodSync(path.join(this.directory,name),0o600);this.files.set(name,identity(stat));
    }
  }
  checkFiles() {
    this.checkDirectories();
    const current=fs.readdirSync(this.directory);
    if(current.length!==this.files.size || current.some(name=>!this.files.has(name)))throw Error('files_replaced');
    for(const [name,expected] of this.files)if(!same(this.fileStat(name),expected))throw Error('file_replaced');
  }
  open(name,append=false) {
    this.checkFiles();
    const expected=this.files.get(name),target=path.join(this.directory,name);
    const flags=(append?fs.constants.O_APPEND:0)|fs.constants.O_WRONLY|fs.constants.O_NOFOLLOW
      |(expected?0:fs.constants.O_CREAT|fs.constants.O_EXCL);
    const fd=fs.openSync(target,flags,0o600);
    try {
      const stat=fs.fstatSync(fd);
      if(!stat.isFile() || stat.nlink!==1 || (expected && !same(stat,expected)))throw Error('file_replaced');
      this.checkDirectories();if(!same(this.fileStat(name),stat))throw Error('file_replaced');
      if(!expected)this.files.set(name,identity(stat));
      return fd;
    }catch(error){fs.closeSync(fd);throw error;}
  }
  writeFile(name,bytes,append=false) {
    const fd=this.open(name,append);
    try {if(!append)fs.ftruncateSync(fd,0);fs.writeFileSync(fd,bytes);}finally{fs.closeSync(fd);}
  }
  read(name) {
    this.checkFiles();const expected=this.files.get(name);if(!expected)return '';
    const fd=fs.openSync(path.join(this.directory,name),fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
    try {if(!same(fs.fstatSync(fd),expected))throw Error('file_replaced');this.checkDirectories();return fs.readFileSync(fd,'utf8');}
    finally{fs.closeSync(fd);}
  }
  persistIntegrity(){this.writeFile('integrity.json',JSON.stringify(this.integrity)+'\n');}
  failure(){this.available=false;this.integrity.write_failures++;this.integrity.incomplete=true;}
  status(){return {available:!!this.available,...this.integrity,max_files:this.maxFiles,max_file_bytes:this.maxBytes};}
  omit(){this.integrity.omitted=Math.min(2147483647,this.integrity.omitted+1);this.integrity.incomplete=true;
    try {if(this.available)this.persistIntegrity();}catch(_){this.failure();}}
  append(record) {
    if(!this.available)return false;
    try {
      const line=JSON.stringify(record)+'\n',bytes=Buffer.byteLength(line);
      if(bytes>this.maxBytes){this.omit();return false;}
      this.checkFiles();
      const stat=this.files.has(names[0])?this.fileStat(names[0]):null;
      if(stat && stat.size+bytes>this.maxBytes) {
        for(let i=this.maxFiles-1;i>=0;i--) {
          const name=names[i];if(!this.files.has(name))continue;
          this.checkFiles();
          if(i===this.maxFiles-1)fs.unlinkSync(path.join(this.directory,name));
          else {fs.renameSync(path.join(this.directory,name),path.join(this.directory,names[i+1]));
            this.files.set(names[i+1],this.files.get(name));}
          this.files.delete(name);this.checkFiles();
        }
        this.integrity.rotations++;this.integrity.incomplete=true;this.persistIntegrity();
      }
      this.writeFile(names[0],line,true);return true;
    }catch(_){this.failure();return false;}
  }
  readEvents() {
    const events=[];
    try {for(const name of names.slice(0,this.maxFiles).reverse())if(this.files.has(name))
      for(const line of this.read(name).split('\n'))if(line)try {events.push(JSON.parse(line));}catch(_){this.integrity.incomplete=true;}}
    catch(_){this.failure();}
    return events;
  }
  preview() {
    try {
      this.checkFiles();const token=randomBytes(24).toString('hex');
      const files=[...this.files].map(([name,id])=>({name,...id,size:this.fileStat(name).size,mtimeMs:this.fileStat(name).mtimeMs}));
      this.tokens.clear();this.tokens.set(token,{files});
      return {available:true,scope_id:this.scopeId,token,status:this.status()};
    }catch(_){this.failure();return {available:false,scope_id:this.scopeId,status:this.status()};}
  }
  reset(expected) {
    const preview=this.tokens.get(expected?.token);this.tokens.delete(expected?.token);
    const result={scope_id:this.scopeId,success:false,partial:false,deleted:0,failed:0};
    try {
      if(!preview || expected.scope_id!==this.scopeId)throw Error('invalid_preview');
      this.checkFiles();
      if(preview.files.length!==this.files.size)throw Error('files_changed');
      for(const file of preview.files) {
        const stat=this.fileStat(file.name);
        if(!same(stat,file) || stat.size!==file.size || stat.mtimeMs!==file.mtimeMs)throw Error('file_changed');
      }
      for(const file of preview.files) {
        try {this.checkFiles();if(!same(this.fileStat(file.name),file))throw Error('file_changed');
          fs.unlinkSync(path.join(this.directory,file.name));this.files.delete(file.name);result.deleted++;}
        catch(_){result.failed++;}
      }
      if(result.failed){result.partial=result.deleted>0;this.failure();}
      else {this.integrity={rotations:0,write_failures:0,omitted:0,incomplete:false};this.available=true;this.persistIntegrity();result.success=true;}
    }catch(_){result.failed++;if(result.deleted>0){result.partial=true;this.failure();}}
    return {...result,status:this.status()};
  }
}
module.exports={DiagnosticWriter};
