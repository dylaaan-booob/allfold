'use strict';

const canceled=()=>Object.assign(Error('Import canceled'),{code:'canceled'});

class OperationLimit {
  #running=0;
  #waiting=[];

  constructor(limit) {
    if(!Number.isInteger(limit) || limit<1)throw RangeError('Invalid Import concurrency limit');
    this.limit=limit;
  }

  async run(signal,operation) {
    if(signal?.aborted)throw canceled();
    if(this.#running<this.limit)this.#running++;
    else await new Promise((resolve,reject)=>{
      const abort=()=>{
        const index=this.#waiting.indexOf(grant);
        if(index!==-1)this.#waiting.splice(index,1);
        reject(canceled());
      };
      const grant=()=>{
        signal?.removeEventListener('abort',abort);
        resolve();
      };
      this.#waiting.push(grant);
      signal?.addEventListener('abort',abort,{once:true});
    });
    try {
      if(signal?.aborted)throw canceled();
      return await operation();
    } finally {
      const grant=this.#waiting.shift();
      if(grant)grant();
      else this.#running--;
    }
  }
}

class ImportResources {
  #pdf;
  #writer;
  #uncertain=false;

  constructor({pdfLimit,writerLimit}) {
    this.#pdf=new OperationLimit(pdfLimit);
    this.#writer=new OperationLimit(writerLimit);
  }

  download(signal,operation) {
    return this.#pdf.run(signal,operation);
  }

  async write(signal,current,operation) {
    let dispatched=false;
    const check=()=>{
      if(this.#uncertain)throw Object.assign(Error('Another Zotero write is uncertain'),{code:'write_stopped'});
      current();
    };
    try {
      return await this.#writer.run(signal,async()=>{
        try {
          check();
          return await operation(()=>{
            // Local API invokes this synchronously after credential and target checks.
            check();
            dispatched=true;
          });
        } catch(error) {
          // Latch before releasing the permit. Already-dispatched HTTP calls still settle.
          if(dispatched)this.#uncertain=true;
          throw error;
        }
      });
    } catch(error) {
      if(!dispatched)error.no_effect=true;
      throw error;
    }
  }
}

module.exports={ImportResources};
