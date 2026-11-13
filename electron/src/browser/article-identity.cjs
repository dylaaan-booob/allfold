'use strict';
// Unicode lowercase-to-casefold differences, generated from Python str.casefold (Unicode 15).
const casefold=require('./doi-casefold.json');
// Same prefix stripping, case-insensitive comparison and syntax as identifiers.valid_doi.
function validDOI(value) {
  if(typeof value!=='string')return null;
  const doi=value.trim().replace(/^(?:https?:\/\/(?:dx\.)?doi\.org\/|doi:\s*)/i,'').trim().toLowerCase().replace(/[^\x00-\x7f]/gu,char=>casefold[char] || char);
  return /^10\.\d{4,9}\/[^\s]+$/u.test(doi)?doi:null;
}
function articleURL(value) {
  try {
    const url=new URL(value);
    if(!['https:','http:'].includes(url.protocol) || url.username || url.password || url.href.length>4096)return null;
    return url;
  }catch {return null;}
}
function locationDOIs(value) {
  const url=articleURL(value);if(!url || /^(?:dx\.)?doi\.org$/i.test(url.hostname))return [];
  // A query DOI belongs to a supported article endpoint, never an arbitrary search/redirect URL.
  const values=/\/article\/?$/i.test(url.pathname)?[...url.searchParams.getAll('doi'),...url.searchParams.getAll('id')]:[];
  try {
    let path=decodeURIComponent(url.pathname);
    // IOP's retained article fixtures distinguish DOI segments from the /meta and /pdf views.
    if(url.hostname==='iopscience.iop.org' && path.startsWith('/article/'))path=path.replace(/\/(?:meta|pdf)\/?$/,'').replace(/\/$/,'');
    if(url.hostname==='projecteuclid.org' && path.startsWith('/journals/') && path.endsWith('.full'))path=path.slice(0,-5);
    values.push(path.match(/(?:^|\/)(10\.\d{4,9}\/[^\s]+)$/)?.[1]);
  }catch { /* Malformed escapes cannot prove an article. */ }
  return values.map(validDOI).filter(Boolean);
}
function articleIdentity(target,doc,probe) {
  if(probe?.limited)return {outcome:'unconfirmed',reason:'evidence_limit'};
  if(probe?.multiple)return {outcome:'unconfirmed',reason:'multiple_articles'};
  if(!Array.isArray(probe?.values) || probe.values.length>32 || probe.values.some(value=>typeof value!=='string' || value.length>1024))
    return {outcome:'unconfirmed',reason:'evidence_limit'};
  const values=new Set([...probe.values.map(validDOI).filter(Boolean),...(probe.article || probe.values.some(value=>validDOI(value))?locationDOIs(doc.url):[])]);
  if(values.size>1)return {outcome:'conflict',reason:'multiple_dois'};
  const doi=validDOI(target.doi);
  if(doi) {
    if(!values.size)return {outcome:'unconfirmed',reason:'identity_missing'};
    return values.has(doi)?{outcome:'confirmed',reason:'doi',doi}:{outcome:'conflict',reason:'doi_mismatch'};
  }
  if(target.doi)return {outcome:'not_applicable',reason:'invalid_target'};
  // This relation is supplied by the trusted upstream caller, never inferred from a request URL.
  const established=articleURL(target.confirmed_article_url),current=articleURL(doc.url);
  if(established && current && established.href===current.href)
    return {outcome:'confirmed',reason:'established_article_url'};
  return {outcome:'not_applicable',reason:'identity_missing'};
}
module.exports={validDOI,articleURL,articleIdentity};
