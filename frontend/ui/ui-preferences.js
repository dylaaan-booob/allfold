'use strict';
// Local presentation preferences are independent of configuration and task state.
window.allfoldUIPreferences=(()=>{
  const keys={archiveDisabled:'allfold.ui.archive-disabled',fullscreenDisabled:'allfold.ui.fullscreen-disabled'};
  const values={archiveDisabled:true,fullscreenDisabled:false};
  for(const name of Object.keys(keys)){
    try {
      const saved=localStorage.getItem(keys[name]);
      if(saved==='true' || saved==='false')values[name]=saved==='true';
    }catch { /* Keep usable session defaults when local storage is unavailable. */ }
  }
  function set(name,value) {
    if(typeof value!=='boolean')throw new TypeError('UI preference must be boolean');
    const changed=values[name]!==value;
    values[name]=value;
    let failure;
    try {localStorage.setItem(keys[name],String(value));}catch(error){failure=error;}
    if(changed)window.dispatchEvent(new CustomEvent('ui-preferences-changed',{detail:{name,value}}));
    if(failure)throw failure;
  }
  return Object.freeze({
    archiveDisabled:()=>values.archiveDisabled,
    fullscreenDisabled:()=>values.fullscreenDisabled,
    setArchiveDisabled:value=>set('archiveDisabled',value),
    setFullscreenDisabled:value=>set('fullscreenDisabled',value),
  });
})();
