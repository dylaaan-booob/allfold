'use strict';
const {createServer}=require('node:net');
const {randomInt}=require('node:crypto');

let attempts=0;
function probe() {
  attempts++;
  const port=randomInt(49152,65535);
  const server=createServer();
  server.once('error',error=>{
    if(error.code==='EADDRINUSE' && attempts<3)probe();
    else process.exitCode=1;
  });
  server.listen({host:'127.0.0.1',port,exclusive:true},()=>{
    // Electron must bind this port next; another process can still win that race.
    server.close(error=>{
      if(error)process.exitCode=1;
      else process.stdout.write(String(port));
    });
  });
}
probe();
