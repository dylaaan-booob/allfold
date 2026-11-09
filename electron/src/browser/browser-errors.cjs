'use strict';
// Fixed diagnostic fields only; raw exceptions and page data never cross the bridge.
class BrowserFailure extends Error {
  constructor(stage, code, status) {
    super(code);
    this.diagnostic = {stage, code};
    if (Number.isInteger(status) && status >= 100 && status <= 599) this.diagnostic.status = status;
  }
}
function checkPage(status, title, html) {
  if (status === 418 || /Unusual Traffic Detected\s*\(Error 418\)/i.test(title))
    throw new BrowserFailure('navigation', 'site_restricted', 418);
  if (/\bCPE00001\b/.test(html) && /There was a problem providing the content you requested/i.test(html))
    throw new BrowserFailure('navigation', 'content_access_blocked', status);
  // Imperva can serve an access-denial document with an HTTP 200 status.
  if (status === 200 && /_Incapsula_Resource/.test(html)) {
    const frameShell = /<body\b[^>]*>((?:\s*<iframe\b[^>]*>[^<]*<\/iframe>)+)\s*<\/body>/i.exec(html);
    const deniedFrame = /<iframe\b[^>]*\ssrc\s*=\s*(["'])\/_Incapsula_Resource(?:\?([^"']*))?\1[^>]*>\s*Request unsuccessful\.\s*Incapsula incident ID:\s*([0-9]{1,32}-[0-9]{1,32}(?=\s|<|$))?/i;
    const denied = frameShell && deniedFrame.exec(frameShell[1]);
    if (denied) {
      const [, , query, displayed] = denied;
      const params = new URLSearchParams(query?.replace(/&amp;/gi, '&'));
      const codes = params.getAll('edet');
      const edet = codes.length === 1 && /^[0-9]{1,3}$/.test(codes[0]) ? Number(codes[0]) : undefined;
      const ids = params.getAll('incident_id');
      const incident = ids.length ? ids[0] : displayed;
      // Imperva's CAPTCHA is interactive even though the outer document says "Request unsuccessful".
      const failure = new BrowserFailure('navigation', edet === 12 ? 'verification_page' : 'site_restricted', status);
      if (edet !== undefined) failure.diagnostic.imperva_edet = edet;
      if (ids.length <= 1 && /^[0-9]{1,32}-[0-9]{1,32}$/.test(incident)
          && (!displayed || displayed === incident)) failure.diagnostic.imperva_incident_id = incident;
      throw failure;
    }
  }
  // A localized challenge document has both page options and its challenge-page orchestrator.
  const cloudflareDocument = /\b_cf_chl_opt\s*=\s*\{/.test(html)
    && /\/cdn-cgi\/challenge-platform\/[^\s"'<>]*orchestrate\/chl_page\//i.test(html);
  if (/^(Just a moment|Attention Required)/i.test(title)
    || cloudflareDocument
    || /Are you a robot\?/.test(html) && /Please confirm you are a human by completing the captcha challenge/i.test(html))
    throw new BrowserFailure('navigation', 'verification_page', status);
  if (status >= 400) throw new BrowserFailure('navigation', 'http_error', status);
}
function diagnosticFor(error, stage) {
  const diagnostic = error instanceof BrowserFailure ? {...error.diagnostic} : {stage, code:'failed'};
  const netError = String(error?.message || '').match(/\bERR_[A-Z0-9_]+\b/)?.[0];
  if (netError) diagnostic.net_error = netError;
  return diagnostic;
}
module.exports = {BrowserFailure, checkPage, diagnosticFor};
