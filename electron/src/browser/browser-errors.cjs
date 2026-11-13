'use strict';
// Fixed diagnostic fields only; raw exceptions and page data never cross the bridge.
class BrowserFailure extends Error {
  constructor(stage, code, status) {
    super(code);
    this.diagnostic = {stage, code};
    if (Number.isInteger(status) && status >= 100 && status <= 599) this.diagnostic.status = status;
  }
}
function checkPage(status, access) {
  const markers=access?.markers;
  if(!markers || access.limited)throw new BrowserFailure('navigation','page_probe_unconfirmed',status);
  if(status===418 || markers.unusualTraffic)throw new BrowserFailure('navigation','site_restricted',418);
  if(markers.contentDenied)throw new BrowserFailure('navigation','content_access_blocked',status);
  if(status===200 && access.imperva) {
    const {edet,incident}=access.imperva;
    const error=new BrowserFailure('navigation',edet===12?'verification_page':'site_restricted',status);
    if(Number.isInteger(edet) && edet>=0 && edet<=999)error.diagnostic.imperva_edet=edet;
    if(typeof incident==='string' && /^[0-9]{1,32}-[0-9]{1,32}$/.test(incident))error.diagnostic.imperva_incident_id=incident;
    throw error;
  }
  if(markers.cloudflareTitle || markers.cloudflareOptions && markers.cloudflareOrchestrator || markers.robot || markers.hcaptcha)
    throw new BrowserFailure('navigation','verification_page',status);
  if(status>=400)throw new BrowserFailure('navigation','http_error',status);
}
function diagnosticFor(error, stage) {
  const diagnostic = error instanceof BrowserFailure ? {...error.diagnostic} : {stage, code:'failed'};
  const netError = String(error?.message || '').match(/\bERR_[A-Z0-9_]+\b/)?.[0];
  if (netError) diagnostic.net_error = netError;
  return diagnostic;
}
module.exports = {BrowserFailure, checkPage, diagnosticFor};
