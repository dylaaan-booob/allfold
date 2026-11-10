// RhinE / RhineLabUI MIT adaptation; see SOURCES.md and licenses/.
import {createAutosave} from './settings-autosave.js';
import {renderRunResult} from './run-results.js';
import {readImportChoices,renderImportRows} from './research-scope-import.js';
import {providerNames as providerDefaults} from './business-results.js';
import {resetImpact} from './history-view.js';
const keyMask='••••••••';
const root=document.getElementById('configuration-workspace');
const markup=document.createElement('template');
markup.innerHTML=`<header class="s-header">
<div class="s-header-actions">
<span id="s-dirty" class="s-dirty">Saved baseline</span>
<button id="s-undo" class="s-button" disabled>UNDO</button>
<button id="s-autosave-retry" class="s-button" hidden>Retry</button><button id="s-autosave-reconcile" class="s-button" hidden>Review saved state</button>
</div>
</header>
<p id="s-message" class="s-message" role="status" aria-live="polite" hidden>
</p>
<div class="s-content">
<section id="s-settings" class="s-panel s-settings-grid" hidden aria-labelledby="settings-open">
<div class="s-settings-main">
<fieldset class="s-setting-group">
<legend>Monitor</legend>
<label class="s-setting-row" data-field="name">
<span class="s-setting-label">Monitor Name</span>
<input type="text" data-monitor="name" >
</label>
</fieldset>
<fieldset class="s-setting-group">
<legend>Workflow</legend>
<label class="s-setting-row s-field-wide" data-field="workspace">
<span class="s-setting-label">Output Workspace</span>
<input type="text" data-monitor="workspace" >
</label>
<label class="s-setting-row" data-field="log">
<span class="s-setting-label">Log Level</span>
<select data-monitor="log">
<option>DEBUG</option>
<option>INFO</option>
<option>WARNING</option>
<option>ERROR</option>
</select>
</label>
<p id="s-log-help" class="s-help s-field-wide">级别修改后重启应用生效；运行记录与关键结果始终保留。</p>
</fieldset>
<fieldset id="s-institution" class="s-setting-group">
<legend>Institution</legend>
<label class="s-setting-row s-field-wide" data-field="institutionName">
<span class="s-setting-label">Institution</span>
<input id="s-institution-query" type="text" data-monitor="institutionName" autocomplete="off" placeholder="输入中文或英文名称后选择机构" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="s-institutions" aria-describedby="s-institution-help">
</label>
<div id="s-institution-popup" popover="manual"><div id="s-institutions" role="listbox" aria-label="机构搜索结果"></div><p id="s-institution-results" role="status"></p></div>
<label class="s-setting-row s-field-wide" data-field="idp">
<span class="s-setting-label">Public IdP Entity ID</span>
<input type="text" data-monitor="idp" readonly>
</label>
<label class="s-setting-row s-check s-field-wide" data-field="useShibboleth">
<input type="checkbox" data-monitor="useShibboleth">
<span class="s-setting-label">Use Shibboleth Login</span>
</label>
<p class="s-help s-field-wide">默认使用 CARSI 机构检索；勾选后优先使用 Shibboleth，失败时回退机构检索一次。</p>
<p id="s-institution-help" class="s-help s-field-wide" role="status">正在加载本地机构名录。</p>
</fieldset>
<fieldset id="s-institution-auth" class="s-setting-group" hidden>
<legend>机构认证自动登录</legend>
<label class="s-setting-row s-field-wide">
<span class="s-setting-label">用户名</span>
<input id="s-cas-username" type="text" autocomplete="off" spellcheck="false">
</label>
<label class="s-setting-row s-field-wide">
<span class="s-setting-label">密码</span>
<input id="s-cas-password" type="password" autocomplete="new-password" aria-describedby="s-cas-status">
</label>
<p id="s-cas-status" class="s-help" role="status" aria-live="polite" hidden></p>
</fieldset>
</div>
<aside class="s-system-sidebar" aria-label="System">
<section id="s-system" class="s-system" aria-label="System">
<div class="s-system-intro">
<h2 class="s-system-title">System</h2>
<div class="s-files">
<button id="s-files" class="s-button" aria-expanded="false" aria-controls="s-file-menu">FILES ↓</button>
<div id="s-file-menu" class="s-file-menu" popover="auto" aria-label="Files">
<button data-file-action="import">Import Research Scope</button>
<button data-file-action="export">Export User Data</button>

<button data-file-action="reload">Reload Settings from Disk</button>
</div>
</div>
</div>
<label class="s-setting-row s-check s-field-wide">
<input id="s-developer-mode" type="checkbox">
<span class="s-setting-label">Developer Mode</span>
</label>
<p class="s-help">Developer Mode 默认关闭，控制 Layout、Archive 和 Paper 调试工具；关闭后，已保存的布局目标仍然生效。此开关独立保存在本浏览器，独立于 YAML 配置。</p>
<label class="s-setting-row s-check s-field-wide">
<input id="s-disable-archive" type="checkbox">
<span class="s-setting-label">禁用 Archive 视图</span>
</label>
<p class="s-help">Workspace 使用 ARRAY；活动操作结束后再切换布局。此本地偏好立即生效。</p>
<label class="s-setting-row s-check s-field-wide">
<input id="s-disable-fullscreen" type="checkbox">
<span class="s-setting-label">禁用全屏运行界面</span>
</label>
<p class="s-help">Discover 在 Workflows 中显示进度。设置对下次任务生效。</p>
      <details>
<summary>Zotero Integration</summary>
<div class="s-diagnostic">
<p id="s-zotero-result">Not checked. Electron 与 Desktop 状态未检查。</p>
<button data-diagnostic="zotero" class="s-button">Refresh</button>
</div>
</details>
      <details>
<summary>Workspace Health</summary>
<div class="s-diagnostic">
<p id="s-health-result">Not checked. 使用已保存路径。</p>
<button data-diagnostic="health" class="s-button">Refresh</button>
</div>
</details>
      <details>
<summary>Diagnostics</summary>
<div class="s-diagnostic">
<p class="s-help">导出当前配置中保留的最近诊断，不含网页正文、凭据或 Workspace 文件。仅在本地下载，不自动上传。</p>
<button id="s-export-diagnostics" class="s-button" type="button">导出最近诊断</button>
<p id="s-export-diagnostics-status" class="s-help" role="status"></p>
</div>
</details>
      <div class="s-reset">
<div>
<span class="s-eyebrow">RESET / SEPARATE ACTION</span>
<h2>Reset</h2>
<code id="s-reset-path">
</code>
</div>
<div class="s-reset-confirm">
<label>范围<select id="s-reset-scope"><option value="workspace">Workspace</option><option value="logs">Logs</option></select></label>
<div class="s-actions">
<button id="s-reset-cancel" class="s-button">Cancel</button>
<button id="s-reset-workspace" class="s-button s-primary" disabled>CONFIRM RESET ↗</button>
</div>
<p id="s-reset-result" class="s-help" role="status">尚未执行 Reset。</p>
</div>
</div>
    </section>
</aside>
</section>
<section id="s-run" class="s-panel s-editor-grid" hidden aria-labelledby="run-open">
<aside class="s-directory" aria-label="Run Database">
<div class="s-directory-heading"><span>DATABASE</span><div class="s-directory-order"><button class="s-button" disabled aria-label="New Provider unavailable" title="New Provider unavailable">+</button><button id="s-provider-up" class="s-button" aria-label="Move Provider up">↑</button><button id="s-provider-down" class="s-button" aria-label="Move Provider down">↓</button></div></div>
<div id="s-providers" class="s-directory-list">
</div>
<div class="s-directory-tools">
<div class="s-actions">
<button class="s-button" disabled>Delete</button>
</div>
</div>
</aside>
<div class="s-browser">
<div class="s-browser-head s-run-head">
<h2 id="s-run-title">Overview</h2>
<button id="s-provider-run" class="s-button" disabled hidden>RUN ↗</button>
</div>
<div class="s-run-body">
<div id="s-run-overview">
<fieldset class="s-setting-group" aria-label="Search configuration">
<label class="s-setting-row s-field-wide" data-field="expression">
<textarea data-monitor="expression" rows="5" spellcheck="false" aria-label="Keyword expression">
</textarea>
<span class="s-help">AND / OR、括号、精确短语 &quot;…&quot;、词尾 *（至少 4 字符）；不支持 NOT 或邻近查询。</span>
</label>
<label class="s-setting-row" data-field="from">
<span class="s-setting-label">Start Month</span>
<input type="month" data-monitor="from" >
</label>
<label class="s-setting-row" data-field="to">
<span class="s-setting-label">End Month</span>
<input type="month" data-monitor="to" >
</label>
</fieldset>
<div id="s-run-operations" class="s-run-operations">
</div>
</div>
<div id="s-run-provider" hidden>
<div class="s-run-query">
<span class="s-eyebrow">SEARCH EXPRESSION / READ ONLY</span>
<pre id="s-run-expression" aria-live="polite">
</pre>
<p id="s-run-expression-error" class="s-field-error" role="status">
</p>
</div>
<fieldset data-provider-settings="pubmed" class="s-setting-group" aria-label="PubMed settings" hidden>
<label class="s-setting-row" data-field="pubmedKey">
<span class="s-setting-label">API Key</span>
<input type="password" data-monitor="pubmedKey" autocomplete="new-password" spellcheck="false">
</label>
<p id="s-pubmed-key-status" class="s-help">
</p>
</fieldset>
<fieldset data-provider-settings="openalex" class="s-setting-group" aria-label="OpenAlex settings" hidden>
<label class="s-setting-row" data-field="openalexKey">
<span class="s-setting-label">API Key</span>
<input type="password" data-monitor="openalexKey" autocomplete="new-password" spellcheck="false">
</label>
<p id="s-openalex-key-status" class="s-help">
</p>
</fieldset>
<fieldset data-provider-settings="europe_pmc" class="s-setting-group" aria-label="Europe PMC role" hidden><p class="s-help">Europe PMC 仅按已确认的正式 PMID 定向补全 PPR 关联；不执行期刊 Discovery。</p></fieldset>
<fieldset data-provider-settings="crossref" class="s-setting-group" aria-label="Crossref settings" hidden>
<label class="s-setting-row" data-field="crossrefMailto">
<span class="s-setting-label">Contact Email</span>
<input type="email" data-monitor="crossrefMailto" >
</label>
</fieldset>

</div>
</div>
</div>
<aside class="s-context" aria-label="Run Context">
<label class="s-provider-alias" hidden><span class="s-context-title">DATABASE NAME</span><input id="s-provider-alias" maxlength="120" autocomplete="off"></label>
<div class="s-context-title">LAST RUN</div>
<div id="s-run-records">
</div>
<p id="s-run-feedback" class="s-help" role="status" aria-live="polite">
</p>
<button id="s-run-retry" class="s-button" hidden>Retry Inbox refresh</button>
<button id="s-run-refresh" class="s-button">Refresh</button>
</aside>
</section>
<section id="s-journals-page" class="s-panel workbench-layout" aria-labelledby="journals-open" hidden>
<nav class="navigation-rail" aria-label="Journals navigation"><div id="s-journal-scope" class="rail-group" role="group" aria-label="Journal scope"><button class="rail-button" data-scope="subject" data-flyout="subject" title="SUBJECT" aria-label="SUBJECT"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h7l2 3h9v12H3z"/></svg></button><button class="rail-button" data-scope="access" data-flyout="access" title="ACCESS" aria-label="ACCESS"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10h16v11H4zM8 10V7a4 4 0 0 1 8 0v3M12 14v3"/></svg></button><button class="rail-button" data-scope="custom" data-flyout="custom" title="LABEL" aria-label="LABEL"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m3 3 9 1 9 9-8 8-9-9z"/><circle cx="8" cy="8" r="1"/></svg></button></div><div id="s-journal-layout" class="rail-group" role="group" aria-label="Journal layout"><button class="rail-button" data-layout="array" title="ARRAY" aria-label="ARRAY"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v4H4zM4 15h16v4H4z"/></svg></button><button class="rail-button" data-layout="grid" title="GRID" aria-label="GRID"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/></svg></button></div></nav><aside id="journal-flyout" class="navigation-flyout" aria-label="Journal directory" tabindex="-1" hidden><div class="flyout-heading"><span id="journal-directory-title">SUBJECT</span><button data-flyout-close aria-label="Close Directory">×</button></div>
<div id="s-entities" class="s-directory-list" data-flyout-list></div>
<div class="s-directory-order"><button id="s-edit-entity" class="s-button" title="Edit Group" aria-label="Edit Group">Edit</button><button id="s-new-entity" class="s-button">+</button><button id="s-delete-entity" class="s-button" disabled>−</button><button id="s-entity-up" class="s-button">↑</button><button id="s-entity-down" class="s-button">↓</button></div>
</aside>
<div class="s-browser workspace-content" tabindex="-1"><div class="s-browser-head s-journals-head"><h2 id="s-journals-title" data-journal-title>All Journals</h2>
<div class="s-journal-add"><button id="s-add-journal" class="s-button">+ JOURNAL</button></div></div>
<div id="s-journals" class="s-journal-list"></div></div>
<aside id="journal-sidebar" class="functional-sidebar" aria-label="Journal and directory details" hidden>
<div class="sidebar-resize" role="separator" tabindex="0" aria-label="Resize Details" aria-orientation="vertical"></div>
<div class="sidebar-heading"><span>DETAILS</span><button data-sidebar-close aria-label="Close Details">×</button></div><div class="sidebar-scroll" data-functional-view="details">
<div id="s-entity-detail"><div id="s-entity-description"></div>
</div>
<div id="s-journal-detail" hidden></div><div id="s-journal-actions" hidden></div>
</div></aside><nav class="tool-rail" aria-label="Journals tools"><button class="rail-button" data-sidebar-view="details" aria-controls="journal-sidebar" title="DETAILS" aria-label="Details"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 3h16v18H4zM8 7h8M8 12h8M8 17h4"/></svg></button></nav></section>
    <section id="s-file-preview" class="s-file-preview" hidden aria-label="Full file preview">
<div class="s-preview-head">
<div>
<span class="s-eyebrow">FILES / TRANSIENT PREVIEW</span>
<h2 id="s-preview-title">
</h2>
</div>
<span id="s-preview-file" class="s-eyebrow">
</span>
</div>
<div class="s-preview-body">
<p id="s-preview-summary" class="s-preview-summary">
</p>
<div id="s-preview-columns" class="s-preview-columns">
</div>
</div>
<div id="s-preview-actions" class="s-preview-actions">
</div>
</section>
  </div>
  <dialog id="s-dialog" class="s-dialog" aria-labelledby="s-dialog-title">
<h2 id="s-dialog-title">
</h2>
<div id="s-dialog-body" class="s-dialog-body">
</div>
<div id="s-dialog-actions" class="s-actions">
</div>
</dialog>`;
const $=id=>document.getElementById(id);
for(const [panel,page]of [['s-journals-page','journals-view'],['s-run','run-page'],['s-settings','settings-view']]){
  $(page).append(markup.content.querySelector('#'+panel));
}
root.querySelector('.s-content').append(markup.content.querySelector('#s-file-preview'));
document.body.append(markup.content.querySelector('#s-dialog'));
const shell=$('settings-shell'),header=markup.content.querySelector('.s-header');

shell.append(markup.content.querySelector('#s-message'),header.querySelector('.s-header-actions'));header.remove();
const settingsPage=$('s-settings');

for(const button of root.querySelectorAll('[data-diagnostic]')){
 const summary=button.closest('details').querySelector('summary'),name=document.createElement('span'),status=document.createElement('span');
 name.className='s-diagnostic-name';name.textContent=summary.textContent;status.id=`s-${button.dataset.diagnostic}-summary`;status.className='s-diagnostic-summary';status.textContent='Not checked';summary.replaceChildren(name,status);
}
const reset=document.querySelector('.s-reset'),resetDisclosure=document.createElement('details'),resetSummary=document.createElement('summary');
resetDisclosure.id='s-reset-section';resetDisclosure.className='s-reset';
resetSummary.append(Object.assign(document.createElement('span'),{className:'s-diagnostic-name',textContent:'Reset'}),$('s-reset-path'));
resetDisclosure.append(resetSummary,reset.querySelector('.s-reset-confirm'));reset.replaceWith(resetDisclosure);


