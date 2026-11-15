// Adapted from LBEILC DocumentDecryption, MIT. See SOURCES.md.
// A font strut defines the same first-line ink rectangle for unknown text.
function abstractLineMetrics(target) {
  const probe=document.createElement('span');
  probe.textContent='Ag';
  probe.style.cssText='position:absolute;left:0;top:0;visibility:hidden;white-space:pre';
  target.append(probe);
  const range=document.createRange(); range.selectNodeContents(probe);
  const bounds=probe.getBoundingClientRect(), rect=range.getBoundingClientRect();
  const metrics={top:rect.top-bounds.top-1,height:rect.height+2,
    lineHeight:parseFloat(getComputedStyle(target).lineHeight)};
  probe.remove();
  return metrics;
}
