'use strict';
const {isIP}=require('node:net');
const {BrowserFailure}=require('./browser-errors.cjs');
const {validDOI,articleURL}=require('./article-identity.cjs');
const invalid=()=>{throw new BrowserFailure('navigation','document_operation_failed');};
function publicClueURL(value) {
  if(typeof value!=='string'||value.length>4096||/[\s\x00-\x1f\x7f\\]/.test(value))return null;
  try {const url=new URL(value),host=url.hostname.toLowerCase().replace(/\.$/,'');
    if(!['http:','https:'].includes(url.protocol)||url.username||url.password||isIP(host.replace(/^\[|\]$/g,''))
      || !host.includes('.') || /(?:^|\.)(?:localhost|local|internal|invalid|test|corp|lan|home|intranet)$/.test(host))return null;
    return url.href;
  }catch{return null;}
}
function boundedPdfClues(value) {
  if(!value || Object.keys(value).sort().join(',')!=='candidates,content_type,diagnostics,identifiers,landing_url,observed_at,platform,status'
    || JSON.stringify(value).length>65536 || !['complete','partial','failed'].includes(value.status) || !articleURL(value.landing_url)
    || typeof value.observed_at!=='string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(value.observed_at) || !Number.isFinite(Date.parse(value.observed_at))
    || typeof value.platform!=='string'||!/^[a-z][a-z0-9-]{0,63}$/.test(value.platform)
    || !['journal-article','conference-paper','unknown'].includes(value.content_type)
    || !Array.isArray(value.identifiers)||value.identifiers.length>16||!Array.isArray(value.candidates)||value.candidates.length>32
    || !Array.isArray(value.diagnostics)||value.diagnostics.length>2||value.diagnostics.some(code=>!['pdf_budget_exceeded','pdf_parse_failed'].includes(code)))invalid();
  const identifiers=value.identifiers.map(item=>{if(!item || Object.keys(item).sort().join(',')!=='kind,rule_id,value'
      || !/^[a-z][a-z0-9_]{0,63}$/.test(item.kind)||typeof item.value!=='string'||!/^[A-Za-z0-9_.:/-]{1,256}$/.test(item.value)||!/^R\d{3}$/.test(item.rule_id))invalid();return {...item};});
  const candidates=value.candidates.map(item=>{if(!item || Object.keys(item).some(key=>!['stage','rule_id','url','action','reader_kind','referer','field'].includes(key))
      || !['P3','P4'].includes(item.stage)||! /^(?:R\d{3}|GENERIC)$/.test(item.rule_id)||!publicClueURL(item.url)
      || item.field!==undefined&&!['citation_pdf_url','fulltext_pdf_url'].includes(item.field)
      || item.action!==undefined && item.action!=='refresh_form'||item.reader_kind!==undefined&&!['sciencedirect','lww','ieee'].includes(item.reader_kind)
      || item.referer!==undefined&&!articleURL(item.referer))invalid();return {...item};});
  if(value.status==='failed' && (!value.diagnostics.length||candidates.length||identifiers.length))invalid();
  return {...value,identifiers,candidates,diagnostics:[...new Set(value.diagnostics)]};
}
function qualifyReader(reader,identity) {
  if(!reader||Object.keys(reader).some(key=>!['rule_id','platform','url','identifier','target','source_url','stage'].includes(key))
    || !['P1','P2','P3','P4','P5'].includes(reader.stage)||!reader.target||JSON.stringify(reader.target)!==JSON.stringify(identity)
    || !publicClueURL(reader.url)||!publicClueURL(reader.source_url))invalid();
  const url=new URL(reader.url),source=new URL(reader.source_url),id=reader.identifier;
  // The source URL and exact identifier are supplied by the trusted host's
  // immutable candidate chain, never inferred from an arbitrary reader iframe.
  let kind;
  if(reader.rule_id==='R024'&&reader.platform==='sciencedirect'
    && /^(?:www\.)?sciencedirect\.com$/.test(source.hostname)&&/^[SB][0-9]{7}[0-9X][0-9]{7}[0-9X]$/i.test(id)
    && (/^(?:www\.)?sciencedirect\.com$/.test(url.hostname)
      && ['/science/article/pii/'+id+'/pdfft','/science/article/pii/'+id+'/pdf'].includes(url.pathname)
      || url.hostname==='pdf.sciencedirectassets.com' && url.protocol===source.protocol
        && url.pathname.endsWith('/1-s2.0-'+id+'/main.pdf'))
    && (source.pathname==='/science/article/pii/'+id||source.pathname.startsWith('/science/article/pii/'+id+'/')))kind='sciencedirect';
  if(reader.rule_id==='R025'&&reader.platform==='ieee'&&url.hostname==='ieeexplore.ieee.org'&&source.hostname===url.hostname
    && /^\d{1,16}$/.test(id)&&/^\/(?:stamp\/stamp.jsp|stampPDF\/getPDF.jsp)$/.test(url.pathname)&&url.searchParams.get('arnumber')===id
    && (source.pathname==='/document/'+id||source.searchParams.get('arnumber')===id))kind='ieee';
  if(reader.rule_id==='R053'&&reader.platform==='optica'&&/^(?:opg\.optica\.org|(?:www\.)?osapublishing\.org)$/.test(url.hostname)
    && source.hostname===url.hostname&&url.pathname==='/viewmedia.cfm'&&typeof id==='string'&&id.length<=256&&url.searchParams.get('uri')===id
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
module.exports={boundedPdfClues,qualifyReader,publicClueURL};
