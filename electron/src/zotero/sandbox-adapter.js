'use strict';
// Official source files stay unchanged; only HTTP's XHR transport is hosted in Main. No save API.
window.allfoldTranslatorReady=(async () => {
  const operationId=new URL(location.href).searchParams.get('operation');
  Zotero.isManifestV3 = false;
  Zotero.isBookmarklet = false;
  const collator=new Intl.Collator(['en-US'],{numeric:true,sensitivity:'base'});
  Zotero.localeCompare=(a,b)=>collator.compare(a,b);
  Zotero.debug = () => {};
  Zotero.logError = () => {};
  Zotero.getVersion = () => '5.0';
  Zotero.Prefs = {
    get: name => name === 'downloadAssociatedFiles' ? true : name === 'automaticSnapshots' ? false : undefined,
    getAsync: async () => undefined,
  };
  Zotero.Messaging = {sendMessage: async () => {throw Error('Page messaging unavailable');}};
  const [registry, formats] = await Promise.all([
    fetch('/registry.json').then(r=>r.json()), fetch('/dateFormats.json').then(r=>r.json()),
  ]);
  const byID = new Map();
  for (const info of registry) {
    const translator = new Zotero.Translator({...info});
    byID.set(translator.translatorID,translator);
    for (const [type, mask] of Object.entries(TRANSLATOR_TYPES))
      if (translator.translatorType & mask) Zotero.Translators._cache[type].push(translator);
  }
  for (const values of Object.values(Zotero.Translators._cache)) values.sort((a,b)=>a.priority-b.priority);
  Zotero.Translators._initialized = true;
  Zotero.Translators.get = async id => byID.get(id) || false;
  Zotero.Translators.getAllForType = async type => Zotero.Translators._cache[type] || [];
  Zotero.Translators.getCodeForTranslator = Zotero.Promise.method(async t => {
    const found = byID.get(t.translatorID); if (!found) throw Error('Unknown pinned Translator');
    if(found.code===undefined){
      const response=await fetch('/translators/'+encodeURIComponent(found.translatorID)+'.js');
      if(!response.ok)throw Error('Pinned Translator code unavailable');
      found.code=await response.text();
    }
    return found.code;
  });
  Zotero.Schema.init(); Zotero.Date.init(formats);
  class TransportError extends Error {
    constructor(error){super('HTTP transport failed ('+error.code+')');this.kind='transport';this.code=error.code;this.net_error=error.net_error;}
  }
  Zotero.HTTP._requestXHR = async (method,url,options) => {
    options.headers ||= {};if(options.successCodes===undefined)options.successCodes=null;
    if (['GET','HEAD'].includes(method)) {
      if (options.body != null) throw Error(`HTTP ${method} cannot have a request body`);
    } else if (options.body && !(options.body instanceof ArrayBuffer)) {
      if (options.headers['Content-Type'] !== 'multipart/form-data')
        options.body = typeof options.body === 'string' ? options.body : JSON.stringify(options.body);
      if (!options.headers['Content-Type']) options.headers['Content-Type'] = 'application/x-www-form-urlencoded';
      else if (options.headers['Content-Type'] === 'multipart/form-data') delete options.headers['Content-Type'];
    }
    const raw = await window.translatorHost.request({operationId,method,url,body:options.body,
      headers: options.headers, responseType: options.responseType,
      timeout:options.timeout, referrer:options.referrer});
    if(!raw.ok) {
      if(raw.error.code==='timeout')throw Object.assign(new Zotero.HTTP.TimeoutError(url,options.timeout),{kind:'transport',code:'timeout'});
      if(raw.error.code==='network_error' && options.successCodes===false)
        return {status:0,statusText:raw.error.net_error || '',response:raw.error.net_error || '',responseText:raw.error.net_error || '',
          responseType:options.responseType || '',responseURL:url,getResponseHeader:()=>null,getAllResponseHeaders:()=>''};
      if(raw.error.code==='network_error')throw Object.assign(new Zotero.HTTP.StatusError({status:0},url),
        {kind:'transport',code:raw.error.code,net_error:raw.error.net_error});
      throw new TransportError(raw.error);
    }
    const headers = new Map(raw.headers.map(([k,v])=>[k.toLowerCase(),v]));
    const charset=options.responseCharset || (options.responseType==='json'?'utf-8':
      (headers.get('content-type') || '').match(/charset\s*=\s*["']?([^;\s"']+)/i)?.[1] || 'utf-8');
    const text=options.responseType==='arraybuffer'?undefined:LiteratureDocumentCompat.decode(raw.bytes,charset);
    const xhr = {status:raw.status,statusText:raw.statusText || '',responseType:options.responseType || '',responseURL:raw.url,
      responseText:text,
      getResponseHeader: key=>headers.get(key.toLowerCase()) || null,
      getAllResponseHeaders: ()=>raw.headers.map(([k,v])=>k+': '+v).join('\r\n')};
    // StatusError carries Retry-After back to the unchanged official request() wrapper.
    if (options.successCodes === null && (raw.status < 200 || raw.status >= 300)
      || Array.isArray(options.successCodes) && !options.successCodes.includes(raw.status))
      throw new Zotero.HTTP.StatusError(xhr,url,['','text'].includes(xhr.responseType)?text:undefined);
    xhr.response = text;
    if (options.responseType === 'document') {
      const type = (headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
      const doc = new DOMParser().parseFromString(text,Zotero.HTTP.determineDOMParserContentType(type));
      xhr.response = Zotero.HTTP.wrapDocument(doc,raw.url);
    } else if (options.responseType === 'json') xhr.response = LiteratureDocumentCompat.json(text);
    else if (options.responseType === 'arraybuffer')
      xhr.response = raw.bytes.buffer.slice(raw.bytes.byteOffset,raw.bytes.byteOffset+raw.bytes.byteLength);
    return xhr;
  };
  Zotero.COHTTP.request = Zotero.HTTP.request;
  // Official TranslateHost's virtual saver returns JSON only; no Desktop/cloud save API exists here.
  Zotero.Translate.ItemSaver.prototype.saveItems=async function(items){
    this.items=(this.items || []).concat(items);return items;
  };
  let detection=null;
  function createDocument({html,url,rootURL=url,cookie=''},detect,observers) {
    const target=new URL(url);
    if(!['http:','https:'].includes(target.protocol) || target.username || target.password)throw Error('Invalid translation document');
    html=html.replace(/<(video|audio)(?:\s[^>]*)?(?:\/>|>.*?<\/\1>)/gis,'')
      .replace(/<noscript(?:\s[^>]*)?(?:\/>|>.*?<\/noscript>)/gis,'');
    const doc=LiteratureDocumentCompat.normalize(new DOMParser().parseFromString(html,'text/html'));
    let base=doc.querySelector('base[href]');
    const baseURL=base?new URL(base.getAttribute('href'),url).href:url;
    if(!base)base=doc.createElement('base');base.setAttribute('href',baseURL);doc.head.appendChild(base);
    class HostMutationObserver {
      observe(node,options) {
        if(!(node instanceof Node))throw TypeError('MutationObserver requires a Node');
        const selector=node.nodeType===Node.DOCUMENT_NODE?null:
          node.nodeType===Node.ELEMENT_NODE?Zotero.Utilities.Connector.getNodeSelector(node):undefined;
        if(selector===undefined)throw TypeError('Remote observer requires Document or Element');
        observers.push({selector,options:options || {childList:true,subtree:true}});
      }
      disconnect() {}
    }
    return Zotero.HTTP.wrapDocument(doc,url,{cookie:detect?'':cookie,defaultView:{MutationObserver:HostMutationObserver,top:{document:{location:{href:rootURL}}}}});
  }
  function errorSummary(error) {
    const message=String(error?.message ?? error);
    const missing=message.match(/\b(?:Zotero\.)?HTTP\.(processDocuments|addDefaultReferrer|getDefaultReferrer|isSameOrigin|isLessSecure)\s+is not (?:a function|defined)\b/);
    const names=['TypeError','ReferenceError','SyntaxError','RangeError'];
    const name=names.includes(error?.name)?error.name:
      message.match(/(?:^|\n)(?:Error:\s*)?(TypeError|ReferenceError|SyntaxError|RangeError):/)?.[1];
    if(missing)return {error_kind:'host_api_missing',api_name:'HTTP.'+missing[1],...(name?{error_name:name}:{})};
    return name?{error_kind:'script_exception',error_name:name}:{};
  }
  function failure(error,info={}) {
    const status=error instanceof Zotero.HTTP.StatusError?error.status:undefined;
    return {ok:false,...info,error:{kind:error?.kind==='transport'?'transport':status!==undefined?'http_status':'translation',
      ...(error?.kind==='transport'?{code:error.code,net_error:error.net_error}:{}),
      message:String(error?.message ?? error),...errorSummary(error),...(status!==undefined?{status}:{})},
      terminal:['timeout','canceled','document_changed'].includes(error?.code)};
  }
  function apiParent(item,proxy) {
    const clean=JSON.parse(JSON.stringify(item));
    for(const field of ['dateAdded','dateModified','id','itemID','path','version'])delete clean[field];
    if(clean.url && proxy?.toProper)clean.url=proxy.toProper(clean.url);
    return Zotero.Utilities.Item.itemToAPIJSON(clean)[0];
  }
  function matchingDOI(item,doi) {
    const value=String(item?.DOI || '').trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,'').toLowerCase();
    if(!/^10\.\d{4,9}\/\S+$/.test(value))return 'translator_doi_missing';
    return value===doi?null:'doi_mismatch';
  }
  window.allfoldTranslator = {
    count:registry.length,
    clear(){if(detection)detection.active=false;detection=null;},
    async detect({html,url,rootURL=url}) {
      this.clear();
      const state={html,url,rootURL,observers:[],active:true};detection=state;
      try {
        const document=createDocument(state,true,state.observers);
        state.candidates=(await Zotero.TranslateWeb.detect({document})).filter(t=>t.itemType
          && !['multiple','webpage','attachment','note'].includes(t.itemType)
          && t.runMode===Zotero.Translator.RUN_MODE_IN_BROWSER);
        return {ok:true,candidateCount:state.candidates.length,observers:state.observers,
          candidates:state.candidates.map(t=>({translatorID:t.translatorID,itemType:t.itemType,priority:t.priority,
            proxy:t.proxy?.toJSON?t.proxy.toJSON():t.proxy || null}))};
      }catch(error){return failure(error,{observers:state.observers});}
    },
    async translate({snapshot,candidate,cookie='',doi,forEnrichment=false}) {
      let state=detection;
      if(snapshot && candidate) {
        const selected=byID.get(candidate.translatorID);
        if(!selected)return failure(Error('Unknown pinned Translator'));
        selected.itemType=candidate.itemType;
        selected.proxy=candidate.proxy?new Zotero.Proxy(candidate.proxy):null;
        state={...snapshot,active:true,observers:[],candidates:[selected]};detection=state;
      }
      if(!state?.active)return failure(Error('Translation context ended'));
      let last={ok:false,error:{kind:'translation',code:'translator_no_items',message:'No eligible single-item Translator'}};
      for(const selected of state.candidates) {
        if(!state.active)return {...failure(Error('Translation canceled')),terminal:true};
        const info={translator:selected.label,translatorID:selected.translatorID};
        try {
          const document=createDocument({...state,cookie},false,state.observers);
          const {items,proxy}=await Zotero.TranslateWeb.translate({document,translators:[selected],
            onSelect:(_obj,_items,callback)=>callback(false)});
          if(!state.active)return {...failure(Error('Translation canceled')),terminal:true};
          const code=!items?.length?'translator_no_items':items.length!==1?'translator_multiple_items':matchingDOI(items[0],doi) || (typeof items[0].title!=='string' || !items[0].title.trim() || typeof items[0].itemType!=='string' || ['multiple','webpage','attachment','note'].includes(items[0].itemType)?'translator_invalid_item':null);
          if(code){last={ok:false,...info,itemCount:items?.length || 0,error:{kind:'translation',code,message:code}};continue;}
          if(forEnrichment)for(const item of items)for(const field of ['date','accepted']) {
            const parsed=Zotero.Date.strToDate(item[field] || '');item[field+'_parts']={};
            for(const key of ['year','month','day'])if(parsed[key]!=null && /^\d+$/.test(String(parsed[key])))
              item[field+'_parts'][key]=Number(parsed[key])+(key==='month'?1:0);
          }
          if(proxy?.toProper)for(const item of items)for(const attachment of item.attachments || [])if(attachment.url)attachment._allfoldProperURL=proxy.toProper(attachment.url);
          return {ok:true,...info,proxy:proxy?.toJSON?proxy.toJSON():proxy || null,
            items:JSON.parse(JSON.stringify(items)),apiItem:forEnrichment?undefined:apiParent(items[0],proxy),itemCount:1};
        }catch(error){last=failure(error,info);if(last.terminal)break;}
      }
      return {...last,observers:state.observers};
    },
    async searchDOI({doi,url,forEnrichment=false}) {
      const info={translator:'DOI Content Negotiation',translatorID:'b28d0d42-8549-4c6d-83fc-8382874a5cb9',
        proxy:url?Object.values(Zotero.Proxies.getPotentialProxies(url)).find(Boolean) || null:null};
      try {
        const translate=new Zotero.Translate.Search();
        translate.setSearch({itemType:'journalArticle',DOI:doi});
        await translate.setTranslator(info.translatorID);
        const items=await translate.translate({libraryID:false,saveAttachments:false});
        const code=!items?.length?'translator_no_items':items.length!==1?'translator_multiple_items':
          matchingDOI(items[0],doi) || (typeof items[0].title!=='string' || !items[0].title.trim() || typeof items[0].itemType!=='string' || ['multiple','webpage','attachment','note'].includes(items[0].itemType)?'translator_invalid_item':null);
        if(code)return {ok:false,...info,itemCount:items?.length || 0,error:{kind:'translation',code}};
        if(forEnrichment)for(const item of items)for(const field of ['date','accepted']) {
          const parsed=Zotero.Date.strToDate(item[field] || '');item[field+'_parts']={};
          for(const key of ['year','month','day'])if(parsed[key]!=null && /^\d+$/.test(String(parsed[key])))
            item[field+'_parts'][key]=Number(parsed[key])+(key==='month'?1:0);
        }
        return {ok:true,...info,items:JSON.parse(JSON.stringify(items)),apiItem:forEnrichment?undefined:apiParent(items[0],info.proxy?new Zotero.Proxy(info.proxy):null),itemCount:1};
      }catch(error){return failure(error,info);}
    },
  };
})().catch(() => {window.allfoldTranslatorError = 'Official translation runtime could not initialize';});
