'use strict';
// Select through CARSI's own autocomplete so its handler owns the Entity ID and form submission.
function institutionPageAction(action,name,expiresAt) {
  if(window.top!==window || location.origin!=='https://ds.carsi.edu.cn' || location.pathname!=='/login/index.html')
    return {status:'unverified'};
  const visible=el=>!!el && el.getClientRects().length>0 && getComputedStyle(el).visibility!=='hidden';
  if([...document.querySelectorAll('.pop-mod.x-show')].some(visible))return {status:'manual'};
  if([...document.querySelectorAll('.loading-unit')].some(visible))return {status:'busy'};
  const form=document.querySelector('#idpForm'),input=form?.querySelector('input#show');
  const entity=form?.querySelector('input#hid-inp'),button=form?.querySelector('#idpSkipButton');
  if(!form || !visible(input) || !entity || !visible(button) || input.disabled || button.disabled)
    return {status:'pending',dispatched:false};
  const target=new URL(form.action,location.href);
  if(target.origin!=='https://ds.carsi.edu.cn' || target.pathname!=='/Shibboleth.sso/Login'
    || target.username || target.password || form.method.toLowerCase()!=='post')return {status:'unverified'};
  if(action==='state')return {status:'ready'};
  if(Date.now()>=expiresAt)return {status:'expired',dispatched:false};
  if(action==='fill') {
    entity.value='';
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,name);
    input.focus();input.dispatchEvent(new Event('input',{bubbles:true}));
    input.dispatchEvent(new Event('change',{bubbles:true}));
    return {status:'filled'};
  }
  if(action!=='select' || input.value!==name)return {status:'unverified'};
  const normalize=value=>value.trim().replace(/\s+/g,' ').toLowerCase();
  const matches=[...input.parentElement.querySelectorAll('ul.typeahead li')].filter(visible).filter(li=>{
    const label=li.textContent.trim(),parts=label.match(/^(.*)（(.*)）$/);
    return [label,...(parts?parts.slice(1):[])].some(value=>normalize(value)===normalize(name));
  });
  if(!matches.length)return {status:'missing',dispatched:false};
  if(matches.length!==1)return {status:'ambiguous',dispatched:false};
  const item=matches[0],link=item.querySelector('a');
  if(!link)return {status:'unverified',dispatched:false};
  // The plugin submits its active item, rather than the item receiving click.
  item.dispatchEvent(new MouseEvent('mouseover',{bubbles:true}));
  if(!item.classList.contains('active'))return {status:'unverified'};
  link.click();
  if(!entity.value || normalize(input.value)!==normalize(item.textContent))return {status:'unverified'};
  button.click();
  return {status:'submitted',dispatched:true};
}
// Project-owned DOM actions retained from the Connector executors. AGPLv3-or-later.
function resourcePageAction(action, name, query = name, token, expiresAt) {
  const key = '__allfoldCARSIRefresh';
  const previous = globalThis[key];
  if (action === 'cleanup') {
    if (previous?.token === token) previous.dispose();
    return {status: 'cleaned'};
  }
  if (location.origin !== 'https://ds.carsi.edu.cn' || location.pathname !== '/resource/resource.php')
    return {status: 'failed', code: 'document_changed'};
  const jq = window.jQuery;
  const visible = el => !!el?.isConnected && el.getClientRects().length > 0
    && getComputedStyle(el).visibility !== 'hidden' && Number(getComputedStyle(el).opacity) > 0;
  const usable = el => visible(el) && !el.disabled && !el.readOnly && el.getAttribute('aria-disabled') !== 'true';
  const inputs = [...document.querySelectorAll('input#searchKey.searchInput')].filter(usable);
  const buttons = [...document.querySelectorAll('button.Btn1.searBtn')].filter(usable);
  const schools = [...document.querySelectorAll('input[type="checkbox"]#onlyMySchool[name="onlyMySchool"]')].filter(usable);
  const input = inputs[0], button = buttons[0], school = schools[0];
  const ready = () => document.readyState === 'complete'
    && inputs.length === 1 && buttons.length === 1 && schools.length === 1
    && typeof school.checked === 'boolean' && usable(input) && usable(button) && usable(school)
    && typeof jq === 'function' && typeof jq.fn?.on === 'function' && typeof jq.fn?.off === 'function'
    && ![...document.querySelectorAll('.x-container.shade')].some(visible)
    && ![...document.querySelectorAll('.loading-unit')].some(visible);
  const select = state => {
    if (state.matches.size > 1) return {status: 'ambiguous'};
    if (!state.matches.size) return {status: 'missing'};
    try {
      const record = state.matches.values().next().value;
      if (typeof record.wayfless !== 'string' || !record.wayfless) return {status: 'unverified'};
      const target = new URL(record.wayfless, location.href);
      if (target.origin !== 'https://ds.carsi.edu.cn' || target.pathname !== '/resource/resourceDetail.php'
        || target.username || target.password || target.hash) return {status: 'unverified'};
      return {status: 'selected', url: target.href};
    } catch (_) {return {status: 'unverified'};}
  };
  if (action === 'ready') return {status: ready() ? 'ready' : 'pending', checked: school?.checked};
  if (action === 'poll') {
    if (!previous || previous.token !== token) return {status: 'failed', code: 'refresh_unconfirmed'};
    if (previous.error) return {status: 'failed', code: previous.error};
    if (previous.seen && previous.pending.size === 0 && ready()) {
      if (school.checked || input.value !== previous.query || document.querySelector('#isShowAll')?.value !== 'y')
        return {status: 'failed', code: 'refresh_unconfirmed'};
      return {status: 'complete', ...(previous.search ? {selection: select(previous)} : {})};
    }
    return {status: 'pending'};
  }
  if (!['filter', 'search'].includes(action) || previous || !ready() || Date.now() >= expiresAt)
    return {status: 'failed', code: 'controls_unavailable'};
  if (action === 'search') {
    if (school.checked) return {status: 'failed', code: 'controls_unavailable'};
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, query);
    if (input.value !== query) return {status: 'failed', code: 'controls_unavailable'};
  }
  const expectedQuery = input.value;
  const namespace = '.lmCARSI' + token;
  const state = {token, query: expectedQuery, search: action === 'search', seen: false,
    pending: new Map(), matches: new Map(), error: null, timer: null};
  state.dispose = () => {
    jq(document).off(namespace);
    state.pending.clear();state.matches.clear();
    clearTimeout(state.timer);
    window.removeEventListener('pagehide', state.dispose);
    if (globalThis[key]?.token === token) delete globalThis[key];
  };
  globalThis[key] = state;
  const expired = xhr => {
    try {
      const url = new URL(state.pending.get(xhr)?.native?.responseURL || xhr.responseURL);
      return url.origin === 'https://ds.carsi.edu.cn' && !url.username && !url.password
        && url.pathname === '/login/index.html';
    } catch (_) {return false;}
  };
  try {
    // Bind only the site's own native request; response records own resource identity.
    jq(document).on('ajaxSend' + namespace, (_event, xhr, settings) => {
      let url;
      try {url = new URL(settings.url, location.href);} catch (_) {return;}
      if (url.origin !== location.origin || url.pathname !== '/resource/getResource.php') return;
      if ((settings.type || 'GET').toUpperCase() !== 'GET'
        || url.searchParams.get('searchKey') !== expectedQuery || url.searchParams.get('isShowAll') !== 'y') {
        return;
      }
      state.seen = true;
      const request = {succeeded: false, native: null};
      state.pending.set(xhr, request);
      // jqXHR may omit responseURL; capture only this matched request's native XHR.
      const createXHR = settings.xhr || jq.ajaxSettings?.xhr;
      if (typeof createXHR === 'function') settings.xhr = function (...args) {
        request.native = createXHR.apply(this, args);
        return request.native;
      };
    });
    jq(document).on('ajaxSuccess' + namespace, (_event, xhr, _settings, data) => {
      if (!state.pending.has(xhr)) return;
      if (expired(xhr)) {state.error = 'carsi_session_expired';return;}
      try {
        if (!Array.isArray(data)) throw Error('Invalid resource response');
        if (state.search) {
          for (const item of data) {
            // The envelope also contains filter objects and JSON-encoded count strings.
            if (!item || typeof item !== 'object' || !Object.hasOwn(item, 'res')) continue;
            if (!Array.isArray(item.res)) throw Error('Invalid resource list');
            for (const encoded of item.res) {
              if (typeof encoded !== 'string') throw Error('Invalid resource record');
              const record = JSON.parse(encoded);
              if (!record || typeof record.id !== 'string' || !record.id || typeof record.name !== 'string')
                throw Error('Invalid resource record');
              if (record.name === name) state.matches.set(record.id, record);
            }
          }
        }
        state.pending.get(xhr).succeeded = true;
      } catch (_) {state.error ||= 'resource_request_failed';}
    });
    jq(document).on('ajaxError' + namespace, (_event, xhr) => {
      if (state.pending.has(xhr)) {
        if (expired(xhr)) state.error = 'carsi_session_expired';
        else state.error ||= 'resource_request_failed';
      }
    });
    jq(document).on('ajaxComplete' + namespace, (_event, xhr) => {
      if (!state.pending.has(xhr)) return;
      if (expired(xhr)) state.error = 'carsi_session_expired';
      else if (!state.pending.get(xhr).succeeded) state.error ||= 'resource_request_failed';
      state.pending.delete(xhr);
    });
    window.addEventListener('pagehide', state.dispose, {once: true});
    state.timer = setTimeout(state.dispose, Math.max(0, expiresAt - Date.now()));
    if (action === 'filter') {
      if (!school.checked) {state.dispose();return {status: 'failed', code: 'controls_unavailable'};}
      school.click();
    } else button.click();
    if (school.checked || input.value !== expectedQuery || document.querySelector('#isShowAll')?.value !== 'y')
      state.error = 'controls_unavailable';
    return {status: 'pending'};
  } catch (_) {
    state.dispose();
    return {status: 'failed', code: 'controls_unavailable'};
  }
}