// Reparent the existing controls; one controller and one saved source own them.
const icon=(path)=>`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
function sideShell(id,label,view='configuration') {
  const side=document.createElement('aside');side.id=id;side.className='functional-sidebar';side.hidden=true;side.setAttribute('aria-label',label);
  side.innerHTML=`<div class="sidebar-resize" role="separator" tabindex="0" aria-label="Resize ${label}" aria-orientation="vertical"></div><div class="sidebar-heading"><span>${label}</span><button data-sidebar-close aria-label="Close ${label}">×</button></div><div class="sidebar-scroll" data-functional-view="${view}"></div>`;
  return side;
}
function rail(label,buttons,tool=false) {
  const node=document.createElement('nav');node.className=tool?'tool-rail':'navigation-rail';node.setAttribute('aria-label',label);node.innerHTML=buttons;return node;
}
const runPanel=$('s-run'),runMain=runPanel.querySelector('.s-browser'),runDirectory=runPanel.querySelector('.s-directory'),runContext=runPanel.querySelector('.s-context');
runPanel.className='s-panel workbench-layout';runMain.classList.add('workspace-content');runMain.tabIndex=-1;
runDirectory.className='navigation-flyout';runDirectory.id='run-provider-flyout';runDirectory.hidden=true;runDirectory.tabIndex=-1;
const runDirectoryTitle=document.createElement('div');runDirectoryTitle.className='flyout-heading';runDirectoryTitle.innerHTML='<span>PROVIDER DIRECTORY</span><button data-flyout-close aria-label="Close Provider Directory">×</button>';runDirectory.prepend(runDirectoryTitle);
$('s-providers').setAttribute('data-flyout-list','');
const runSidebar=sideShell('run-configuration-sidebar','PROVIDER');
runSidebar.querySelector('.sidebar-scroll').append(runContext.querySelector('.s-provider-alias'));
for(const fieldset of runPanel.querySelectorAll('[data-provider-settings]'))runSidebar.querySelector('.sidebar-scroll').append(fieldset);
const wosAccess=document.createElement('section');wosAccess.dataset.providerSettings='wos';wosAccess.innerHTML='<h3>Institution Access</h3><p id="s-wos-access-status" class="s-help"></p><button id="s-wos-access" class="s-button">Open Login</button>';runSidebar.querySelector('.sidebar-scroll').append(wosAccess);
const runHistory=document.createElement('section');runHistory.className='s-run-history';runHistory.append(...runContext.childNodes);runContext.remove();runMain.querySelector('.s-run-body').append(runHistory);
runPanel.prepend(rail('Run navigation',`<button class="rail-button" id="s-run-overview-open" title="Overview" aria-label="Overview">${icon('M4 4h16v16H4zM4 10h16M10 10v10')}</button><button class="rail-button" data-flyout="providers" title="Provider Directory" aria-label="Provider Directory">${icon('M4 5h16M4 12h16M4 19h16')}</button>`));
runPanel.append(runSidebar,rail('Run tools',`<button class="rail-button" data-sidebar-view="configuration" aria-label="Provider configuration" title="Provider configuration">${icon('M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M10 15v6')}</button>`,true));
const monitorName=settingsPage.querySelector('[data-field="name"]');$('s-run-overview').querySelector('fieldset').prepend(monitorName);
const keptSettings=document.createElement('div');keptSettings.id='s-kept-configuration-bridge';keptSettings.hidden=true;document.body.append(keptSettings);
const concurrencyFields=[
  ['prepare_service_concurrency','prepareServiceConcurrency','Service preparation',5],
  ['paper_service_concurrency','paperServiceConcurrency','Papers per Service',8],
  ['paper_global_concurrency','paperGlobalConcurrency','Total Papers',16],
  ['translator_concurrency','translatorConcurrency','Translator workers',6],
  ['pdf_concurrency','pdfConcurrency','PDF downloads',8],
  ['zotero_writer_concurrency','zoteroWriterConcurrency','Zotero writers',4],
];
function concurrencyGroup(fields) {
  const group=document.createElement('fieldset');
  group.className='s-setting-group';
  group.innerHTML='<legend>Concurrency</legend>'+fields.map(([,key,label,max])=>
    `<label class="s-setting-row" data-field="${key}"><span class="s-setting-label">${label}</span>
      <input type="number" data-monitor="${key}" min="1" max="${max}" step="1"></label>`).join('');
  return group;
}
const loginLimits=concurrencyGroup(concurrencyFields.slice(0,1)),workflowFields=concurrencyGroup(concurrencyFields.slice(1));
keptSettings.append(loginLimits,workflowFields,$('s-institution'),$('s-institution-auth'));
settingsPage.querySelector('.s-settings-main').querySelector('fieldset').remove();
const applicationGroup=settingsPage.querySelector('.s-settings-main fieldset');applicationGroup.querySelector('legend').textContent='Application';applicationGroup.dataset.settingsSection='application';
const workspaceApply=document.createElement('button');workspaceApply.id='s-workspace-apply';workspaceApply.className='s-button';workspaceApply.textContent='Review Workspace change';applicationGroup.append(workspaceApply);
const appearanceGroup=document.createElement('fieldset');appearanceGroup.className='s-setting-group';appearanceGroup.dataset.settingsSection='appearance';appearanceGroup.innerHTML='<legend>Appearance</legend>';
const developerGroup=document.createElement('fieldset');developerGroup.className='s-setting-group';developerGroup.dataset.settingsSection='developer';developerGroup.innerHTML='<legend>Developer</legend>';
for(const [id,group] of [['s-disable-archive',appearanceGroup],['s-disable-fullscreen',appearanceGroup],['s-developer-mode',developerGroup]]){const label=$(id).closest('label'),help=label.nextElementSibling;group.append(label);if(help?.matches('.s-help'))group.append(help);}
const dataGroup=document.createElement('section');dataGroup.dataset.settingsSection='data';dataGroup.innerHTML='<h2>Data</h2>';
const files=$('s-files').closest('.s-files');dataGroup.append(files,$('s-reset-section') || settingsPage.querySelector('.s-reset'));
settingsPage.querySelector('.s-settings-main').append(appearanceGroup,dataGroup,developerGroup);
for(const node of settingsPage.querySelectorAll('[data-settings-section]'))node.hidden=node.dataset.settingsSection!=='application';
const settingsMain=settingsPage.querySelector('.s-settings-main');settingsMain.classList.add('workspace-content');settingsMain.tabIndex=-1;
const oldSystem=settingsPage.querySelector('.s-system-sidebar'),settingsSidebar=sideShell('settings-system-sidebar','SYSTEM','system');settingsSidebar.querySelector('.sidebar-scroll').append($('s-system'));oldSystem.remove();
settingsPage.className='s-panel workbench-layout';
const settingsButtons=['application','appearance','data','developer'].map((name,index)=>`<button class="rail-button" data-settings-open="${name}" title="${name[0].toUpperCase()+name.slice(1)}" aria-label="${name[0].toUpperCase()+name.slice(1)}">${icon(['M4 4h16v16H4zM8 8h8M8 12h8M8 16h4','M12 3a9 9 0 1 0 9 9h-9z','M4 5h16v14H4zM8 9h8M8 13h8','M8 5 2 12l6 7M16 5l6 7-6 7M14 3l-4 18'][index])}</button>`).join('');
settingsPage.prepend(rail('Settings navigation',settingsButtons));
const settingsFlyout=document.createElement('aside');settingsFlyout.className='navigation-flyout';settingsFlyout.hidden=true;settingsFlyout.innerHTML='<button data-flyout-close aria-label="Close Settings directory">×</button>';settingsPage.append(settingsFlyout,settingsSidebar,rail('Settings tools',`<button class="rail-button" data-sidebar-view="system" title="System / Diagnostics" aria-label="System / Diagnostics">${icon('M4 4h16v16H4zM12 10v7M12 7v1')}</button>`,true));
for(const button of settingsPage.querySelectorAll('[data-settings-open]'))button.addEventListener('click',()=>{for(const node of settingsPage.querySelectorAll('[data-settings-section]'))node.hidden=node.dataset.settingsSection!==button.dataset.settingsOpen;for(const entry of settingsPage.querySelectorAll('[data-settings-open]'))entry.setAttribute('aria-pressed',String(entry===button));});
settingsPage.querySelector('[data-settings-open="application"]').setAttribute('aria-pressed','true');
for(const host of [runMain.querySelector('.s-run-body'),settingsMain,loginLimits,workflowFields,$('s-institution')]){const status=document.createElement('p');status.className='s-help s-domain-save-status';status.dataset.autosaveStatus='';host.append(status);}
function mountWorkflowSettings() {
  const access=$('login-access-settings') || $('kept-access-settings');
  const login=$('login-workflow-settings'),workflow=$('kept-workflow-settings');
  if(access)for(const node of [$('s-institution'),$('s-institution-auth')])if(node.parentElement!==access)access.append(node);
  if(login && loginLimits.parentElement!==login)login.append(loginLimits);
  if(workflow && workflowFields.parentElement!==workflow)workflow.append(workflowFields);
}
for(const name of ['login-settings-mount','kept-settings-mount','workspace-navigation-state'])
  window.addEventListener(name,mountWorkflowSettings);
mountWorkflowSettings();
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy=value=>structuredClone(value);
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
const views=['journals-page','run','settings'];
const navigation={'journals-page':'journals',run:'run',settings:'settings'};
const transitions=new Map(views.map(view=>[view,new SurfaceTransition($('s-'+view),$('s-'+view),180,180)]));
let saved=null,draft=null,view='settings',preview=null,revision=0,loading=true,operationPending=false;
let serverState=null,reconcileRequired=false,autosave=null;
let autosaveStatus={status:'Saved',dirty:false,busy:false,storageError:''};
let institutions=[],institutionInputInvalid=false,institutionCatalogMessage='正在加载本地机构名录。';
const casAPI=typeof window.allfoldDesktop?.casStatus==='function'?window.allfoldDesktop:null;
let casSaved={configured:false,username:'',revision:null},casDraft={username:'',password:''},casError='',casReadVersion=0;
const casEditVersions={username:0,password:0};
let selectedProvider='overview',expressions={},runState=null,expressionTimer,expressionVersion=0;
let journalLayout='array';
let journalTitleScroll=null;
const ui={scope:'subject',directory:{subject:'all',access:'all',custom:'all'},journal:null,detail:'entity',search:''};
let assignmentUndo=null;
const covers=new Map();
const identifiers=j=>[j.issn,j.eissn].filter(Boolean);
let coverJob={phase:'Idle',journal_key:null,busy:false,supported:false};
let coverTimer=null;
const dialog=$('s-dialog');let dialogFocus=null,dialogVersion=0;
let directoryScope='subject';
const journalLayoutHost=window.allfoldLayout.create({root:$('s-journals-page'),workspace:'journals',
  minContentWidth:window.allfoldLayoutModel.minOperationalSize.journals,
  preview(scope){directoryScope=scope;if(draft)renderDirectory();},
});
const runLayoutHost=window.allfoldLayout.create({root:runPanel,workspace:'run',minContentWidth:360});
const settingsLayoutHost=window.allfoldLayout.create({root:settingsPage,workspace:'settings',minContentWidth:360});
let cropEditor=null;
const configurationDirty=()=>Boolean(saved && draft && !same(saved,draft));
const explicitDirty=()=>Boolean(saved && draft && (draft.monitor.workspace!==saved.monitor.workspace || ['pubmed','openalex'].some(provider=>draft.monitor[provider+'KeyAction']!=='keep') || casDirty() || institutionInputInvalid));
const casPasswordAction=()=>casDraft.password===keyMask?'keep':casDraft.password?'replace':casSaved.configured?'clear':'keep';
const casDirty=()=>Boolean(casAPI && (casDraft.username.trim()!==casSaved.username || casPasswordAction()!=='keep'));
const dirty=()=>configurationDirty() || casDirty() || institutionInputInvalid || autosaveStatus.dirty;

const list=()=>draft.list;
const sources=()=>list().journals;
const sourceName=()=>'Journals';
const journal=id=>list().journals.find(j=>j.id===id);
const group=id=>list().groups.find(g=>g.id===id);
const groupName=id=>group(id)?.name || 'Ungrouped';
function message(text,tone='normal') {$('s-message').textContent=text;$('s-message').dataset.tone=tone;$('s-message').hidden=!text;}
function updateDirty() {
  $('s-files').disabled=operationPending;
  for(const button of $('s-file-menu').querySelectorAll('[data-file-action]'))button.disabled=loading && button.dataset.fileAction!=='reload';
  const explicit=explicitDirty();
  const status=loading?'Loading':autosaveStatus.status;
  for(const node of document.querySelectorAll('[data-autosave-status]'))node.textContent=autosaveStatus.storageError || (explicit && !autosaveStatus.dirty?'Pending explicit confirmation':status);
  $('s-dirty').textContent=autosaveStatus.storageError || (explicit && !autosaveStatus.dirty?'Pending confirmation':status);$('s-dirty').dataset.dirty=String(dirty());
  $('s-autosave-retry').hidden=!['Failed','Pending'].includes(status) || !autosaveStatus.dirty;
  $('s-autosave-reconcile').hidden=!['Conflict','Partial'].includes(status);
  const unsaved=dirty();
  $('settings-open').setAttribute('aria-label',unsaved?'Settings · Pending changes':'Settings');
  $('s-workspace-apply').disabled=loading || operationPending || draft?.monitor.workspace===saved?.monitor.workspace;
  $('s-undo').hidden=window.workspaceNavigation.current()!=='journals';
  $('s-undo').disabled=loading || operationPending || reconcileRequired || Boolean(preview) || !assignmentUndo;
  $('s-reset-path').textContent=$('s-reset-scope').value==='logs'?'当前配置的 Logs':serverState?.saved_workspace || 'Unavailable';
  const logging=serverState?.logging;
  $('s-log-help').textContent=`${logging?`当前采集级别：${logging.effective_level.toUpperCase()}${logging.environment_override?'（ALLFOLD_LOG_LEVEL 控制）':''}。`:''}级别修改后重启应用生效；运行记录与关键结果始终保留。`;
  window.workspaceNavigation.refresh();window.dispatchEvent(new Event('settings-draft-changed'));
}
document.addEventListener('focusout',event=>{if(event.target.matches('#s-provider-alias,#s-entity-name,[data-service-field]'))void autosave?.flush();});
function changed({immediate=false}={}) {revision++;if(autosave && !loading)autosave.edit(ordinaryValues(),{immediate});updateDirty();renderRun();}
function setOperationPending(value) {
  operationPending=value;root.dataset.busy=String(value);
  root.querySelector('.s-content').inert=value || loading;for(const id of ['login-access-settings','login-workflow-settings','kept-workflow-settings'])if($(id))$(id).inert=value || loading;updateDirty();
}
function casErrorText(code) {
  return ({cas_encryption_unavailable:'系统安全存储不可用，未保存或自动填写凭据。',
    cas_store_unreadable:'机构登录凭据无法读取或解密；请重新填写用户名和密码以替换。',
    cas_store_write_failed:'机构登录凭据保存失败，原有密文保留。',cas_store_clear_failed:'机构登录凭据未能清除。',
    cas_revision_conflict:'机构凭据已改变，请重新读取状态后核对。',cas_store_busy:'机构凭据正在提交，请稍候。',cas_task_active:'活动任务正在使用机构凭据，草稿保留。',cas_credentials_required:'首次配置必须同时填写用户名和密码。',cas_invalid_credentials:'请填写有效的用户名和密码。'})[code]
    || '机构登录凭据操作未完成，草稿保留，请确认 Electron 仍在运行后重试。';
}
function renderCAS() {
  $('s-institution-auth').hidden=!casAPI;
  $('s-cas-username').value=casDraft.username;$('s-cas-password').value=casDraft.password;
  $('s-cas-password').placeholder=casSaved.configured?'清空后可明确确认删除密码':'选填';
  $('s-cas-status').textContent=casError;$('s-cas-status').hidden=!casError;
}
async function loadCASStatus({resetDraft=true}={}) {
  if(!casAPI)return;
  const readVersion=++casReadVersion,editVersions={...casEditVersions};
  let result;
  try {result=await casAPI.casStatus();}catch {result={ok:false};}
  if(readVersion!==casReadVersion)return;
  casSaved={configured:result?.ok && result.configured===true,username:result?.ok?result.username || '':'',revision:typeof result?.revision==='string'?result.revision:null};
  if(resetDraft)for(const [field,value] of Object.entries({username:casSaved.username,password:casSaved.configured?keyMask:''}))
    if(editVersions[field]===casEditVersions[field])casDraft[field]=value;
  casError=result?.ok?(resetDraft?'':'安全存储状态已重新读取；未提交输入保留，请核对后明确确认。'):
    casErrorText(result?.error)+(resetDraft?'':' 未提交输入保留。');
  renderCAS();updateDirty();renderRun();
}
for(const field of ['username','password'])$('s-cas-'+field).addEventListener('input',()=>{
  casDraft[field]=$('s-cas-'+field).value;casEditVersions[field]++;changed();
});
renderCAS();
function showDialog(title,body,choices) {
  closeLabelPicker();
  clearCropEditor();
  if(dialog.open)dialog.close();
  const version=++dialogVersion;
  dialogFocus=document.activeElement;$('s-dialog-title').textContent=title;$('s-dialog-body').innerHTML=body;
  $('s-dialog-actions').replaceChildren();
  for(const {label,run,primary=false,disabled=false} of choices) {
    const button=document.createElement('button');button.className='s-button'+(primary?' s-primary':'');button.textContent=label;
    button.disabled=disabled;
    button.addEventListener('click',async()=>{button.disabled=true;try {if(await run?.()!==false && dialogVersion===version && dialog.open)dialog.close();}catch(error){message(error.message,'error');}finally{button.disabled=false;}});$('s-dialog-actions').append(button);
  }
  dialog.showModal();window.workspaceNavigation.refresh();
}
const cancel={label:'Cancel'};
function clearCropEditor() {
  cropEditor?.instance?.destroy();cropEditor=null;dialog.classList.remove('s-crop-dialog');
}
dialog.addEventListener('cancel',event=>{if(cropEditor?.pending)event.preventDefault();});
dialog.addEventListener('close',()=>{
  if(dialog.open)return;
  clearCropEditor();
  const target=dialogFocus?.isConnected && !dialogFocus.disabled && !dialogFocus.closest('[hidden]')?dialogFocus:$('settings-open');
  if(!root.hidden && (document.activeElement===document.body || dialog.contains(document.activeElement)))target.focus({preventScroll:true});
  window.workspaceNavigation.refresh();
});
function confirm(title,text,run,label='Confirm') {showDialog(title,`<p>${esc(text)}</p>`,[cancel,{label,primary:true,run}]);}
function memberList(items) {return `<ul>${items.map(name=>`<li>${esc(name)}</li>`).join('')}</ul>`;}
function closeMenu() {
  if($('s-file-menu').matches(':popover-open'))$('s-file-menu').hidePopover();
  $('s-files').setAttribute('aria-expanded','false');
}
$('s-file-menu').addEventListener('toggle',event=>$('s-files').setAttribute('aria-expanded',String(event.newState==='open')));
settingsPage.addEventListener('scroll',closeMenu);
$('settings-system-sidebar').addEventListener('scroll',closeMenu);
window.addEventListener('resize',closeMenu);
const scrollPositions=new Map();
function pageScrollers() {
  const panel=$('s-'+view);
  return [panel,...panel.querySelectorAll('.s-directory-list,.s-journal-list,.s-journal-grid,.s-context,.sidebar-scroll,.s-settings-main,.s-system-sidebar,.s-run-body')];
}
function rememberScroll() {
  // A hidden previous root reports zero scroll after top-level presentation changes.
  if(!root.hidden && !preview && window.workspaceNavigation.current()===navigation[view])for(const node of pageScrollers())scrollPositions.set(node,[node.scrollLeft,node.scrollTop]);
}
function restoreScroll() {
  for(const node of pageScrollers()){
    const position=scrollPositions.get(node);if(position){node.scrollLeft=position[0];node.scrollTop=position[1];}
  }
}
function switchView(next,instant=false) {
  if(preview || next===view)return;
  rememberScroll();transitions.get(view).dispose();$('s-'+view).hidden=true;
  view=next;
  transitions.get(view).show(instant || reduced());closeMenu();
}
function configurationAvailable() {return !dialog.open && !preview && !operationPending;}
function openSettings(next='settings',instant=false) {
  if(!configurationAvailable())return false;
  const page=navigation[next],samePage=window.workspaceNavigation.current()===page;
  if(!window.workspaceNavigation.go(page,{instant}))return false;
  if(samePage){switchView(next,instant);restoreScroll();window.workspaceNavigation.refresh();}
  return true;
}
for(const page of ['journals','run','settings'])window.workspaceNavigation.register(page,{
  canEnter:configurationAvailable,canLeave:configurationAvailable,
  leave:()=>{rememberScroll();journalLayoutHost.closeFlyout({restoreFocus:false});runLayoutHost.closeFlyout({restoreFocus:false});stopJournalTitleScroll();closeLabelPicker();transitions.get(view).dispose();closeMenu();},
  enter:({instant})=>{
    const next=page==='journals'?'journals-page':page;
    if(next===view)transitions.get(view).show(instant || reduced());else switchView(next,instant);
    updateDirty();restoreScroll();syncLayouts();if(page==='run')void refreshRun();
  },
});
function syncLayouts(){
  journalLayoutHost.sync();runLayoutHost.sync();settingsLayoutHost.sync();
  for(const button of root.querySelectorAll('[data-layout]'))button.setAttribute('aria-pressed',String(button.dataset.layout===journalLayout));
  for(const button of root.querySelectorAll('[data-scope]'))button.setAttribute('aria-pressed',String(button.dataset.scope===ui.scope));
}
// Match Kept's delayed, one-way title reveal without changing its controller or bundle.
function stopJournalTitleScroll() {
  if(!journalTitleScroll)return;
  const {node,frame}=journalTitleScroll;
  cancelAnimationFrame(frame);node.scrollLeft=0;node.style.removeProperty('text-overflow');
  journalTitleScroll=null;
}
function startJournalTitleScroll(node) {
  stopJournalTitleScroll();
  const distance=node.scrollWidth-node.clientWidth;
  if(distance<=0 || reduced())return;
  node.style.textOverflow='clip';
  const state={node,frame:0};let started=null;
  journalTitleScroll=state;
  const step=now=>{
    started??=now;
    node.scrollLeft=Math.min(distance,Math.max(0,now-started-400)*.04);
    state.frame=node.scrollLeft<distance?requestAnimationFrame(step):0;
  };
  state.frame=requestAnimationFrame(step);
}
function bindJournalTitleScroll(node) {
  node.addEventListener('pointerenter',()=>startJournalTitleScroll(node));
  node.addEventListener('pointerleave',()=>{if(journalTitleScroll?.node===node)stopJournalTitleScroll();});
}
bindJournalTitleScroll($('s-journals-title'));
window.addEventListener('resize',stopJournalTitleScroll);
function closeLabelPicker() {const picker=$('s-journal-labels');if(picker)picker.open=false;}
function setJournalLayout(layout) {
  if(!['array','grid'].includes(layout) || layout===journalLayout)return;
  journalLayout=layout;renderJournals();syncLayouts();
}
function setJournalScope(scope) {
  if(!['subject','access','custom'].includes(scope) || scope===ui.scope)return;
  ui.scope=scope;directoryScope=scope;reconcileSelections(true);renderJournalsPage();
}
for(const button of root.querySelectorAll('[data-layout]'))button.addEventListener('click',()=>setJournalLayout(button.dataset.layout));
for(const button of root.querySelectorAll('[data-scope]'))button.addEventListener('click',()=>setJournalScope(button.dataset.scope));
syncLayouts();
for(const surface of [root,shell])surface.addEventListener('keydown',event=>{
  if(event.key==='Escape' && !dialog.open){if($('s-journal-labels')?.open){event.preventDefault();closeLabelPicker();$('s-journal-labels').querySelector('summary').focus({preventScroll:true});}else if(preview)closePreview();else if($('s-file-menu').matches(':popover-open')){closeMenu();$('s-files').focus({preventScroll:true});}}
});
function moveDirectoryIndex(container,delta) {
  const rows=[...container.querySelectorAll(':scope > button:not(:disabled):not([hidden])')];
  if(!rows.length)return false;
  const current=rows.findIndex(row=>row.getAttribute('aria-current')==='true');
  const next=current<0?(delta>0?0:rows.length-1):(current+delta+rows.length)%rows.length;
  // Reuse selection handlers, then resolve the row again after their render.
  rows[next].click();
  const selected=container.querySelector('button[aria-current=true]');
  selected?.focus({preventScroll:true});
  selected?.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
  return true;
}
document.addEventListener('keydown',event=>{
  if(event.defaultPrevented || !['ArrowUp','ArrowDown'].includes(event.key) ||
      event.altKey || event.metaKey || event.ctrlKey || event.shiftKey ||
      loading || reconcileRequired || root.hidden || root.closest('[inert]') || !configurationAvailable() ||
      document.querySelector('dialog[open], [popover]:popover-open') || event.target.isContentEditable ||
      event.target.closest('input,textarea,select,[contenteditable],[role=separator],[inert]'))return;
  const page=window.workspaceNavigation.current();
  const directory=page==='run'?$('s-providers'):null;
  if(directory && moveDirectoryIndex(directory,event.key==='ArrowUp'?-1:1))event.preventDefault();
});
$('s-files').addEventListener('click',()=>{
  const menu=$('s-file-menu');
  if(menu.matches(':popover-open')){closeMenu();return;}
  const anchor=$('s-files').getBoundingClientRect();
  menu.style.top=`${anchor.bottom+8}px`;
  menu.style.left=`${Math.max(18,Math.min(anchor.left,innerWidth-318))}px`;
  menu.style.maxHeight=`${Math.max(80,innerHeight-anchor.bottom-26)}px`;
  menu.showPopover();$('s-files').setAttribute('aria-expanded','true');menu.querySelector('button').focus();
});
document.addEventListener('pointerdown',event=>{if(!event.target.closest('.s-files'))closeMenu();if(!event.target.closest('.s-label-field'))closeLabelPicker();});

workspaceSearch.register('journals',{
  label:'Journal',
  items:()=>saved?.list.journals.map(j=>({
    id:j.id,name:j.name,detail:identifiers(j).join(' / '),keywords:(j.aliases || []).join(' '),
  })) || [],
  select:item=>{
    if(!journal(item.id) || !openSettings('journals-page',true))return false;
    if(!entityMembers().some(j=>j.id===item.id))ui.directory[ui.scope]='all';
    selectJournal(item.id);
    const row=[...$('s-journals').querySelectorAll('[data-journal]')].find(row=>row.dataset.journal===item.id);
    row?.focus({preventScroll:true});row?.scrollIntoView({block:'nearest'});
    return true;
  },
});
function syncMonitor() {
  document.querySelectorAll('[data-monitor]').forEach(input=>{const value=draft.monitor[input.dataset.monitor];if(input.type==='checkbox')input.checked=value;else input.value=value ?? '';});
  syncInstitution();
  for(const provider of ['pubmed','openalex'])syncKey(provider);scheduleExpressions();renderRun();
}
document.querySelectorAll('[data-monitor]').forEach(input=>input.addEventListener(input.tagName==='SELECT' || input.type==='checkbox'?'change':'input',()=>{
  if(input.dataset.monitor==='institutionName')return;
  draft.monitor[input.dataset.monitor]=input.type==='checkbox'?input.checked:input.value;
  for(const provider of ['pubmed','openalex'])if(input.dataset.monitor===provider+'Key')syncKey(provider);
  changed({immediate:input.tagName==='SELECT' || input.type==='checkbox'});
  if(['expression'].includes(input.dataset.monitor))scheduleExpressions();
}));
const institutionLabel=row=>`${row.name}（${row.name_en}）`;
function syncInstitution() {
  closeInstitutionPopup();
  if(!draft)return;
  const row=institutions.find(item=>item.idp_entity_id===draft.monitor.idp);
  $('s-institution-query').value=row?institutionLabel(row):draft.monitor.institutionName || draft.monitor.idp || '';
  $('s-institution-query').setCustomValidity('');institutionInputInvalid=false;
  $('s-institution-help').textContent=institutionCatalogMessage || (!row && (draft.monitor.institutionName || draft.monitor.idp)
    ?'当前机构未收录，原配置保留；可搜索并选择其他机构。':'');
}
async function loadInstitutionCatalog() {
  try {
    const response=await fetch('/static/ui_next/carsi-institutions.json');
    if(!response.ok)throw new Error('Institution catalog unavailable');
    institutions=await response.json();
    institutionCatalogMessage='';
  } catch {institutionCatalogMessage='本地机构名录无法加载，原配置保留；请重新加载页面。';}
  if(!institutionInputInvalid)syncInstitution();
}
const institutionInput=$('s-institution-query'),institutionPopup=$('s-institution-popup'),institutionList=$('s-institutions');
let institutionMatches=[],institutionActive=-1,institutionComposing=false;
function closeInstitutionPopup() {
  if(institutionPopup.matches(':popover-open'))institutionPopup.hidePopover();
  institutionInput.setAttribute('aria-expanded','false');institutionInput.removeAttribute('aria-activedescendant');
  institutionActive=-1;
}
function showInstitutionMatches() {
  const query=institutionInput.value.trim().toLocaleLowerCase();
  if(!query || institutionComposing){closeInstitutionPopup();return;}
  const rank=row=>{
    const names=[row.name,row.name_en].map(name=>(name || '').toLocaleLowerCase());
    return names.some(name=>name===query)?0:names.some(name=>name.startsWith(query))?1:names.some(name=>name.includes(query))?2:3;
  };
  const matches=institutions.map(row=>({row,rank:rank(row)})).filter(item=>item.rank<3).sort((a,b)=>a.rank-b.rank);
  institutionMatches=matches.slice(0,8).map(item=>item.row);institutionActive=-1;
  institutionList.replaceChildren(...institutionMatches.map((row,index)=>{
    const option=document.createElement('div');option.id=`s-institution-option-${index}`;option.className='s-institution-option';
    option.setAttribute('role','option');option.setAttribute('aria-selected','false');
    const name=document.createElement('span'),english=document.createElement('small');name.textContent=row.name;english.textContent=row.name_en;
    option.append(name,english);option.addEventListener('pointerdown',event=>event.preventDefault());
    option.addEventListener('click',()=>selectInstitution(index));return option;
  }));
  $('s-institution-results').textContent=matches.length>8?'仅显示前 8 项，请继续输入以缩小范围。':matches.length?'':'没有匹配的机构。';
  const rect=institutionInput.getBoundingClientRect();
  institutionPopup.style.left=`${rect.left}px`;institutionPopup.style.top=`${rect.bottom}px`;institutionPopup.style.bottom='auto';
  institutionPopup.style.width=`${Math.min(rect.width,window.innerWidth-rect.left-8)}px`;
  const above=window.innerHeight-rect.bottom<280 && rect.top>window.innerHeight-rect.bottom;
  if(above){institutionPopup.style.top='auto';institutionPopup.style.bottom=`${window.innerHeight-rect.top}px`;}
  institutionPopup.style.maxHeight=`${Math.max(0,Math.min(280,(above?rect.top:window.innerHeight-rect.bottom)-8))}px`;
  if(!institutionPopup.matches(':popover-open'))institutionPopup.showPopover();
  institutionInput.setAttribute('aria-expanded','true');institutionInput.removeAttribute('aria-activedescendant');
}
function selectInstitution(index) {
  const row=institutionMatches[index];if(!row)return;
  institutionInput.value=institutionLabel(row);institutionInput.dispatchEvent(new Event('input',{bubbles:true}));
  closeInstitutionPopup();institutionInput.focus();
}
institutionInput.addEventListener('focus',()=>{
  const selected=institutions.find(row=>row.idp_entity_id===draft?.monitor.idp);
  if(institutionInput.value && institutionInput.value!==institutionLabel(selected || {name:'',name_en:''}))showInstitutionMatches();
});
institutionInput.addEventListener('compositionstart',()=>{institutionComposing=true;closeInstitutionPopup();});
institutionInput.addEventListener('compositionend',()=>{institutionComposing=false;showInstitutionMatches();});
institutionInput.addEventListener('keydown',event=>{
  if(event.isComposing || institutionComposing)return;
  if(event.key==='Escape'){closeInstitutionPopup();return;}
  if(!institutionPopup.matches(':popover-open'))return;
  if(event.key==='ArrowDown' || event.key==='ArrowUp'){
    if(!institutionMatches.length)return;
    event.preventDefault();institutionActive=institutionActive<0?(event.key==='ArrowDown'?0:institutionMatches.length-1):(institutionActive+(event.key==='ArrowDown'?1:-1)+institutionMatches.length)%institutionMatches.length;
    institutionList.querySelectorAll('[role=option]').forEach((option,index)=>option.setAttribute('aria-selected',String(index===institutionActive)));
    const active=$(`s-institution-option-${institutionActive}`);institutionInput.setAttribute('aria-activedescendant',active.id);active.scrollIntoView({block:'nearest'});
  } else if(event.key==='Enter' && institutionActive>=0){event.preventDefault();selectInstitution(institutionActive);}
});
institutionInput.addEventListener('blur',closeInstitutionPopup);
document.addEventListener('pointerdown',event=>{if(event.target!==institutionInput && !institutionPopup.contains(event.target))closeInstitutionPopup();});
window.addEventListener('resize',closeInstitutionPopup);
window.addEventListener('scroll',event=>{if(!institutionPopup.contains(event.target))closeInstitutionPopup();},true);
$('s-institution-query').addEventListener('input',()=>{
  const input=$('s-institution-query'),text=input.value.trim();
  const row=institutions.find(item=>institutionLabel(item)===text);
  const current=institutions.find(item=>item.idp_entity_id===draft.monitor.idp);
  const unchanged=text===(current?institutionLabel(current):draft.monitor.institutionName || draft.monitor.idp || '');
  institutionInputInvalid=!!text && !row && !unchanged;
  if(!text || row){draft.monitor.institutionName=row?.name || '';draft.monitor.idp=row?.idp_entity_id || '';}
  document.querySelector('[data-monitor="idp"]').value=draft.monitor.idp;
  input.setCustomValidity(institutionInputInvalid?'请从候选列表选择机构，或清空选择。':'');
  $('s-institution-help').textContent=institutionInputInvalid?input.validationMessage:institutionCatalogMessage;
  changed();
  if(!institutionComposing && document.activeElement===input)showInstitutionMatches();
});
function syncKey(provider) {
  const input=document.querySelector(`[data-monitor="${provider}Key"]`),value=draft.monitor[provider+'Key'];
  const configured=!!serverState?.values[provider+'_key_configured'];
  draft.monitor[provider+'KeyAction']=value===keyMask?'keep':value?'replace':configured?'clear':'keep';
  input.placeholder=configured?'清空后可明确确认删除 Key':'选填';
  $('s-'+provider+'-key-status').textContent=serverState?.values[provider+'_key_error'] ||
    (draft.monitor[provider+'KeyAction']==='clear'?'待清除 API Key。':configured?'已配置本地 Key；输入新值替换，清空以删除。':'未配置本地 API Key。')+' 使用下方按钮明确确认替换或清除。';
}
const providerOrder=()=>draft?.monitor.providerOrder || Object.keys(providerDefaults);
const providerName=id=>id==='integrated'?'Integrated Run':draft?.monitor.aliases[id] || providerDefaults[id];
function runBlockReason() {
  return loading?'正在加载配置。':operationPending?'正在提交明确确认的修改。':preview?'请先结束文件 Preview。':reconcileRequired || ['Conflict','Partial'].includes(autosaveStatus.status)?'保存存在冲突，请核对磁盘状态。':explicitDirty()?'凭据或 Workspace 修改需要独立确认。':'';
}
function scheduleExpressions() {
  clearTimeout(expressionTimer);const version=++expressionVersion;
  expressions={};renderRun();
  expressionTimer=setTimeout(async()=>{
    try {
      const data=await uiNext.request('/api/ui-next/run-expression',{keyword_expression:draft.monitor.expression});
      if(version===expressionVersion){expressions=data.providers;renderRun();window.dispatchEvent(new Event('settings-draft-changed'));}
    }catch(error){if(version===expressionVersion){expressions=Object.fromEntries(providerOrder().map(id=>[id,{error:error.message}]));renderRun();}}
  },300);
}
function renderRun() {
  if(!draft)return;
  const focusedProvider=document.activeElement?.dataset.provider;
  $('s-providers').innerHTML=providerOrder().map((id,index)=>`<button class="kept-manager-row s-directory-row" data-provider="${id}" title="${esc(id==='overview'?'Overview':providerName(id))}" aria-current="${selectedProvider===id}"><span class="rhine-index-number">${String(index).padStart(2,'0')}</span><span class="rhine-index-name">${esc(id==='overview'?'Overview':providerName(id))}</span></button>`).join('');
  if(focusedProvider)$('s-providers').querySelector(`[data-provider="${focusedProvider}"]`)?.focus({preventScroll:true});
  const position=providerOrder().indexOf(selectedProvider);
  $('s-provider-up').disabled=position<=0;$('s-provider-down').disabled=position<0 || position===providerOrder().length-1;
  if(document.activeElement!==$('s-provider-alias'))$('s-provider-alias').value=providerName(selectedProvider) || '';
  $('s-run-overview-open').setAttribute('aria-pressed',String(selectedProvider==='overview'));
  $('s-wos-access-status').textContent='Web of Science 使用 Login 中已准备的 Service 页面。';
  const overview=selectedProvider==='overview';
  $('s-provider-alias').closest('label').hidden=overview;
  $('s-run-title').textContent=overview?'Overview':providerName(selectedProvider);
  $('s-run-overview').hidden=!overview;$('s-run-provider').hidden=overview;
  $('s-provider-run').hidden=true;
  $('s-run-provider').querySelector('.s-run-query').hidden=!['pubmed','openalex','wos'].includes(selectedProvider);
  if(!overview){
    $('s-provider-run').dataset.runProvider=selectedProvider;
    $('s-run-expression').textContent=expressions[selectedProvider]?.expression || (!expressions[selectedProvider]?'正在生成表达式…':'');
    $('s-run-expression-error').textContent=expressions[selectedProvider]?.error || '';
  }
  for(const group of root.querySelectorAll('[data-provider-settings]'))group.hidden=group.dataset.providerSettings!==selectedProvider;
  const discovery=new Set(['pubmed','wos','openalex']);
  const choices=ids=>ids.map(id=>`<label class="s-setting-row s-check"><span class="s-setting-label">${esc(providerName(id))}</span><input type="checkbox" data-discovery-provider="${id}" ${draft.monitor.enabledProviders.includes(id)?'checked':''}></label>`).join('');
  $('s-run-operations').innerHTML=`<fieldset class="s-setting-group"><legend>Journal Discovery</legend>${choices(providerOrder().filter(id=>discovery.has(id)))}</fieldset><div class="s-run-operation"><button class="s-button" data-run-provider="integrated" disabled>Run ↗</button><p class="s-help" data-run-reason="integrated"></p></div><p class="s-help">Run 自动使用 PubMed、OpenAlex、Europe PMC、Crossref 与原生预印本 API 在保存新 Paper 前补全身份、日期和预印本关系。</p>`;
  updateRunButtons();renderRunRecords();
}
function updateRunButtons() {
  for(const button of root.querySelectorAll('[data-run-provider]')){
    const id=button.dataset.runProvider,entry=runState?.providers[id];
    const reason=runBlockReason() || (window.uiRun?.active()?'已有 Run 正在运行。':'') || expressions[id]?.error ||
      (!expressions[id]?'正在生成表达式…':'') || (!window.inboxRun?.available()?'Workspace 或当前操作尚未就绪。':'') || (!entry?.enabled?entry?.message || '正在读取运行状态。':'');
    button.disabled=!!reason;button.title=reason || 'Run '+providerName(id);button.dataset.blockReason=reason;
    const hint=root.querySelector(`[data-run-reason="${id}"]`);if(hint){hint.textContent=reason;hint.hidden=!reason;}
  }
}
function renderRunRecords() {
  if(!runState){$('s-run-records').innerHTML='<p class="s-help">正在读取最近运行结果…</p>';return;}
  const expanded=new Set([...$('s-run-records').querySelectorAll('details[open]')].map(node=>node.dataset.resultDetail));
  const ids=['integrated'];
  $('s-run-records').innerHTML=ids.map(id=>{
    const entry=runState?.providers[id];
    return `<section class="s-run-record"><h3>${esc(providerName(id))}</h3>${renderRunResult(entry?.result_summary,{compact:selectedProvider==='overview',id})}</section>`;
  }).join('');
  for(const node of $('s-run-records').querySelectorAll('details'))node.open=expanded.has(node.dataset.resultDetail);
}
async function refreshRun() {
  try {runState=await uiNext.request('/api/ui-next/run');renderRun();}
  catch(error){$('s-run-feedback').textContent=error.message;}
}
$('s-run-operations').addEventListener('change',event=>{
  const id=event.target.dataset.discoveryProvider;if(!id)return;
  const selected=new Set(draft.monitor.enabledProviders);
  if(event.target.checked)selected.add(id);else selected.delete(id);
  draft.monitor.enabledProviders=providerOrder().filter(provider=>selected.has(provider));
  changed({immediate:true});
});
$('s-providers').addEventListener('click',event=>{const button=event.target.closest('[data-provider]');if(button){selectedProvider=button.dataset.provider;renderRun();runLayoutHost.closeFlyout();runLayoutHost.openSidebar('configuration');}});
$('s-run-overview-open').addEventListener('click',()=>{selectedProvider='overview';renderRun();runLayoutHost.closeFlyout();runLayoutHost.closeSidebar();});
$('s-wos-access').addEventListener('click',()=>window.workspaceNavigation.go('login',{instant:true}));
$('s-provider-alias').addEventListener('change',()=>{
  const id=selectedProvider;if(id==='overview')return;
  const input=$('s-provider-alias'),value=input.value.trim();
  if(!value || value.length>120 || /[\x00-\x1f]/.test(value)){message('Display alias 必须为 1–120 个可打印字符。','error');input.value=providerName(id);return;}
  if(value===providerDefaults[id])delete draft.monitor.aliases[id];else draft.monitor.aliases[id]=value;
  changed({immediate:true});
});
function moveProvider(direction) {
  const order=providerOrder(),index=order.indexOf(selectedProvider),to=index+direction;
  if(index<0 || to<0 || to>=order.length)return;
  [order[index],order[to]]=[order[to],order[index]];changed({immediate:true});
}
$('s-provider-up').addEventListener('click',()=>moveProvider(-1));
$('s-provider-down').addEventListener('click',()=>moveProvider(1));
$('s-run-refresh').addEventListener('click',()=>void refreshRun());
$('s-run-retry').addEventListener('click',()=>void window.uiRun?.retry());
root.addEventListener('click',event=>{const button=event.target.closest('[data-run-provider]');if(button && !button.disabled)void window.uiRun?.start(button.dataset.runProvider,button);});
window.uiRunPage={
  canRun:id=>!runBlockReason() && !!expressions[id]?.expression && !expressions[id]?.error,
  providerName,selectedProviders:()=>[...draft.monitor.enabledProviders],refresh:refreshRun,updateButtons:updateRunButtons,
  open:()=>openSettings('run',true),
  report:(text,details=[],retry=false)=>{$('s-run-feedback').textContent=[text,...details].join('\n');$('s-run-retry').hidden=!retry;},
};
window.addEventListener('settings-draft-changed',updateRunButtons);
// refreshWorkspace releases snapshotApplying before renderEnrich emits this event.
window.addEventListener('enrich-state',updateRunButtons);
window.addEventListener('run-state',event=>{runState=event.detail;renderRun();});

function entityName(value,labels=false) {
  if(typeof value!=='string' || !value.trim() || /[|\p{C}\u2028\u2029]/u.test(value) || (labels && value.includes(';')))throw new Error('名称不能为空，不能包含竖线、换行、控制字符；标签还不能包含分号。');
  return value.trim();
}
function labelName(value) {return entityName(value,true);}
const labelKey=name=>'label:'+name;
function scopeInfo(scope=ui.scope) {
  return scope==='subject'?{items:list().groups,entity:'Group',empty:'Ungrouped',kind:'group'}:
    scope==='access'?{items:list().services,entity:'Service',empty:'Unassigned',kind:'service'}:
      {items:list().labels,entity:'Label',empty:'Unlabeled',kind:'label'};
}
function entityMembers(id=ui.directory[ui.scope],scope=ui.scope) {
  return sources().filter(j=>{
    if(id==='all')return true;
    if(scope==='subject')return id==='none'?!j.groupId:j.groupId===id;
    if(scope==='access')return id==='none'?!j.serviceId:j.serviceId===id;
    return id==='none'?!j.labels.length:j.labels.some(name=>labelKey(name)===id);
  });
}
function selectedEntity(scope=ui.scope) {return scopeInfo(scope).items.find(item=>item.id===ui.directory[scope]);}
function directoryRow(id,name,count,index,current,kind) {
  const rail=Math.round(6+18*Math.log10(count+1)/Math.log10(Math.max(10,sources().length)+1));
  return `<button class="kept-manager-row s-directory-row" data-entity="${esc(id)}" data-kind="${kind}" title="${esc(name)}" style="--index-rail:${rail}px" aria-current="${current===id}" ${kind==='group' && !['all','none'].includes(id)?'draggable="true"':''}><span class="rhine-index-number">${String(index).padStart(2,'0')}</span><span class="rhine-index-name">${esc(name)}</span><span class="rhine-index-count">${count}</span></button>`;
}
function renderDirectory() {
  const info=scopeInfo(directoryScope),id=ui.directory[directoryScope],container=$('s-entities'),scroll=container.scrollTop,horizontal=container.scrollLeft,focused=document.activeElement?.dataset.entity;
  const entries=[{id:'all',name:'All '+sourceName()},{id:'none',name:info.empty},...info.items];
  container.innerHTML=entries.map((item,i)=>directoryRow(item.id,item.name,entityMembers(item.id,directoryScope).length,i,id,info.kind)).join('');
  container.scrollTop=scroll;container.scrollLeft=horizontal;
  if(focused)container.querySelector(`[data-entity="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
  const index=info.items.indexOf(selectedEntity(directoryScope));
  $('s-edit-entity').disabled=$('s-delete-entity').disabled=index<0;
  $('s-entity-up').disabled=index<=0;$('s-entity-down').disabled=index<0 || index===info.items.length-1;
  for(const [button,action] of [['s-edit-entity','Edit'],['s-new-entity','New'],['s-delete-entity','Delete'],['s-entity-up','Move up'],['s-entity-down','Move down']]){
    $(button).setAttribute('aria-label',`${action} ${info.entity}`);$(button).title=`${action} ${info.entity}`;
  }
  $('journal-directory-title').textContent={subject:'SUBJECT',access:'ACCESS',custom:'LABEL'}[directoryScope];
}
function visibleJournals() {
  const query=ui.search.trim().toLowerCase();
  return entityMembers().filter(j=>`${j.name} ${identifiers(j).join(' ')} ${(j.aliases || []).join(' ')}`.toLowerCase().includes(query));
}
function coverOf(j) {return covers.get(j.id) || {image:null,phase:'Generated'};}
function coverStyle(cover) {
  const size=Math.min(cover.width,cover.height),crop=cover.crop || {x:(cover.width-size)/2,y:(cover.height-size)/2,size};
  return `width:${cover.width/crop.size*100}%;left:${-crop.x/crop.size*100}%;top:${-crop.y/crop.size*100}%`;
}
function renderJournals() {
  stopJournalTitleScroll();
  const container=$('s-journals'),scroll=container.scrollTop,items=visibleJournals(),focused=document.activeElement?.dataset.journal;
  container.className=journalLayout==='grid'?'s-journal-grid':'s-journal-list';
  container.innerHTML=items.length?items.map(j=>{
    const attrs=`data-journal="${esc(j.id)}" data-current="${ui.journal===j.id && ui.detail==='journal'}" draggable="true" tabindex="0" role="group" aria-label="${esc(j.name)} · Enter for details"`;
    if(journalLayout==='array')return `<article class="s-journal-row" ${attrs}><div><strong data-journal-title title="${esc(j.name)}">${esc(j.name)}</strong><small>${esc(identifiers(j).join(' / '))} · ${esc(groupName(j.groupId))}</small></div></article>`;
    const cover=coverOf(j);
    return `<article class="s-journal-card" ${attrs}><div class="s-card-art">${cover.image?`<img src="${esc(cover.image)}" alt="${esc(j.name)} cover" loading="lazy" style="${coverStyle(cover)}">`:'<span class="s-eyebrow">GENERATED COVER</span>'}</div><h3 data-journal-title title="${esc(j.name)}">${esc(j.name)}</h3><p class="s-card-meta">${esc(identifiers(j).join(' / '))}<br>${esc(groupName(j.groupId))}</p>${j.labels.length?`<p class="s-card-labels">${j.labels.map(esc).join(' · ')}</p>`:''}</article>`;
  }).join(''):`<p class="s-empty">${sources().length?'没有符合筛选的来源。':'关注列表为空，请添加来源。'}</p>`;
  container.scrollTop=scroll;
  container.querySelectorAll('[data-journal-title]').forEach(bindJournalTitleScroll);
  if(focused)container.querySelector(`[data-journal="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
}
function assignmentOf(j) {return {groupId:j.groupId,serviceId:j.serviceId,labels:[...j.labels]};}
function clearAssignmentUndo() {assignmentUndo=null;}
function changeJournalAssignment(j,patch) {
  const before=assignmentOf(j),after={...before,...patch};
  if(same(before,after))return;
  Object.assign(j,copy(after));assignmentUndo={id:j.id,before,after};
  changed({immediate:true});renderJournalsPage();
}
function undoJournalAssignment() {
  if(loading || operationPending || preview || reconcileRequired || !assignmentUndo)return;
  const {id,before,after}=assignmentUndo,j=journal(id);
  if(!j || !same(assignmentOf(j),after)){clearAssignmentUndo();updateDirty();return;}
  Object.assign(j,copy(before));clearAssignmentUndo();changed({immediate:true});renderJournalsPage();
}
$('s-undo').addEventListener('click',undoJournalAssignment);
function journalIdentity(j) {
  return `<dl><div><dt>ISSN</dt><dd>${esc(j.issn || '—')}</dd></div><div><dt>eISSN</dt><dd>${esc(j.eissn || '—')}</dd></div></dl>`;
}
function renderEntityDetail() {
  const info=scopeInfo(),entity=selectedEntity(),description=$('s-entity-description'),rows=entityMembers();
  $('s-entity-detail').hidden=ui.detail!=='entity';
  if(!entity){description.innerHTML=`<h2>${esc(ui.directory[ui.scope]==='all'?'All '+sourceName():info.empty)}</h2><p class="s-help">${rows.length} ${sourceName()}</p>`;return;}
  description.innerHTML=`<label>${info.entity} name<input id="s-entity-name" value="${esc(entity.name)}" autocomplete="off"></label>${ui.scope==='access'?`<label>Access Method<select data-service-field="method"><option value="carsi">CARSI</option><option value="manual">Manual Login</option></select></label><label>Service URL<input data-service-field="url" value="${esc(entity.url)}" type="url" placeholder="Optional public HTTP(S) URL"></label>`:''}<p class="s-help">${rows.length} ${sourceName()}</p>`;
  $('s-entity-name').addEventListener('change',event=>renameEntity(entity,event.target.value));
  if(ui.scope==='access'){
    description.querySelector('select').value=entity.method;
    description.querySelectorAll('[data-service-field]').forEach(input=>input.addEventListener(input.tagName==='SELECT'?'change':'input',()=>{
      if(entity[input.dataset.serviceField]===input.value)return;
      entity[input.dataset.serviceField]=input.value;changed({immediate:input.tagName==='SELECT'});
    }));
  }
}
function renderJournalDetail() {
  const j=journal(ui.journal),detail=$('s-journal-detail'),actions=$('s-journal-actions');
  detail.hidden=actions.hidden=ui.detail!=='journal' || !j;
  if(!j){detail.innerHTML='';actions.innerHTML='';return;}
  const cover=coverOf(j),isSaved=saved.list.journals.some(row=>row.id===j.id),busy=coverJob.busy;
  const previous=$('s-journal-labels'),open=previous?.dataset.journalId===j.id && previous.open;
  const labelScroll=previous?.querySelector('.s-label-options')?.scrollTop || 0;
  const labelSummary=j.labels.join('; ') || 'Unlabeled';
  detail.innerHTML=`<h2>${esc(j.name)}</h2><section class="s-journal-cover" aria-label="Cover"><div class="s-context-title">COVER</div>${cover.image?`<img class="s-cover" src="${esc(cover.image)}" alt="${esc(j.name)} cover">`:''}<div class="s-cover-status" role="status">${esc(cover.phase)}${coverJob.journal_key===j.id && coverJob.message?' · '+esc(coverJob.message):''}${isSaved?'':' · Save Journal before Cover operations'}</div><div class="s-cover-controls"><button data-cover="search" class="s-button" ${!isSaved || busy || !coverJob.supported?'disabled':''}>Search</button><button data-cover="upload" class="s-button" ${!isSaved || busy?'disabled':''}>Upload</button><button data-cover="crop" class="s-button" ${!isSaved || busy || !cover.image?'disabled':''}>Crop</button>${coverJob.busy && coverJob.journal_key===j.id?'<button data-cover="cancel" class="s-button">Cancel</button>':''}</div></section>`+journalIdentity(j)+`<label>Group<select id="s-journal-group"><option value="">Ungrouped</option>${list().groups.map(g=>`<option value="${esc(g.id)}">${esc(g.name)}</option>`).join('')}</select></label><label>Service<select id="s-journal-service"><option value="">Unassigned</option>${list().services.map(s=>`<option value="${esc(s.id)}">${esc(s.name)}</option>`).join('')}</select></label><div class="s-label-field"><span id="s-label-caption">Label</span><details id="s-journal-labels" class="s-label-select" data-journal-id="${esc(j.id)}" ${open?'open':''}><summary aria-labelledby="s-label-caption s-label-summary"><span id="s-label-summary" title="${esc(labelSummary)}">${esc(labelSummary)}</span></summary><div class="s-label-options" role="group" aria-label="Label assignments">${list().labels.map(label=>`<label class="s-check"><input type="checkbox" data-journal-label="${esc(label.name)}" ${j.labels.includes(label.name)?'checked':''}>${esc(label.name)}</label>`).join('')}${list().labels.length?'':'<p class="s-help">在 LABEL 目录中添加标签。</p>'}</div></details></div>`;
  $('s-journal-group').value=j.groupId || '';$('s-journal-service').value=j.serviceId || '';
  $('s-journal-labels').querySelector('.s-label-options').scrollTop=labelScroll;
  $('s-journal-group').addEventListener('change',event=>changeJournalAssignment(j,{groupId:event.target.value || null}));
  $('s-journal-service').addEventListener('change',event=>changeJournalAssignment(j,{serviceId:event.target.value || null}));
  detail.querySelectorAll('[data-journal-label]').forEach(input=>input.addEventListener('change',()=>{
    assignLabel(j,input.dataset.journalLabel,input.checked);
    detail.querySelector(`[data-journal-label="${CSS.escape(input.dataset.journalLabel)}"]`)?.focus({preventScroll:true});
  }));
  actions.innerHTML=`<div class="s-context-divider s-remove-operation"><button class="s-button" data-remove-journal="${esc(j.id)}">Remove Journal</button></div>`;
  detail.querySelector('[data-cover=search]').addEventListener('click',()=>startCovers(j.id));
  detail.querySelector('[data-cover=upload]').addEventListener('click',()=>uploadCover(j));
  detail.querySelector('[data-cover=crop]').addEventListener('click',()=>cropCover(j));
  const resourceButton=document.createElement('button');resourceButton.className='s-button';resourceButton.textContent='Discover / choose Service';resourceButton.disabled=!isSaved;resourceButton.addEventListener('click',()=>void journalResources(j).catch(error=>message(error.message,'error')));detail.append(resourceButton);
  detail.querySelector('[data-cover=cancel]')?.addEventListener('click',()=>void coverAction('/settings/covers/search/cancel',{request_id:coverJob.request_id}));
}
async function journalResources(j) {
  if(!await window.allfoldAutosave?.flush()){message('配置尚未保存，草稿保留；请重试或处理冲突。','error');return;}
  const base='/api/ui-next/settings/journals/'+encodeURIComponent(j.id);
  let catalog=await formRequest('/api/ui-next/settings/catalog');
  const catalogOptions=()=>catalog.resources.map(r=>`<option value="${esc(r.production)}">${esc(r.production)}</option>`).join('');
  const choice=async(method)=>{
    const result=await formRequest(base+'/service',{selection_method:method,selection_name:method==='manual'?$('s-resource-name').value:$('s-resource-catalog').value,selection_url:$('s-resource-url').value});
    if(await acceptOperation(result))dialog.close();
  };
  showDialog('Journal Service · '+j.name,`<p>当前默认：${esc(list().services.find(s=>s.id===j.serviceId)?.name || 'Unresolved')}。同步只读取共享证据，保存选择仅影响此 Journal 与当前配置。</p><p id="s-catalog-status">Catalog: ${esc(catalog.status)} ${esc(catalog.error || '')}</p><label>Official CARSI Resource<select id="s-resource-catalog">${catalogOptions()}</select></label><label>Manual Service name<input id="s-resource-name"></label><label>Manual public HTTP(S) URL<input id="s-resource-url" type="url"></label><details open><summary>GOKB / CARSI evidence</summary><pre id="s-resource-evidence">尚未查询 GOKB。可直接选择官方 CARSI、Manual 或 Unresolved。</pre></details>`,[
    cancel,
    {label:'Refresh Catalog',run:async()=>{catalog=await formRequest('/api/ui-next/settings/catalog',{refresh:'yes'});$('s-resource-catalog').innerHTML=catalogOptions();$('s-catalog-status').textContent='Catalog: '+catalog.status+' '+(catalog.error || '')+' '+JSON.stringify(catalog.changes);return false;}},
    {label:'Discover GOKB',run:async()=>{$('s-resource-evidence').textContent=JSON.stringify(await formRequest(base+'/resolve'),null,2);return false;}},
    {label:'Refresh GOKB / Catalog',run:async()=>{$('s-resource-evidence').textContent=JSON.stringify(await formRequest(base+'/resolve',{refresh:'yes'}),null,2);return false;}},
    {label:'Use unique candidate',run:()=>choice('auto')},
    {label:'Save CARSI',primary:true,run:()=>choice('carsi')},
    {label:'Save Manual',run:()=>choice('manual')},
    {label:'Keep Unresolved',run:()=>choice('unresolved')},
  ]);
}
function renderJournalsPage() {
  renderDirectory();
  stopJournalTitleScroll();
  const info=scopeInfo(),id=ui.directory[ui.scope];
  $('s-journals-title').textContent=$('s-journals-title').title=id==='all'?'All '+sourceName():id==='none'?info.empty:selectedEntity()?.name || 'All '+sourceName();
  renderJournals();renderEntityDetail();renderJournalDetail();syncLayouts();workspaceSearch.refresh();
}
function assignLabel(j,name,assigned) {
  if(!list().labels.some(label=>label.name===name))return;
  const labels=assigned?[...new Set([...j.labels,name])]:j.labels.filter(label=>label!==name);
  changeJournalAssignment(j,{labels});
}
function renameEntity(entity,value) {
  const info=scopeInfo();let name;
  try{name=entityName(value,ui.scope==='custom');}catch(error){message(error.message,'error');renderEntityDetail();return;}
  if(name===entity.name)return;
  const target=info.items.find(row=>row.id!==entity.id && (ui.scope==='custom'?row.name===name:row.name.toLowerCase()===name.toLowerCase()));
  if(target && ui.scope!=='custom'){message('名称重复。','error');renderEntityDetail();return;}
  const previous=entity.id,oldName=entity.name;
  if(ui.scope==='subject'){
    entity.id=groupKey(name);
    for(const j of list().journals)if(j.groupId===previous)j.groupId=entity.id;
    if(assignmentUndo)for(const snapshot of [assignmentUndo.before,assignmentUndo.after])if(snapshot.groupId===previous)snapshot.groupId=entity.id;
  }else if(ui.scope==='custom'){
    const replace=labels=>[...new Set(labels.map(label=>label===oldName?name:label))];
    for(const j of list().journals)j.labels=replace(j.labels);
    if(assignmentUndo)for(const snapshot of [assignmentUndo.before,assignmentUndo.after])snapshot.labels=replace(snapshot.labels);
    if(target)list().labels=list().labels.filter(row=>row.id!==previous);else entity.id=labelKey(name);
  }
  entity.name=name;ui.directory[ui.scope]=target?.id || entity.id;
  changed({immediate:true});renderJournalsPage();
}
function moveEntity(direction) {
  const items=scopeInfo().items,from=items.indexOf(selectedEntity()),to=from+direction;
  if(from<0 || to<0 || to>=items.length)return;
  const [entity]=items.splice(from,1);items.splice(to,0,entity);changed({immediate:true});renderDirectory();
}
function deleteEntity() {
  const entity=selectedEntity();if(!entity)return;
  const info=scopeInfo(),scope=ui.scope,members=list().journals.filter(j=>ui.scope==='subject'?j.groupId===entity.id:ui.scope==='custom'?j.labels.includes(entity.name):j.serviceId===entity.id);
  const effect=scope==='subject'?'将移至 Ungrouped，保留 Custom Labels。':scope==='access'?'将成为 Unassigned。':'将移除此标签的全部分配。';
  showDialog(`Delete ${info.entity}`,`<p>${esc(entity.name)}${scope==='access'?' / '+esc(entity.id):''}</p><p>${members.length} Journals ${effect}</p>${memberList(members.map(j=>j.name))}`,[cancel,{label:`Delete ${info.entity}`,primary:true,run:async()=>{
    if(scope==='access'){
      if(!await autosave?.flush())return false;
      const source=copy(saved);source.list.services=source.list.services.filter(row=>row.id!==entity.id);
      for(const journal of source.list.journals)if(journal.serviceId===entity.id)journal.serviceId=null;
      return applyExplicit(source,{}, {skipFlush:true});
    }
    const refers=snapshot=>scope==='subject'?snapshot.groupId===entity.id:scope==='access'?snapshot.serviceId===entity.id:snapshot.labels.includes(entity.name);
    if(assignmentUndo && [assignmentUndo.before,assignmentUndo.after].some(refers))clearAssignmentUndo();
    for(const j of members){if(scope==='subject')j.groupId=null;else if(scope==='access')j.serviceId=null;else j.labels=j.labels.filter(label=>label!==entity.name);}
    if(scope==='subject')list().groups=list().groups.filter(row=>row.id!==entity.id);
    else if(scope==='access')list().services=list().services.filter(row=>row.id!==entity.id);
    else list().labels=list().labels.filter(row=>row.id!==entity.id);
    ui.directory[scope]='none';ui.detail='entity';changed({immediate:true});renderJournalsPage();
  }}]);
}
function createEntity() {
  const info=scopeInfo(),scope=ui.scope;
  showDialog(`New ${info.entity}`,`<label>${info.entity} name<input id="s-new-entity-name" autocomplete="off"></label>${scope==='access'?'<label>Service URL<input id="s-new-service-url" placeholder="Optional HTTP(S) URL"></label><label>Access Method<select id="s-new-service-method"><option value="carsi">CARSI</option><option value="manual">Manual Login</option></select></label>':''}<p id="s-entity-error" role="alert"></p>`,[cancel,{label:'Create',primary:true,run:()=>{
    let name;try{name=entityName($('s-new-entity-name').value,scope==='custom');}catch(error){$('s-entity-error').textContent=error.message;return false;}
    if(info.items.some(item=>scope==='custom'?item.name===name:item.name.toLowerCase()===name.toLowerCase())){$('s-entity-error').textContent='名称重复。';return false;}
    const entity=scope==='access'?{id:'svc_'+crypto.randomUUID().replaceAll('-',''),name,url:$('s-new-service-url').value.trim(),method:$('s-new-service-method').value}:{id:scope==='subject'?groupKey(name):labelKey(name),name};
    info.items.push(entity);ui.directory[scope]=entity.id;ui.detail='entity';changed({immediate:true});renderJournalsPage();journalLayoutHost.openSidebar('details');
  }}]);$('s-new-entity-name').focus();
}
function activateDirectory() {if(ui.scope!==directoryScope)setJournalScope(directoryScope);}
$('s-edit-entity').addEventListener('click',()=>{activateDirectory();ui.detail='entity';renderEntityDetail();renderJournalDetail();journalLayoutHost.openSidebar('details');journalLayoutHost.closeFlyout();});
$('s-new-entity').addEventListener('click',()=>{activateDirectory();createEntity();});
$('s-entity-up').addEventListener('click',()=>{activateDirectory();moveEntity(-1);});$('s-entity-down').addEventListener('click',()=>{activateDirectory();moveEntity(1);});
$('s-delete-entity').addEventListener('click',()=>{activateDirectory();deleteEntity();});
$('s-entities').addEventListener('click',event=>{const row=event.target.closest('[data-entity]');if(!row)return;ui.scope=directoryScope;ui.directory[ui.scope]=row.dataset.entity;ui.detail='entity';ui.journal=null;renderJournalsPage();journalLayoutHost.closeSidebar();journalLayoutHost.closeFlyout();});
function selectJournal(id) {ui.journal=id;ui.detail='journal';renderJournalsPage();journalLayoutHost.openSidebar('details');}
$('s-journals').addEventListener('click',event=>{const row=event.target.closest('[data-journal]');if(row)selectJournal(row.dataset.journal);});
$('s-journals').addEventListener('keydown',event=>{if(event.target.matches('[data-journal]') && ['Enter',' '].includes(event.key)){event.preventDefault();selectJournal(event.target.dataset.journal);$('s-journals').querySelector(`[data-journal="${CSS.escape(ui.journal)}"]`)?.focus({preventScroll:true});}});
root.addEventListener('click',event=>{const button=event.target.closest('[data-remove-journal]');if(button)removeJournal(journal(button.dataset.removeJournal));});
function removeJournal(j) {
  if(!j)return;
  confirm('Remove Journal',`${j.name} / ${identifiers(j).join(' / ')}。仅从监测名单移除；保留 Workspace Papers、封面资产、Group 和 Label 注册项。`,()=>{
    if(assignmentUndo?.id===j.id)clearAssignmentUndo();
    list().journals=list().journals.filter(row=>row.id!==j.id);
    if(ui.journal===j.id){ui.journal=null;ui.detail='entity';}
    changed({immediate:true});renderJournalsPage();
  },'Remove from list');
}
$('s-add-journal').addEventListener('click',()=>{
  let candidates=[];
  showDialog('Add Journal','<label>Name / ISSN / eISSN<input id="s-add-query" autocomplete="off"></label><div id="s-add-results"></div><p id="s-add-error" role="alert"></p>',[
    cancel,
    {label:'Search',run:async()=>{
      const query=$('s-add-query').value.trim();
      candidates=[];$('s-add-results').replaceChildren();$('s-add-error').textContent='';
      if(!query){$('s-add-error').textContent='请输入期刊名称、ISSN 或 eISSN。';return false;}
      try {
        const response=await fetch('/api/ui-next/settings/journals/search?q='+encodeURIComponent(query),{cache:'no-store'});
        const data=await response.json();
        if(!response.ok)throw new Error(data.message || 'Journal lookup failed');
        if(!dialog.open || $('s-add-query')?.value.trim()!==query)return false;
        candidates=data.candidates;
        $('s-add-results').innerHTML=candidates.map((c,i)=>`<label class="s-lookup-candidate"><input type="radio" name="journal-candidate" value="${i}"><span><strong>${esc(c.name)}</strong><small>ISSN ${esc(c.issn || '—')} · eISSN ${esc(c.eissn || '—')}</small></span></label>`).join('');
        if(!candidates.length)$('s-add-error').textContent='未找到具有有效标识的期刊。';
      }catch(error){if($('s-add-error'))$('s-add-error').textContent=error.message;}
      return false;
    }},
    {label:'Add to Draft',primary:true,run:()=>{
      const chosen=$('s-add-results').querySelector('input:checked');
      if(!chosen){$('s-add-error').textContent='请选择一条候选记录。';return false;}
      const c=candidates[Number(chosen.value)];
      if(list().journals.some(j=>identifiers(j).some(i=>[c.issn,c.eissn].includes(i)))){
        $('s-add-error').textContent='候选标识与已有 Journal 重叠；请检查身份冲突，不会自动合并。';return false;
      }
      const id=c.issn || c.eissn;
      const added={id,name:c.name,issn:c.issn,eissn:c.eissn,serviceId:ui.scope==='access'?(selectedEntity()?.id || null):null,groupId:ui.scope==='subject'?(selectedEntity()?.id || null):null,labels:ui.scope==='custom' && selectedEntity()?[selectedEntity().name]:[]};
      list().journals.push(added);
      ui.journal=id;ui.detail='journal';changed({immediate:true});renderJournalsPage();message('Journal 已加入 Draft。');
    }}
  ]);
  $('s-add-query').addEventListener('input',()=>{candidates=[];$('s-add-results').replaceChildren();});
  $('s-add-query').focus();
});

// One native drag payload; assignment controls provide the keyboard alternative.
let drag=null;
root.addEventListener('dragstart',event=>{
  const node=event.target.closest('[data-journal],[data-entity][draggable]');if(!node)return;
  drag=node.dataset.journal?{kind:'journal',id:node.dataset.journal}:{kind:'group',id:node.dataset.entity};
  event.dataTransfer.setData('text/plain',JSON.stringify(drag));event.dataTransfer.effectAllowed='move';
});
function dropTarget(event) {
  const node=event.target.closest('[data-entity]');if(!drag || !node || node.dataset.entity==='all')return null;
  if(drag.kind==='journal' && ['subject','access'].includes(directoryScope))return node;
  if(drag.kind==='group' && directoryScope==='subject' && group(node.dataset.entity))return node;
  return null;
}
root.addEventListener('dragover',event=>{const target=dropTarget(event);if(target){event.preventDefault();event.dataTransfer.dropEffect='move';target.dataset.drop='true';}});
root.addEventListener('dragleave',event=>{event.target.closest('[data-drop]')?.removeAttribute('data-drop');});
root.addEventListener('drop',event=>{
  const target=dropTarget(event);if(!target)return;event.preventDefault();
  if(drag.kind==='journal'){
    const j=journal(drag.id),next=target.dataset.entity==='none'?null:target.dataset.entity;
    if(j)changeJournalAssignment(j,directoryScope==='subject'?{groupId:next}:{serviceId:next});
  }else{
    const items=list().groups,from=items.findIndex(g=>g.id===drag.id),to=items.findIndex(g=>g.id===target.dataset.entity);
    if(from>=0 && to>=0 && from!==to){const [g]=items.splice(from,1);items.splice(to,0,g);changed({immediate:true});renderDirectory();}
  }
  drag=null;root.querySelectorAll('[data-drop]').forEach(node=>node.removeAttribute('data-drop'));
});
root.addEventListener('dragend',()=>{drag=null;root.querySelectorAll('[data-drop]').forEach(node=>node.removeAttribute('data-drop'));});

async function refreshCovers() {
  clearTimeout(coverTimer);
  try {
    coverJob=await uiNext.request('/settings/covers/search');
    const data=await uiNext.request('/api/ui-next/settings');applyCoverDetails(data);
    renderJournalsPage();
  } catch(error){message(error.message,'error');}
  if(coverJob.phase==='Running')coverTimer=setTimeout(refreshCovers,1000);
}
async function coverAction(path,extra={}) {
  try {await formRequest(path,extra,{draft:false});await refreshCovers();}
  catch(error){message(error.message,'error');}
}
function startCovers(id) {
  if(typeof id!=='string' || !id.trim())return;
  void coverAction('/settings/covers/search',{journal_key:id});
}

function cropCover(j) {
  const cover=coverOf(j);
  if(!cover.image || coverJob.busy)return;
  const editor={instance:null,ready:false,pending:false};
  showDialog('Crop Cover',`<div class="s-crop-stage"><img id="s-crop-image" src="${esc(cover.image)}" alt="${esc(j.name)} cover"></div><label class="s-crop-zoom">Zoom<input id="s-crop-zoom" type="range" step="any" disabled></label><p class="s-help">拖动图片或裁剪框，调整边角改变裁剪区域。Apply 立即保存。</p><p id="s-crop-error" class="s-field-error" role="alert"></p>`,[cancel,{label:'Apply',primary:true,disabled:true,run:async()=>{
    if(!editor.ready || editor.pending)return false;
    editor.pending=true;cancelButton.disabled=zoom.disabled=true;error.textContent='';editor.instance.disable();
    try {
      const data=editor.instance.getData(),epsilon=Math.max(cover.width,cover.height)*1e-7;
      const edge=(value,limit)=>value<0 && value>=-epsilon?0:value>limit && value<=limit+epsilon?limit:value;
      const size=edge(Math.min(data.width,data.height),Math.min(cover.width,cover.height));
      const result=await formRequest('/settings/covers/'+encodeURIComponent(j.id)+'/crop',{
        sha256:cover.sha256,x:edge(data.x,cover.width-size),y:edge(data.y,cover.height-size),size,
      },{draft:false});
      setCoverDetail(j.id,result.cover);renderJournals();renderJournalDetail();return true;
    } catch(failure){error.textContent=failure.message;return false;}
    finally {editor.pending=false;cancelButton.disabled=zoom.disabled=false;editor.instance.enable();}
  }}]);
  cropEditor=editor;dialog.classList.add('s-crop-dialog');
  const img=$('s-crop-image'),zoom=$('s-crop-zoom'),error=$('s-crop-error');
  const cancelButton=$('s-dialog-actions').firstElementChild,apply=$('s-dialog-actions').lastElementChild;
  const active=()=>cropEditor===editor && dialog.open;
  zoom.addEventListener('input',()=>editor.instance?.zoomTo(Number(zoom.value)));
  void img.decode().then(()=>{
    if(!active())return;
    if(img.naturalWidth!==cover.width || img.naturalHeight!==cover.height)throw new Error('封面已更换，请重新打开 Crop。');
    const side=Math.min(cover.width,cover.height),crop=cover.crop || {x:(cover.width-side)/2,y:(cover.height-side)/2,size:side};
    editor.instance=new window.Cropper(img,{
      aspectRatio:1,viewMode:1,dragMode:'move',autoCropArea:1,
      movable:true,cropBoxMovable:true,cropBoxResizable:true,zoomable:true,
      rotatable:false,scalable:false,checkOrientation:false,checkCrossOrigin:false,toggleDragModeOnDblclick:false,
      data:{x:crop.x,y:crop.y,width:crop.size,height:crop.size},
      ready(){
        if(!active())return;
        const data=this.cropper.getImageData(),ratio=data.width/data.naturalWidth;
        zoom.min=ratio/4;zoom.max=ratio*8;zoom.value=ratio;
        editor.ready=true;apply.disabled=zoom.disabled=false;
      },
      zoom(event){if(editor.ready)zoom.value=event.detail.ratio;},
    });
  }).catch(failure=>{if(active()){error.textContent='无法初始化裁剪：'+failure.message;apply.disabled=true;}});
}
function uploadCover(j) {
  showDialog('Upload Cover','<label>Image file<input id="s-upload-file" type="file" accept="image/*"></label><p id="s-upload-error" role="alert"></p>',[cancel,{label:'Upload',primary:true,run:async()=>{
    const file=$('s-upload-file').files[0];if(!file){$('s-upload-error').textContent='请选择图片。';return false;}
    await coverAction('/settings/covers/'+encodeURIComponent(j.id)+'/upload',{file});
  }}]);
}
window.addEventListener('pagehide',()=>clearTimeout(coverTimer));

function closePreview() {
  preview=null;$('s-file-preview').hidden=true;$('s-'+view).hidden=false;
  updateDirty();restoreScroll();window.workspaceNavigation.refresh();$('s-files').focus({preventScroll:true});
}
function beginPreview(kind,title,filename,summary,columns,choices) {
  rememberScroll();transitions.get(view).dispose();$('s-'+view).hidden=true;
  preview={kind,revision};$('s-file-preview').hidden=false;
  window.workspaceNavigation.refresh();
  $('s-preview-title').textContent=title;$('s-preview-file').textContent=filename;$('s-preview-summary').textContent=summary;
  $('s-preview-columns').innerHTML=columns.map(({title,text})=>`<div><h3>${esc(title)}</h3><pre>${esc(text)}</pre></div>`).join('');
  $('s-preview-columns').style.gridTemplateColumns=columns.length===1?'minmax(0,1fr)':'';
  $('s-preview-actions').replaceChildren();
  for(const choice of choices){const button=document.createElement('button');button.className='s-button'+(choice.primary?' s-primary':'');button.textContent=choice.label;button.addEventListener('click',async()=>{button.disabled=true;try{await choice.run();}catch(error){message(error.message,'error');}finally{button.disabled=false;}});$('s-preview-actions').append(button);}
  updateDirty();$('s-preview-title').tabIndex=-1;$('s-preview-title').focus({preventScroll:true});
}
function selectImport() {
  showDialog('Import Research Scope','<label>Markdown file<input id="s-import-file" type="file" accept=".md,text/markdown"></label><label><input id="s-import-query" type="checkbox"> 对缺少有效 Service 的 Journal 查询 GOKB（可选）</label><p class="s-help">支持 Journals 名称列表或表格。Preview 后选择身份、补充名称/ISSN 或 Service，再确认增量添加。</p><p id="s-import-error" role="alert"></p>',[cancel,{label:'Preview',primary:true,run:async()=>{
    const file=$('s-import-file').files[0];if(!file){$('s-import-error').textContent='请选择 .md 文件。';return false;}
    await openImport(file,{},$('s-import-query').checked);
  }}]);
}
function importChoices() {
  return readImportChoices($('s-preview-columns'));
}
async function openImport(file,choices={},query=false) {
  if(!await window.allfoldAutosave?.flush()){message('普通配置尚未落盘，请先处理保存状态。','error');return;}
  const data=await formRequest('/settings/import/preview',{markdown_file:file,import_choices:JSON.stringify(choices),query_gokb:query?'yes':'no'});
  showIssues(data);
  if(!data.import_plan)return false;
  const p=data.import_plan;
  beginPreview('import','Import Research Scope Preview',data.import_filename,p.changes.join('\n') || '没有待添加的已识别 Journal；可补充或选择候选。',[],[
    {label:'Cancel Import',run:closePreview},
    {label:'Update Preview',run:()=>openImport(file,importChoices(),$('s-preview-query').checked)},
    {label:'Confirm Import',primary:true,run:confirmImport}]);
  Object.assign(preview,{data,file});
  $('s-preview-columns').innerHTML=`<div><label><input type="checkbox" id="s-preview-query" ${query?'checked':''}> 对缺少有效 Service 的 Journal 查询 GOKB</label>${p.services.map(s=>`<p>${esc(s.name)} · ${esc(s.status)} · ${esc(s.message)}</p>`).join('')}${renderImportRows(p,choices)}</div>`;
  const confirmButton=$('s-preview-actions').lastElementChild;
  $('s-preview-columns').addEventListener('input',()=>{confirmButton.disabled=true;$('s-preview-summary').textContent='Selections changed. Choose Update Preview before Confirm.';},{once:true});
  return true;
}
async function executeImport(discard=false) {
  const current=preview;if(!current || current.kind!=='import')return;
  const data=await formRequest('/settings/import/confirm',{
    markdown_import_payload:current.data.import_payload,markdown_import_filename:current.data.import_filename,
    markdown_import_proof:current.data.import_proof,confirm_full_import:'yes',...(discard?{import_discard:'yes'}:{})});
  if(await acceptOperation(data) && discard)await loadCASStatus();
}
function confirmImport() {
  if(!dirty())return executeImport();
  showDialog('Resolve unsaved Settings','<p>Import 将增量添加到当前配置。明确 Discard 会丢弃全部 Settings 草稿；已保存的其他 Journal 保留。</p>',[
    cancel,{label:'Save & refresh Preview',run:async()=>{const file=preview.file;dialog.close();await saveDraft(()=>openImport(file));}},
    {label:'Discard all Draft & Import',primary:true,run:()=>executeImport(true)},
  ]);
}
async function exportFile(kind='list',discard=false) {
  if(!discard && !await window.allfoldAutosave?.flush()){message('普通配置尚未落盘，请先处理保存状态。','error');return;}
  if(dirty() && !discard){
    showDialog('Resolve unsaved Settings','<p>导出只使用已保存配置。请选择 Save、丢弃全部 Settings 草稿或 Cancel。</p>',[cancel,
      {label:'Save & export',run:async()=>{dialog.close();await saveDraft(()=>exportFile(kind));}},
      {label:'Discard all Draft & export',primary:true,run:()=>exportFile(kind,true)}]);return;
  }
  const result=await formRequest('/settings/export',discard?{export_discard:'yes'}:{},{download:true});
  if(!result.blob){showIssues(result);return;}
  if(discard){await loadSettings();await refreshSavedWorkspace();}
  const text=await result.blob.text();
  beginPreview(kind,'Export User Data',result.filename,'当前配置已保存的 Journal、Group、Label、Service 与顺序；不含凭据和外部缓存。',[{title:'Saved file',text}],[
    {label:'Return to Settings',run:closePreview},{label:'Download',primary:true,run:()=>{const url=URL.createObjectURL(result.blob),link=document.createElement('a');link.href=url;link.download=result.filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}}]);
}
function reloadSettings() {
  if(!draft){void loadSettings();
void refreshRun();return;}
  showDialog('Reload Settings from Disk','<p>丢弃全部未保存配置并重新读取文件。独立 Cover 资源保留。</p><label>Type RELOAD<input id="s-reload-word" autocomplete="off" spellcheck="false"></label><p id="s-reload-error" role="alert"></p>',[cancel,{label:'Reload / discard draft',primary:true,run:async()=>{
    if($('s-reload-word').value!=='RELOAD'){$('s-reload-error').textContent='请输入完整的 RELOAD。';return false;}
    await autosave?.pause();
    try{if(await acceptOperation(await formRequest('/settings/reload',{reload_step:'confirm',reload_word:'RELOAD'})))await loadCASStatus();}
    finally{autosave?.resume();}
  }}]);$('s-reload-word').focus();
}
root.querySelectorAll('[data-file-action]').forEach(button=>button.addEventListener('click',()=>{
  closeMenu();if(preview || operationPending){message('请先完成或退出当前操作。');return;}
  const actions={import:selectImport,export:()=>exportFile(),reload:reloadSettings};
  Promise.resolve(actions[button.dataset.fileAction]()).catch(error=>message(error.message,'error'));
}));

function reconcileSelections(filter=false) {
  for(const [scope,items] of [['subject',list().groups],['access',list().services],['custom',list().labels]]){
    const id=ui.directory[scope];if(!['all','none'].includes(id) && !items.some(item=>item.id===id))ui.directory[scope]='all';
  }
  if(!journal(ui.journal) || (filter && !visibleJournals().some(j=>j.id===ui.journal))){ui.journal=null;ui.detail='entity';}
}

// Group keys are derived from names and are never a persisted identity.
function groupKey(name) {return 'group:'+name;}
function project(data) {
  const v=data.values,order=v.provider_order;
  if(!Array.isArray(order) || order.length!==Object.keys(providerDefaults).length || new Set(order).size!==order.length || order.some(id=>!Object.hasOwn(providerDefaults,id)))throw new Error('provider_order 必须完整且不重复地列出所有支持的 Provider；请修正 YAML 后 Reload。');
  return {monitor:{name:v.name,expression:v.keyword_expression,enabledProviders:[...(v.enabled_providers || [])],aliases:{...(v.provider_aliases || {})},providerOrder:[...order],crossrefMailto:v.crossref_mailto || "",pubmedKeyAction:"keep",pubmedKey:v.pubmed_key_configured?keyMask:"",openalexKeyAction:"keep",openalexKey:v.openalex_key_configured?keyMask:"",from:v.from_month,to:v.to_month,
    workspace:v.output_dir,log:v.log_level,
    ...Object.fromEntries(concurrencyFields.map(([name,key])=>[key,v[name]])),zoteroTarget:v.zotero_target || null,institutionName:v.institution_name,
    idp:v.institution_idp_entity_id,useShibboleth:v.institution_use_shibboleth ?? false},
    revisions:{pubmed_key_revision:v.pubmed_key_revision || "missing",openalex_key_revision:v.openalex_key_revision || "missing",monitor_revision_exists:v.monitor_revision_exists,monitor_revision_digest:v.monitor_revision_digest,
      journal_revision_exists:v.journal_revision_exists,journal_revision_digest:v.journal_revision_digest},
    list:{journals:v.journals.map(j=>({id:j.issn || j.eissn,name:j.name,issn:j.issn || null,eissn:j.eissn || null,
        serviceId:j.access_service_id || null,groupId:j.group?groupKey(j.group):null,labels:j.labels?j.labels.split(';').map(labelName):[]})),
      services:v.access_services.map(s=>({id:s.id,name:s.name,url:s.access_url,method:s.access_method})),
      groups:v.groups.map(name=>({id:groupKey(name),name})),
      labels:v.custom_labels.map(name=>({id:labelKey(name),name}))}};
}
function setCoverDetail(id,detail) {
  const previous=covers.get(id),next={...detail,
    image:['Uploaded','Downloaded'].includes(detail.state)?'/settings/covers/'+encodeURIComponent(id)+'/image?revision='+detail.sha256:null,
    phase:detail.state+(detail.message?' · '+detail.message:'')};
  covers.set(id,next);
  if(!same(previous,next))window.dispatchEvent(new CustomEvent('journal-cover-changed',{detail:{journalKey:id,cover:detail}}));
}
function applyCoverDetails(data) {
  for(const [id,detail] of Object.entries(data.covers || {}))setCoverDetail(id,detail);
  for(const id of covers.keys())if(!Object.hasOwn(data.covers || {},id))covers.delete(id);
}
const ordinaryMonitorFields={zotero_target:'zoteroTarget',name:'name',keyword_expression:'expression',from_month:'from',to_month:'to',log_level:'log',enabled_providers:'enabledProviders',crossref_mailto:'crossrefMailto',provider_aliases:'aliases',provider_order:'providerOrder',...Object.fromEntries(concurrencyFields.map(([name,key])=>[name,key])),institution_name:'institutionName',institution_idp_entity_id:'idp',institution_use_shibboleth:'useShibboleth'};
function ordinaryValues(source=draft) {
  const values=Object.fromEntries(Object.entries(ordinaryMonitorFields).map(([field,key])=>[field,copy(source.monitor[key])]));
  values.groups=source.list.groups.map(group=>group.name);values.custom_labels=source.list.labels.map(label=>label.name);
  values.access_services=source.list.services.map(service=>({id:service.id,name:service.name,access_url:service.url,access_method:service.method}));
  values.journals=source.list.journals.map(journal=>({name:journal.name,issn:journal.issn || '',eissn:journal.eissn || '',group:source.list.groups.find(group=>group.id===journal.groupId)?.name || '',labels:journal.labels.join('; '),access_service_id:journal.serviceId || ''}));
  return values;
}
function ordinaryData(data) {
  return {base:Object.fromEntries(['monitor_revision_exists','monitor_revision_digest','journal_revision_exists','journal_revision_digest'].map(key=>[key,data.values[key]])),values:ordinaryValues(project(data))};
}
function applyOrdinaryValues(values) {
  for(const [field,key] of Object.entries(ordinaryMonitorFields))draft.monitor[key]=copy(values[field]);
  const projected=project({...serverState,values:{...serverState.values,...values}});
  const listChanged=!same(draft.list,projected.list);
  if(listChanged)draft.list=projected.list;
  for(const input of document.querySelectorAll('[data-monitor]')){
    if(document.activeElement===input || !Object.values(ordinaryMonitorFields).includes(input.dataset.monitor))continue;
    const value=draft.monitor[input.dataset.monitor];if(input.type==='checkbox')input.checked=value;else if(input.value!==String(value??''))input.value=value??'';
  }
  if(listChanged){reconcileSelections();renderJournalsPage();}
}
function initializeAutosave(data,{restore=false}={}) {
  if(!autosave) {
    let storage;try{storage=localStorage;}catch{}
    autosave=createAutosave({storage,key:'allfold.configuration-draft:'+data.config_path,
      write:async patch=>{
        const response=await fetch('/api/ui-next/settings/autosave',{method:'POST',cache:'no-store',headers:{Accept:'application/json','Content-Type':'application/json'},body:JSON.stringify({...patch,csrf_token:uiNext.csrf_token})});
        const result=await response.json();if(!response.ok)throw Error(result.message || 'Autosave failed');
        if(!result.saved){message(result.message || result.outcome,'error');if(result.outcome==='INVALID_DRAFT')showIssues(result);return result;}
        return {...result,...ordinaryData(result),response:result};
      },
      onSaved:(result,values)=>{
        const data=result.response;serverState=data;saved=project(data);draft.revisions=copy(saved.revisions);
        applyOrdinaryValues(values);reconcileRequired=false;applyCoverDetails(data);updateDirty();renderRun();
        clearValidationIssues();message('');
        window.dispatchEvent(new Event('settings-saved'));
      },
      onRestore:values=>{applyOrdinaryValues(values);},
      onState:state=>{autosaveStatus=state;updateDirty();updateRunButtons();},
    });
    window.allfoldZoteroPreference={get value(){return draft?.monitor.zoteroTarget || null;},
      async set(value){if(loading || operationPending)return false;draft.monitor.zoteroTarget=copy(value);changed({immediate:true});return await autosave.flush();}};
    window.allfoldAutosave={flush:async()=>{
      if(loading || operationPending || explicitDirty())return false;
      return await autosave.flush();
    },get status(){return autosave.status;},get dirty(){return autosave.dirty || explicitDirty();},get busy(){return autosave.busy || operationPending;}};
  }
  autosave.initialize(ordinaryData(data),{restore});
}
async function applyExplicit(source,approval={}, {skipFlush=false}={}) {
  if(operationPending || (!skipFlush && !await autosave?.flush()))return false;
  const retained=copy(draft.monitor),previous=copy(saved.monitor);
  source.revisions=copy(draft.revisions);
  const data=await formRequest('/settings/save',approval, {source});
  if(data.deletion_plan){
    const lines=data.deletion_plan.services.map(service=>'Service: '+service.name);
    for(const [id,members] of data.deletion_plan.service_members)for(const journal of members)lines.push(`${journal.name} → Unassigned (${id})`);
    showDialog('Confirm saved Service removal',`<p>影响由当前磁盘版本计算；Workspace 和 Zotero 数据保留。</p>${memberList(lines)}`,[cancel,{label:'Confirm removal',primary:true,run:()=>applyExplicit(source,{confirm_settings_deletions:'yes',settings_deletion_proof:data.deletion_proof},{skipFlush:true})}]);return false;
  }
  if(!data.saved){showIssues(data);if(['PARTIAL_SAVE','REVISION_CONFLICT'].includes(data.save?.outcome))reconcileRequired=true;return false;}
  serverState=data;saved=project(data);draft=copy(saved);
  for(const key of ['workspace','pubmedKey','pubmedKeyAction','openalexKey','openalexKeyAction'])
    if(!same(retained[key],source.monitor[key]) || same(source.monitor[key],previous[key]))draft.monitor[key]=retained[key];
  initializeAutosave(data);syncMonitor();renderJournalsPage();updateDirty();showIssues(data);await refreshRun();await refreshSavedWorkspace();return true;
}
async function saveProviderKey(provider) {
  if(!await autosave?.flush())return false;
  const source=copy(saved);source.monitor[provider+'KeyAction']=draft.monitor[provider+'KeyAction'];source.monitor[provider+'Key']=draft.monitor[provider+'Key'];
  return applyExplicit(source);
}
for(const provider of ['pubmed','openalex']) {
  const button=document.createElement('button');button.type='button';button.className='s-button';button.textContent='Review API Key change';button.dataset.secretProvider=provider;
  $(`s-${provider}-key-status`).parentElement.append(button);
  button.addEventListener('click',()=>{
    const action=draft.monitor[provider+'KeyAction'];if(action==='keep'){message('API Key 没有待提交的修改。');return;}
    confirm(action==='clear'?'Clear API Key':'Replace API Key',`${providerName(provider)}：${action==='clear'?'删除本地 API Key。':'替换本地 API Key。'}凭据单独提交，不进入普通配置恢复存储。`,()=>saveProviderKey(provider));
  });
}
$('s-workspace-apply').addEventListener('click',()=>{
  const next=draft.monitor.workspace;
  confirm('Change Output Workspace',`当前：${saved.monitor.workspace}。更改为：${next}。后续任务将读取新目录；原 Workspace 文件保留。`,async()=>{
    if(!await autosave?.flush())return false;
    const source=copy(saved);source.monitor.workspace=next;return applyExplicit(source);
  });
});
const casSaveButton=document.createElement('button');casSaveButton.id='s-cas-save';casSaveButton.className='s-button';casSaveButton.textContent='Review credential change';$('s-institution-auth').append(casSaveButton);
const casRefresh=document.createElement('button');casRefresh.className='s-button';casRefresh.textContent='Re-read credential status';$('s-institution-auth').append(casRefresh);
casRefresh.addEventListener('click',async()=>{if(casAPI && !operationPending)await loadCASStatus({resetDraft:false});});
casSaveButton.addEventListener('click',()=>{
  const action=casPasswordAction();
  if(!casDirty()){message('机构凭据没有待提交的修改。');return;}
  if(casSaved.revision===null){casError='安全存储版本无法读取，草稿保留；请先重新读取状态。';renderCAS();return;}
  confirm(action==='clear'?'Clear CARSI credentials':'Replace CARSI credentials',action==='clear'?'清除 Electron 安全存储中的机构用户名与密码。':'仅替换 Electron 安全存储中的机构凭据。当前页面不会显示已保存密码。',async()=>{
    if(!await autosave?.flush())return false;
    if(action!=='clear' && (!casDraft.username.trim() || (!casSaved.configured && action!=='replace'))){casError=casErrorText('cas_credentials_required');renderCAS();return false;}
    setOperationPending(true);
    try {
      const response=await fetch('/api/ui-next/settings/credentials',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf_token:uiNext.csrf_token,operation:action==='clear'?'clear':'save',username:casDraft.username.trim(),password:action==='replace'?casDraft.password:'',expected_revision:casSaved.revision})});
      const result=await response.json();
      if(!response.ok || !result.ok){casError=casErrorText(result.error);renderCAS();message(result.message || casError,'error');return false;}
      casReadVersion++;casSaved={configured:result.configured,username:result.username,revision:result.revision};casDraft={username:result.username,password:result.configured?keyMask:''};casError='';renderCAS();updateDirty();return true;
    }catch{casError='凭据提交结果无法确认；草稿保留，请重新读取安全存储状态后核对。';renderCAS();return false;}
    finally{setOperationPending(false);}
  });
});
$('s-autosave-retry').addEventListener('click',()=>void autosave?.retry());
$('s-autosave-reconcile').addEventListener('click',async()=>{
  if(autosave?.busy)return;
  try {
    const actual=await uiNext.request('/api/ui-next/settings');
    const lines=Object.entries(ordinaryValues()).filter(([field,value])=>!same(value,ordinaryData(actual).values[field])).map(([field])=>field);
    showDialog('Review saved configuration',`<p>磁盘已重新读取。保留草稿与磁盘不同的字段：</p>${memberList(lines)}<p>重新应用会以当前磁盘版本再次验证；Reload 将丢弃草稿。</p>`,[cancel,{label:'Reload / discard draft',run:reloadSettings},{label:'Reapply retained draft',primary:true,run:async()=>{
      serverState=actual;saved=project(actual);draft.revisions=copy(saved.revisions);reconcileRequired=false;autosave.rebase(ordinaryData(actual));return await autosave.flush();
    }}]);
  }catch(error){message(error.message,'error');}
});
for(const input of document.querySelectorAll('[data-monitor]'))if(!['workspace','pubmedKey','openalexKey'].includes(input.dataset.monitor))input.addEventListener('blur',()=>{if(!institutionInputInvalid)void autosave?.flush();});
window.addEventListener('online',()=>{if(autosave?.status==='Failed')void autosave.retry();});
window.addEventListener('beforeunload',event=>{if(dirty() || autosave?.busy){event.preventDefault();event.returnValue='仍有待提交的配置；普通草稿可在恢复后核对，凭据不会进入恢复存储。';}});

function adoptState(data) {
  closeLabelPicker();
  const resetChanged=serverState && serverState.values.monitor_revision_digest!==data.values.monitor_revision_digest;
  const firstLoad=!serverState;clearAssignmentUndo();serverState=data;uiNext.csrf_token=data.csrf_token;saved=project(data);draft=copy(saved);revision++;
  loading=false;reconcileRequired=false;initializeAutosave(data,{restore:firstLoad});applyCoverDetails(data);reconcileSelections();syncMonitor();renderJournalsPage();updateDirty();
  if(resetChanged){clearReset();if($('s-reset-section').open)void refreshResetPreview();}
}
function submission(source=draft) {
  if(institutionInputInvalid)throw new Error('请从候选列表选择机构，或清空选择。');
  for(const provider of ['pubmed','openalex'])syncKey(provider);
  const form=new FormData(),m=source.monitor;
  for(const [field,key] of Object.entries({name:'name',keyword_expression:'expression',crossref_mailto:'crossrefMailto',pubmed_key_action:'pubmedKeyAction',openalex_key_action:'openalexKeyAction',from_month:'from',to_month:'to',
    output_dir:'workspace',log_level:'log',...Object.fromEntries(concurrencyFields.map(([name,key])=>[name,key])),
    institution_name:'institutionName',institution_idp_entity_id:'idp'}))form.set(field,String(m[key]??''));
  for(const id of m.providerOrder)form.append('provider_order',id);
  for(const id of m.enabledProviders)form.append('enabled_providers',id);
  for(const [id,alias] of Object.entries(m.aliases))form.set('provider_alias_'+id,alias);
  form.set('zotero_target',JSON.stringify(m.zoteroTarget || null));
  form.set('institution_use_shibboleth',m.useShibboleth?'1':'');
  for(const [key,value] of Object.entries(source.revisions))form.set(key,value);
  for(const g of source.list.groups)form.append('settings_group',g.name);
  for(const label of source.list.labels)form.append('settings_custom_label',label.name);
  const journals=source.list.journals;
  journals.forEach((j,i)=>{for(const [key,value] of Object.entries({journal_name:j.name,journal_issn:j.issn || '',journal_eissn:j.eissn || '',
    journal_group:source.list.groups.find(group=>group.id===j.groupId)?.name || '',journal_access_service_id:j.serviceId || '',journal_labels:j.labels.join('; '),journal_order:String(i)}))form.append(key,value);});
  for(const s of source.list.services)for(const [key,value] of Object.entries({service_id:s.id,service_name:s.name,service_access_url:s.url,service_access_method:s.method}))form.append(key,value);
  return form;
}
async function formRequest(path,extra={},options={}) {
  if(operationPending)throw new Error('当前操作尚未结束。');
  closeLabelPicker();
  const form=options.draft===false?new FormData():submission(options.source || draft);
  if(path==='/settings/save')for(const provider of ['pubmed','openalex'])if((options.source || draft).monitor[provider+'KeyAction']==='replace')form.set(provider+'_api_key',(options.source || draft).monitor[provider+'Key']);
  form.set('csrf_token',uiNext.csrf_token || '');for(const [key,value] of Object.entries(extra))form.set(key,value);
  setOperationPending(true);
  try {
    let response;
    try {response=await fetch(path,{method:'POST',headers:{Accept:'application/json'},body:form,cache:'no-store'});}
    catch {if(path==='/settings/save')reconcileRequired=true;throw new Error('无法连接 Allfold；草稿保留，请确认服务仍在运行。');}
    if(options.download && response.ok && response.headers.get('Content-Disposition')){
      const filename=response.headers.get('Content-Disposition').match(/filename="([^"]+)"/)?.[1] || 'list.md';
      return {blob:await response.blob(),filename};
    }
    let data;
    try{data=await response.json();}catch{if(path==='/settings/save')reconcileRequired=true;throw new Error('服务响应无法读取；请 Reload 核对磁盘状态，当前草稿保留。');}
    if(!response.ok){const error=new Error(data.message || data.reset_error || `请求失败 (${response.status})`);error.state=data;throw error;}
    return data;
  } finally {setOperationPending(false);}
}
function clearValidationIssues() {
  document.querySelectorAll('.s-validation-error').forEach(node=>node.remove());
  document.querySelectorAll('[data-monitor]').forEach(input=>input.setAttribute('aria-invalid','false'));
}
function showIssues(data) {
  const issues=data.issues || [],validation=data.validation?.issues || [];
  const all=[...new Map([...issues,...validation].map(i=>[JSON.stringify([i.field,i.message]),i])).values()];
  const texts=[...new Set(all.map(i=>i.message))];
  message([data.message,...texts].filter(Boolean).join(' '),data.saved?'normal':'error');
  const fields={pubmed_api_key:'pubmedKey',openalex_api_key:'openalexKey',name:'name',keyword_expression:'expression',crossref_mailto:'crossrefMailto',pubmed_key_action:'pubmedKeyAction',openalex_key_action:'openalexKeyAction',from_month:'from',to_month:'to',output_dir:'workspace',
    log_level:'log',...Object.fromEntries(concurrencyFields.map(([name,key])=>[name,key])),
    'institution.name':'institutionName','institution.idp_entity_id':'institutionName',
    'institution.use_shibboleth':'useShibboleth','institution':'institutionName',kept_workflow:'paperGlobalConcurrency'};
  clearValidationIssues();
  let first;
  for(const issue of all){const key=fields[issue.field];if(!key)continue;const input=document.querySelector(`[data-monitor="${key}"]`);input.setAttribute('aria-invalid','true');
    const hint=document.createElement('span');hint.className='s-field-error s-validation-error';hint.textContent=issue.message;input.parentElement.append(hint);first ||= input;}
  if(all.length){if(preview)closePreview();if(dialog.open)dialog.close();}
  if(!first && all.some(issue=>issue.field?.startsWith('provider_aliases'))){selectedProvider='openalex';openSettings('run',true);renderRun();$('s-provider-alias').focus();}
  if(!first && all.some(issue=>/journal|access_service|groups|custom_labels/.test(issue.field || '')))openSettings('journals-page',true);
  if(first){const key=first.dataset.monitor;
    if(['name','expression','from','to','pubmedKey','openalexKey','crossrefMailto'].includes(key)){selectedProvider=key==='pubmedKey'?'pubmed':key==='openalexKey'?'openalex':key==='crossrefMailto'?'crossref':'overview';openSettings('run',true);renderRun();}
    else if(['prepareServiceConcurrency','institutionName','idp','useShibboleth'].includes(key)){
      window.workspaceNavigation.go('login',{instant:true});
      $('login-page').querySelector(`[data-sidebar-view="${key==='prepareServiceConcurrency'?'workflow':'access'}"]`)?.click();
    }
    else if(concurrencyFields.some(([,field])=>field===key)){
      window.workspaceNavigation.go('kept',{instant:true});
      window.dispatchEvent(new CustomEvent('kept-open-sidebar',{detail:{view:'workflow'}}));
    }
    else openSettings('settings',true);first.focus();}
}
async function refreshSavedWorkspace() {
  try {await window.uiWorkspace.refresh();}
  catch(error){message('配置状态已更新；Workspace 读取失败：'+error.message,'error');}
}
async function acceptOperation(data) {
  if(data.saved){if(preview)closePreview();adoptState(data);showIssues(data);await refreshRun();await refreshSavedWorkspace();return true;}
  if(data.save?.outcome==='PARTIAL_SAVE')reconcileRequired=true;
  showIssues(data);updateDirty();return false;
}
async function saveDraft(after=()=>{}) {
  if(operationPending || loading || explicitDirty()) {message('凭据和 Workspace 修改须先独立确认；普通配置草稿保留。','error');return false;}
  if(!await autosave?.flush())return false;
  await after();return true;
}

async function refreshDiagnostic(kind) {
  const button=root.querySelector(`[data-diagnostic="${kind}"]`);button.disabled=true;
  try {
    const data=await uiNext.request('/api/ui-next/settings/diagnostics/'+kind);
    const summary=kind==='zotero'?`Electron: ${data.electron_connected?'connected':'disconnected'} · Desktop: ${data.zotero_instance?.message || data.zotero_instance?.outcome || 'See details'}`:data.health_config_error || `${data.health_workspace?.issues?.length || 0} Workspace issues`;
    $('s-'+kind+'-summary').textContent=summary;$('s-'+kind+'-result').textContent=JSON.stringify(data,null,2);
  } catch(error){$('s-'+kind+'-summary').textContent='Unavailable';$('s-'+kind+'-result').textContent=error.message;}
  finally {button.disabled=false;}
}
root.querySelectorAll('[data-diagnostic]').forEach(button=>button.addEventListener('click',()=>void refreshDiagnostic(button.dataset.diagnostic)));
let resetPlan=null,resetVersion=0;
async function refreshResetPreview() {
  const version=++resetVersion,scope=$('s-reset-scope').value;
  resetPlan=null;$('s-reset-workspace').disabled=true;$('s-reset-result').textContent='正在确认目标…';
  try {
    const data=await uiNext.request('/api/ui-next/settings/reset-preview?scope='+scope);
    if(version!==resetVersion || scope!==$('s-reset-scope').value)return;
    resetPlan={...data,scope};$('s-reset-result').textContent=data.reset_error || resetImpact(scope,data.reset_plan);
    $('s-reset-path').textContent=scope==='logs'?'当前配置的 Logs':data.reset_plan?.workspace || 'Unavailable';
  }catch(error){if(version===resetVersion){resetPlan=null;$('s-reset-result').textContent=error.message;}}
  if(version===resetVersion)$('s-reset-workspace').disabled=!resetPlan?.reset_token;
}
$('s-reset-section').addEventListener('toggle',()=>{if($('s-reset-section').open)void refreshResetPreview();});
$('s-reset-scope').addEventListener('change',()=>{clearReset();void refreshResetPreview();});
function clearReset() {resetVersion++;$('s-reset-workspace').disabled=true;resetPlan=null;}
$('s-reset-cancel').addEventListener('click',()=>{clearReset();$('s-reset-section').open=false;});
function resetReport(data) {
  const producers=data?.reset_result;
  const values=[producers?.native,producers?.python].filter(Boolean);
  return [data?.reset_error,values.length?`日志文件：已删除 ${values.reduce((n,p)=>n+(p.deleted || 0),0)}；未删除 ${values.reduce((n,p)=>n+(p.failed || 0),0)}。`:''].filter(Boolean).join(' ');
}
$('s-reset-workspace').addEventListener('click',()=>{
  if(!resetPlan?.reset_token)return;
  const current=resetPlan,scope=current.scope;
  confirm(`Confirm ${scope==='logs'?'Logs':'Workspace'} Reset`,resetImpact(scope,current.reset_plan),async()=>{
    try {
      const result=await formRequest(`/settings/${scope}-reset`,{reset_token:current.reset_token},{draft:false});
      $('s-reset-result').textContent=resetReport(result);
      if(result.reset_success){
        window.dispatchEvent(new Event(scope==='logs'?'logs-reset':'workspace-reset'));
        if(scope==='workspace'){await refreshSavedWorkspace();await refreshDiagnostic('health');}
      }
    }catch(error){$('s-reset-result').textContent=error.state?resetReport(error.state):error.message;}finally{clearReset();}
  },scope==='logs'?'清除 Logs':'永久删除 Workspace');
});
$('s-export-diagnostics').addEventListener('click',async()=>{
  const button=$('s-export-diagnostics');button.disabled=true;
  $('s-export-diagnostics-status').textContent='正在生成本地诊断包…';
  try {await window.allfoldHistory.exportTask();$('s-export-diagnostics-status').textContent='诊断包已生成，仅在本地下载。';}
  catch(error){$('s-export-diagnostics-status').textContent=error.message;}
  finally {button.disabled=false;}
});
async function loadSettings() {
  loading=true;root.querySelector('.s-content').inert=true;updateDirty();
  try {const data=await uiNext.request('/api/ui-next/settings');adoptState(data);await loadCASStatus();coverJob=data.cover_search;journalLayoutHost.sync();
    if(data.issues.length)message(data.issues.map(i=>`${i.message}${i.path?' · '+i.path:''}`).join('\n'),'error');
    else message('');
    if(coverJob.phase==='Running')coverTimer=setTimeout(refreshCovers,1000);
  }catch(error){message(error.message,'error');}
  finally{root.querySelector('.s-content').inert=loading;updateDirty();}
}
const developerModeKey='inbox-rhine.developer-mode';
function savedDeveloperMode() {
  try{return localStorage.getItem(developerModeKey)==='true';}catch{return false;}
}
const developerModeToggle=$('s-developer-mode');
function applyDeveloperMode(enabled) {
  document.documentElement.classList.toggle('developer-mode',enabled);
  window.dispatchEvent(new Event('developer-mode-change'));
}
developerModeToggle.checked=savedDeveloperMode();
applyDeveloperMode(developerModeToggle.checked);
developerModeToggle.addEventListener('change',()=>{
  applyDeveloperMode(developerModeToggle.checked);
  try{localStorage.setItem(developerModeKey,String(developerModeToggle.checked));}
  catch{message('Developer Mode 已切换，但浏览器不允许保存该设置。','error');}
});
const presentationPreferences=[
  {id:'s-disable-archive',read:'archiveDisabled',write:'setArchiveDisabled'},
  {id:'s-disable-fullscreen',read:'fullscreenDisabled',write:'setFullscreenDisabled'},
];
function syncPresentationPreferences() {
  for(const {id,read} of presentationPreferences)$(id).checked=window.allfoldUIPreferences[read]();
}
syncPresentationPreferences();
for(const {id,write} of presentationPreferences)$(id).addEventListener('change',()=>{
  try {window.allfoldUIPreferences[write]($(id).checked);}
  catch {message('界面偏好已切换，但本机不允许保存该设置。','error');}
});
window.addEventListener('ui-preferences-changed',syncPresentationPreferences);
void loadInstitutionCatalog();
void loadSettings();
void refreshRun();
