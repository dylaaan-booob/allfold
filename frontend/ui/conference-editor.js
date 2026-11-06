const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function conferenceDetail(c,scope) {
  return `<h2>${esc(c.name)}</h2><p>${esc(c.abbreviation)}</p><code>${esc(c.dblp_stream)}</code>${c.aliases.length?`<p>${c.aliases.map(esc).join(' · ')}</p>`:''}<label>Group<select id="s-conference-group"><option value="">Ungrouped</option>${scope.groups.map(g=>`<option value="${esc(g.id)}" ${c.groupId===g.id?'selected':''}>${esc(g.name)}</option>`).join('')}</select></label><fieldset><legend>Labels</legend>${scope.labels.map(l=>`<label class="s-check"><input type="checkbox" data-conference-label="${esc(l.name)}" ${c.labels.includes(l.name)?'checked':''}>${esc(l.name)}</label>`).join('')}</fieldset><p class="s-help">此处管理离线 Series；当前 Integrated Run 和 API 补全不检索会议。</p>`;
}

export function conferenceValues(scope) {
  return (scope.conferences || []).map(c=>({id:c.id,name:c.name,abbreviation:c.abbreviation,
    aliases:c.aliases,dblp_stream:c.dblp_stream,
    group:scope.groups.find(g=>g.id===c.groupId)?.name || null,labels:c.labels}));
}
