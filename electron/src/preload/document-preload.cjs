'use strict';
// Host-initiated fixed observations only. No contextBridge API is exposed to sites.
const {ipcRenderer,webFrame}=require('electron');
const documentId=Array.from(crypto.getRandomValues(new Uint32Array(4))).join('-');
// Node references live only in the isolated observation world. They detect a
// replaced body/primary object without exporting content or observing forever.
function documentSubject() {
  const state=globalThis.__allfoldSubject ||= {nodes:new WeakMap(),next:0};
  const id=node=>{if(!node)return 0;if(!state.nodes.has(node))state.nodes.set(node,++state.next);return state.nodes.get(node);};
  const legal=node=>{for(let el=node;el;el=el.parentElement)if(['script','style','noscript','template','nav'].includes(el.localName) || el.hidden
    || el.getAttribute('aria-hidden')?.toLowerCase()==='true' || /(?:^|;)\s*display\s*:\s*none\s*(?:!important\s*)?(?:;|$)/i.test(el.getAttribute('style') || '')
    || ['navigation','contentinfo'].includes(el.getAttribute('role')?.toLowerCase()) || el.localName==='footer' && !el.closest('article'))return false;return true;};
  const articles=[...document.querySelectorAll('article')].filter(node=>legal(node) && !node.parentElement?.closest('article'));
  const h1=[...document.querySelectorAll('h1')].find(legal);
  return [id(document.body),id(h1),id(articles.length===1?articles[0]:null)].join(':');
}
const operations={
  binding() {return {type:document.contentType};},
  access() {
    const title=document.title;
    const markers={unusualTraffic:/Unusual Traffic Detected\s*\(Error 418\)/i.test(title),
      cloudflareTitle:/^(Just a moment|Attention Required)/i.test(title),
      cloudflareOptions:false,cloudflareOrchestrator:false,robot:false,contentDenied:false,hcaptcha:false,hcaptchaVisible:false,login:false};
    // Compute predicates locally; no script/text/URL or proportional collection crosses IPC.
    for(const script of document.querySelectorAll('script')) {
      const src=script.getAttribute('src') || '';
      if(/\/cdn-cgi\/challenge-platform\/[^\s"'<>]*orchestrate\/chl_page\//i.test(src))markers.cloudflareOrchestrator=true;
      if(/\b_cf_chl_opt\s*=\s*\{/.test(script.textContent || ''))markers.cloudflareOptions=true;
    }
    let robot=false,human=false,cpe=false,denied=false;
    const walker=document.createTreeWalker(document.body || document,NodeFilter.SHOW_TEXT,{
      acceptNode:node=>node.parentElement?.closest('script,style,template,noscript')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT,
    });
    while(walker.nextNode()) {
      const text=walker.currentNode.nodeValue || '';
      robot ||= /Are you a robot\?/.test(text);
      human ||= /Please confirm you are a human by completing the captcha challenge/i.test(text);
      cpe ||= /\bCPE00001\b/.test(text);
      denied ||= /There was a problem providing the content you requested/i.test(text);
    }
    markers.robot=robot && human;markers.contentDenied=cpe && denied;
    // Resource presence alone never identifies a Cloudflare main challenge.
    for(const frame of document.querySelectorAll('iframe[src]')) {
      try {const url=new URL(frame.getAttribute('src'),location.href);
        if(/(^|\.)hcaptcha\.com$/i.test(url.hostname)) {
          markers.hcaptcha=true;
          const style=getComputedStyle(frame);
          if(frame.getClientRects().length && style.visibility!=='hidden' && style.visibility!=='collapse')markers.hcaptchaVisible=true;
        }
      } catch { /* No URL evidence. */ }
    }
    markers.login=[...document.querySelectorAll('input[type="password"],input[autocomplete="one-time-code"]')].some(node=>node.getClientRects().length>0);
    let imperva=null;
    const children=document.body?.children;
    const shell=children?.length>0 && [...children].every(node=>node.localName==='iframe')
      && [...document.body.childNodes].every(node=>node.nodeType!==3 || !node.nodeValue.trim());
    if(shell)for(const frame of children) {
      const fallback=frame.textContent || '';
      if(!/^\s*Request unsuccessful\.\s*Incapsula incident ID:/i.test(fallback))continue;
      let url;try {url=new URL(frame.getAttribute('src'),location.href);}catch {continue;}
      if(url.origin!==location.origin || url.pathname!=='/_Incapsula_Resource')continue;
      const params=url.searchParams,codes=params.getAll('edet'),ids=params.getAll('incident_id');
      const displayed=fallback.match(/Incapsula incident ID:\s*([0-9]{1,32}-[0-9]{1,32})(?=\s|$)/i)?.[1];
      imperva={};
      if(codes.length===1 && /^[0-9]{1,3}$/.test(codes[0]))imperva.edet=Number(codes[0]);
      const incident=ids.length?ids[0]:displayed;
      if(ids.length<=1 && /^[0-9]{1,32}-[0-9]{1,32}$/.test(incident) && (!displayed || displayed===incident))imperva.incident=incident;
      break;
    }
    return {markers,imperva};
  },
  extract(wantAbstract) {
    // This function is serialized into the isolated observation world. Its helpers
    // are deliberately local: there is no page API, network or caller evaluator.
    const diagnostics=new Set(),values=new Set(),budgetEnd=Date.now()+5000;
    const guard=()=>{if(Date.now()>budgetEnd)throw Error('extraction_budget_exceeded');};
    const normalize=value=>String(value || '').replace(/\s+/gu,' ').trim();
    const excluded=node=>{
      for(let el=node?.nodeType===1?node:node?.parentElement;el;el=el.parentElement) {
        if(['script','style','noscript','template','nav'].includes(el.localName) || el.hidden
          || el.getAttribute('aria-hidden')?.toLowerCase()==='true'
          || /(?:^|;)\s*display\s*:\s*none\s*(?:!important\s*)?(?:;|$)/i.test(el.getAttribute('style') || '')
          || ['navigation','contentinfo'].includes(el.getAttribute('role')?.toLowerCase())
          || el.localName==='footer' && !el.closest('article'))return true;
      }
      return false;
    };
    const legal=node=>!excluded(node);
    const body=document.body;
    if(!body)throw Error('document_operation_failed');
    const articles=[...body.querySelectorAll('article')].filter(node=>legal(node) && !node.parentElement?.closest('article'));
    const firstH1=[...body.querySelectorAll('h1')].find(legal);
    const root=articles.length===1 && firstH1 && articles[0].contains(firstH1)?articles[0]:body;
    const blockTags=new Set(['address','article','aside','blockquote','dd','details','div','dl','dt','fieldset','figcaption','figure','footer','form','h1','h2','h3','h4','h5','h6','header','hr','li','main','ol','p','pre','section','table','tbody','td','th','thead','tr','ul']);
    const semantic=new Set(['p','h1','h2','h3','h4','h5','h6','dt','dd','blockquote','figcaption','pre','address']);
    const months=['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
    const monthName='(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\\.?';
    const stamp='(?:T\\d{2}:\\d{2}(?::\\d{2}(?:\\.\\d+)?)?(?:Z|[+-]\\d{2}:?\\d{2})?)?';
    const formats=[
      [new RegExp('\\d{4}([-\\/])\\d{1,2}(?:\\1\\d{1,2}'+stamp+')?','gi'),'year'],
      [/\d{1,2}\/\d{1,2}\/\d{4}/g,'numeric'],
      [/\d{4}年\d{1,2}月(?:\d{1,2}[日号])?/g,'chinese'],
      [new RegExp('\\d{1,2}(?:st|nd|rd|th)?\\s+'+monthName+'\\s*,?\\s*\\d{4}','gi'),'englishDay'],
      [new RegExp(monthName+'\\s+\\d{1,2}(?:st|nd|rd|th)?(?:,\\s*|\\s+)\\d{4}','gi'),'englishFirst'],
      [new RegExp(monthName+'\\s+\\d{4}','gi'),'englishMonth'],
      [new RegExp('\\d{4}\\s+'+monthName,'gi'),'yearEnglish'],
    ];
    const canonical=(year,month,day)=>{
      const leap=year%4===0 && (year%100!==0 || year%400===0);
      if(year<1 || year>9999 || month<1 || month>12 || day!==undefined && (day<1 || day>[31,leap?29:28,31,30,31,30,31,31,30,31,30,31][month-1]))return null;
      return String(year).padStart(4,'0')+'-'+String(month).padStart(2,'0')+(day===undefined?'':'-'+String(day).padStart(2,'0'));
    };
    const parse=(text,whole=false)=>{
      text=normalize(text);
      const identityTokens=[...text.matchAll(/(?:\b[a-z][a-z\d+.-]*:)?\/\/[^\s<>"']+|\bwww\.[^\s<>"']+|\b10\.\d{4,9}\/\S+/gi)];
      const candidates=[];
      for(const [regex,kind] of formats) {
        regex.lastIndex=0;
        for(const match of text.matchAll(regex))candidates.push({text:match[0],start:match.index,end:match.index+match[0].length,kind});
      }
      candidates.sort((a,b)=>a.start-b.start || b.end-a.end);
      const output=[];let end=-1;
      for(const item of candidates) {
        if(item.start<end)continue;
        end=item.end; // Even an invalid full date suppresses its month substring.
        if(identityTokens.some(token=>item.start<token.index+token[0].length && item.end>token.index))continue;
        const before=text[item.start-1] || '',after=text[item.end] || '';
        if(/[\p{L}\p{N}_/.-]/u.test(before) || /[\p{L}\p{N}_/-]/u.test(after) || after==='.' && /\w/.test(text[item.end+1] || ''))continue;
        if(whole && (item.start!==0 || item.end!==text.length))continue;
        const numbers=item.text.match(/\d+/g).map(Number);let year,month,day;
        if(item.kind==='year' || item.kind==='chinese') [year,month,day]=numbers;
        else if(item.kind==='numeric') {
          const [a,b,y]=numbers;year=y;
          if(a>12 && b<=12){day=a;month=b;}else if(b>12 && a<=12){month=a;day=b;}else continue;
        } else {
          month=months.indexOf(item.text.match(/[A-Za-z]+/g).find(word=>!['st','nd','rd','th'].includes(word.toLowerCase())).slice(0,3).toLowerCase())+1;
          if(item.kind==='englishDay' || item.kind==='englishFirst')[day,year]=numbers;
          else [year]=numbers;
        }
        if(item.kind==='year' && /T/i.test(item.text)) {
          const time=item.text.match(/T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?(?:Z|([+-])(\d{2}):?(\d{2}))?$/i);
          if(!time || Number(time[1])>23 || Number(time[2])>59 || Number(time[3] || 0)>59 || Number(time[5] || 0)>23 || Number(time[6] || 0)>59)continue;
        }
        const value=canonical(year,month,day);if(value)output.push(value);
      }
      return output;
    };
    const add=(text,whole=false)=>{for(const value of parse(text,whole)){values.add(value);if(values.size>256)throw Error('document_operation_failed');}};
    // Keep li/tr indivisible. Else split at independent block structures; inline
    // descendants remain continuous, with explicit boundaries around each link.
    const readRecord=node=>{
      guard();
      const text=[],times=[];
      const walk=el=>{
        if(el.nodeType===3){text.push(el.nodeValue);return;}
        if(el.nodeType!==1 || excluded(el))return;
        if(el.localName==='time')times.push(el.getAttribute('datetime') || '');
        const boundary=el.localName==='a'?'\u0000':blockTags.has(el.localName)?' ':'';
        if(boundary)text.push(boundary);
        for(const child of el.childNodes)walk(child);
        if(boundary)text.push(boundary);
      };
      walk(node);
      const matching=text.join(''),context=normalize(matching.replace(/\u0000/g,''));
      // Count Unicode code points, not UTF-16 code units.
      let length=0;for(const _point of context)if(++length>150)return;
      for(const part of matching.split('\u0000'))add(part);
      for(const datetime of times)add(datetime,true);
    };
    const visit=node=>{
      guard();
      if(node.nodeType!==1 || excluded(node))return;
      if(node.localName==='li' || node.localName==='tr' || semantic.has(node.localName)){readRecord(node);return;}
      const hasBlocks=[...node.children].some(child=>legal(child) && blockTags.has(child.localName));
      if(!hasBlocks){readRecord(node);return;}
      let inline=[];
      const flush=()=>{if(inline.length){const holder=document.createElement('div');for(const child of inline)holder.append(child.cloneNode(true));readRecord(holder);inline=[];}};
      for(const child of node.childNodes) {
        if(child.nodeType===1 && blockTags.has(child.localName)){flush();visit(child);}else inline.push(child);
      }
      flush();
    };
    visit(root);
    const metas=[...document.head?.querySelectorAll('meta[content]') || []];
    const key=node=>(node.getAttribute('name') || node.getAttribute('property') || '').trim().toLowerCase();
    const ogArticle=metas.some(node=>key(node)==='og:type' && normalize(node.getAttribute('content')).toLowerCase()==='article');
    const dateKeys=new Set(['citation_publication_date','citation_online_date','citation_cover_date','dc.date','prism.publicationdate','citation_date']);
    for(const meta of metas)if(dateKeys.has(key(meta)) || key(meta)==='article:published_time' && ogArticle)add(meta.getAttribute('content'),true);
    // The only JSON-LD entrances are top-level values, direct @graph members and
    // an inline WebPage.mainEntity. References/recommendations are never walked.
    const schemaContext=context=>typeof context==='string'?/^https?:\/\/schema\.org\/?$/i.test(context)
      :Array.isArray(context)?context.some(schemaContext)
      :context && typeof context==='object' && schemaContext(context['@vocab']);
    const typeIs=(object,name,inherited)=>{
      const types=Array.isArray(object?.['@type'])?object['@type']:[object?.['@type']];
      const context=Object.hasOwn(object || {},'@context')?schemaContext(object['@context']):inherited;
      return types.some(type=>typeof type==='string' && (new RegExp('^https?://schema\\.org/'+name+'$','i').test(type) || context && type===name));
    };
    const ldArticles=[];let complexLD=false;
    const entry=(object,inherited=false)=>{
      if(!object || typeof object!=='object' || Array.isArray(object))return;
      const context=Object.hasOwn(object,'@context')?schemaContext(object['@context']):inherited;
      if(typeIs(object,'Article',inherited) || typeIs(object,'ScholarlyArticle',inherited))ldArticles.push(object);
      if(typeIs(object,'WebPage',inherited) && object.mainEntity) {
        const entity=object.mainEntity;
        if(Array.isArray(entity) || typeof entity!=='object' || !typeIs(entity,'Article',context) && !typeIs(entity,'ScholarlyArticle',context))complexLD=true;
        else ldArticles.push(entity);
      }
    };
    for(const script of document.querySelectorAll('script[type]')) {
      guard();
      if(script.getAttribute('type')?.trim().toLowerCase()!=='application/ld+json')continue;
      try {
        if(script.textContent.length>262144){diagnostics.add('json_ld_invalid');continue;}
        const data=JSON.parse(script.textContent);
        for(const object of Array.isArray(data)?data:[data]) {
          entry(object);
          if(Array.isArray(object?.['@graph']))for(const member of object['@graph'])entry(member,schemaContext(object['@context']));
        }
      }catch {diagnostics.add('json_ld_invalid');}
    }
    const unique=new Map();
    for(const candidate of ldArticles) {
      const fields=['@id','url','headline','name','identifier','datePublished','dateModified','abstract'];
      const signature=JSON.stringify(fields.map(field=>candidate[field] ?? null));
      const id=typeof candidate['@id']==='string' && candidate['@id']?candidate['@id']:signature;
      if(unique.has(id) && unique.get(id).signature!==signature)complexLD=true;
      unique.set(id,{signature,object:candidate});
    }
    const ldArticle=!complexLD && unique.size===1?[...unique.values()][0].object:null;
    if(complexLD || unique.size>1)diagnostics.add('json_ld_ambiguous');
    if(ldArticle)for(const name of ['datePublished','dateModified'])if(typeof ldArticle[name]==='string')add(ldArticle[name],true);
    const days=new Set([...values].filter(value=>value.length===10).map(value=>value.slice(0,7)));
    const dates=[...values].filter(value=>value.length===10 || !days.has(value)).sort().map(value=>({value,precision:value.length===7?'month':'day'}));
    let abstract=null;
    if(wantAbstract) {
      try {
      const headingSelector='h2,h3,h4,h5,h6,[role="heading"],.section-title,.section-heading';
      const headingLabel=node=>normalize(node?.textContent).replace(/^[\s:：.,;*!#()[\]{}—–-]+|[\s:：.,;*!#()[\]{}—–-]+$/gu,'').toLowerCase();
      const isHeading=node=>node?.nodeType===1 && node.matches('h1,h2,h3,h4,h5,h6,[role="heading"],.section-title,.section-heading');
      const level=node=>/^h[1-6]$/.test(node?.localName)?Number(node.localName[1]):Number(node?.getAttribute('aria-level')) || 2;
      const nextSection=node=>(isHeading(node) || node?.nodeType===1 && node.matches('p,dt'))
        && /^(keywords?|introduction|references|bibliography|graphical abstract|video abstract|lay summary|author summary|plain language summary)$/i.test(headingLabel(node));
      const peripheral=node=>{
        if(excluded(node))return true;
        for(let el=node?.nodeType===1?node:node?.parentElement;el;el=el.parentElement) {
          if(el.matches('nav,aside,footer,[role="navigation"],[role="complementary"],[role="doc-bibliography"],#references,.references,.related-articles,.recommended-articles,.recommendations,.recommended,.recommendation,.table-of-contents,.toc'))return true;
          const labels=[el.id,...el.classList,el.getAttribute('aria-label') || ''];
          if(labels.some(label=>/^(?:graphical[-_ ]abstract|video[-_ ]abstract|lay[-_ ]summary|author[-_ ]summary|plain[-_ ]language[-_ ]summary)$/i.test(label)))return true;
          if(el===root)break;
        }
        return false;
      };
      const abstractExcluded=(node,allowOwnControl=false)=>{
        if(peripheral(node))return true;
        for(let el=node;el;el=el.parentElement) {
          if(el.matches('button,[role="button"],figcaption,caption,figure,.keywords,.keyword-list,[role="doc-noteref"]')
            && !(allowOwnControl && el===node && el.matches('button,[role="button"]')))return true;
          if(el===root)break;
        }
        return false;
      };
      const preview=node=>{
        const elements=[...(node.nodeType===1?[node]:[]),...node.querySelectorAll('[class]')];
        if(elements.some(el=>!abstractExcluded(el) && [...el.classList].some(token=>/(?:^|[-_])(?:preview|teaser|truncated)(?:$|[-_])/i.test(token))))return true;
        for(const action of node.querySelectorAll('button,a,[role="button"]'))
          // A direct Read more control signals a fragment; controls inside an
          // excluded abstract subtree do not describe the candidate's content.
          if(!abstractExcluded(action,true) && /^(?:read|show|view)\s+(?:more|full(?:\s+abstract)?)[\s.…]*$/i.test(normalize(action.textContent)))return true;
        return false;
      };
      const eligibleText=value=>{
        const text=normalize(value);
        return !text || /^[\s.…-]+$/.test(text)
          || /^(?:no abstract(?: available)?|abstract (?:unavailable|not available)|please (?:log|sign) in(?: to (?:view|read) (?:the )?abstract)?)[.!]?$/i.test(text)
          || /^(?:read|show|view)\s+(?:more|full(?:\s+abstract)?)[\s.…]*$/i.test(text)?null:value;
      };
      const textFrom=(nodes,ignored=new Set())=>{
        const chunks=[];let size=0;
        const push=text=>{size+=text.length;if(size>131072)throw Error('abstract_budget_exceeded');chunks.push(text);};
        const walk=node=>{
          guard();
          if(ignored.has(node))return;
          if(node.nodeType===3){push(node.nodeValue);return;}
          if(node.nodeType!==1 || abstractExcluded(node))return;
          const label=headingLabel(node);
          if((isHeading(node) || node.localName==='p') && /^(abstract|summary)$/.test(label))return;
          if(node.localName==='a' && /^(download(?:\s+\w+)*|copy|share|read more|show more|view full abstract)$/i.test(normalize(node.textContent)))return;
          const block=blockTags.has(node.localName) || node.localName==='br' || isHeading(node);
          if(block)push('\n');
          for(const child of node.childNodes) {if(nextSection(child))break;walk(child);}
          if(block)push('\n');
        };
        for(const node of nodes)walk(node);
        const value=chunks.join('').split(/\r?\n/).map(normalize).filter(Boolean).join('\n');
        if(value.length>65536)throw Error('abstract_budget_exceeded');
        return eligibleText(value);
      };
      const safe=read=>{try{return read();}catch(error){if(error.message==='extraction_budget_exceeded')throw error;diagnostics.add(error.message==='abstract_budget_exceeded'?'abstract_budget_exceeded':'abstract_candidate_failed');return null;}};
      const uniqueText=items=>{const choices=[...new Set(items.filter(Boolean))];return {value:choices.length===1?choices[0]:null,conflict:choices.length>1};};
      const marked=node=>{
        if(['abstract','abstracts'].includes(node.id.toLowerCase()) || [...node.classList].some(token=>['abstract','abstract-content','abstractinfull'].includes(token.toLowerCase())))return true;
        if(!node.matches('section,[role="region"]'))return false;
        if(normalize(node.getAttribute('aria-label')).toLowerCase()==='abstract')return true;
        const ids=normalize(node.getAttribute('aria-labelledby')).split(' ').filter(Boolean);
        if(ids.length!==1)return false;
        const matches=[...document.querySelectorAll('[id]')].filter(title=>title.id===ids[0]);
        return matches.length===1 && root.contains(matches[0]) && legal(matches[0]) && isHeading(matches[0]) && normalize(matches[0].textContent).toLowerCase()==='abstract';
      };
      const containers=[root,...root.querySelectorAll('[id],[class],section[aria-label],section[aria-labelledby],[role="region"]')]
        .filter(node=>marked(node) && !abstractExcluded(node) && !node.matches('button,a') && !isHeading(node))
        .filter(node=>{
          const title=node.querySelector(headingSelector);
          if(!/^(graphical abstract|video abstract|lay summary|author summary|plain language summary)$/i.test(headingLabel(title)))return true;
          const prefix=document.createRange();prefix.setStart(node,0);prefix.setEndBefore(title);
          return !!normalize(prefix.toString());
        });
      // Only whole, explicitly marked candidate copies can deduplicate. Keep
      // unmarked parent paragraphs and ordinary repeated scientific text.
      const readOwner=node=>{
        const descendants=containers.filter(other=>other!==node && node.contains(other));
        const children=descendants.filter(child=>!descendants.some(other=>other!==child && other.contains(child)));
        const ignored=new Set(),seen=new Set(),choices=[];
        if(!children.length)return {value:textFrom([node]),conflict:false,ignored};
        for(const child of children) {
          const result=readOwner(child);
          if(result.conflict)return result;
          for(const duplicate of result.ignored)ignored.add(duplicate);
          if(result.value) {
            choices.push(result.value);
            if(seen.has(result.value))ignored.add(child);
            seen.add(result.value);
          }
        }
        // Without content outside the marked children, different complete
        // copies remain competing candidates rather than one concatenation.
        const outside=textFrom([node],new Set([...ignored,...children]));
        const conflict=!outside && uniqueText(choices).conflict;
        return {value:conflict?null:textFrom([node],ignored),conflict,ignored};
      };
      const owners=containers.filter(node=>!containers.some(other=>other!==node && other.contains(node)));
      const owned=owners.map(node=>safe(()=>preview(node)?null:readOwner(node)));
      const a1=uniqueText(owned.map(result=>result?.value));
      a1.conflict ||= owned.some(result=>result?.conflict);
      abstract=a1.conflict?null:a1.value;
      if(!abstract && !a1.conflict) {
        const headings=[...root.querySelectorAll(headingSelector)].filter(node=>!peripheral(node));
        const hasAbstract=headings.some(node=>headingLabel(node)==='abstract');
        const a2=[];
        for(const heading of headings) {
          const name=headingLabel(heading);
          if(name!=='abstract' && !(name==='summary' && !hasAbstract))continue;
          a2.push(safe(()=>{
            let section=heading.closest('section,[role="region"]');
            if(section===root || !section || section.matches('article,main'))section=null;
            if(section && peripheral(section) || preview(section || heading.parentElement))return null;
            const scope=section || heading.parentElement;
            const ending=[...scope.querySelectorAll('p,dt,h1,'+headingSelector)].find(node=>!peripheral(node)
              && heading.compareDocumentPosition(node)&Node.DOCUMENT_POSITION_FOLLOWING
              && (nextSection(node) || isHeading(node) && level(node)<=level(heading)));
            if(!section && !ending)return null;
            const range=document.createRange();range.setStartAfter(heading);
            if(ending)range.setEndBefore(ending);else range.setEnd(scope,scope.childNodes.length);
            // Clone only the bounded semantic section; never whole-page HTML.
            return textFrom(range.cloneContents().childNodes);
          }));
        }
        abstract=uniqueText(a2).value;
      }
      const structuredTags=[...blockTags,'br','a','b','strong','i','em','span','sub','sup','u','italic','bold','xref','img','wbr','button','script','style','noscript','template','abstract','sec','title'];
      const structuredTagName='(?:[\\w-]+:)?(?:'+structuredTags.join('|')+')';
      const markupStart='(?:/?'+structuredTagName+'(?:\\s|/?>)|!--|!DOCTYPE\\b)';
      const structuredMarkup=new RegExp('^\\s*<'+structuredTagName+'(?:\\s|/?>)|</'+structuredTagName+'\\s*>|<!--|<!DOCTYPE','i');
      const cleanStructured=value=>{
        if(value && typeof value==='object' && !Array.isArray(value))value=value['@value'] ?? value.text;
        if(typeof value!=='string')return null;
        if(value.length>131072)throw Error('abstract_budget_exceeded');
        if(structuredMarkup.test(value)) {
          // The detached template is inert. Only known markup is interpreted;
          // scientific <T>, E<T> and incomplete x<y remain literal text.
          const markup=value.replace(new RegExp('<(?!'+markupStart+')','gi'),'&lt;')
            .replace(/<(\/?)(?:[\w-]+:)([a-z][\w-]*)(?=[\s/>])/gi,'<$1$2')
            .replace(/<(\/?)(abstract|sec|title|italic|bold|xref)(?=[\s/>])/gi,(_match,slash,tag)=>
              '<'+slash+({abstract:'section',sec:'section',title:'h3',italic:'em',bold:'strong',xref:'a'}[tag.toLowerCase()]));
          const template=document.createElement('template');template.innerHTML=markup;
          if(preview(template.content))return null;
          return textFrom(template.content.childNodes);
        }
        const normalized=value.split(/\r?\n/).map(normalize).filter(Boolean).join('\n');
        if(normalized.length>65536)throw Error('abstract_budget_exceeded');
        return eligibleText(normalized);
      };
      if(!abstract)for(const name of ['citation_abstract','dcterms.abstract','dc.description.abstract']) {
        const candidate=uniqueText(metas.filter(node=>key(node)===name).map(node=>safe(()=>cleanStructured(node.getAttribute('content')))));
        if(candidate.value){abstract=candidate.value;break;}
      }
      if(!abstract && ldArticle)abstract=safe(()=>cleanStructured(ldArticle.abstract));
      } catch(error) {
        if(error.message==='extraction_budget_exceeded')throw error;
        abstract=null;diagnostics.add(error.message==='abstract_budget_exceeded'?'abstract_budget_exceeded':'abstract_candidate_failed');
      }
    }
    guard();
    return {metadata:{dates,abstract},diagnostics:[...diagnostics]};
  },
  pdf(readerKind,knownState,articleProbe,doiCasefold) {
    const diagnostics=new Set(),candidates=[],identifiers=[],seen=new Set(),landing_url=location.href;
    // Reserve space within the 64 KiB fact DTO for the final landing URL,
    // exact target and Python's typed/default candidate fields as well.
    const fieldsLimit=55000;
    const host=location.hostname.toLowerCase(),path=location.pathname,end=Date.now()+2000;
    const entries=[
      ['nature','R037',/(^|\.)nature\.com$/],['bmc','R038',/(^|\.)biomedcentral\.com$/],['rsc','R040',/^pubs\.rsc\.org$/],
      ['plos','R041',/^journals\.plos\.org$/],['mdpi','R042',/(^|\.)mdpi\.com$/],['copernicus','R043',/(^|\.)copernicus\.org$/],
      ['acs','R044',/^pubs\.acs\.org$/],['aip','R045',/^pubs\.aip\.org$/],['jama','R046',/^jamanetwork\.com$/],
      ['rup','R047',/(^|\.)rupress\.org$/],['ash','R048',/(^|\.)ashpublications\.org$/],['arvo','R049',/(^|\.)arvojournals\.org$/],
      ['geoscienceworld','R050',/^pubs\.geoscienceworld\.org$/],['cambridge','R051',/(^|\.)cambridge\.org$/],['highwire','R052',/(^|\.)bmj\.com$/],
      ['optica','R053',/^(?:opg\.optica\.org|(?:www\.)?osapublishing\.org)$/],['degruyter','R054',/^(?:www\.)?degruyterbrill\.com$/],
      ['emerald','R055',/^(?:www\.)?emerald\.com$/],['brill','R056',/(^|\.)brill\.com$/],['elife','R057',/(^|\.)elifesciences\.org$/],
      ['thieme','R058',/(^|\.)thieme-connect\.(?:com|de)$/],['microbiology','R059',/(^|\.)microbiologyresearch\.org$/],
      ['lww','R060',/^(?:pdfs\.)?journals\.lww\.com$/],['siam','R061',/^epubs\.siam\.org$/],
      ['oce','R060',/^oce\.ovid\.com$/],
      ['sciencedirect','R024',/^(?:www\.)?sciencedirect\.com$/],['ieee','R025',/^ieeexplore\.ieee\.org$/],
      ['oup','R020',/^academic\.oup\.com$/],['atypon','R039',/^(?:onlinelibrary\.wiley\.com|journals\.sagepub\.com|www\.tandfonline\.com|www\.annualreviews\.org|pubs\.aiaa\.org|www\.liebertpub\.com|www\.worldscientific\.com)$/],
    ];
    const [platform,rule_id]=readerKind==='sciencedirect' && host==='pdf.sciencedirectassets.com'
      ? ['sciencedirect','R024'] : entries.find(item=>item[2].test(host)) || ['generic','GENERIC'];
    // Main supplies the existing article-identity casefold data, not page code.
    const normalizeDoi=value=>{if(typeof value!=='string')return null;const doi=value.trim().replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i,'').trim().toLowerCase().replace(/[^\x00-\x7f]/gu,char=>doiCasefold[char] || char);return /^10\.\d{4,9}\/[^\s]+$/u.test(doi)?doi:null;};
    // The fixed article probe owns the scholarly DOI sources; PDF qualification
    // reuses its bounded values instead of maintaining another alias list.
    const doiValues=[...new Set((articleProbe?.values || []).map(normalizeDoi).filter(Boolean))];
    const decode=value=>{try{return decodeURI(value);}catch{return value;}};
    const pathDoi=normalizeDoi(decode(path).match(/\/doi\/(?:abs\/|full\/)?(10\.\d{4,9}\/[^\s]+)$/)?.[1]);
    const targetDoi=doiValues.length===1?doiValues[0]:doiValues.length?null:pathDoi;
    const sameArticle=value=>{const link=url(value);if(!link)return false;const doi=normalizeDoi(decode(new URL(link).pathname).match(/\/doi\/(?:pdf|epdf|pdfplus)\/(10\.\d{4,9}\/[^\s]+)$/)?.[1]);return !doi || !!targetDoi && doi===targetDoi;};
    const type=[...document.head?.querySelectorAll('meta[content]') || []].filter(node=>/^(?:citation_type|dc.type)$/i.test(node.getAttribute('name') || node.getAttribute('property') || '')).map(node=>node.getAttribute('content').toLowerCase()).join(' ');
    const unsupported=/book|chapter|supplement/i.test(type) || /\/(?:chapter|chapter-abstract|books|book)\//i.test(path);
    const content_type=unsupported?'unknown':/conference|proceeding/i.test(type)?'conference-paper':/journal|article/i.test(type)?'journal-article':'unknown';
    const guard=()=>{if(Date.now()>end)throw Error('pdf_budget_exceeded');};
    const url=value=>{if(typeof value!=='string'||!value.trim())return null;if(value.length>4096)throw Error('pdf_budget_exceeded');
      try{if(/[\s\x00-\x1f\x7f\\]/.test(value))return null;const out=new URL(value,landing_url),hostname=out.hostname.toLowerCase().replace(/\.$/,'');
        if(!['http:','https:'].includes(out.protocol)||out.username||out.password||!hostname.includes('.')||/(?:^|\.)(?:localhost|local|internal|invalid|test|corp|lan|home|intranet)$/.test(hostname))return null;
        if(/^\d+\.\d+\.\d+\.\d+$/.test(hostname)||hostname.includes(':'))return null;return out.href;}catch{return null;}};
    const add=(value,stage='P4',extra={})=>{guard();const resolved=url(value);if(!resolved||seen.has(resolved))return;
      const candidate={stage,rule_id,url:resolved,...extra};
      if(candidates.length>=32 || JSON.stringify({identifiers,candidates:[...candidates,candidate]}).length>fieldsLimit)throw Error('pdf_budget_exceeded');
      seen.add(resolved);candidates.push(candidate);};
    const excluded=(node,allowNavigation=false)=>{for(let owner=node;owner;owner=owner.parentElement) {
      if(owner.matches('footer,aside,[role="doc-bibliography"],[role="doc-endnotes"],[data-related],[hidden],[aria-hidden="true"]') || !allowNavigation && owner.matches('nav')
        || /references|related|recommend|supplement/i.test(owner.id+' '+(owner.getAttribute('class') || ''))
        || /(?:^|;)\s*display\s*:\s*none\s*(?:!important\s*)?(?:;|$)/i.test(owner.getAttribute('style') || ''))return true;
    }return false;};
    const main=document.querySelector('article') || document.body;
    const bodyEntry=(node,attribute='href',allowNavigation=false)=>{
      if(excluded(node,allowNavigation))return false;
      const value=attribute===null?null:node.getAttribute(attribute),label=node.textContent+' '+(node.getAttribute('title') || '')+' '+(value || '');
      const identity=normalizeDoi(node.closest('[data-doi]')?.getAttribute('data-doi'));
      return !/supplement|supporting|appendix|whole issue|entire issue|issue pdf|other article/i.test(label)
        && (!identity || !!targetDoi && identity===targetDoi) && (attribute===null || sameArticle(value));
    };
    const explicit=(selector,attribute='href',extra={})=>{for(const node of document.querySelectorAll(selector)){guard();if(bodyEntry(node,attribute))add(node.getAttribute(attribute),'P4',extra);}};
    const addId=(kind,value)=>{if(typeof value==='string' && /^[A-Za-z0-9_.:/-]{1,256}$/.test(value) && !identifiers.some(item=>item.kind===kind&&item.value===value)) {
      const identifier={kind,value,rule_id};
      if(identifiers.length>=16 || JSON.stringify({identifiers:[...identifiers,identifier],candidates}).length>fieldsLimit)throw Error('pdf_budget_exceeded');
      identifiers.push(identifier);
    }};
    let status='complete';
    try {
      if(knownState==='__allfold_pdf_overflow__')throw Error('pdf_budget_exceeded');
      if(!readerKind && !unsupported) {
        for(const name of ['citation_pdf_url','fulltext_pdf_url'])for(const meta of document.head?.querySelectorAll('meta[content]') || [])
          if((meta.getAttribute('name') || meta.getAttribute('property') || '').toLowerCase()===name)add(meta.getAttribute('content'),'P3',{field:name});
        if(['acs','aip','jama','rup','ash','arvo','geoscienceworld','oup'].includes(platform))explicit('a.article-pdfLink[href]');
        if(platform==='jama')explicit('a#pdf-link[data-article-url]','data-article-url');
        if(platform==='nature')explicit('a[data-track-action="download pdf"][href]');
        if(platform==='degruyter')explicit('a.downloadPdf[href]');
        if(platform==='emerald'){explicit('a.intent_pdf_link[href]');if(/\/full\/pdf$/.test(path))add(landing_url);}
        if(platform==='optica')explicit('a#link-pdf[href]');
        if(platform==='elife')for(const node of document.querySelectorAll('.article-download-list a[href]'))if(bodyEntry(node) && /\bpdf\b/i.test(node.textContent+' '+node.getAttribute('title')))add(node.getAttribute('href'));
        if(platform==='microbiology')explicit('.download-pdf form.ft-download-content__form--pdf[action]','action',{action:'refresh_form'});
        if(['atypon','siam'].includes(platform))for(const node of document.querySelectorAll('a[href]')){const target=url(node.getAttribute('href'));if(target && new URL(target).hostname===host && /\/doi\/(?:pdf|epdf|pdfplus)\//.test(new URL(target).pathname) && targetDoi && bodyEntry(node))add(target);}
        if(['acs','oup'].includes(platform)) {
          const resourceIds=new Set();
          for(const node of main?.querySelectorAll('a[href*="/Citation/Download"]') || []) {
            guard();if(excluded(node))continue;const resolved=url(node.getAttribute('href'));if(!resolved)continue;
            const target=new URL(resolved),ids=target.searchParams.getAll('resourceId'),types=target.searchParams.getAll('resourceType');
            if(target.hostname===host && /^\/Citation\/Download\/?$/.test(target.pathname) && types.length===1 && types[0]==='3'
              && ids.length===1 && /^[0-9]{1,16}$/.test(ids[0]))resourceIds.add(ids[0]);
          }
          if(resourceIds.size===1){addId('resource_id',[...resourceIds][0]);addId('resource_type','3');}
        }
        if(platform==='sciencedirect') {
          const pii=path.match(/\/pii\/([SB][0-9]{7}[0-9X][0-9]{7}[0-9X])(?:\/|$)/i)?.[1];
          if(pii) {
            addId('pii',pii);
            // The current article's PDF toolbar may live in navigation. Only
            // this exact PII/path relationship can relax generic nav exclusion.
            for(const node of document.querySelectorAll('a[href]')) {
              guard();if(!bodyEntry(node,'href',true))continue;
              const resolved=url(node.getAttribute('href'));if(!resolved)continue;
              const link=new URL(resolved);
              const page=new URL(landing_url),reader=link.origin===page.origin
                && ['/science/article/pii/'+pii+'/pdfft','/science/article/pii/'+pii+'/pdf'].includes(link.pathname);
              const asset=link.hostname==='pdf.sciencedirectassets.com' && link.protocol==='https:'
                && link.pathname.endsWith('/1-s2.0-'+pii+'/main.pdf');
              if(reader || asset)
                add(resolved,'P4',{reader_kind:'sciencedirect',referer:landing_url});
            }
          }
        }
        if(platform==='ieee') {
          const pathId=path.match(/^\/document\/([0-9]{1,16})\/?$/)?.[1],queryIds=new URL(landing_url).searchParams.getAll('arnumber');
          if(queryIds.length===0)addId('article_number',pathId);
          else if(queryIds.length===1 && /^[0-9]{1,16}$/.test(queryIds[0]) && (!pathId || pathId===queryIds[0]))addId('article_number',queryIds[0]);
        }
        if(platform==='lww') {
          const numbers=new Set();
          for(const node of main?.querySelectorAll('[onclick*="PDFDownloadInit"]') || []) {
            guard();if(!bodyEntry(node,null))continue;
            const match=node.getAttribute('onclick').match(/PDFDownloadInit\(\s*['"]([0-9]{8}-[0-9]{9}-[0-9]{5})['"]/);if(match)numbers.add(match[1]);
          }
          if(numbers.size===1)addId('an',[...numbers][0]);
        }
        // Generic entrances need the current article region and a single decidable main PDF.
        const generic=[];
        for(const node of main?.querySelectorAll('a[href]') || []) {guard();if(!bodyEntry(node))continue;const text=(node.textContent+' '+(node.getAttribute('title') || '')).replace(/\s+/g,' ').trim();
          if((/^(?:download\s+)?(?:full[ -]?text\s+|article\s+)?pdf(?:\s+download)?$/i.test(text)||node.getAttribute('type')==='application/pdf') && url(node.getAttribute('href')))generic.push(node.getAttribute('href'));}
        const unique=[...new Set(generic.map(url))];if(unique.length===1)add(unique[0],'P4',{rule_id:'GENERIC'});
      }
      if(!unsupported && platform==='sciencedirect' && typeof knownState==='string')add(knownState,'P4',{reader_kind:'sciencedirect'});
      if(!unsupported && platform==='lww' && typeof knownState==='string')add(knownState,'P4',{reader_kind:'lww',referer:landing_url});
      if(readerKind==='sciencedirect') {
        if(host==='pdf.sciencedirectassets.com' && document.contentType==='application/pdf')add(landing_url);
        explicit('#redirect-message a[href]');explicit('.PdfEmbed > object[data]','data');
        for(const meta of document.head?.querySelectorAll('meta[http-equiv][content]') || [])if(meta.getAttribute('http-equiv').toLowerCase()==='refresh')add(meta.getAttribute('content').match(/^\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*["']?([^"']+)["']?\s*$/i)?.[1]);
      }
      if(readerKind==='ieee') {explicit('frame[src],iframe[src]','src',{reader_kind:'ieee'});for(const meta of document.head?.querySelectorAll('meta[http-equiv][content]') || [])if(meta.getAttribute('http-equiv').toLowerCase()==='refresh')add(meta.getAttribute('content').match(/;\s*url\s*=\s*["']?([^"']+)/i)?.[1]);}
      if(readerKind==='optica'){explicit('frame:not(:first-of-type)[src]','src');add(new URL(landing_url).searchParams.get('gotourl'));}
      if(readerKind==='oce') {
        const carrier=value=>{const parsed=url(value);if(!parsed)return;const viewer=new URL(parsed),files=viewer.searchParams.getAll('file');
          if(viewer.hostname==='oce.ovid.com' && viewer.pathname==='/pdfviewer/web/viewer.html' && files.length===1) {
            const pdf=url(files[0]);if(pdf && new URL(pdf).hostname==='assets.ovid.com')add(pdf);
          }};
        carrier(landing_url);
        for(const node of document.querySelectorAll('iframe[src]')){guard();if(!excluded(node))carrier(node.getAttribute('src'));}
      }
      if(knownState===false)throw Error('pdf_parse_failed');
    }catch(error){status=candidates.length||identifiers.length?'partial':'failed';diagnostics.add(error.message==='pdf_budget_exceeded'?'pdf_budget_exceeded':'pdf_parse_failed');}
    return {status,landing_url,observed_at:new Date().toISOString(),platform,content_type,identifiers,candidates,diagnostics:[...diagnostics]};
  },
  article() {
    const keys=new Set(['citation_doi','bepress_citation_doi','prism.doi','dc.identifier','dc.identifier.doi','dcterms.identifier']);
    const values=[];let limited=false;
    const add=value=>{
      if(typeof value!=='string')return;
      if(value.length>1024 || values.length>=32){limited=true;return;}
      values.push(value);
    };
    // Only head scholarly metadata belongs to the main Document, never references/frames.
    for(const node of document.head?.querySelectorAll('meta[content]') || [])
      if(keys.has((node.getAttribute('name') || node.getAttribute('property') || '').toLowerCase()))add(node.getAttribute('content'));
    const peripheral='nav,#references,.references,[role="doc-bibliography"],.related-articles,.recommended-articles';
    const articles=[...document.querySelectorAll('article')].filter(node=>!node.closest(peripheral) && !node.parentElement?.closest('article'));
    const multiple=articles.length>1;
    // Scoped replacement for the historical SciELO DOI locator, without Translator IDs.
    if(/(^|\.)scielo\.(?:br|org|cl|sa\.cr|org\.mx|org\.za)$/i.test(location.hostname))
      for(const node of document.querySelectorAll('article a._doi[href],.article a._doi[href]'))
        if(!node.closest(peripheral))add(node.getAttribute('href'));
    return {values,limited,multiple,article:articles.length===1};
  },
};
ipcRenderer.on('document:operation',async(_event,{id,action,expectedDocumentId,expectedURL,args,doiCasefold})=>{
  if(!Object.hasOwn(operations,action) || !args || typeof args!=='object' || Array.isArray(args)
    || (action==='extract'?Object.keys(args).length!==1 || typeof args.wantAbstract!=='boolean':action==='pdf'?Object.keys(args).length!==1 || ![null,'sciencedirect','ieee','optica','lww','oce'].includes(args.readerKind):Object.keys(args).length!==0)) {
    ipcRenderer.send('document:result',{id,error:'document_operation_failed'});return;
  }
  const url=location.href;
  if(expectedDocumentId && expectedDocumentId!==documentId || expectedURL!==url) {
    ipcRenderer.send('document:result',{id,error:'document_changed'});return;
  }
  try {
    let knownState=null;
    if(action==='pdf') {
      const host=location.hostname;
      const code=/^(?:www\.)?sciencedirect\.com$/.test(host)?'(()=>{try{const v=typeof article!=="undefined"?article?.pdfDownload?.urlMetadata:null;return typeof v==="string"?(v.length<=4096?v:"__allfold_pdf_overflow__"):null;}catch{return false;}})()':/^(?:pdfs\.)?journals\.lww\.com$/.test(host)?'(()=>{try{const v=typeof pdfDownloadDetails!=="undefined"?pdfDownloadDetails?.pdfUrl:null;return typeof v==="string"?(v.length<=4096?v:"__allfold_pdf_overflow__"):null;}catch{return false;}})()':null;
      if(code)try{knownState=await webFrame.executeJavaScript(code);}catch{knownState=false;}
    }
    const subject='('+documentSubject.toString()+')()';
    const source=name=>'('+operations[name].toString().replace(/^\w+\(/,'function(')+')()';
    // Access and article facts are observed in one synchronous DOM turn.
    const code=action==='article'?'({access:'+source('access')+',article:{...'+source('article')+',subject:'+subject+'}})'
      :action==='extract'?'({...('+operations.extract.toString().replace(/^\w+\(/,'function(')+')('+JSON.stringify(args.wantAbstract)+'),subject:'+subject+'})':action==='pdf'?'({clues:('+operations.pdf.toString().replace(/^\w+\(/,'function(')+')('+JSON.stringify(args.readerKind)+','+JSON.stringify(knownState)+','+source('article')+','+JSON.stringify(doiCasefold)+'),subject:'+subject+'})':source(action);
    const result=await webFrame.executeJavaScriptInIsolatedWorld(999,[{code}]);
    if(location.href!==url)throw Error('document_changed');
    ipcRenderer.send('document:result',{id,result,documentId,url});
  }catch {ipcRenderer.send('document:result',{id,error:'document_operation_failed'});}
});
