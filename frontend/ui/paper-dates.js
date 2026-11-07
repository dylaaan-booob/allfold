(() => {
  const names={'accepted':'Accepted','published-online':'Published online',published:'Published','source-date':'Published'};
  const value=item=>[item.year,item.month,item.day].filter(part=>part!==undefined && part!==null).map((part,i)=>i?String(part).padStart(2,'0'):String(part).padStart(4,'0')).join('-');
  const detail=item=>[item.provider,item.record_id,item.version,item.source_label,item.url].filter(Boolean).join(' · ');
  window.allfoldPaperDates={render(paper,first,journal){
    const evidence=paper.date_evidence || [];
    first.textContent=paper.first_public_at || '—';
    first.title=evidence.filter(item=>item.kind==='preprint' && item.first_version && value(item)===paper.first_public_at).map(detail).join('\n');
    const publication=paper.publication_date;
    const facts=[...evidence];
    if((paper.publication_type==='journal' || paper.journal) && publication &&
        !facts.some(item=>['published','source-date'].includes(item.kind) && value(item)===publication)){
      const [year,month,day]=publication.split('-').map(Number);
      facts.push({kind:'published',publication_type:'journal',year,month,day});
    }
    const events=facts.filter(item=>item.publication_type==='journal' && Object.hasOwn(names,item.kind)).sort((a,b)=>{
      const key=item=>[item.year,item.month || 1,item.day || 1].map((part,i)=>String(part).padStart(i?2:4,'0')).join('-');
      return key(a).localeCompare(key(b)) || detail(a).localeCompare(detail(b));
    });
    const rows=new Map();
    for(const item of events){
      const key=JSON.stringify([names[item.kind],value(item),item.provider || '',item.record_id || '',item.version || '']);
      if(!rows.has(key))rows.set(key,{item,details:new Set()});
      rows.get(key).details.add(detail(item));
    }
    journal.replaceChildren(...Array.from(rows.values(),({item,details})=>{
      const line=document.createElement('div');
      line.textContent=[names[item.kind],value(item),item.provider].filter(Boolean).join(' · ');
      line.title=Array.from(details).join('\n');return line;
    }));
    if(!events.length)journal.textContent='—';
  }};
})();
