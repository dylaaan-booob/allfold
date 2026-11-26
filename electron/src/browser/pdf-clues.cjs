'use strict';
const {isIP}=require('node:net');
const {BrowserFailure}=require('./browser-errors.cjs');
const {validDOI,articleURL}=require('./article-identity.cjs');
const invalid=()=>{throw new BrowserFailure('navigation','document_operation_failed');};
function publicClueURL(value) {
  if(typeof value!=='string'||/[\s\x00-\x1f\x7f\\]/.test(value))return null;
  try {const url=new URL(value),host=url.hostname.toLowerCase().replace(/\.$/,'');
    if(!['http:','https:'].includes(url.protocol)||url.username||url.password||isIP(host.replace(/^\[|\]$/g,''))
      || !host.includes('.') || /(?:^|\.)(?:localhost|local|internal|invalid|test|corp|lan|home|intranet)$/.test(host))return null;
    return url.href;
  }catch{return null;}
}
function boundedPdfClues(value) {
  if(!value || Object.keys(value).sort().join(',')!=='candidates,content_type,diagnostics,identifiers,landing_url,observed_at,platform,status'
    || !['complete','partial','failed'].includes(value.status)
    || typeof value.observed_at!=='string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(value.observed_at) || !Number.isFinite(Date.parse(value.observed_at))
    || typeof value.platform!=='string'||!/^[a-z][a-z0-9-]{0,63}$/.test(value.platform)
    || !['journal-article','conference-paper','unknown'].includes(value.content_type)
    || !Array.isArray(value.identifiers)||!Array.isArray(value.candidates)
    || !Array.isArray(value.diagnostics)||value.diagnostics.length>3||value.diagnostics.some(code=>!['pdf_budget_exceeded','pdf_parse_failed','pdf_context_missing'].includes(code)))invalid();
  const identifiers=value.identifiers.map(item=>{if(!item || Object.keys(item).sort().join(',')!=='kind,rule_id,value'
      || !/^[a-z][a-z0-9_]{0,63}$/.test(item.kind)||typeof item.value!=='string'||!/^[A-Za-z0-9_.:/-]{1,256}$/.test(item.value)||!/^R\d{3}$/.test(item.rule_id))invalid();return {...item};});
  const diagnostics=new Set(value.diagnostics);
  const landing_url=articleURL(value.landing_url)?value.landing_url:null;
  if(!landing_url)diagnostics.add('pdf_context_missing');
  const candidates=value.candidates.flatMap(item=>{if(!item || Object.keys(item).some(key=>!['stage','rule_id','url','action','reader_kind','referer','field'].includes(key))
      || !['P3','P4'].includes(item.stage)||! /^(?:R\d{3}|GENERIC)$/.test(item.rule_id)
      || item.field!==undefined&&!['citation_pdf_url','fulltext_pdf_url'].includes(item.field)
      || item.action!==undefined && item.action!=='refresh_form'||item.reader_kind!==undefined&&!['sciencedirect','lww','ieee'].includes(item.reader_kind))invalid();
    const {referer,...candidate}=item;
    if(!publicClueURL(candidate.url)){diagnostics.add('pdf_context_missing');return [];}
    if(referer!=null) {
      if(publicClueURL(referer))candidate.referer=referer;
      else diagnostics.add('pdf_context_missing');
    }
    return [candidate];
  });
  if(value.status==='failed' && (!value.diagnostics.length||candidates.length||identifiers.length))invalid();
  const status=value.status==='complete' && diagnostics.size?'partial':value.status;
  return {...value,status,landing_url,identifiers,candidates,diagnostics:[...diagnostics]};
}
function qualifyReader(reader,identity) {
  if(!reader||Object.keys(reader).some(key=>!['rule_id','platform','url','identifier','target','source_url','stage'].includes(key))
    || !['P1','P2','P3','P4','P5'].includes(reader.stage)||!reader.target||JSON.stringify(reader.target)!==JSON.stringify(identity)
    || !publicClueURL(reader.url)||!publicClueURL(reader.source_url))invalid();
  const url=new URL(reader.url),source=new URL(reader.source_url),id=reader.identifier;
  // The source URL and exact identifier are supplied by the trusted host's
  // immutable candidate chain, never inferred from an arbitrary reader iframe.
  let kind;
  if(reader.rule_id==='R024'&&reader.platform==='sciencedirect'&&/^(?:www\.)?sciencedirect\.com$/.test(url.hostname)
    && /^(?:www\.)?sciencedirect\.com$/.test(source.hostname)&&/^[SB][0-9]{7}[0-9X][0-9]{7}[0-9X]$/i.test(id)
    && ['/science/article/pii/'+id+'/pdfft','/science/article/pii/'+id+'/pdf'].includes(url.pathname)
    && (source.pathname==='/science/article/pii/'+id||source.pathname.startsWith('/science/article/pii/'+id+'/')))kind='sciencedirect';
  if(reader.rule_id==='R025'&&reader.platform==='ieee'&&url.hostname==='ieeexplore.ieee.org'&&source.hostname===url.hostname
    && /^\d{1,16}$/.test(id)&&/^\/(?:stamp\/stamp.jsp|stampPDF\/getPDF.jsp)$/.test(url.pathname)&&url.searchParams.get('arnumber')===id
    && (source.pathname==='/document/'+id||source.searchParams.get('arnumber')===id))kind='ieee';
  if(reader.rule_id==='R053'&&reader.platform==='optica'&&/^(?:opg\.optica\.org|(?:www\.)?osapublishing\.org)$/.test(url.hostname)
    && source.hostname===url.hostname&&/^\/(?:[A-Za-z0-9_-]+\/)?viewmedia\.cfm$/.test(url.pathname)&&typeof id==='string'&&id.length<=256&&url.searchParams.get('uri')===id
    && source.searchParams.get('uri')===id)kind='optica';
  if(reader.rule_id==='R060'&&reader.platform==='lww'&&url.hostname==='journals.lww.com'&&source.hostname===url.hostname
    && /^\d{8}-\d{9}-\d{5}$/.test(id)&&/^\/[^/]+\/_layouts\/15\/oaks.journals\/downloadpdf.aspx$/i.test(url.pathname)
    && url.searchParams.get('an')===id&&source.pathname.split('/')[1]===url.pathname.split('/')[1])kind='lww';
  if(reader.rule_id==='R060'&&reader.platform==='oce'&&url.hostname==='oce.ovid.com'&&source.hostname===url.hostname
    && /^\d{8}-\d{9}-\d{5}$/.test(id)&&source.pathname==='/article/'+id+'/HTML'
    && (url.pathname===source.pathname || url.pathname==='/pdfviewer/web/viewer.html'))kind='oce';
  if(!kind || !identity || !(validDOI(identity.doi)||articleURL(identity.confirmed_article_url)))invalid();
  return kind;
}
function scienceDirectAsset(identifier,landing) {
  return landing.origin==='https://pdf.sciencedirectassets.com'
    && landing.pathname.endsWith('/1-s2.0-'+identifier+'/main.pdf');
}
function matchingScienceDirectAssetGet(identifier,request,landingURL) {
  if(request?.method!=='GET')return null;
  const landing=new URL(landingURL),get=new URL(request.url);
  if(!scienceDirectAsset(identifier,landing) || get.origin!==landing.origin
    || get.pathname!==landing.pathname || get.search!==landing.search)return null;
  return request;
}
function readerDiagnosticFields(reader,result,observed) {
  if(reader?.rule_id!=='R024' || !result.pdf_clues)return {};
  const entry=new URL(reader.url),landing=new URL(result.pdf_clues.landing_url);
  let relation='other-origin';
  if(landing.origin===entry.origin) {
    relation='other-path';
    if(landing.pathname===entry.pathname)relation='reader';
    else if(landing.pathname==='/science/article/pii/'+reader.identifier)relation='article';
  }
  const fields={reader_entry:entry.searchParams.get('download')==='true'?'download':entry.search?'other-query':'plain',
    reader_landing:relation,reader_pdf_candidates:result.pdf_clues.candidates.length};
  if(observed) {
    const get=observed.lastGetURL?new URL(observed.lastGetURL):null;
    const samePath=get && get.origin===landing.origin && get.pathname===landing.pathname;
    fields.reader_last_method=observed.method==='GET'?'get':observed.method==='POST'?'post':observed.method?'other':'unobserved';
    fields.reader_last_get_relation=!get?'unobserved':!samePath?'other':get.search===landing.search?'exact':'same-path';
    fields.reader_target_asset=scienceDirectAsset(reader.identifier,landing);
  }
  const navigation=result.reader_result;
  if(navigation) {
    const request=new URL(navigation.url);
    entry.hash='';request.hash='';
    fields.reader_request_changed=request.href!==entry.href;
    fields.reader_context_changed=navigation.context_changed;
  }
  return fields;
}
module.exports={boundedPdfClues,qualifyReader,publicClueURL,matchingScienceDirectAssetGet,readerDiagnosticFields};
