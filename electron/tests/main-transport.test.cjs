'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {EventEmitter}=require('node:events');
const source=fs.readFileSync(path.join(__dirname,'../src/main.cjs'),'utf8');
test('authenticated bridge ready installs saved detail level before manual browser activity',async()=>{
  const levels=[],messages=[];
  class Socket extends EventEmitter {
    constructor(){super();Socket.current=this;}
    addEventListener(...args){this.on(...args);}
    close(){throw Error('unexpected close');}
  }
  const context=vm.createContext({WebSocket:Socket,base:'http://127.0.0.1:18767',token:'fixture',bridgeReady:false,
    setLogLevel:value=>levels.push(value),send:value=>messages.push(value)});
  vm.runInContext(source.slice(source.indexOf('async function connect('),source.indexOf('async function main(')),context);
  const connecting=context.connect();Socket.current.emit('open');
  assert.equal(messages[0].type,'hello');assert.equal(messages[0].token,'fixture');
  Socket.current.emit('message',{data:JSON.stringify({type:'ready',log_level:'warn'})});await connecting;
  assert.deepEqual(levels,['warn']);assert.equal(context.bridgeReady,true);
});
test('unexpected Python startup exit persists its safe event before HTTP readiness',async()=>{
  const child=new EventEmitter();child.stdout=new EventEmitter();child.stderr=new EventEmitter();child.exitCode=null;
  const logs=[],context=vm.createContext({path,ROOT:'/isolated',fs:{existsSync:()=>true},spawn:()=>child,
    process:{env:{},stderr:{write(){}}},setTimeout,clearTimeout,
    token:'fixture',exiting:false,base:undefined,activeOperation:null,readyToExit:false,
    dialog:{showErrorBox(){throw Error('existing startup error UI must remain deferred');}},
    app:{quit(){throw Error('existing startup quit remains deferred');}},log:(level,event,details)=>logs.push({level,event,...details})});
  vm.runInContext(source.slice(source.indexOf('async function startPython('),source.indexOf('async function connect(')),context);
  const starting=context.startPython('/isolated/config.yaml','');child.emit('exit',1,null);
  await assert.rejects(starting,/Python exited during startup/);
  assert.deepEqual(logs,[{level:'error',event:'python_exited',exit_code:1}]);assert.equal(context.readyToExit,true);
});
