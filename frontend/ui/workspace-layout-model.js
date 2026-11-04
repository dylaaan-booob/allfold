'use strict';
// Target sizes are preferences; measured sizes never flow back into them.
window.allfoldLayoutModel=(()=>{
  const defaults=Object.freeze({railWidth:48,flyoutPreferredWidth:280,sidebarPreferredWidth:320});
  const limits=Object.freeze({railWidth:[36,72],flyoutPreferredWidth:[220,480],sidebarPreferredWidth:[260,560]});
  const minOperationalSize=Object.freeze({array:360,journals:320,sidebar:260});
  function targets(stored) {
    const value={...defaults};
    for(const [name,[min,max]] of Object.entries(limits))
      if(typeof stored?.[name]==='number' && Number.isFinite(stored[name]) && stored[name]>=min && stored[name]<=max)value[name]=Math.round(stored[name]);
    return value;
  }
  function measure(width,preferred,contentMinimum,expanded) {
    const available=Math.max(0,width-2*preferred.railWidth);
    const docked=available>=contentMinimum+minOperationalSize.sidebar;
    const sidebarEffectiveWidth=expanded?Math.min(preferred.sidebarPreferredWidth,docked?available-contentMinimum:available):0;
    return {sidebarMode:!expanded?'closed':docked?'docked':'overlay',sidebarEffectiveWidth,
      contentWidth:available-(expanded && docked?sidebarEffectiveWidth:0),
      flyoutEffectiveWidth:Math.min(preferred.flyoutPreferredWidth,available)};
  }
  return Object.freeze({defaults,limits,minOperationalSize,targets,measure});
})();
