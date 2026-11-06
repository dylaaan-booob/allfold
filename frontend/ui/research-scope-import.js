const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function readImportChoices(container) {
  const choices={};
  container.querySelectorAll('[data-scope-row]').forEach(element=>{
    const choice={skip:element.querySelector('[data-import-skip]').checked};
    if(element.dataset.scopeKind==='conference'){
      for(const field of ['conference','dblp stream'])choice[field]=element.querySelector(`[data-import-field="${field}"]`).value;
      const candidate=element.querySelector('[data-import-candidate]').value;if(candidate)choice.candidate=JSON.parse(candidate);
      choices[element.dataset.scopeRow]=choice;return;
    }
    for(const field of ['journal','issn','eissn'])choice[field]=element.querySelector(`[data-import-field="${field}"]`).value;
    const candidate=element.querySelector('[data-import-candidate]').value;
    if(candidate)choice.candidate=JSON.parse(candidate);
    const method=element.querySelector('[data-import-method]').value;
    if(method!=='keep') {
      choice['service']=method==='unresolved'?'':element.querySelector('[data-import-service]').value;
      choice['access method']=method==='unresolved'?'carsi':method;
      choice['access url']=element.querySelector('[data-import-url]').value;
      choice.unresolved=method==='unresolved';
    }
    choices[element.dataset.scopeRow]=choice;
  });
  return choices;
}

export function renderImportRows(p,choices={}) {
  return p.rows.map(row=>{
    const input=(field,label)=>`<label>${label}<input data-import-field="${field}" value="${esc(row.supplied[field] || '')}"></label>`;
    if(row.kind==='conference') {
      const choice=choices[row.index] || {};
      return `<fieldset data-scope-row="${row.index}" data-scope-kind="conference"><legend>${esc(row.supplied.conference || 'Conference')} · ${esc(row.status)}</legend><p>${row.messages.map(esc).join(' · ')}</p><p>Group: ${esc(row.supplied.group || 'Ungrouped')} · Labels: ${esc(row.supplied.label || '(none)')}</p><label><input type="checkbox" data-import-skip ${choice.skip?'checked':''}> Skip this row</label>${input('conference','Conference')}${input('dblp stream','DBLP Stream')}<label>Series<select data-import-candidate><option value="">Automatic exact match</option>${row.candidates.map(c=>`<option value="${esc(JSON.stringify({id:c.id,dblp_stream:c.dblp_stream}))}" ${choice.candidate?.id===c.id?'selected':''}>${esc(c.abbreviation)} · ${esc(c.dblp_stream)}</option>`).join('')}</select></label></fieldset>`;
    }
    const current=p.proposed.access_services.find(s=>s.id===row.journal?.access_service_id);
    const choice=choices[row.index] || {};
    const method=choice.unresolved?'unresolved':choice['access method'] || 'keep';
    const candidates=row.candidates.map(c=>{
      const pair={issn:c.issn,eissn:c.eissn};
      const selected=choice.candidate?.issn===c.issn && choice.candidate?.eissn===c.eissn;
      return `<option value="${esc(JSON.stringify(pair))}" ${selected?'selected':''}>${esc(c.name)} · ${esc([c.issn,c.eissn].filter(Boolean).join(' / '))}</option>`;
    }).join('');
    const methods=[['keep','Keep supplied Service / Resolver result'],['carsi','Official CARSI production'],
      ['manual','Manual Service'],['unresolved','Unresolved']].map(([value,label])=>
        `<option value="${value}" ${method===value?'selected':''}>${label}</option>`).join('');
    return `<fieldset data-scope-row="${row.index}"><legend>${esc(row.supplied.journal || row.supplied.issn || 'Journal')} · ${esc(row.status)}</legend><p>${row.messages.map(esc).join(' · ')} · Service: ${esc(row.service_status)}</p><p>Group: ${esc(row.supplied.group || 'Ungrouped')} · Labels: ${esc(row.supplied.label || '(none)')}</p><label><input type="checkbox" data-import-skip ${choices[row.index]?.skip?'checked':''}> Skip this row</label>${input('journal','Name')}${input('issn','ISSN')}${input('eissn','eISSN')}<label>Identity candidate<select data-import-candidate><option value="">Automatic exact match / correct fields above</option>${candidates}</select></label><details><summary>Identity / Resolver evidence</summary><pre>${esc(JSON.stringify({candidates:row.candidates,resolution:row.resolution},null,2))}</pre></details><label>Service choice<select data-import-method>${methods}</select></label><label>Service name<input data-import-service value="${esc(current?.name || row.supplied.service || '')}"></label><label>Manual access URL<input data-import-url value="${esc(current?.access_url || row.supplied['access url'] || '')}"></label></fieldset>`;
  }).join('');
}
