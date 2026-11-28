'use strict';

const XMU_IDP='https://idp.xmu.edu.cn/idp/shibboleth';

function matchesXmuSchool(institution) {
  if(!institution)return false;
  const {institution_name:name,idp_entity_id:entity}=institution;
  if(name && !['厦门大学','xiamen university'].includes(name.toLocaleLowerCase('en-US')))return false;
  return entity ? entity===XMU_IDP : !!name;
}

function xmuLoginContext(institution,value) {
  if(!matchesXmuSchool(institution) || !URL.canParse(value))return false;
  const url=new URL(value);
  return !url.username && !url.password && (
    url.origin==='https://ids.xmu.edu.cn' && /^\/authserver\/login\/?$/.test(url.pathname)
    || url.origin==='https://idp.xmu.edu.cn' && url.pathname.startsWith('/idp/profile/')
  );
}

function secureXmuLoginURL(institution,value) {
  if(!URL.canParse(value))return;
  const url=new URL(value);
  if(url.origin!=='http://ids.xmu.edu.cn')return;
  url.protocol='https:';
  if(xmuLoginContext(institution,url.href))return url.href;
}

module.exports={matchesXmuSchool,xmuLoginContext,secureXmuLoginURL};
