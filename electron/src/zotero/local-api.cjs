'use strict';
const http=require('node:http');
const {createHash,randomBytes}=require('node:crypto');
const ORIGIN='http://127.0.0.1:23119';
const KEY=/^[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}$/;
const failure=(code,status)=>Object.assign(Error(code),{code,...(status?{status}:{})});
function validateTarget(value) {
  if(!value || typeof value.server_id!=='string' || !/^[A-Za-z0-9]{1,128}$/.test(value.server_id)
    || !['user','group'].includes(value.library_type) || !/^\d{1,20}$/.test(value.library_id)
    || value.library_type==='user' && value.library_id!=='0'
    || value.collection_key!=null && !KEY.test(value.collection_key))throw failure('invalid_target');
  return Object.freeze({server_id:value.server_id,library_type:value.library_type,library_id:value.library_id,collection_key:value.collection_key || null});
}
const prefix=target=>'/api/'+(target.library_type==='user'?'users':'groups')+'/'+target.library_id;
function requestLocal(url,options) {
  return new Promise((resolve,reject)=>{
    const request=http.request(url,{method:options.method,headers:options.headers},incoming=>{
      const chunks=[];let size=0;
      incoming.on('data',chunk=>{size+=chunk.length;if(size>4*1024*1024)request.destroy(failure('response_too_large'));else chunks.push(chunk);});
      incoming.on('error',()=>{clearTimeout(timer);reject(failure('connection_lost'));});
      incoming.on('end',()=>{clearTimeout(timer);resolve(new Response([204,205,304].includes(incoming.statusCode)?null:Buffer.concat(chunks),{status:incoming.statusCode,headers:incoming.headers}));});
    });
    request.on('error',error=>{clearTimeout(timer);reject(failure(error.code==='timeout'?'timeout':'connection_lost'));});
    const timer=setTimeout(()=>request.destroy(failure('timeout')),options.timeout || 30000);
    request.end(options.body);
  });
}
class LocalAPI {
  constructor({transport=requestLocal,store}={}) {this.transport=transport;this.store=store || require('./local-auth.cjs').keyStore;}
  async request(path,{method='GET',server_id,key,body,headers={},timeout}={}) {
    if(!path.startsWith('/api/') || path.includes('://') || path.includes('..'))throw failure('invalid_local_path');
    let response;
    try {response=await this.transport(ORIGIN+path,{method,redirect:'error',timeout,headers:{Accept:'application/json','Zotero-API-Version':'3','Zotero-Allowed-Request':'1',
      ...(server_id?{'Zotero-Server-ID':server_id}:{}),...(key?{'Zotero-API-Key':key}:{}),...headers},body});}
    catch(error){throw failure(error.code==='timeout'?'timeout':'connection_lost');}
    const actual=response.headers.get('Zotero-Server-ID');
    if(server_id && actual!==server_id || response.status===412)throw failure('server_id_mismatch',response.status);
    let denied=false;if(response.status===403 && path==='/api/local/authorize'){try{denied=(await response.clone().json())?.denied===true;}catch{}}
    const codes={401:'authorization_required',403:'access_denied',404:'target_missing',409:'conflict',412:'server_id_mismatch',428:'precondition_required',429:'rate_limited'};
    if(!response.ok)throw failure(denied?'authorization_denied':codes[response.status] || 'api_failure',response.status);
    return response;
  }
  async instance() {
    const response=await this.request('/api/');
    const version=response.headers.get('X-Zotero-Version') || '';
    const match=version.match(/^(\d+)\.(\d+)\.(\d+)(?:$|[^\d])/);
    if(!match || Number(match[1])<10 || Number(match[1])===10 && Number(match[2])===0 && Number(match[3])<6)throw failure('unsupported_version');
    const server_id=response.headers.get('Zotero-Server-ID');if(!server_id)throw failure('missing_server_id');
    return {server_id,version};
  }
  async authorize() {
    const instance=await this.instance();
    const response=await this.request('/api/local/authorize',{method:'POST',server_id:instance.server_id,body:JSON.stringify({appName:'Allfold'}),headers:{'Content-Type':'application/json'},timeout:120000});
    const value=await response.json();
    if(!value?.remember)throw failure('always_allow_required');
    if(typeof value.key!=='string' || !/^[A-Za-z0-9]{32}$/.test(value.key))throw failure('invalid_response');
    await this.store.write({server_id:instance.server_id,key:value.key});
    return {ok:true,server_id:instance.server_id,authorized:true};
  }
  async credentials(target) {
    const stored=await this.store.read();
    if(!stored || stored.server_id!==target.server_id)throw failure('authorization_required');
    return stored.key;
  }
  async targets() {
    const instance=await this.instance(),server_id=instance.server_id;
    const groupsResponse=await this.request('/api/users/0/groups?limit=1000',{server_id});
    const groups=await groupsResponse.json();
    if(!Array.isArray(groups) || Number(groupsResponse.headers.get('Total-Results') || groups.length)>groups.length)throw failure('invalid_response');
    const libraries=[{type:'user',id:'0',name:'My Library',editable:true,files_editable:true},...groups.map(group=>({type:'group',id:String(group.id),name:String(group.data?.name || 'Group'),editable:null,files_editable:null}))];
    for(const library of libraries) {
      if(!/^\d{1,20}$/.test(library.id))throw failure('invalid_response');
      const response=await this.request(prefix({library_type:library.type,library_id:library.id})+'/collections?limit=1000',{server_id});
      const rows=await response.json();
      if(!Array.isArray(rows) || Number(response.headers.get('Total-Results') || rows.length)>rows.length)throw failure('target_list_incomplete');
      const byKey=new Map(rows.map(row=>[row.key || row.data?.key,row.data]));
      library.collections=rows.map(row=>{
        const key=row.key || row.data?.key,data=row.data;
        if(!KEY.test(key) || !data || typeof data.name!=='string')throw failure('invalid_response');
        let parts=[data.name],parent=data.parentCollection,seen=new Set([key]);
        while(parent) {if(seen.has(parent)||!byKey.has(parent))throw failure('invalid_response');seen.add(parent);const value=byKey.get(parent);parts.unshift(value.name);parent=value.parentCollection;}
        return {key,name:data.name,parent_key:data.parentCollection || null,path:parts.join(' / ')};
      });
    }
    const stored=await this.store.read();
    return {ok:true,...instance,authorized:stored?.server_id===server_id,libraries};
  }
  async validate(value) {
    const target=validateTarget(value),instance=await this.instance();
    if(instance.server_id!==target.server_id)throw failure('server_id_mismatch');
    await this.credentials(target);
    const path=prefix(target)+(target.collection_key?'/collections/'+target.collection_key:'/items?limit=1');
    await this.request(path,{server_id:target.server_id});return target;
  }
  async read(target,path) {target=validateTarget(target);if(!/^\/items\/[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}(?:\/children)?$/.test(path))throw failure('invalid_local_path');return (await this.request(prefix(target)+path,{server_id:target.server_id})).json();}
  async create(value,item) {
    const target=validateTarget(value),key=await this.credentials(target);
    const response=await this.request(prefix(target)+'/items',{method:'POST',server_id:target.server_id,key,
      headers:{'Content-Type':'application/json'},body:JSON.stringify([item])});
    let data;try{data=await response.json();}catch{throw failure('unattributable_response');}
    if(data?.failed?.['0'])throw Object.assign(failure('object_rejected',Number(data.failed['0'].code)),{no_effect:data.failed['0'].key===item.key && !Object.keys(data.successful || {}).length});
    if(response.status!==200 || data?.successful?.['0']?.key!==item.key || Object.keys(data.failed || {}).length
      || Object.keys(data.successful || {}).length!==1)throw failure('unattributable_response');
    return {key:item.key,version:data.successful['0'].version,status:response.status};
  }
  async upload(value,attachmentKey,bytes,{filename,contentType,mtime=Date.now()}={}) {
    const target=validateTarget(value),key=await this.credentials(target);
    if(!KEY.test(attachmentKey) || !Buffer.isBuffer(bytes) || !bytes.length)throw failure('invalid_attachment');
    if(typeof filename!=='string' || !/^[^\/\\\r\n"\x00]{1,200}$/.test(filename) || typeof contentType!=='string' || !/^[a-zA-Z0-9!#$&^_.+-]+\/[a-zA-Z0-9!#$&^_.+-]+$/.test(contentType))throw failure('invalid_attachment');
    const filePath=prefix(target)+'/items/'+attachmentKey+'/file';
    const headers={'Content-Type':'application/x-www-form-urlencoded','If-None-Match':'*'};
    const md5=createHash('md5').update(bytes).digest('hex');
    const response=await this.request(filePath,{method:'POST',server_id:target.server_id,key,headers,
      body:new URLSearchParams({md5,filename,filesize:String(bytes.length),mtime:String(Math.trunc(mtime)),contentType,params:'1'}).toString()});
    const authorization=await response.json();
    if(authorization?.exists===1)return {registered:true,md5};
    const uploadKey=authorization?.uploadKey;
    if(typeof uploadKey!=='string' || !/^[a-zA-Z0-9]{32}$/.test(uploadKey) || authorization.url!==ORIGIN+'/api/local/uploads/'+uploadKey
      || authorization.params?.key!==md5 || Object.keys(authorization.params).length!==1)throw failure('invalid_upload_destination');
    const boundary='allfold'+randomBytes(16).toString('hex');
    const body=Buffer.concat([Buffer.from('--'+boundary+'\r\nContent-Disposition: form-data; name="key"\r\n\r\n'+md5+'\r\n--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+filename+'"\r\nContent-Type: '+contentType+'\r\n\r\n'),bytes,Buffer.from('\r\n--'+boundary+'--\r\n')]);
    // Upload key is a bearer capability. Never send the Local API key to its URL.
    const uploaded=await this.request('/api/local/uploads/'+uploadKey,{method:'POST',server_id:target.server_id,timeout:60000,headers:{'Content-Type':'multipart/form-data; boundary='+boundary},body});
    if(uploaded.status!==201)throw failure('upload_failed',uploaded.status);
    const registered=await this.request(filePath,{method:'POST',server_id:target.server_id,key,headers,body:new URLSearchParams({upload:uploadKey}).toString()});
    if(registered.status!==204)throw failure('registration_failed',registered.status);
    return {registered:true,md5};
  }
}
function objectKey() {const alphabet='23456789ABCDEFGHIJKLMNPQRSTUVWXYZ';return Array.from(randomBytes(8),value=>alphabet[value%alphabet.length]).join('');}
module.exports={LocalAPI,validateTarget,objectKey,KEY,ORIGIN};
