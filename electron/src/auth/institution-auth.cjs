'use strict';

// Self-contained: inspect and act only in the captured native main-frame document.
// Inspection returns fixed categories; only authorized consent actions return transient form data to Main.
function institutionAuthPage(action='inspect',credentials=null,expectedStep=null,mode='page') {
  const unacted=action==='act'?{acted:false}:{};
  try {
    const url=new URL(location.href);
    if(window.top!==window || !['http:','https:'].includes(url.protocol) || url.username || url.password)
      return {step:'manual',waiting:true,...unacted};
    const visible=node=>!!node && node.isConnected && node.getClientRects().length>0
      && getComputedStyle(node).visibility!=='hidden' && getComputedStyle(node).display!=='none';
    const usable=node=>visible(node) && !node.disabled && !node.readOnly && node.getAttribute('aria-disabled')!=='true';
    const text=node=>(node?.innerText || node?.textContent || '').replace(/\s+/g,' ').trim();
    const name=node=>[node.getAttribute('aria-label'),node.getAttribute('placeholder'),
      ...[...(node.labels || [])].map(text),
      ...(node.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean).map(id=>text(document.getElementById(id))),
      node.name,node.id].filter(Boolean).join(' ');
    const inputs=[...document.querySelectorAll('input')].filter(visible);
    const controls=[...document.querySelectorAll('button,input[type=submit],input[type=button],a,[role=button]')].filter(visible);
    const caption=node=>[text(node),node.getAttribute('aria-label'),node.tagName==='INPUT'?node.value:''].join(' ').trim();
    const institution=mode==='institution';
    const scope=node=>node.form || node.closest('form,dialog,[role=dialog],fieldset,main,[role=main],section');
    const within=(node,root)=>!!root && (node.form===root || root.contains(node));
    const heading=root=>[root?.getAttribute('aria-label'),
      ...(root?[...root.querySelectorAll('h1,h2,[role=heading],legend')].filter(visible).map(text):[]),
      ...(institution?[document.title]:[])].filter(Boolean).join(' ');
    const positive=(root,pattern)=>controls.filter(node=>within(node,root)
      && pattern.test(caption(node)) && !/拒绝|取消|不同意|reject|deny|cancel|decline/i.test(caption(node)));
    const regions=[...document.querySelectorAll('form,dialog,[role=dialog],fieldset,main,[role=main],section')].filter(visible);
    const passwords=inputs.filter(node=>node.type==='password');
    const loginPattern=/登录|登陆|sign\s*in|log\s*in|提交|submit/i;
    const loginScopes=new Set(passwords.map(scope).filter(Boolean));
    for(const node of inputs)if(['text','email','tel','number'].includes(node.type)
      && (node.autocomplete==='username' || node.type==='email'
        || /用户名|账号|帐号|账户|学号|工号|user.?name|user.?id|account|email|登录名/i.test(name(node)))
      && positive(scope(node),/登录|登陆|sign\s*in|log\s*in/i).length)loginScopes.add(scope(node));
    const messageNodes=[...document.querySelectorAll('[role=alert],[role=status],[aria-live],.error,.errors,.error-message,[class*=error],[id*=Error],[id*=error]')]
      .filter(visible);
    const rejection=/(?:用户名|用户|账号|帐号|账户|学工号|学号|工号|密码|口令).{0,24}(?:错误|不正确|有误|不存在|无效|不匹配)|(?:错误|无效)的?(?:用户名|账号|帐号|账户|密码)|(?:invalid|incorrect|wrong|unknown)\s+(?:(?:user\s*name|user\s*id|account|credentials?|password)|user\s*name\s+or\s+password)|(?:user\s*name|account|password|credentials?).{0,32}(?:incorrect|invalid|not\s+(?:correct|valid|found|recognized)|does\s+not\s+(?:exist|match))/i;
    // A login form can place an error beside an input without an alert role/class.
    const nearby=passwords.flatMap(node=>[...scope(node)?.querySelectorAll('p,span,div') || []])
      .filter(node=>visible(node) && !node.children.length).map(text);
    const rejected=value=>rejection.test(value)
      && !/如果|若|将会|超过.{0,6}次|错误.{0,6}次数|\bif\b|\bwill\b|remaining attempts/i.test(value);
    const loginMessages=messageNodes.filter(node=>[...loginScopes].some(root=>within(node,root)));
    const errorText=loginMessages.map(text).concat(nearby);
    if(errorText.some(rejected))
      return {step:'error',waiting:true,code:'institution_credentials_rejected'};
    const tokens=value=>value.replace(/([A-Z]+)([A-Z][a-z])/g,'$1 $2').replace(/([a-z\d])([A-Z])/g,'$1 $2')
      .replace(/[_\-.]+/g,' ');
    const codePattern=/验证码|动态码|一次性(?:密码|口令|验证码)|\b(?:otp|totp|captcha)\b|\bone\s+time\s+(?:password|passcode|code)\b|\bverification\s+code\b/i;
    const challenge=inputs.some(node=>['text','tel','number','password'].includes(node.type)
      && (node.autocomplete==='one-time-code' || codePattern.test(tokens(name(node)))
        && (institution || loginScopes.has(scope(node))
          || /验证|认证|verification|authenticate|identity/i.test(heading(scope(node)))
            && positive(scope(node),/验证|确认|提交|verify|confirm|submit|continue/i).length)))
      || [...document.querySelectorAll('iframe[src],[class*=captcha],[id*=captcha],[id*=Captcha]')].some(node=>visible(node)
        && (/(?:^|[\/._-])(?:recaptcha|hcaptcha|turnstile)(?:[\/.?_-]|$)/i.test(node.getAttribute('src') || '')
          || node.querySelector('img,canvas,input,iframe')
            && /验证码|滑块|拖动|人机验证|verify (?:that )?you are human|complete (?:the )?captcha/i.test(text(node))))
      || regions.some(root=>/双因素|多因素|二次验证|身份验证|扫码确认|multi[ -]factor authentication|two[ -]factor authentication|verify your identity|\bMFA\b/i.test(heading(root))
        && /(?:approve|confirm).{0,40}(?:sign.in|login|authentication|request)|(?:check|open).{0,30}(?:authenticator|authentication app)|请.{0,20}(?:批准|确认).{0,12}(?:登录|请求)|扫码确认/i.test(text(root)))
      || regions.some(root=>/验证码|人机验证|verify (?:that )?you are human|complete (?:the )?captcha/i.test(heading(root))
        && root.querySelector('img,canvas,input') && positive(root,/验证|确认|继续|verify|confirm|continue/i).length);
    // Some pages reuse error styles for permanent help; styles alone do not establish an error.
    const loginError=inputs.some(node=>loginScopes.has(scope(node)) && node.getAttribute('aria-invalid')==='true')
      || loginMessages.some(node=>text(node) && (node.getAttribute('role')==='alert'
        || /失败|错误|出错|异常|不可用|无法|\b(?:error|failed|failure|unavailable|invalid|incorrect|denied)\b/i.test(text(node))));
    if(challenge || (passwords.length && loginError))return {step:'manual',waiting:true,...unacted};
    const sameForm=(node,form)=>form?node.form===form || form.contains(node):!node.form;
    let step='none',target,username,password,checks=[],radio,consentURL;
    // Reject controls may belong to a separate form, and need not be visible.
    const fields=[...document.querySelectorAll('[name]')];
    const release=fields.some(node=>node.name==='_eventId_AttributeReleaseRejected');
    const terms=fields.some(node=>node.name==='_eventId_TermsRejected');
    if(release || terms) {
      if(release && terms)return {step:'manual',waiting:true,...unacted};
      const buttons=fields.filter(node=>node.name==='_eventId_proceed'
        && ['BUTTON','INPUT'].includes(node.tagName) && node.type==='submit' && node.form);
      if(buttons.length!==1 || !usable(buttons[0]) || buttons[0].matches(':disabled'))
        return {step:'manual',waiting:true,...unacted};
      target=buttons[0];
      const form=target.form;
      consentURL=new URL(target.getAttribute('formaction')===null?form.action:target.formAction,document.baseURI);
      const method=target.getAttribute('formmethod')===null?form.method:target.formMethod;
      const encoding=target.getAttribute('formenctype')===null?form.enctype:target.formEnctype;
      if(!['http:','https:'].includes(consentURL.protocol) || consentURL.origin!==url.origin || consentURL.username || consentURL.password
        || method.toLowerCase()!=='post' || encoding!=='application/x-www-form-urlencoded')
        return {step:'manual',waiting:true,...unacted};
      const elements=[...form.elements];
      if(terms) {
        checks=elements.filter(node=>node.name==='_shib_idp_consentIds' && node.type==='checkbox'
          && (node.required || node.getAttribute('aria-required')==='true'));
        if(!checks.length || checks.some(node=>node.matches(':disabled') || (!node.checked && !usable(node))))
          return {step:'manual',waiting:true,...unacted};
        step='terms';
      } else {
        const options=elements.filter(node=>node.name==='_shib_idp_consentOptions'
          && node.value==='_shib_idp_globalConsent');
        if(options.length>1 || options.some(node=>node.type!=='radio' || !usable(node) || node.matches(':disabled')))
          return {step:'manual',waiting:true,...unacted};
        radio=options[0];step='release';
      }
    } else if(passwords.length) {
      if(passwords.length!==1 || !usable(passwords[0]))return {step:'manual',waiting:true,...unacted};
      password=passwords[0];
      if(password.autocomplete==='new-password')return {step:'manual',waiting:true,...unacted};
      const candidates=inputs.filter(node=>sameForm(node,password.form) && within(node,scope(password)) && usable(node)
        && ['text','email','tel','number'].includes(node.type));
      const named=candidates.filter(node=>node.autocomplete==='username'
        || /用户名|账号|帐号|账户|学号|工号|学工号|user.?name|user.?id|account|email|电子邮箱|登录名/i.test(name(node)));
      const users=named.length?named:candidates;
      const buttons=positive(scope(password),loginPattern);
      if(users.length!==1 || buttons.length!==1)return {step:'manual',waiting:true,...unacted};
      username=users[0];target=buttons[0];step='login';
    } else {
      const switches=controls.filter(node=>/密码登录|密码登陆|账号登录|帐号登录|账户登录|账号密码|password\s+(?:login|sign.in)|(?:use|sign.in.with).{0,15}password/i.test(caption(node))
        && (institution || /登录|登陆|sign\s*in|log\s*in/i.test(heading(scope(node)))));
      // A publisher's optional sign-in entry does not establish a page barrier.
      // Only the authorized institution flow may switch authentication methods.
      if(institution && switches.length===1){step='account';target=switches[0];}
      // A personalization heading is not a login barrier; require a form or explicit QR login.
      else if(loginScopes.size || regions.some(root=>/扫码登录|二维码登录|scan.{0,15}(?:QR|code).{0,15}(?:login|sign.in)/i.test(heading(root))
        && root.querySelector('img,canvas')))
        return {step:'manual',waiting:true,...unacted};
    }
    const state={step,waiting:step!=='none'};
    if(action!=='act')return state;
    if(!institution || step==='none' || step!==expectedStep)return {...state,acted:false};
    if(!visible(target))return {step:'manual',waiting:true,acted:false};
    if(step==='login') {
      if(!credentials)return {...state,acted:false};
      const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
      for(const [input,value] of [[username,credentials.username],[password,credentials.password]]) {
        if(!usable(input))return {step:'manual',waiting:true};
        input.focus();setter.call(input,value);
        input.dispatchEvent(new Event('input',{bubbles:true}));
        input.dispatchEvent(new Event('change',{bubbles:true}));input.blur();
      }
    } else if(step==='terms' || step==='release') {
      for(const node of checks)node.checked=true;
      if(radio)radio.checked=true;
      const data=new FormData(target.form,target);
      if([...data.values()].some(value=>typeof value!=='string'))return {step:'manual',waiting:true};
      return {...state,submission:{url:consentURL.href,body:new URLSearchParams(data).toString(),referrer:url.href}};
    }
    if(!usable(target))return {step:'manual',waiting:true,...(step==='account'?unacted:{})};
    target.click();
    return {...state,acted:true};
  } catch (_) {return {step:'manual',waiting:true,code:'auth_execution_failed'};}
}
module.exports={institutionAuthPage};
