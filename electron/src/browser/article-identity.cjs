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
  if(typeof value!=='string' || /[\s\x00-\x1f\x7f\\]/.test(value))return null;
  try {
    const url=new URL(value);
    if(!['https:','http:'].includes(url.protocol) || url.username || url.password)return null;
    return url;
  }catch {return null;}
}
module.exports={validDOI,articleURL};