function detailPageAction(action,expiresAt) {
  if (location.origin !== 'https://ds.carsi.edu.cn'
    || location.pathname !== '/resource/resourceDetail.php') return {status: 'unverified'};
  const controls = [...document.querySelectorAll('a[href]')].filter(link => {
    const style = getComputedStyle(link);
    return link.getClientRects().length > 0 && style.visibility !== 'hidden' && Number(style.opacity) > 0
      && !link.disabled && link.getAttribute('aria-disabled') !== 'true' && style.pointerEvents !== 'none'
      && (link.innerText || '').replace(/^[\s\u00a0]+|[\s\u00a0]+$/g, '') === '访问资源'
      && /^javascript:gotoResource\(.+\)\s*;?$/.test(link.getAttribute('href') || '');
  });
  if (!controls.length) return {status: 'pending'};
  if (controls.length !== 1) return {status: 'unverified'};
  if (Date.now() >= expiresAt) return {status: 'unverified'};
  if (action === 'visit') controls[0].click();
  return {status: action === 'visit' ? 'visited_click' : 'ready'};
}

    function imagePageAction() {
        if (document.readyState === "loading") return {ready: false};
        const main = document.querySelector('main, [role="main"]');
        if (!main) return {ready: false};
        const first = [...main.querySelectorAll("img")].find(image => {
            if (!image.getClientRects().length) return false;
            const link = image.closest("a[href]");
            return image.closest('[role="button"]') || (link && new URL(link.href, location.href).pathname === "/imgres");
        });
        if (!first) return {ready: false};
        const thumbnail = first.currentSrc || first.src;
        const holder = first.closest("[data-docid], [jsdata]");
        const resultID = holder?.getAttribute("data-docid") || holder?.getAttribute("jsdata")?.split(";")[1];
        const records = [];
        // Google encodes URL strings as JSON strings in thumbnail/original pairs.
        const pattern = /"([-\w]+)",\s*\["((?:[^"\\]|\\.)+)",\s*\d+,\s*\d+\],\s*\["((?:[^"\\]|\\.)+)",\s*\d+,\s*\d+\]/g;
        for (const script of document.scripts) {
            for (const match of script.textContent.matchAll(pattern)) {
                records.push({id: match[1], thumbnail: JSON.parse(`"${match[2]}"`), original: JSON.parse(`"${match[3]}"`)});
            }
        }
        const link = first.closest("a[href]");
        const record = resultID ? records.find(item => item.id === resultID) : records.find(item => item.thumbnail === thumbnail);
        const original = link && new URL(link.href, location.href).searchParams.get("imgurl") || record?.original;
        try {
            const url = new URL(original);
            if (!["http:", "https:"].includes(url.protocol) || url.username || url.password
                || url.href === thumbnail || /(^|\.)encrypted-tbn\d*\.(?:gstatic|google)\.com$/.test(url.hostname)) return {ready: true, source_url: null};
            return {ready: true, source_url: url.href};
        } catch (_) { return {ready: true, source_url: null}; }
    }

    const SELECTORS = Object.freeze({
        query: 'textarea#advancedSearchInputArea', search: 'button[data-ta="run-search"]',
        count: '[data-ta="search-info"][data-ta-search-info-count]',
        exportMenu: 'button#export-trigger-btn', plainText: 'button#exportToFieldTaggedButton',
        dialog: 'app-export-out-details',
        range: 'input[name="outputMethodType"][value="fromRange"]',
        first: 'input[name="markFrom"]', last: 'input[name="markTo"]',
        content: '#option-authorTitleSourceAbstract', export: 'button#exportButton'
    });
    // Every page mutation is synchronous and checks a short action deadline, not an ownership lease.
    // No timer or observer is allowed to dispatch clicks after this call returns.
    function pageStep(op, args, selectors, expiresAt) {
        const visible = el => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
        const nodes = (selector, root = document) => [...root.querySelectorAll(selector)].filter(visible);
        const one = (selector, root = document) => {
            const found = nodes(selector, root);
            if (found.length !== 1) throw new Error('control_not_unique');
            return found[0];
        };
        const writable = el => {
            if (Date.now() >= expiresAt) throw new Error('action_expired');
            if (el.disabled || el.getAttribute('aria-disabled') === 'true' || el.readOnly) throw new Error('control_disabled');
            return el;
        };
        const click = el => writable(el).click();
        const set = (el, value) => {
            writable(el);
            const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, String(value));
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            if (el.value !== String(value) || el.validity && !el.validity.valid) throw new Error('input_value_mismatch');
        };
        const dialog = () => one(selectors.dialog);
        const key = '__allfoldWoSDownload';
        try {
            if (op === 'cleanup') {
                const state = globalThis[key];
                if (state?.token === args.token) state.cleanup();
                return {ok: true};
            }
            if (document.body?.innerText.includes('Server.unexpectedError'))
                throw new Error('server_unexpected_error');
            const notices = nodes('app-captcha-details, [role="dialog"], [role="alert"]');
            const verification = notices.some(el => /verify (?:that )?you are human|verification required|complete.*captcha|验证码|人机验证|安全验证/i.test(el.innerText || ''))
                    || nodes('iframe[src*="recaptcha"], iframe[src*="hcaptcha"]').length > 0;
            if (op === 'verification') return {ready: !verification};
            if (verification) throw new Error('verification_required');
            // Database selection constrains business actions, not challenge checks or cleanup.
            if (!location.pathname.startsWith('/wos/woscc/')) throw new Error('core_collection_unverified');
            if (op === 'ready') return {ready: nodes(selectors.query).length === 1 && nodes(selectors.search).length === 1};
            if (op === 'search') {
                if (nodes(selectors.count).length) throw new Error('stale_search_results');
                set(one(selectors.query), args.query);
                click(one(selectors.search));
                return {submitted: true};
            }
            if (op === 'result') {
                const count = nodes(selectors.count);
                if (count.length !== 1 || nodes('[aria-busy="true"], [role="progressbar"]').length) return {ready: false};
                if (!location.pathname.startsWith('/wos/woscc/summary/')) return {ready: false};
                const raw = count[0].getAttribute('data-ta-search-info-count');
                if (!/^\d+(?:[,\s]\d{3})*$/.test(raw || '')) return {ready: false};
                const total = Number(raw.replace(/[,\s]/g, ''));
                return {ready: Number.isSafeInteger(total), total};
            }
            if (op === 'controlReady') return {ready: nodes(selectors[args.control]).length === 1};
            if (op === 'contentReady') return {ready: nodes(selectors.content).length === 1};
            if (op === 'selectContent') {click(one(selectors.content)); return {ok: true};}
            if (op === 'exportMenu') {click(one(selectors.exportMenu)); return {ok: true};}
            if (op === 'plainText') {click(one(selectors.plainText)); return {ok: true};}
            if (op === 'dialog') {
                const dialogs = nodes(selectors.dialog);
                if (dialogs.length !== 1) return {ready: false};
                const end = nodes(selectors.last, dialogs[0]);
                if (end.length !== 1) return {ready: false};
                const max = Number(end[0].getAttribute('max'));
                return {ready: true, limit: Number.isSafeInteger(max) && max > 0 ? Math.min(max, 1000) : 1000};
            }
            if (op === 'configure') {
                const root = dialog();
                const radios = [...root.querySelectorAll(selectors.range)];
                if (radios.length !== 1) throw new Error('control_not_unique');
                const radio = radios[0];
                const label = radio.labels && [...radio.labels].find(visible);
                click(visible(radio) ? radio : label || one(selectors.range, root));
                if (!radio.checked) throw new Error('export_range_unverified');
                set(one(selectors.first, root), args.first);
                set(one(selectors.last, root), args.last);
                click(one('[role="combobox"]', root));
                return {ok: true};
            }
            if (op === 'arm') {
                if (globalThis[key]) throw new Error('download_observer_busy');
                const state = {token: args.token, urls: [], content: null};
                const proto = HTMLAnchorElement.prototype;
                const original = proto.click;
                const observe = anchor => {
                    if (anchor && typeof anchor.href === 'string' && anchor.href && !state.urls.includes(anchor.href))
                        state.urls.push(anchor.href);
                };
                const listener = event => observe(event.target.closest?.('a[href]'));
                const wrapped = function (...values) {observe(this); return original.apply(this, values);};
                state.cleanup = () => {
                    document.removeEventListener('click', listener, true);
                    if (proto.click === wrapped) proto.click = original;
                    if (globalThis[key] === state) delete globalThis[key];
                };
                if (Date.now() >= expiresAt) throw new Error('action_expired');
                proto.click = wrapped;
                document.addEventListener('click', listener, true);
                globalThis[key] = state;
                return {ok: true};
            }
            if (op === 'export') {
                const root = dialog();
                if (!one(selectors.range, root).checked || one(selectors.first, root).value !== String(args.first)
                        || one(selectors.last, root).value !== String(args.last)) throw new Error('export_range_unverified');
                // Angular material exposes the selected option through its combobox.
                const content = document.querySelector(selectors.content);
                const selected = content?.getAttribute('aria-selected') === 'true';
                const values = nodes('[role="combobox"]', root).map(el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim());
                if (!selected && !values.some(value => value === 'Author, Title, Source, Abstract'))
                    throw new Error('export_content_unverified');
                click(one(selectors.export, root));
                return {ok: true};
            }
            if (op === 'links') {
                const state = globalThis[key];
                return {urls: state?.token === args.token ? [...state.urls] : []};
            }
            throw new Error('unknown_dom_step');
        } catch (error) {
            return {error: /^[a-z_]+$/.test(error.message) ? error.message : 'dom_step_failed'};
        }
    }


module.exports={institutionPageAction,resourcePageAction,detailPageAction,imagePageAction,pageStep,SELECTORS};
