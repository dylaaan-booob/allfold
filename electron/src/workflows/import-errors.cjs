'use strict';
// Compatibility entry point: old callers and new code must share constructor identity.
const {BrowserFailure:ImportFailure,checkPage,diagnosticFor}=require('../browser/browser-errors.cjs');
function failedImport(error, stage, saving) {
  return {parent:{outcome:saving?'uncertain':'no_effect'},pdf:{outcome:'unverified'},settled:true,
    diagnostic:diagnosticFor(error,stage)};
}
module.exports={ImportFailure,checkPage,failedImport};
