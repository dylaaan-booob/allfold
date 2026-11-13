'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {THIRD_PARTY_DIR}=require('../shared/paths.cjs');
const source = path.join(THIRD_PARTY_DIR, 'useragent-switcher/v3');

async function configureBrowserIdentity(partition, preloadDirectory, {sessionEvents}={}) {
  if(!sessionEvents)throw Error('Shared Browser Session events required');
  const userAgent = partition.getUserAgent();
  const context = vm.createContext({location: {protocol: 'chrome-extension:'},
    chrome: {declarativeNetRequest: {ResourceType: []}, storage: {local: {get: async prefs => prefs}}}});
  for (const name of ['external/ua-parser.min.js', 'agent.js', 'network.js'])
    vm.runInContext(fs.readFileSync(path.join(source, name), 'utf8'), context, {filename: name});
  const {Agent, Network} = vm.runInContext('({Agent, Network})', context);
  const agent = new Agent();
  await agent.prefs({parser: {}, userAgentData: true, protected: []});
  const payload = JSON.parse(JSON.stringify(agent.parse(userAgent)));
  if (!payload.userAgentDataBuilder) throw Error('Browser identity payload unavailable');
  const names = ['user-agent', 'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform'];
  const operations = JSON.parse(JSON.stringify(new Network().action(payload, 'net').requestHeaders))
    .filter(op => names.includes(op.header.toLowerCase()));
  if (operations.length !== 4 || new Set(operations.map(op => op.header.toLowerCase())).size !== 4
    || operations.some(op => op.operation !== 'set' || typeof op.value !== 'string'))
    throw Error('Browser identity header operations unavailable');

  // Session preload is synchronous, including native popups and subframes.
  // The bridge executes only this fixed script; it exposes no API to the page.
  const preload = `'use strict';
const {contextBridge} = require('electron');
if (!process.sandboxed || !process.contextIsolated) throw Error('Browser identity requires sandbox and context isolation');
if (['http:', 'https:', 'about:'].includes(location.protocol)) contextBridge.executeInMainWorld({func: function(payload, chromiumVersion) {
  // Capture the native capability before the upstream script replaces Navigator's getter.
  const nativeUAData = navigator.userAgentData;
  const nativeGetHighEntropyValues = nativeUAData?.getHighEntropyValues;
  const port = new EventTarget();
  port.dataset = {ready:'true', id:'diagnostic'};
  port.prefs = payload;
  port.ogs = new Map();
  const document = {getElementById: () => port};
${fs.readFileSync(path.join(source, 'data/inject/override.js'), 'utf8')}
  port.dispatchEvent(new CustomEvent('override', {detail:{id:'diagnostic', reason:'browser-identity'}}));
  const data = navigator.userAgentData;
  const prototype = Object.getPrototypeOf(data);
  if (typeof nativeGetHighEntropyValues !== 'function') {
    delete prototype.getHighEntropyValues;
  } else {
    Object.defineProperty(prototype, 'getHighEntropyValues', {configurable: true, writable: true,
      value: function getHighEntropyValues(hints) {
        // Let Chromium validate arguments, receiver and permissions; never fill omitted device fields.
        return Reflect.apply(nativeGetHighEntropyValues, this === data ? nativeUAData : this, arguments).then(values => {
          const result = {...values, brands: data.brands, mobile: data.mobile, platform: data.platform};
          if (values.uaFullVersion) result.uaFullVersion = chromiumVersion;
          if (values.fullVersionList?.length) result.fullVersionList = data.brands.map(({brand, version}) => ({brand,
            version: brand === 'Chromium' || brand === 'Google Chrome' ? chromiumVersion : version + '.0.0.0'}));
          return result;
        });
      }});
  }
}, args:[${JSON.stringify(payload)}, process.versions.chrome]});
`;
  fs.mkdirSync(preloadDirectory, {recursive: true});
  const preloadFile = path.join(preloadDirectory, 'browser-identity-preload.cjs');
  fs.writeFileSync(preloadFile, preload, {mode: 0o600});
  const preloadId = partition.registerPreloadScript({type: 'frame', filePath: preloadFile});
  const headersRegistration=sessionEvents.subscribe('beforeSendHeaders',(details,state) => {
    const https=details.url?.startsWith('https:');
    const requestHeaders = Object.fromEntries(Object.entries(state.requestHeaders)
      .filter(([name]) => !https || !names.includes(name.toLowerCase())));
    if(https)for (const op of operations) requestHeaders[op.header] = op.value;
    return {requestHeaders};
  });
  return {userAgent, headers: Object.fromEntries(operations.map(op => [op.header, op.value])),
    dispose() {
      partition.unregisterPreloadScript(preloadId);
      headersRegistration.dispose();
      fs.rmSync(preloadFile, {force: true});
    }};
}
module.exports = {configureBrowserIdentity};
