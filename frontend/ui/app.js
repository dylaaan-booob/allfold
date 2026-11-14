'use strict';
// RhinE archive.js / motion.js + visual-lab's Canvas affine drawing adaptation.
// Original springs, selection shoulders, axes, quads and sprites are retained.
// See SOURCES.md for the browser adaptation boundary.
const $ = id => document.getElementById(id);
const BG = '#eeede7', INK = '#252821', MUTED = '#63665d', ORANGE = '#ff7a01';
let archiveLayout, shelfCapacity = archiveDebug.values.shelfCapacity;
// Only the artwork is scaled; the archive origin stays independent of Journal selection.
const ARCHIVE_FRAME = { scale: 1.2, controlHeight: 40 };
const mix = (a, b, t) => a + (b - a) * t;
const easeInOut = t => t < .5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const pad = n => String(n).padStart(2, '0');
// Browser CSS pixels are logical dp; round only at the device-pixel boundary.
const dp = value => Math.round(value * (devicePixelRatio || 1)) / (devicePixelRatio || 1);
const initialParams = new URLSearchParams(location.search);
const initialView = initialParams.get('view') ?? 'inbox';
const initialPaper = initialParams.get('paper');
const initialLinkValid = ['inbox','kept','candidates','downloaded','trash'].includes(initialView) &&
  [...initialParams.keys()].every(key=>['view','paper'].includes(key)) &&
  initialParams.getAll('view').length <= 1 && initialParams.getAll('paper').length <= 1 &&
  (!initialParams.has('paper') || (initialParams.has('view') &&
    /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(initialPaper)));
window.uiNextInitialLink = initialLinkValid
  ? {view:initialView,paper:initialPaper?.toLowerCase() || null}
  : {view:'inbox',paper:null};
const mediaQuery = matchMedia('(prefers-reduced-motion: reduce)');
let REDUCE_MOTION = mediaQuery.matches;
function Spring(x = 0, w = 16) { return { x, v: 0, to: x, w }; }
function stepSpring(s, dt) {
    if (REDUCE_MOTION) { s.x = s.to; s.v = 0; return false; }
    const a = s.w * s.w * (s.to - s.x) - 2 * s.w * s.v;
    s.v += a * dt;
    s.x += s.v * dt;
    if (Math.abs(s.to - s.x) < 0.01 && Math.abs(s.v) < 0.05) { s.x = s.to; s.v = 0; return false; }
    return true;
}

// Whole, ordered Group segments are the units of packing and balancing.
function allocateShelves(logicalGroups, capacity) {
  if(!Number.isSafeInteger(capacity) || capacity<1)throw new RangeError('Invalid shelf capacity');
  const segments=[];
  logicalGroups.map((group,order)=>({group,order}))
    .sort((a,b)=>b.group.journals.length-a.group.journals.length || a.order-b.order)
    .forEach(({group,order})=>{
      const parts=Math.ceil(group.journals.length/capacity);
      for(let part=0;part<parts;part++)segments.push({groupId:group.id??order,name:group.name,order,
        originalPart:part,part:part+1,parts,journals:group.journals.slice(part*capacity,(part+1)*capacity)});
    });
  const order=(a,b)=>a.order-b.order || a.originalPart-b.originalPart;
  segments.sort((a,b)=>b.journals.length-a.journals.length || order(a,b));
  const result=[],loads=[];
  for(const segment of segments){
    let index=loads.findIndex(load=>load+segment.journals.length<=capacity);
    if(index<0){index=result.length;result.push({segments:[]});loads.push(0);}
    result[index].segments.push(segment);loads[index]+=segment.journals.length;
  }
  for(;;){
    let best=null;
    const consider=(from,to,a,b=null)=>{
      const left=loads[from]-a.journals.length+(b?.journals.length||0);
      const right=loads[to]+a.journals.length-(b?.journals.length||0);
      if(left>capacity || right>capacity)return;
      const removed=left===0?1:0,delta=left*left+right*right-loads[from]**2-loads[to]**2;
      if(!removed && delta>=0)return;
      if(!best || removed>best.removed || (removed===best.removed && delta<best.delta))best={from,to,a,b,left,right,removed,delta};
    };
    // This stable scan order also breaks ties between equally good operations.
    for(let from=0;from<result.length;from++)for(let to=0;to<result.length;to++){
      if(from===to)continue;
      for(const a of [...result[from].segments].sort(order)){
        consider(from,to,a);
        if(from<to)for(const b of [...result[to].segments].sort(order))consider(from,to,a,b);
      }
    }
    if(!best)break;
    const {from,to,a,b,left,right}=best;
    result[from].segments.splice(result[from].segments.indexOf(a),1);
    if(b){result[to].segments.splice(result[to].segments.indexOf(b),1);result[from].segments.push(b);}
    result[to].segments.push(a);loads[from]=left;loads[to]=right;
    if(!left){result.splice(from,1);loads.splice(from,1);}
  }
  for(const shelf of result)shelf.segments.sort(order);
  refreshShelfSegments(result);
  return result;
}
function refreshShelfSegments(shelves) {
  const byGroup=new Map();
  for(const shelf of shelves){
    shelf.segments=shelf.segments.filter(segment=>segment.journals.length);
    shelf.journals=shelf.segments.flatMap(segment=>segment.journals);
    for(const segment of shelf.segments){
      if(!byGroup.has(segment.groupId))byGroup.set(segment.groupId,[]);
      byGroup.get(segment.groupId).push(segment);
    }
  }
  for(const segments of byGroup.values())segments.sort((a,b)=>a.originalPart-b.originalPart)
    .forEach((segment,index)=>{segment.part=index+1;segment.parts=segments.length;});
}


let logicalGroups = [], shelves = [], rows = [], journalMeta, railMeta, arrayClear, arrayFrost, railImages;
const covers = new Map(), lists = new Map(), hitAreas = [];
const coverChanges = new Map(), coverLoads = new Map();
let coverSequence=0;
const fadedSprites = new Map();
const state = { shelf: 0, track: 0, ready: false, view: 'selected', pendingPaper: null, focusSource: null };
// Bounded shelf positions move as one strip; each row owns its Journal scroll.
const strip = Spring(0, 9);
let selectedCoverQuad = [], stageWidth = 0, inspectionWidth = 0, inspectionFrames = [];
const inspection = { time: 0, target: 0, duration: archiveDebug.values.totalDurationMs / 1000, removeAfter: false, completionPending: false };
const directoryScroll = Spring(0, 12);
const directoryCanvas = document.createElement('canvas');
directoryCanvas.width = directoryCanvas.height = 768;
const directoryContext = directoryCanvas.getContext('2d');
let directoryAreas = [];
const decryption = new DocumentDecryption();
const paragraphLayout = window.ParagraphLayout?.create($('paper-abstract'), {
  scrollRoot:$('paper-detail'),
  onLayout:()=>{if(decryption.active) decryption.refresh();},
});
const filePanel = document.querySelector('.file-panel');
const completionSurface = new SurfaceTransition($('empty-inbox'), undefined, archiveDebug.values.liftEndMs, 180);
const downloadedPapers = new Map(),trashPapers=new Map();
let librarySnapshot;
let readerContext=null;
const reviewPanel=document.querySelector('.review-right');
const paperNavigation=reviewPanel.querySelector('.paper-navigation');
const paperTitle=$('view-paper-title'),paperMetadata=$('paper-metadata-details');
const decisionButtons=[$('reject-paper'),$('restore-paper'),$('clear-paper-metadata')];
const decisionHost=decisionButtons[0].parentElement;
let decisionPending=false, snapshotApplying=false, settingsRefreshPending=false;
const paperTools={paperId:null,fields:null,loading:false,error:'',generation:0,pending:false,focus:null,kind:null,diagnosticGeneration:0};
const paperToolsBusy=()=>paperTools.pending || $('paper-tools-dialog').open;
const currentPaper = () => readerContext ? readerContext.entries.find(e=>e.paper.id===state.pendingPaper)?.paper : selectedJournal()?.papers.find(p => p.id === state.pendingPaper);
const reviewPapers = () => readerContext ? readerContext.entries.map(e=>e.paper) : (selectedJournal()?.papers || []);
const reviewJournal = () => readerContext ? readerContext.entries.find(e=>e.paper.id===state.pendingPaper)?.journal : selectedJournal();
const configurationActive=()=>['journals','login','run','settings'].includes(window.workspaceNavigation.current());
const inboxActive=()=>window.workspaceNavigation.current()==='workspace' && $('selected-view').dataset.workspaceLayout==='archive';
const arrayActive=()=>window.workspaceNavigation.current()==='workspace' && $('selected-view').dataset.workspaceLayout==='array';
const navigationBusy=()=>decisionPending || Boolean(snapshotApplying) || paperToolsBusy() ||
  (inspection.target ? inspection.time!==inspection.duration : inspection.time!==0);
function syncNavigation() {window.workspaceNavigation.refresh();}
function refreshInboxControls() {
  const busy=navigationBusy(),previewOpen=$('s-file-preview')?.hidden===false;
  const settingsBusy=$('configuration-workspace').dataset.busy==='true';
  $('open-journal-more').disabled=!state.ready || state.view!=='selected' || busy || previewOpen || settingsBusy ||
    !inboxActive() || $('run-view').open;
  const debugView=arrayActive()?'array':inboxActive()?(state.view==='journal'?'journal':'selected'):'none';
  const showArchiveDebug=inboxActive() && document.documentElement.classList.contains('developer-mode');
  $('archive-debug').hidden=!showArchiveDebug;
  document.documentElement.classList.toggle('archive-debug-active',showArchiveDebug);
  archiveDebug.setContext(debugView,showArchiveDebug,state.ready && !busy && !previewOpen && !settingsBusy &&
    !window.workspaceArray?.workflowBusy() && !$('run-view').open &&
    (debugView!=='journal' || (inspection.target && inspection.time===inspection.duration)));
  renderPaperTools();
}
window.addEventListener('workspace-navigation-state',refreshInboxControls);
window.addEventListener('developer-mode-change',syncNavigation);
const activeSlots = group => shelves[group].journals.flatMap((j, i) => j ? [i] : []);
const liftDuration = () => archiveDebug.values.liftEndMs / 1000;
const phaseTurn = () => easeInOut(clamp((inspection.time - liftDuration()) / (inspection.duration - liftDuration())));
const phaseLift = () => easeInOut(clamp(inspection.time / liftDuration()));
const AR = { hover: -1, hoverTick: -1, focusTick: -1, rulerDrag: null, rulerStart: Spring(0, 14), ticks: new Map() };
const slotOf = (row, i) => i;
// Empty slots are presentation only; allocation and navigation use real Journals.
const slotCount = () => shelfCapacity;
const selectedRow = () => rows[state.shelf];
const selectedJournal = () => shelves[state.shelf]?.journals[selectedRow()?.sel];
let W = 0, H = 0, ratio = 1, running = false, lastTime = 0, lastWheel = 0;
const canvas = $('archive'), ctx = canvas.getContext('2d');
function caseTargets(i, r, active, row, hover = AR.hover) {
    const d = slotOf(row, i) - slotOf(row, r.sel), bell = Math.exp(-d * d / 4.5) - .32 * Math.exp(-d * d / 18);
    const isSel = active && i === r.sel;
    const hd = i - hover, hov = active && hover >= 0 ? .5 * Math.exp(-hd * hd / 2.2) : 0;
    return {
        lift: (active ? 1.1 : .65) * bell + hov + (isSel ? 1.35 : 0),
        clear: isSel ? 1 : 0,
        gap: active ? (i > r.sel ? .55 : i < r.sel ? -.25 : 0) : 0,
    };
}

let CASE_POLY = null;
function casePoly() {
    if (CASE_POLY && CASE_POLY.meta === journalMeta) return CASE_POLY;   // made again for another skin's case.json
    const m = journalMeta.array.origin, ax = journalMeta.axes, at = (x, y, z) => [m[0] + x * ax.x[0] + y * ax.y[0] + z * ax.z[0], m[1] + x * ax.x[1] + y * ax.y[1] + z * ax.z[1]];
    CASE_POLY = [at(-2, -.23, 0), at(2, -.23, 0), at(2, -.23, 3.5), at(2, .23, 3.5), at(-2, .23, 3.5), at(-2, -.23, 3.5)];
    CASE_POLY.meta = journalMeta;
    return CASE_POLY;
}


function archiveFrame(width = W, height = H) {
  const ax=journalMeta.axes, m=journalMeta.array, points=casePoly();
  const boxWidth=Math.max(...points.map(p=>p[0]))-Math.min(...points.map(p=>p[0]));
  const boxHeight=Math.max(...points.map(p=>p[1]))-Math.min(...points.map(p=>p[1]));
  const k=Math.max(.05,Math.min(.54 * ARCHIVE_FRAME.scale * clamp(Math.min(width/936,height/731),1,1.6),
    (width-dp(48))/boxWidth,(height-dp(106))/boxHeight));
  const lift=caseTargets(0,{sel:0},true,null,-1).lift;
  const center=m.cover.reduce((p,q)=>[p[0]+q[0]/4,p[1]+q[1]/4],[0,0]);
  const offset=[(center[0]-m.origin[0])*k,(center[1]-m.origin[1]+lift*ax.z[1])*k];
  // RhinE's whole-scene origin leaves room in front of the shelves. Moving this
  // origin also moves every rail/case; the sprite axes and camera remain intact.
  const y=Math.max(height-dp(87),(height-dp(56))/2-offset[1]);
  const anchor=Math.max(0,((height-dp(56))/2-y-offset[1])/(ax.y[1]*k));
  // The resting cover center passes through the center of the artwork area.
  // This origin depends on the viewport only, never on the selected Journal.
  return {k,baseK:k,x:width/2-offset[0]-anchor*ax.y[0]*k,y,anchor,width,height};
}
function geometry() {
  return archiveFrame();
}
function projection(group, index, lift, gap = 0, position = state.track - strip.x) {
  const g = geometry(), ax = journalMeta.axes;
  const y = index - rows[group].scroll.x + gap, x = -position * 4.7;
  return [g.x + (x * ax.x[0] + y * ax.y[0] + lift * ax.z[0]) * g.k,
          g.y + (x * ax.x[1] + y * ax.y[1] + lift * ax.z[1]) * g.k];
}
function transformedQuad(q, ox, oy, k) { return q.map(([x, y]) => [ox + x * k, oy + y * k]); }
function quadImage(image, q, ox, oy, k, alpha = 1) {
  ctx.save(); ctx.globalAlpha *= alpha;
  ctx.transform((q[1][0] - q[0][0]) * k / image.width, (q[1][1] - q[0][1]) * k / image.width,
    (q[3][0] - q[0][0]) * k / image.height, (q[3][1] - q[0][1]) * k / image.height, ox + q[0][0] * k, oy + q[0][1] * k);
  ctx.drawImage(image, 0, 0); ctx.restore();
}
function sourceIdentity(source) {
  return {value:source.issn || source.eissn || 'UNMAPPED',label:source.issn?'ISSN':source.eissn?'eISSN':'ISSN / eISSN'};
}
function spine(q, ox, oy, k, identifier, label = 'ISSN / eISSN') {
  ctx.save(); ctx.transform((q[1][0] - q[0][0]) * k / 100, (q[1][1] - q[0][1]) * k / 100,
    (q[3][0] - q[0][0]) * k / 60, (q[3][1] - q[0][1]) * k / 60, ox + q[0][0] * k, oy + q[0][1] * k);
  ctx.fillStyle = INK; ctx.font = '500 13px "Geist Mono"'; ctx.fillText(label, 8, 21);
  ctx.font = '15px "Geist Mono"'; ctx.fillText(identifier, 8, 48); ctx.restore();
}
function topTitle(group, index, ox, oy, k) {
  const ax = journalMeta.axes, m = journalMeta.array.origin;
  const map = (x, y, z) => [ox + (m[0] + x * ax.x[0] + y * ax.y[0] + z * ax.z[0]) * k, oy + (m[1] + x * ax.x[1] + y * ax.y[1] + z * ax.z[1]) * k];
  const a = map(-1.8, .15, 3.5), b = map(1.1, .15, 3.5), c = map(-1.8, -.15, 3.5);
  ctx.save(); ctx.transform((b[0] - a[0]) / 290, (b[1] - a[1]) / 290, (c[0] - a[0]) / 33, (c[1] - a[1]) / 33, ...a);
  ctx.fillStyle = '#e9e6dd'; ctx.fillRect(0, 0, 290, 33); ctx.fillStyle = INK;
  ctx.font = '500 13px "Geist Mono"';
  let title = shelves[group].journals[index].name.toUpperCase();
  if (ctx.measureText(title).width > 275) {
    while (ctx.measureText(title + '…').width > 275) title = title.slice(0, -1);
    title += '…';
  }
  ctx.fillText(title, 8, 23); ctx.restore();
}
function arrayCase(group, index, track) {
  const journal = shelves[group].journals[index];
  const isInspected = group === state.shelf && track === state.track && index === selectedRow().sel && inspection.time > 0;
  if (isInspected && phaseTurn() > 0) return;
  const active = track === state.track, position = track - strip.x;
  // Empty cases are drawing slots only, with no Journal or selection state.
  const c = rows[group].cases.get(index) || { lift: { x: 0 }, clear: { x: 0 }, gap: { x: active ? .55 : 0 } };
  const clear = active ? c.clear.x : 0;
  const g = geometry(), m = journalMeta.array;
  const [sx, sy] = projection(group, index, c.lift.x + (isInspected ? 2.2 * phaseLift() : 0), c.gap.x, position);
  const ox = sx - m.origin[0] * g.k, oy = sy - m.origin[1] * g.k, size = 600 * g.k;
  ctx.save();
  const artworkPair = journal && covers.get(journal.key);
  const tint = rowTint(position);
  if (artworkPair) quadImage(artworkPair.blur, m.cover, ox, oy, g.k);
  else {
    ctx.beginPath(); transformedQuad(m.cover, ox, oy, g.k).forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.closePath(); ctx.fillStyle = '#deddd5'; ctx.fill();
  }
  if (tint > 0) {
    ctx.save(); ctx.globalAlpha *= tint;
    ctx.beginPath(); transformedQuad(m.cover, ox, oy, g.k).forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.closePath(); ctx.fillStyle = BG; ctx.fill(); ctx.restore();
    ctx.drawImage(tintedSprite(arrayFrost, tint, 'case'), ox, oy, size, size);
  } else {
    if (artworkPair && clear > .01) quadImage(artworkPair.image, m.cover, ox, oy, g.k, clamp(clear));
    ctx.save(); ctx.globalAlpha *= 1 - clamp(clear); ctx.drawImage(arrayFrost, ox, oy, size, size); ctx.restore();
    ctx.save(); ctx.globalAlpha *= clamp(clear); ctx.drawImage(arrayClear, ox, oy, size, size); ctx.restore();
  }
  ctx.restore();
  ctx.save();
  if (journal && active) {const identity=sourceIdentity(journal);spine(m.label, ox, oy, g.k, identity.value,identity.label);}
  if (journal && tint < .5) topTitle(group, index, ox, oy, g.k);
  ctx.restore();
  const quad = transformedQuad(m.cover, ox, oy, g.k);
  if (journal && active && index === selectedRow().sel) {
    selectedCoverQuad = quad;
  }
  if (journal && active && index === selectedRow().sel && clear > .6 && inspection.time === 0) {
    ctx.fillStyle = ORANGE; quad.forEach(([x, y]) => ctx.fillRect(x - 2.5, y - 2.5, 5, 5));
    const [x, y] = quad[1], lx = x + 22, ly = y - 27;
    ctx.strokeStyle = INK; ctx.lineWidth = .8; ctx.beginPath(); ctx.moveTo(x + 4, y - 4); ctx.lineTo(lx, ly); ctx.lineTo(lx + 24, ly); ctx.stroke();
    const identity=sourceIdentity(journal),label=`${identity.label} ${identity.value}`;
    ctx.font = '9px "Geist Mono"';
    ctx.fillStyle = INK; ctx.fillRect(lx + 24, ly - 9, ctx.measureText(label).width + 14, 18);
    ctx.fillStyle = BG; ctx.fillText(label, lx + 31, ly + 3);
  }
  // Original resting hit polygon avoids moving the target under the pointer.
  const target = journal ? caseTargets(index, rows[group], active, shelves[group], -1) : { lift: 0, gap: c.gap.x };
  const rest = projection(group, index, target.lift, target.gap, position);
  if (active && journal) hitAreas.push({ group, track, index, empty: false, quad: transformedQuad(casePoly(), rest[0] - m.origin[0] * g.k, rest[1] - m.origin[1] * g.k, g.k) });
}
const rowAlpha = position => clamp(1 + position);
const rowTint = position => Math.round(clamp(.38 * clamp(position) + .14 * Math.max(0, position), 0, .8) * 10) / 10;
function tintedSprite(source, f, type) {
  // Canvas equivalent of RhinE's Direct2D colour matrix: RGB*(1-f)+BG*f,
  // preserving source alpha. Cached at the original 0.1 tint steps.
  const key = `${type}-${f}`;
  if (fadedSprites.has(key)) return fadedSprites.get(key);
  const image = document.createElement('canvas'); image.width = source.width; image.height = source.height;
  const g = image.getContext('2d'); g.drawImage(source, 0, 0);
  const pixels = g.getImageData(0, 0, image.width, image.height), bg = [238, 237, 231];
  for (let i = 0; i < pixels.data.length; i += 4)
    for (let c = 0; c < 3; c++) pixels.data[i + c] = pixels.data[i + c] * (1 - f) + bg[c] * f;
  g.putImageData(pixels, 0, 0); fadedSprites.set(key, image); return image;
}
function drawRail(group, slot, slots, position) {
  const g = geometry(), [sx, sy] = projection(group, slot, 0, 0, position), type = slot < 0 ? 'front' : slot >= slots ? 'back' : 'mid';
  ctx.save();
  const ox = sx - railMeta.origin[0] * g.k, oy = sy - railMeta.origin[1] * g.k;
  const tint = rowTint(position), image = railImages[type];
  ctx.drawImage(tint > 0 ? tintedSprite(image, tint, `rail-${type}`) : image, ox, oy, 900 * g.k, 900 * g.k);
  ctx.restore();
}

function caseWindow(group, position, slots) {
  // Source caseWindow's projected visibility, solved as an interval instead of scanning a long Group.
  const g=geometry(), ax=journalMeta.axes, m=journalMeta.array;
  const [x,y]=projection(group,0,0,0,position), dx=ax.y[0]*g.k, dy=-ax.y[1]*g.k, margin=dp(160);
  const left=-Math.max(m.origin[0],railMeta.origin[0])*g.k;
  const right=Math.max(journalMeta.array_res[0]-m.origin[0],900-railMeta.origin[0])*g.k;
  // Include the selection shoulder, hover and inspection lift; capacity itself never uses these animations.
  const top=-Math.max(m.origin[1]+(4.3+.5)*Math.abs(ax.z[1]),railMeta.origin[1])*g.k;
  const bottom=Math.max(journalMeta.array_res[1]-m.origin[1],900-railMeta.origin[1])*g.k;
  return [Math.max(-1,Math.ceil(Math.max((-margin-x-right)/dx,(y+top-H-margin)/dy))),
    Math.min(slots,Math.floor(Math.min((W+margin-x-left)/dx,(y+bottom+margin)/dy)))];
}

function segmentLabel(segment) {
  return segment.name+(segment.parts>1?` ${segment.part} / ${segment.parts}`:'');
}
function draw() {
  if(!inboxActive())return;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, stageWidth, H);
  hitAreas.length = 0;
  selectedCoverQuad = [];
  if (!journalMeta || !shelves.length || W <= 0 || H <= 0) return;
  // Preserve the original shelf viewport while inspection can cross the full stage.
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, W, H); ctx.clip();
  // RhinE's back-to-front rail/case ordering, one finite row per physical shelf.
  for (let track = shelves.length - 1; track >= Math.max(0, Math.floor(strip.x) - 1); track--) {
    const group = track, row = rows[group], pos = track - strip.x, active = track === state.track;
    if (pos <= -1) continue;
    const slots = slotCount(group), [first,last]=caseWindow(group,pos,slots);
    if (first > last) continue;
    ctx.save();
    ctx.globalAlpha = rowAlpha(pos);
    const items = [];
    for (let i = first; i <= last; i++)
      items.push({ i, rail: true, close: -.62 * (i - row.scroll.x + .4) });
    for (let i = Math.max(0,first); i <= Math.min(slots-1,last); i++) {
      const c = row.cases.get(i);
      items.push({ i, rail: false, close: -.62 * (i - row.scroll.x + (c ? c.gap.x : active ? .55 : 0)) + .64 * (c ? c.lift.x : 0) * .2 });
    }
    items.sort((a, b) => a.close - b.close);
    for (const item of items) {
      if (item.rail) drawRail(group, item.i, slots, pos);
      else arrayCase(group, item.i, track);
    }
    ctx.restore();
  }
  const {rightWidth,fadeStart,fadeEnd}=fadeGeometry();
  drawPaneEdge(W,rightWidth);
  const fade = ctx.createLinearGradient(0, fadeStart, 0, fadeEnd);
  fade.addColorStop(0, '#eeede700'); fade.addColorStop(1, BG);
  ctx.fillStyle = fade; ctx.fillRect(0, fadeStart, W, H-fadeStart);
  ctx.restore();
  if (inspection.time > liftDuration()) {
    const progress = phaseTurn();
    ctx.save(); ctx.globalAlpha = progress * .82; ctx.fillStyle = BG; ctx.fillRect(0, 0, stageWidth, H); ctx.restore();
    drawInspection();
    ctx.save();ctx.globalAlpha=progress;
    drawPaneEdge(inspectionWidth,rightWidth);
    ctx.restore();
  }
}

function drawPaneEdge(width,fadeWidth) {
  const edge=ctx.createLinearGradient(width-fadeWidth,0,width,0);
  edge.addColorStop(0,'#eeede700');edge.addColorStop(1,BG);
  ctx.fillStyle=edge;ctx.fillRect(width-fadeWidth,0,fadeWidth,H);
}

function fadeGeometry(frame = geometry()) {
  const k=frame.k, points=casePoly();
  const width=(Math.max(...points.map(p=>p[0]))-Math.min(...points.map(p=>p[0])))*k;
  const height=(Math.max(...points.map(p=>p[1]))-Math.min(...points.map(p=>p[1])))*k;
  // A local offset from the shelf origin, independent of the controls below.
  const fadeEnd=frame.y+dp(39*k/(.54*ARCHIVE_FRAME.scale));
  return {rightWidth:dp(clamp(width*.4,64,128)),fadeEnd,fadeStart:fadeEnd-dp(clamp(height*.3,56,96))};
}

function archiveControlGeometry(width, height, metrics, count, positions = {}) {
  // Each widget owns its width. Other widgets may overlap during free tuning.
  const capacity=Math.min(count,Math.max(1,Math.floor((width*.3-dp(86))/dp(7))));
  const rulerWidth=capacity*dp(7)+dp(86);
  const box=(name,w,h,x,y)=>{
    const p=positions[name];
    return {left:clamp(p?p.x*width-w/2:x,0,Math.max(0,width-w)),
      top:clamp(p?p.y*height-h/2:y,0,Math.max(0,height-h)),width:w};
  };
  return {capacity,
    count:box('count',metrics.countWidth,metrics.countHeight,dp(24),height-dp(150)),
    ruler:box('ruler',rulerWidth,dp(40),width*.34-dp(44),height-dp(68)),
    group:box('group',metrics.groupWidth,metrics.groupHeight,width*.774-metrics.groupWidth/2,height-dp(88)),
  };
}
let archiveControls = null, archiveControlsKey = '';
function archiveControlMetrics() {
  const count=document.querySelector('.selection-count'), group=document.querySelector('.group-navigation');
  // CSS owns these intrinsic/fixed widths. Never feed a hidden measurement
  // back into their inline width, where zero would survive showing the page.
  count.style.removeProperty('width');
  group.style.removeProperty('width');
  if (!count.getClientRects().length || !group.getClientRects().length) return null;
  // Reserve the largest configured digit count so changing Group cannot shift anchors.
  const digits=String(Math.max(1,...shelves.map(g=>g.journals.length))).length;
  $('selection-number').style.minWidth=`${digits}ch`;
  $('selection-total').style.minWidth=`${digits+2}ch`;
  const countBox=count.getBoundingClientRect(),groupBox=group.getBoundingClientRect();
  return {countWidth:countBox.width,countHeight:countBox.height,groupWidth:groupBox.width,groupHeight:groupBox.height};
}
function layoutArchiveControls(metrics = archiveControlMetrics()) {
  if (!metrics || !journalMeta || !railMeta || !shelves.length || W<=0 || H<=0) return;
  const key=[W,H,devicePixelRatio,...Object.values(metrics),shelves[state.shelf].journals.length,JSON.stringify(archiveDebug.values.positions)].join('|');
  if (key===archiveControlsKey) return;
  archiveControlsKey=key;
  archiveControls=archiveControlGeometry(W,H,metrics,shelves[state.shelf].journals.length,archiveDebug.values.positions);
  for (const [selector,box] of [['.selection-count',archiveControls.count],['.journal-navigation',archiveControls.ruler],['.group-navigation',archiveControls.group]]) {
    const style=document.querySelector(selector).style;
    style.left=`${box.left}px`;style.top=`${box.top}px`;
    if (selector==='.journal-navigation') style.width=`${box.width}px`;
  }
}

function caseState(group, index) {
  const row=rows[group];
  let c=row.cases.get(index);
  if(!c){
    const target=caseTargets(index,row,group===state.shelf,shelves[group]);
    c={lift:Spring(target.lift,13),clear:Spring(target.clear,8),gap:Spring(target.gap,11)};
    row.cases.set(index,c);
  }
  return c;
}
function syncCaseCache(group) {
  const row=rows[group],position=group-strip.x;
  const [first,last]=position>-1?caseWindow(group,position,slotCount(group)):[1,0];
  const pinned=group===state.shelf && inspection.time>0?row.sel:-1;
  for(const i of row.cases.keys())if((i<first || i>last) && i!==pinned)row.cases.delete(i);
  for(let i=Math.max(0,first);i<=Math.min(shelves[group].journals.length-1,last);i++)caseState(group,i);
  if(pinned>=0)caseState(group,pinned);
}

function tick(now) {
  if(configurationActive()){running=false;lastTime=0;return;}
  const dt = lastTime ? Math.min(.05, (now - lastTime) / 1000) : .016;
  lastTime = now;
  let more = false;
  if(inboxActive()) {more=stepInspection(dt);syncInspectionPanel();}
  if (inboxActive() && !shelves.length && !readerContext) { draw(); running = false; lastTime = 0; return; }
  if (inboxActive() && state.view === 'selected') {
    more = updateRuler(dt) || more;
    strip.to = state.track;
    more = stepSpring(strip, dt) || more;
    rows.forEach((row, g) => {
      if (REDUCE_MOTION) { row.scroll.x = row.scroll.to; row.scroll.v = 0; }
      more = stepSpring(row.scroll, dt) || more;
      syncCaseCache(g);
      row.cases.forEach((c, i) => {
        const target = shelves[g].journals[i] ? caseTargets(i, row, g === state.shelf, shelves[g]) : {lift:0,clear:0,gap:g === state.shelf ? .55 : 0};
        for (const key of ['lift', 'clear', 'gap']) {
          if(key==='lift')c[key].w=g===state.shelf?13:7;
          c[key].to = target[key];
          if (REDUCE_MOTION) { c[key].x = c[key].to; c[key].v = 0; }
          more = stepSpring(c[key], dt) || more;
        }
      });
    });
  }
  if (inboxActive() && state.view === 'journal') {
    more = stepSpring(directoryScroll, dt) || more;
    if (!inspection.removeAfter) paintDirectory();
  }
  const revealing = decryption.active;
  decryption.update(now / 1000, { clarity: 1 }, REDUCE_MOTION);
  if (revealing && !decryption.active && (state.view === 'journal' || readerContext)) renderReadingControls();
  more = decryption.active || more;
  draw();
  if (more) requestAnimationFrame(tick);
  else { running = false; lastTime = 0; }
}
function wake() { if (!configurationActive() && !running && state.ready) { running = true; lastTime = 0; requestAnimationFrame(tick); } }
function resize() {
  syncNavigation();
  if(!inboxActive() || !archiveLayout){
    if(readerContext && arrayActive()){fillAbstractPlaceholder();if(decryption.active)decryption.refresh();}
    return;
  }
  const metrics=archiveControlMetrics();
  const dimensions=archiveDebug.layout(dp(archiveLayout.infoWidth+archiveLayout.rightMargin)+dp(archiveLayout.gap),
    clamp($('selected-view').clientWidth*.48,640,900));
  const r = canvas.getBoundingClientRect();
  stageWidth=r.width;H=r.height;
  // RhinE infoX / arrayW: round the content + right margin together, then the gap.
  const readerPane=dimensions.readerPaneWidth;
  $('selected-view').style.setProperty('--archive-pane-width',`${dimensions.paneWidth}px`);
  $('selected-view').style.setProperty('--archive-gap',`${dp(archiveLayout.gap)}px`);
  $('selected-view').style.setProperty('--archive-right-margin',`${dp(archiveLayout.rightMargin)}px`);
  $('selected-view').style.setProperty('--reader-pane-width',`${readerPane}px`);
  $('selected-view').style.setProperty('--archive-control-height',`${dp(ARCHIVE_FRAME.controlHeight)}px`);
  W=document.querySelector('.collection').clientWidth;inspectionWidth=stageWidth-readerPane;
  cancelRulerDrag();
  ratio = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(stageWidth * ratio); canvas.height = Math.round(H * ratio);
  if (journalMeta) rows.forEach((row,i)=>{row.scroll.x=row.scroll.to=scrollTarget(row.sel,shelves[i]);row.scroll.v=0;});
  if (shelves.length) {layoutArchiveControls(metrics);layoutRuler();}
  if (state.ready && shelves.length && W > 0 && state.view === 'selected') {
    layoutJournalTitle();
    layoutPaperPreview();
    layoutSelectionDecoration();
  }
  if (state.view === 'journal' && !inspection.target) {
    const selection = returnSelection();
    if (selection) layoutJournalTitle(shelves[selection.group].journals[selection.slot]);
    layoutSelectionDecoration();
  }
  hideTickLabel();
  if (state.view === 'journal' && shelves.length) resetDirectory(true);
  if (state.view === 'journal' || readerContext) fillAbstractPlaceholder();
  if (decryption.active) decryption.refresh();
  wake();
}
new ResizeObserver(resize).observe(canvas);
window.addEventListener('archive-debug-change',()=>{
  const fullyOpen=state.view==='journal' && inspection.target===1 && inspection.time===inspection.duration;
  inspection.duration=archiveDebug.values.totalDurationMs/1000;
  if(fullyOpen)inspection.time=inspection.duration;
  else if(state.view==='selected')inspection.time=0;
  if(shelfCapacity!==archiveDebug.values.shelfCapacity){
    shelfCapacity=archiveDebug.values.shelfCapacity;
    if(state.ready){rebuildShelves();if(shelves.length)updateJournal();}
  }
  syncInspectionPanel();resize();
});
window.addEventListener('archive-controls-change',()=>{
  if(!inboxActive())return;
  if(state.view==='journal')layoutJournalControls(inspectionPose()?.bounds);
  else {layoutArchiveControls();layoutRuler();}
});

function visibleSlots() {
  if (!journalMeta || W <= 0 || H <= 0) return 1;
  // S: a selected case's full resting silhouette must fit, independently of hover and current springs.
  const g=archiveFrame(), ax=journalMeta.axes, m=journalMeta.array;
  const lift=caseTargets(0,{sel:0},true,null,-1).lift;
  const points=casePoly().map(([x,y])=>[g.x+(x-m.origin[0])*g.k,g.y+(y-m.origin[1]+lift*ax.z[1])*g.k]);
  const across=(W-dp(24)-Math.max(...points.map(p=>p[0])))/(ax.y[0]*g.k);
  const above=(Math.min(...points.map(p=>p[1]))-dp(24))/(-ax.y[1]*g.k);
  return Math.max(1,Math.floor(Math.min(across,above))+1);
}
function scrollTarget(index, row) {
  const visible = visibleSlots(), anchor = archiveFrame().anchor;
  return clamp(slotOf(row, index) - anchor, 0, Math.max(0, shelfCapacity - visible));
}
function selectJournal(group, index) {
  if (!state.ready || !shelves.length || state.view !== 'selected') return;
  state.shelf = clamp(group, 0, shelves.length - 1);
  state.track = state.shelf;
  const row = selectedRow();
  row.sel = clamp(index, 0, shelves[state.shelf].journals.length - 1);
  row.scroll.to = scrollTarget(row.sel, shelves[state.shelf]);
  AR.hover = -1;
  updateJournal(); wake();
}
function moveJournal(delta) {
  if (!shelves.length) return;
  const slots = activeSlots(state.shelf), position = slots.indexOf(selectedRow().sel);
  selectJournal(state.shelf, slots[clamp(position + delta, 0, slots.length - 1)]);
}
function moveShelf(delta) {
  if (!shelves.length) return;
  const group = clamp(state.shelf + delta, 0, shelves.length - 1);
  if(group!==state.shelf)selectJournal(group, rows[group].sel);
}
function button(text, label, action) {
  const node = document.createElement('button'); node.type = 'button';
  node.textContent = text; node.setAttribute('aria-label', label);
  node.addEventListener('click', action); return node;
}
function updateJournal() {
  const group = shelves[state.shelf];
  renderJournalFile(state.shelf, selectedRow().sel);
  const slots = activeSlots(state.shelf);
  $('selection-number').textContent = pad(slots.indexOf(selectedRow().sel) + 1);
  $('selection-total').textContent = `/ ${pad(slots.length)}`;
  $('group-number').textContent = `SHELF ${pad(state.shelf + 1)} / ${pad(shelves.length)}`;
  const labels=group.segments.map(segmentLabel);
  $('group-name').replaceChildren(...labels.map(label=>{
    const line=document.createElement('span');line.textContent=label;return line;
  }));
  $('group-name').title=labels.join('\n');
  $('group-name').setAttribute('aria-label',labels.join(', '));
  $('previous-group').disabled=state.shelf===0;
  $('next-group').disabled=state.shelf===shelves.length-1;
  // Keep each Journal's actual list DOM and scroll position across selections.
  if ($('journal-ticks').dataset.group !== String(state.shelf)) {
    cancelRulerDrag();
    hideTickLabel();
    AR.hoverTick = AR.focusTick = -1;
    AR.ticks.clear();
    AR.rulerStart.x = AR.rulerStart.to = rulerStartTarget(); AR.rulerStart.v = 0;
    $('journal-ticks').dataset.group = state.shelf;
    $('journal-ticks').replaceChildren(...slots.map(i => {
      const journal = group.journals[i];
      // Pointer selection commits on release; native keyboard clicks have detail 0.
      const tick = button('', `选择 ${journal.name}`, event => {
        if (event.detail === 0 && rulerEnabled()) selectJournal(state.shelf, i);
      });
      tick.addEventListener('focus', () => { AR.focusTick = i; wake(); });
      tick.addEventListener('blur', () => { AR.focusTick = -1; wake(); });
      return tick;
    }));
  }
  layoutArchiveControls();layoutRuler();
  $('previous-journal').disabled = selectedRow().sel === slots[0];
  $('next-journal').disabled = selectedRow().sel === slots.at(-1);
}
// Render the return destination without removing the case that is still animating.
function renderJournalFile(groupIndex, slot) {
  const group = shelves[groupIndex], j = group.journals[slot];
  filePanel.dataset.journal = j.key;
  layoutJournalTitle(j);
  $('ghost-subject').textContent = j.logicalGroupName.toUpperCase();
  $('archive-subject').textContent=j.logicalGroupName;
  $('profile-identity').textContent = [j.issn,j.eissn].filter(Boolean).join(' / ') || 'UNMAPPED';
  $('profile-publisher').textContent = j.publisher || '未配置';
  $('profile-service').textContent = j.service || '未配置';
  for (const [issn, list] of lists) list.hidden = issn !== j.key;
  for (const id of ['profile-publisher', 'profile-service']) {$(id).removeAttribute('title');$(id).setAttribute('aria-label',$(id).textContent);}
  requestAnimationFrame(()=>{layoutPaperPreview();layoutSelectionDecoration();});
}
function layoutPaperPreview() {
  const list=lists.get(filePanel.dataset.journal),more=$('open-journal-more');
  if (!list || filePanel.hidden) return;
  const total=list.children.length;
  // More follows the final visible row in normal flow; reserve its 28px plus 12px gap only when needed.
  const room=$('archive-preview').clientHeight,allFit=total*30<=room;
  const fit=Math.min(total,Math.max(0,Math.floor((room-(allFit?0:40))/30)));
  [...list.children].forEach((row,i)=>{row.hidden=i>=fit;});
  $('paper-lists').style.height=`${fit*30}px`;
  const remaining=Math.max(0,total-fit);
  more.hidden=remaining===0;
  more.textContent=`+ ${remaining} MORE · OPEN JOURNAL`;
  more.setAttribute('aria-label',`还有 ${remaining} 篇论文，打开完整期刊目录`);
  list.scrollTop=0;
}
$('open-journal-more').addEventListener('click',()=>{
  const more=$('open-journal-more');
  if (!more.disabled && filePanel.dataset.journal===selectedJournal()?.key) openView(null,more);
});
// DOM equivalent of archive.js::drawRuler's plate, also available to keyboard focus.
function rulerCount() {
  return archiveControls?.capacity ?? 8;
}
function rulerStartTarget() {
  const count = shelves[state.shelf]?.journals.length || 0;
  return clamp((selectedRow()?.sel || 0) - Math.floor(rulerCount() / 2), 0, Math.max(0, count - rulerCount()));
}
function updateRuler(dt) {
  AR.rulerStart.to = rulerStartTarget();
  if (REDUCE_MOTION) { AR.rulerStart.x = AR.rulerStart.to; AR.rulerStart.v = 0; }
  let more = stepSpring(AR.rulerStart, dt);
  const hover = AR.hoverTick >= 0 ? AR.hoverTick : AR.focusTick;
  for (let i = 0; i < shelves[state.shelf].journals.length; i++) {
    const distance = hover >= 0 ? i - hover : 99;
    const target = i === selectedRow().sel ? 30 : 10 + 12 * Math.exp(-distance * distance / 1.5);
    if (!AR.ticks.has(i)) AR.ticks.set(i, Spring(target, 18));
    const mark = AR.ticks.get(i); mark.to = target;
    if (REDUCE_MOTION) { mark.x = mark.to; mark.v = 0; }
    more = stepSpring(mark, dt) || more;
  }
  layoutRuler();
  return more;
}
function layoutRuler() {
  if (!shelves.length) return;
  const count = shelves[state.shelf].journals.length, capacity = rulerCount(), start = AR.rulerStart.x;
  $('journal-ticks').style.width = `${Math.min(count, capacity) * dp(7) + dp(4)}px`;
  $('next-journal').style.left = `${Math.min(count, capacity) * dp(7) + dp(54)}px`;
  [...$('journal-ticks').children].forEach((mark, i) => {
    const selected = i === selectedRow().sel, height = dp(AR.ticks.get(i)?.x ?? (selected ? 30 : 10));
    mark.style.left = `${dp(4) + dp((i - start) * 7)}px`;
    mark.style.top = `calc(50% - ${height / 2}px)`;
    mark.style.height = `${height}px`; mark.style.width = `${dp(selected ? 3 : 2)}px`;
    mark.hidden = !selected && (i < Math.floor(start) - 1 || i > start + capacity);
    mark.tabIndex = selected ? 0 : -1;
    mark.setAttribute('aria-current', String(selected));
  });
  const hover = AR.hoverTick >= 0 ? AR.hoverTick : AR.focusTick;
  if (hover >= 0 && rulerEnabled()) showTickLabel($('journal-ticks').children[hover], hover);
  else hideTickLabel();
}
function rulerEnabled() {
  return state.ready && state.view === 'selected' && !inspection.time && !decisionPending && !snapshotApplying && inboxActive();
}
function rulerTickAt(clientX) {
  const rect = $('journal-ticks').getBoundingClientRect();
  return clamp(Math.round((clientX - rect.left - dp(4)) / dp(7) + AR.rulerStart.x), 0, shelves[state.shelf].journals.length - 1);
}
function cancelRulerDrag() {
  const drag = AR.rulerDrag; AR.rulerDrag = null;
  if (drag && $('journal-ticks').hasPointerCapture(drag.pointerId)) $('journal-ticks').releasePointerCapture(drag.pointerId);
}
$('journal-ticks').setAttribute('role', 'group');
$('journal-ticks').addEventListener('pointerdown', event => {
  if (event.button !== 0 || !rulerEnabled()) return;
  event.preventDefault();
  AR.rulerDrag = { pointerId: event.pointerId, group: state.shelf };
  $('journal-ticks').setPointerCapture(event.pointerId);
  AR.hoverTick = rulerTickAt(event.clientX); wake();
});
$('journal-ticks').addEventListener('pointermove', event => {
  if (!rulerEnabled() || (AR.rulerDrag && AR.rulerDrag.pointerId !== event.pointerId)) return;
  AR.hoverTick = rulerTickAt(event.clientX); wake();
});
$('journal-ticks').addEventListener('pointerup', event => {
  const drag = AR.rulerDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  const index = rulerTickAt(event.clientX), enabled = rulerEnabled() && drag.group === state.shelf;
  cancelRulerDrag(); AR.hoverTick = -1;
  if (enabled) {
    selectJournal(state.shelf, index);
    $('journal-ticks').children[index]?.focus({ preventScroll: true });
  }
  wake();
});
for (const name of ['pointercancel', 'lostpointercapture']) $('journal-ticks').addEventListener(name, () => {
  cancelRulerDrag(); AR.hoverTick = -1; wake();
});
$('journal-ticks').addEventListener('pointerleave', () => {
  if (!AR.rulerDrag) { AR.hoverTick = -1; wake(); }
});
$('journal-ticks').addEventListener('keydown', event => {
  if (!rulerEnabled()) return;
  const last = shelves[state.shelf].journals.length - 1;
  const index = { ArrowUp: selectedRow().sel + 1, ArrowDown: selectedRow().sel - 1, Home: 0, End: last }[event.key];
  if (index === undefined) return;
  event.preventDefault(); selectJournal(state.shelf, clamp(index, 0, last));
  $('journal-ticks').children[selectedRow().sel]?.focus({ preventScroll: true });
});
function showTickLabel(tick, index) {
  const journal = shelves[state.shelf]?.journals[index];
  if (!journal) return;
  const label = $('journal-tick-label'), area = document.querySelector('.collection').getBoundingClientRect();
  if (!label.firstElementChild) label.append(document.createElement('span'));
  label.firstElementChild.textContent = `${pad(activeSlots(state.shelf).indexOf(index) + 1)} · ${journal.name}`;
  label.hidden = false;
  const box = label.getBoundingClientRect();
  const marks = $('journal-ticks').getBoundingClientRect();
  const center = marks.left - area.left + dp(4) + (index - AR.rulerStart.x) * dp(7);
  const left = Math.max(dp(8), Math.min(center - box.width / 2, area.width - box.width - dp(8)));
  label.style.left = `${left}px`;
  label.style.top = `${Math.max(dp(8), marks.top - area.top - box.height - dp(10))}px`;
  label.style.setProperty('--ruler-stem-left', `${center - left}px`);
  document.querySelectorAll('#journal-ticks [aria-describedby]').forEach(mark => {
    if (mark !== tick) mark.removeAttribute('aria-describedby');
  });
  tick.setAttribute('aria-describedby', 'journal-tick-label');
}
function hideTickLabel() {
  $('journal-tick-label').hidden = true;
  document.querySelectorAll('#journal-ticks [aria-describedby]').forEach(tick => tick.removeAttribute('aria-describedby'));
}
function layoutSelectionDecoration() {
  if (filePanel.hidden) return;
  const list = lists.get(filePanel.dataset.journal), ghost = $('ghost-subject');
  if (!list || !ghost.getClientRects().length) return;
  const bounds = ghost.getBoundingClientRect(), viewport = list.getBoundingClientRect();
  const overlaps = [...list.children].some(row => {
    const rect = row.getBoundingClientRect();
    return rect.top < Math.min(bounds.bottom, viewport.bottom) && rect.bottom > Math.max(bounds.top, viewport.top);
  });
  document.querySelector('.file-panel').dataset.ghostHidden = String(overlaps);
}
function wrapArchiveTitle(text, width, measure) {
  let remaining = text.replace(/\s+/g, ' ').trim();
  const lines = [];
  while (remaining && lines.length < 2) {
    if (measure(remaining) <= width) { lines.push(remaining); break; }
    const chars = Array.from(remaining);
    if (lines.length === 1) {
      while (chars.length && measure(chars.join('').trimEnd() + '…') > width) chars.pop();
      lines.push(chars.join('').trimEnd() + '…'); break;
    }
    let fit = 0;
    while (fit < chars.length && measure(chars.slice(0, fit + 1).join('')) <= width) fit++;
    fit = Math.max(1, fit);
    const prefix = chars.slice(0, fit).join(''), space = prefix.lastIndexOf(' ');
    const line = space > 0 ? prefix.slice(0, space) : prefix;
    lines.push(line); remaining = remaining.slice(line.length).trimStart();
  }
  return lines;
}
function layoutJournalTitle(journal = selectedJournal()) {
  if (!journal || !archiveLayout) return;
  const title = $('journal-title'), style = getComputedStyle(title);
  ctx.save(); ctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
  const lines = wrapArchiveTitle(journal.name, Math.max(1, title.clientWidth - dp(24)), text => ctx.measureText(text).width);
  ctx.restore();
  title.title = journal.name; title.setAttribute('aria-label', journal.name);
  title.replaceChildren(...lines.map(text => {
    const plate = document.createElement('span'); plate.textContent = text; return plate;
  }));
}
function createLists(journals = shelves.flatMap(group => group.journals)) {
  for (const journal of journals) {
    if (!journal) continue;
    const existing=lists.get(journal.key), scroll=existing?.scrollTop || 0;
    const list = existing || document.createElement('div'); list.className = 'paper-list';
    list.addEventListener('scroll', layoutSelectionDecoration);
    list.dataset.journal = journal.key;
    if (!existing) list.hidden = true;
    list.replaceChildren();
    journal.papers.forEach((paper, i) => {
      const row = button('', paper.title, () => openView(paper.id, row));
      row.className = 'paper-row'; row.dataset.paperId = paper.id;
      const number = document.createElement('span'); number.className = 'row-number'; number.textContent = pad(i + 1);
      const clip = document.createElement('span'); clip.className = 'title-clip';
      const title = document.createElement('span'); title.className = 'title-text';
      clip.append(title);
      const date = document.createElement('time');
      row.append(number, clip, date);
      patchPaperRow(row,paper);
      list.append(row);
    });
    lists.set(journal.key, list); $('paper-lists').append(list);
    list.scrollTop=scroll;
  }
}
function patchPaperRow(row,paper) {
  const title=row.querySelector('.title-text'),date=row.querySelector('time');
  if(title.textContent!==paper.title)title.textContent=paper.title;
  if(row.getAttribute('aria-label')!==paper.title)row.setAttribute('aria-label',paper.title);
  const value=paper.publication_date || '—';
  if(date.textContent!==value)date.textContent=value;
  if(paper.publication_date){if(date.dateTime!==paper.publication_date)date.dateTime=paper.publication_date;date.removeAttribute('aria-label');}
  else {date.removeAttribute('datetime');date.setAttribute('aria-label','Publication date unavailable');}
}

// RhinE lift / 60-frame Inspection driven by the shared stage durations.
function inspectionScale() {
  const crop = journalMeta.inspect.at(-1).crop;
  const k0 = geometry().baseK * journalMeta.array_ppu / journalMeta.inspect_ppu;
  return Math.max(Number.EPSILON, Math.min(k0 * 2.05, inspectionWidth * .9 / crop[2], Math.max(1,H - 190) / crop[3]));
}
function inspectionPose() {
  const turning = phaseTurn();
  if (!turning) return null;
  const g = geometry(), c = caseState(state.shelf,selectedRow().sel);
  const [sx, sy] = projection(state.shelf, selectedRow().sel, c.lift.x + 2.2 * phaseLift(), c.gap.x);
  const start = [sx + (journalMeta.array.center[0] - journalMeta.array.origin[0]) * g.k,
                 sy + (journalMeta.array.center[1] - journalMeta.array.origin[1]) * g.k];
  const frame = turning * 59, i = Math.min(58, Math.floor(frame)), f = frame - i;
  const a = journalMeta.inspect[i], b = journalMeta.inspect[i + 1], crop = journalMeta.inspect[59].crop;
  const k0 = g.k * journalMeta.array_ppu / journalMeta.inspect_ppu;
  const frontK = inspectionScale();
  const k = mix(k0, frontK, turning);
  const end = [inspectionWidth * .5, H * .50];
  const center = a.center.map((v, axis) => mix(v, b.center[axis], f));
  const destination = [end[0] - (crop[0] + crop[2] / 2) * frontK,
                       end[1] - (crop[1] + crop[3] / 2) * frontK];
  const ox = mix(start[0] - center[0] * k, destination[0], turning);
  const oy = mix(start[1] - center[1] * k, destination[1], turning);
  const q = key => a[key].map((point, n) => point.map((v, axis) => mix(v, b[key][n][axis], f)));
  return { ox, oy, k, i, f, a, b, q, bounds: {x:ox + crop[0] * k, y:oy + crop[1] * k, width:crop[2] * k, height:crop[3] * k} };
}
function journalControlGeometry(width,height,bounds,metrics,positions={}) {
  const box=(name,w,h,left,top)=>{
    const p=positions[name];
    return {left:clamp(p?p.x*width-w/2:left,0,Math.max(0,width-w)),
      top:clamp(p?p.y*height-h/2:top,0,Math.max(0,height-h))};
  };
  return {
    inspectionHeading:box('inspectionHeading',metrics.headingWidth,metrics.headingHeight,bounds.x,bounds.y-dp(16)-metrics.headingHeight),
    inspectionBack:box('inspectionBack',metrics.backWidth,metrics.backHeight,bounds.x,bounds.y+bounds.height+dp(16)),
    inspectionActions:box('inspectionActions',metrics.actionsWidth,metrics.actionsHeight,bounds.x+bounds.width-metrics.actionsWidth,bounds.y+bounds.height+dp(16)),
  };
}
function layoutJournalControls(bounds) {
  const area=document.querySelector('#journal-view .review-left');
  if(!bounds || area.dataset.ready!=='true')return;
  const widgets=[...area.querySelectorAll('[data-journal-widget]')];
  const [heading,back,actions]=widgets.map(widget=>widget.getBoundingClientRect());
  const boxes=journalControlGeometry(area.clientWidth,area.clientHeight,bounds,
    {headingWidth:heading.width,headingHeight:heading.height,backWidth:back.width,backHeight:back.height,
      actionsWidth:actions.width,actionsHeight:actions.height},archiveDebug.values.positions);
  for(const widget of widgets){
    const box=boxes[widget.dataset.journalWidget];widget.style.left=`${box.left}px`;widget.style.top=`${box.top}px`;
  }
}
function drawInspection() {
  const pose = inspectionPose();
  if (!pose) return;
  const {ox, oy, k, i, f, a, b, q} = pose, journal = selectedJournal();
  const controls = document.querySelector('#journal-view .review-left');
  controls.dataset.ready = String(inspection.time === inspection.duration && Boolean(inspection.target));
  layoutJournalControls(pose.bounds);
  const revealDuration = Math.min(liftDuration(),inspection.duration - liftDuration());
  const reveal = clamp((inspection.time - (inspection.duration - revealDuration)) / revealDuration);
  quadImage(covers.get(journal.key).image, q('cover'), ox, oy, k);
  if (reveal) quadImage(directoryCanvas, q('cover'), ox, oy, k, reveal);
  const sprite = (image, meta, alpha) => {
    const [x, y, w, h] = meta.crop;
    ctx.save(); ctx.globalAlpha = alpha;
    ctx.drawImage(image, ox + x * k, oy + y * k, w * k, h * k); ctx.restore();
  };
  sprite(inspectionFrames[i], a, 1);
  if (f > .001) sprite(inspectionFrames[i + 1], b, f);
  const identity=sourceIdentity(journal);spine(q('label'), ox, oy, k, identity.value,identity.label);
  selectedCoverQuad = transformedQuad(q('cover'), ox, oy, k);
  ctx.fillStyle = ORANGE;
  selectedCoverQuad.forEach(([x,y]) => ctx.fillRect(x - 2, y - 2, 4, 4));
}
function syncInspectionPanel() {
  if (readerContext || state.view !== 'journal') return;
  filePanel.style.opacity = String(1 - phaseLift());
  const progress = phaseTurn(),{panelShift} = archiveDebug.values;
  $('journal-view').style.setProperty('--journal-reveal-progress',String(progress));
  $('paper-detail').style.opacity = String(progress);
  $('paper-detail').style.transform = `translateX(${panelShift * (1 - progress)}px)`;
  $('journal-view').inert = !(inspection.target === 1 && inspection.time === inspection.duration);
}
function clearInspectionPanel() {
  filePanel.style.removeProperty('opacity');
  $('journal-view').style.removeProperty('--journal-reveal-progress');
  $('paper-detail').style.removeProperty('opacity');
  $('paper-detail').style.removeProperty('transform');
}
function revealCompletionSurface(immediate = false) {
  if (!inspection.completionPending) return;
  syncInspectionPanel();
  inspection.completionPending = false;
  completionSurface.enterDuration = archiveDebug.values.liftEndMs;
  completionSurface.show(immediate || REDUCE_MOTION);
}
function stepInspection(dt) {
  const target = inspection.target ? inspection.duration : 0;
  if (inspection.time === target) return false;
  const nextTime = REDUCE_MOTION ? target : clamp(inspection.time + Math.sign(target - inspection.time) * dt, 0, inspection.duration);
  const lift = liftDuration();
  // Give the completion fade the whole lift phase, even when a frame crosses its boundary.
  inspection.time = !REDUCE_MOTION && !inspection.target && inspection.completionPending && inspection.time > lift && nextTime <= lift ? lift : nextTime;
  if (!inspection.target && inspection.time <= lift) revealCompletionSurface(inspection.time === 0);
  if (inspection.time === inspection.duration) { $('mode-label').textContent = 'ARCHIVE / JOURNAL'; renderReadingControls(); }
  if (inspection.time === 0) finishReturn();
  return inspection.time !== target;
}
function openView(paperId = null, source = canvas) {
  if(window.allfoldUIPreferences.archiveDisabled()){
    if(paperId)window.workspaceArray?.openPaper(paperId);
    return;
  }
  if (state.view !== 'selected' || !shelves.length || decisionPending || snapshotApplying || inspection.time) return;
  $('paper-metadata-details').open=false;
  const journal = selectedJournal();
  cancelRulerDrag(); AR.hoverTick = AR.focusTick = -1; hideTickLabel();
  document.querySelector('.collection-bottom').inert = true;
  state.view = 'journal'; state.pendingPaper = paperId || journal.papers[0].id; state.focusSource = source;

  inspection.target = 1; inspection.removeAfter = false; inspection.completionPending = false;
  canvas.title = journal.name;
  canvas.setAttribute('aria-label', `${journal.name}：论文目录，可滚动并点击标题阅读`);
  document.querySelector('.review-left').dataset.ready = 'false';
  filePanel.hidden = false; filePanel.inert = true;
  $('selected-view').classList.add('inspecting');
  $('mode-label').textContent = 'ARCHIVE / INSPECTION';
  syncInspectionPanel(); $('journal-view').hidden = false;
  resize(); renderPaper();
  if (REDUCE_MOTION) { stepInspection(0); syncInspectionPanel(); }
  fillAbstractPlaceholder(); wake();
}
function back() {
  if (state.view !== 'journal' || !inspection.target || decisionPending || snapshotApplying || paperToolsBusy()) return;
   decryption.reset(null, true);
  inspection.target = 0;
  $('journal-view').inert = true;
  const selection = returnSelection();
  if (selection) {
    filePanel.hidden = false;
    renderJournalFile(selection.group, selection.slot);
    requestAnimationFrame(layoutSelectionDecoration);
  } else {
    filePanel.hidden = true;
    $('selected-view').classList.add('returning-complete');
    inspection.completionPending = true;
  }
  if (inspection.time <= liftDuration()) revealCompletionSurface(true);
  renderReadingControls();
  $('mode-label').textContent = 'ARCHIVE / RETURN';
  if (inspection.time === 0) finishReturn();
  else if (REDUCE_MOTION) stepInspection(0);
  wake();
}
function returnSelection() {
  if (!inspection.removeAfter) return {group:state.shelf, slot:selectedRow().sel};
  const group = shelves[state.shelf], slot = selectedRow().sel;
  if (group.journals.length > 1)
    return {group:state.shelf, slot:slot + 1 < group.journals.length ? slot + 1 : 0};
  if (shelves.length > 1) {
    const nextGroup = (state.shelf + 1) % shelves.length;
    return {group:nextGroup, slot:rows[nextGroup].sel};
  }
  return null;
}
function finishReturn() {
  inspection.completionPending = false;
  paragraphLayout?.clear();
  completionSurface.dispose();
  $('journal-view').hidden = true; $('journal-view').inert = true;
  clearInspectionPanel();
  canvas.removeAttribute('title');
  canvas.setAttribute('aria-label', '期刊档案架：上下键选期刊，左右键切换货架，Enter 查看');
  if (inspection.removeAfter) removeFinishedJournal();
  inspection.removeAfter = false;
  state.pendingPaper = null;
  document.querySelector('.collection-bottom').inert = false;
  $('selected-view').classList.remove('inspecting', 'returning-complete');

  syncNavigation();
  if (!shelves.length) {
    filePanel.hidden = true;
    state.view = 'empty'; $('empty-inbox').hidden = false;
    document.querySelector('.collection').hidden=true;
    $('mode-label').textContent = 'ARCHIVE / COMPLETE'; updateSnapshotCount(); syncNavigation(); return;
  }
  state.view = 'selected'; filePanel.hidden = false; filePanel.inert = false;
  updateJournal(); updateSnapshotCount();
  $('mode-label').textContent = 'ARCHIVE / BROWSE';
  syncNavigation();
  resize();
  const source = state.focusSource?.isConnected && !state.focusSource.hidden ? state.focusSource : canvas;
  source.focus({preventScroll:true});
}
function directoryLayout() {
  if (!journalMeta || W <= 0 || H <= 0 || !selectedJournal()) return null;
  // Match the formal (8000) 768px directory typography, independent of reader text.
  const top=86,start=90,bottom=730,row=116,pitch=128,gap=pitch-row,height=bottom-top;
  return {top,start,bottom,height,row,pitch,x:30,width:708,
    maxScroll:Math.max(0,start-top+selectedJournal().papers.length*pitch-gap-height)};
}
function resetDirectory(immediate = false) {
  const layout = directoryLayout();
  if (!layout) return;
  const index = selectedJournal().papers.findIndex(p => p.id === state.pendingPaper);
  directoryScroll.to = clamp(layout.start-layout.top + index * layout.pitch - (layout.height - layout.row) / 2, 0, layout.maxScroll);
  if (immediate || REDUCE_MOTION) { directoryScroll.x = directoryScroll.to; directoryScroll.v = 0; }
  paintDirectory();
}
function fitDirectoryText(text, width) {
  const g = directoryContext;
  if (g.measureText(text).width <= width) return text;
  const chars = Array.from(text);
  while (chars.length && g.measureText(chars.join('') + '…').width > width) chars.pop();
  return chars.length ? chars.join('') + '…' : '';
}
function directoryTitleLines(text, width) {
  const g = directoryContext;
  if (g.measureText(text).width <= width) return [text];
  const chars = Array.from(text); let n = 0;
  while (n < chars.length && g.measureText(chars.slice(0,n + 1).join('')).width <= width) n++;
  if (!n) return [];
  const prefix = chars.slice(0,n).join(''), space = prefix.lastIndexOf(' ');
  const first = space > 0 ? prefix.slice(0,space) : prefix;
  return [first, fitDirectoryText(text.slice(first.length).trimStart(), width)];
}
function paintDirectory() {
  const m = directoryLayout();
  if (!m) return;
  const journal=selectedJournal(),g=directoryContext;
  directoryScroll.to=clamp(directoryScroll.to,0,m.maxScroll);
  directoryScroll.x=clamp(directoryScroll.x,0,m.maxScroll);
  g.save();g.textBaseline='alphabetic';g.fillStyle=BG;g.fillRect(0,0,768,768);
  g.fillStyle=INK;g.font='500 26px "Source Sans 3", "MiSans", sans-serif';
  g.fillText(fitDirectoryText(journal.name,692),38,45);
  g.fillStyle=INK;g.fillRect(38,65,692,3);
  directoryAreas=[];g.save();g.beginPath();g.rect(m.x,m.top,m.width,m.height);g.clip();
  journal.papers.forEach((paper,index)=>{
    const y=m.start+index*m.pitch-directoryScroll.x;
    if(y+m.row<m.top || y>m.bottom)return;
    const selected=paper.id===state.pendingPaper;
    g.fillStyle=selected?INK:'#e3e3da';g.fillRect(m.x,y,m.width,m.row);
    g.fillStyle=selected?BG:INK;g.font='18px "Geist Mono"';g.fillText(pad(index+1),46,y+30);
    g.font='500 24px "Source Sans 3", "MiSans", sans-serif';
    directoryTitleLines(paper.title,575).forEach((line,i)=>g.fillText(line,91,y+31+i*29));
    g.fillStyle=selected?'#bebfb3':MUTED;g.font='18px "Geist Mono"';
    g.fillText(paper.publication_date || 'DATE UNAVAILABLE',91,y+98);
    const top=Math.max(m.top,y),bottom=Math.min(m.bottom,y+m.row);
    directoryAreas.push({id:paper.id,x:m.x,y:top,width:m.width,height:bottom-top});
  });
  g.restore();g.restore();
}

function directoryPoint(event) {
  if (selectedCoverQuad.length !== 4 || inspection.time !== inspection.duration) return null;
  const rect=canvas.getBoundingClientRect(), x=event.clientX-rect.left, y=event.clientY-rect.top;
  if (!contains(selectedCoverQuad,x,y)) return null;
  const [p,a,,b]=selectedCoverQuad, ax=a[0]-p[0], ay=a[1]-p[1], bx=b[0]-p[0], by=b[1]-p[1];
  const determinant=ax*by-ay*bx;
  return {x:((x-p[0])*by-(y-p[1])*bx)/determinant*768,y:(ax*(y-p[1])-ay*(x-p[0]))/determinant*768};
}
function directoryHit(event) {
  if (state.view !== 'journal' || !inspection.target || inspection.removeAfter) return null;
  const point = directoryPoint(event);
  return point && directoryAreas.find(a => point.x >= a.x && point.x <= a.x+a.width && point.y >= a.y && point.y <= a.y+a.height);
}
function selectPaper(id, immediateDirectory = false) {
  if (decisionPending || snapshotApplying || paperToolsBusy() || inspection.removeAfter || id === state.pendingPaper) return;
   state.pendingPaper = id;
  renderPaper();
  if(readerContext) window.dispatchEvent(new CustomEvent('array-paper-selected',{detail:id}));
  else resetDirectory(immediateDirectory);
  wake();
}
function movePaper(delta) {
  const papers=reviewPapers();
  if (papers.length < 2) return;
  const index=papers.findIndex(p => p.id === state.pendingPaper),next=index+delta;
  selectPaper(papers[(next + papers.length) % papers.length].id,next < 0 || next >= papers.length);
}
function renderField(id, text, missing, bars=1) {
  const root=$(id); root.classList.remove('enrich-new','reveal-pending'); root.replaceChildren();
  if (!missing) { root.textContent=text; return; }
  const placeholder=document.createElement('span');placeholder.className='missing-field';
  placeholder.setAttribute('aria-label','暂无内容');
  for (let i=0;i<bars;i++) { const bar=document.createElement('span'); bar.className='missing-ink'; placeholder.append(bar); }
  root.append(placeholder);
}
function renderPaper(previous=null) {
  const paper=currentPaper(); if (!paper) return;
  const text=(id,value)=>{if($(id).textContent!==value)$(id).textContent=value;};
  const differs=field=>!previous || JSON.stringify(previous[field])!==JSON.stringify(paper[field]);
  if(!previous || differs('abstract'))decryption.reset(null,true);
  const detail=$('paper-detail'), changed=detail.dataset.paperId!==paper.id;
  if(changed) {paperMetadata.open=false;paragraphLayout?.clear();}
  if(readerContext && changed)paperMetadata.open=true;
  const papers=reviewPapers(), index=papers.indexOf(paper);
  text('view-paper-title',paper.title || paper.identity_label); text('view-paper-id',paper.id);
  text('paper-position',`${pad(index+1)} / ${pad(papers.length)}`);
  if (!readerContext) text('directory-position',`${pad(index+1)} / ${pad(papers.length)} PAPERS`);
  for (const id of ['previous-paper','next-paper']) $(id).disabled=papers.length===1;
  renderPaperFields(paper, ['abstract','authors','publication_date'].filter(differs));
  if(['ordinary_dates','first_public_at','preprints','preprint_evidence'].some(differs))
    window.allfoldPaperDates.render(paper,$('paper-dates'),$('paper-date-evidence'));
  text('paper-source',paper.conference || paper.journal || reviewJournal()?.name || '—');
  text('paper-identifiers',Object.entries(paper.external_ids || {}).filter(([key])=>key!=='doi').map(([key,value])=>`${key}: ${value}`).join('; ') || '—');
  text('paper-indexed-terms',(paper.indexed_terms || []).map(item=>`${item.value}${item.kind || item.source ? ` (${[item.kind,item.source].filter(Boolean).join(' · ')})` : ''}`).join('; ') || '—');
  text('paper-providers',(paper.sources || []).map(source=>`${source.provider}${source.role?` (${source.role})`:''}: ${source.record_id}${source.version?` · ${source.version}`:''}`).join('; ') || '—');
  text('paper-doi',paper.doi || 'DOI unavailable');
  if (paper.doi) $('paper-doi').href=`https://doi.org/${encodeURI(paper.doi)}`; else $('paper-doi').removeAttribute('href');
  window.allfoldPreprintLookup.select(readerContext ? paper : null);
  detail.dataset.paperId=paper.id;
  detail.classList.toggle('abstract-locked', !paper.abstract?.trim());
  if (changed) detail.scrollTop=0;
  renderPaperTools((!previous || ['abstract','authors','publication_date'].some(differs)) && !paperToolsBusy());
  renderReadingControls();
}
function renderPaperFields(paper, fields) {
  if (fields.includes('authors')) {
    renderField('paper-authors',paper.authors.join(', '),!paper.authors.length);
    if (paper.authors.length) {
      $('paper-authors').replaceChildren(...paper.authors.flatMap((name,index) => {
        const author=document.createElement('span'); author.className='paper-author'; author.textContent=name;
        return index ? [document.createTextNode('; '),author] : [author];
      }));
    }
  }
  if (fields.includes('publication_date')) {
    renderField('paper-date',paper.publication_date,!paper.publication_date);

  }
  if (fields.includes('abstract')) {
    if(paragraphLayout && paper.abstract?.trim()) {
      $('paper-abstract').classList.remove('enrich-new','reveal-pending');
      paragraphLayout.setText(paper.abstract);
    } else {
      paragraphLayout?.clear();
      renderField('paper-abstract',paper.abstract,!paper.abstract?.trim());
    }
  }
  const missing=Number(!paper.authors.length)+Number(!paper.publication_date);
  $('paper-metadata-summary').textContent=`Infos${missing ? ` · ${missing} missing` : ''}`;
}
function fillAbstractPlaceholder() {
  const placeholder=$('paper-abstract').querySelector('.missing-field');
  if (!placeholder || (state.view!=='journal' && !(readerContext && arrayActive()))) return;
  const root=$('paper-abstract'), metrics=abstractLineMetrics(root);
  const top=metrics.top+24;
  root.style.setProperty('--abstract-ink-top',`${top}px`);
  root.style.setProperty('--abstract-ink-height',`${metrics.height}px`);
  root.style.setProperty('--abstract-line-height',`${metrics.lineHeight}px`);
  const height=root.getBoundingClientRect().height;
  const count=Math.max(1,Math.ceil((height-top)/metrics.lineHeight));
  placeholder.replaceChildren(...Array.from({length:count},(_,i) => {
    const bar=document.createElement('span'); bar.className='missing-ink';
    bar.style.setProperty('--abstract-line',i);
    if (i===count-1) bar.style.height=`${Math.max(0,height-top-i*metrics.lineHeight)}px`;
    return bar;
  }));
}
function renderReadingControls() {
  syncNavigation();window.dispatchEvent(new Event('paper-reading-state'));
  const paper=currentPaper();if(!paper)return;
  const busy=decisionPending || Boolean(snapshotApplying) || paperToolsBusy();
  for(const id of ['previous-paper','next-paper'])$(id).disabled=busy || reviewPapers().length===1;
  const reading=readerContext ? arrayActive() : inspection.time===inspection.duration && inspection.target;
  $('reject-paper').hidden=paper.excluded;
  $('reject-paper').disabled=busy || !reading;
  $('restore-paper').hidden=!paper.excluded;
  $('restore-paper').disabled=busy || !reading;
  $('restore-paper').textContent=paper.metadata_present?'Restore':'解除排除';
  $('clear-paper-metadata').hidden=!paper.excluded || !paper.metadata_present;
  $('clear-paper-metadata').disabled=busy || !reading || paper.cleanup_pending===true;
  $('back').disabled=busy || !inspection.target;
  const collection=paper.collection;
  $('paper-collection').hidden=!paper.metadata_present || !collection;
  const collectionLabels={not_started:'尚未采集',queued:'等待采集',running:'正在采集',completed:'采集完成',failed:'采集未完成',cancelled:'采集已取消'};
  $('paper-collection-status').textContent=['queued','running'].includes(collection?.status)?collectionLabels[collection.status]:
    collection?.cleaning_up?'正在清理 Paper 资源…':collectionLabels[collection?.status] || '';
  $('paper-collection-retry').hidden=paper.excluded || !['failed','cancelled'].includes(collection?.status);
  $('paper-collection-retry').disabled=busy || !collection?.retry_available;
  fillAbstractPlaceholder();
}
$('paper-collection-retry').addEventListener('click',async()=>{
  const paper=currentPaper();
  if(!paper || $('paper-collection-retry').disabled)return;
  const workspace=uiNext.libraryIdentity, epoch=uiNext.workspaceEpoch, id=paper.id, captured=structuredClone(paper.collection.retry);
  decisionPending=true;renderReadingControls();
  try {
    const result=await uiNext.request(`/api/papers/${id}/collection/retry`,{workspace_id:workspace,...captured});
    await applyPaperResponse(result);
  }catch(error){if(epoch===uiNext.workspaceEpoch && !error.stale)uiNext.notice(error.message);}
  finally {if(epoch===uiNext.workspaceEpoch){decisionPending=false;renderReadingControls();scheduleCollectionPoll();}}
});

function renderPaperTools(reload=false) {
  const paper=currentPaper(), reading=readerContext ? arrayActive() : inboxActive() && state.view==='journal' &&
    inspection.target && inspection.time===inspection.duration && !inspection.removeAfter;
  const visible=Boolean(state.ready && reading && paper?.metadata_present && !paper.excluded && document.documentElement.classList.contains('developer-mode'));
  $('paper-dev-tools').hidden=!visible;
  document.documentElement.classList.toggle('paper-tools-active',visible);
  const paperId=visible?paper.id:null;
  if(paperTools.paperId!==paperId){
    paperTools.paperId=paperId;paperTools.fields=null;paperTools.error='';paperTools.loading=false;paperTools.generation++;
    document.querySelectorAll('[data-paper-reset]').forEach(node=>{node.checked=false;});
  }
  if(!visible)return;
  if(!paperToolsBusy() && (reload || (!paperTools.fields && !paperTools.loading && !paperTools.error)))void loadPaperFields(paperId);
  const busy=decisionPending || Boolean(snapshotApplying) || paperToolsBusy();
  const ready=Boolean(paperTools.fields && !paperTools.loading && !busy);
  const checks=[...document.querySelectorAll('[data-paper-reset]')];
  checks.forEach(node=>{node.disabled=!ready;});
  $('paper-reset-fields').disabled=!ready || !checks.some(node=>node.checked);
  $('paper-abstract-input').disabled=!ready || Boolean(paperTools.fields.abstract?.trim());
  $('paper-tools-status').textContent=paperTools.pending?'正在保存…':paperTools.loading?'正在读取字段…':paperTools.error;
}
async function loadPaperFields(paperId) {
  const generation=++paperTools.generation;
  paperTools.loading=true;paperTools.fields=null;paperTools.error='';
  try {
    const fields=await uiNext.request(`/api/papers/${paperId}/fields?workspace_id=${encodeURIComponent(uiNext.libraryIdentity || '')}`);
    if(generation===paperTools.generation && paperTools.paperId===paperId)paperTools.fields=fields;
  }catch(error){if(generation===paperTools.generation)paperTools.error=error.message;}
  finally {if(generation===paperTools.generation){paperTools.loading=false;renderPaperTools();}}
}
function openPaperDialog(kind) {
  const paper=currentPaper();
  if(!paper || $('paper-dev-tools').hidden || paperToolsBusy())return;
  if(kind==='input' && $('paper-abstract-input').disabled)return;
  paperTools.kind=kind;paperTools.focus=document.activeElement;
  paperTools.inputRevision=paperTools.fields?.revision;
  $('paper-tools-title').textContent='Input Abstract';
  $('paper-tools-paper').textContent=paper.title;
  $('paper-input-label').hidden=false;$('paper-dialog-save').hidden=false;
  $('paper-dialog-cancel').textContent='Cancel';
  $('paper-dialog-error').textContent='';$('paper-input-text').value='';$('paper-dialog-save').disabled=true;
  $('paper-tools-dialog').showModal();renderReadingControls();$('paper-input-text').focus();
}

async function submitPaperEdit(kind) {
  const paper=currentPaper();
  if(!paper || paperTools.pending || !paperTools.fields)return;
  const input=kind==='input', fields=[...document.querySelectorAll('[data-paper-reset]:checked')].map(node=>node.dataset.paperReset);
  if(input ? $('paper-dialog-save').disabled : $('paper-reset-fields').disabled)return;
  const body=input?{revision:paperTools.inputRevision,abstract:$('paper-input-text').value}
    :{revision:paperTools.fields.revision,fields};
  const epoch=uiNext.workspaceEpoch;
  paperTools.pending=true;$('paper-dialog-save').disabled=true;$('paper-dialog-cancel').disabled=true;
  $('paper-dialog-error').textContent='';renderReadingControls();
  let saved=false;
  try {
    const result=await uiNext.request(`/api/papers/${paper.id}/${input?'abstract/input':'fields/reset'}`,body);
    if(epoch!==uiNext.workspaceEpoch)return;
    saved=true;
    if(input)$('paper-tools-dialog').close();
    else document.querySelectorAll('[data-paper-reset]').forEach(node=>{node.checked=false;});
    paperTools.fields=null;
    await applyPaperResponse(result);
    uiNext.notice(result.warning || (input?'摘要已保存。':'所选字段已清空。'));
    await refreshWorkspace();
    if(!readerContext && inboxActive())paintDirectory();
  }catch(error){
    if(epoch!==uiNext.workspaceEpoch)return;
    if(error.stale && error.workspaceEpoch===uiNext.workspaceEpoch && error.state?.saved===true &&
       error.state.workspace_id===uiNext.libraryIdentity && error.state.paper?.id===paper.id){
      // A newer applied snapshot may already contain this save. Acknowledge the
      // original write without applying its older projection over that snapshot.
      saved=true;paperTools.fields=null;
      if(input)$('paper-tools-dialog').close();
      uiNext.notice('字段已保存。');
    }else if(saved)uiNext.notice(`字段已保存，但界面刷新失败：${error.message}`);
    else if(input)$('paper-dialog-error').textContent=error.message;
    else {paperTools.error=error.message;uiNext.notice(error.message);}
  }finally{
    if(epoch!==uiNext.workspaceEpoch)return;
    paperTools.pending=false;$('paper-dialog-cancel').disabled=false;renderPaperTools(true);
    $('paper-dialog-save').disabled=!$('paper-input-text').value.trim();renderReadingControls();
    if(input && !$('paper-tools-dialog').open)$('paper-abstract-input').focus();
  }
}
$('paper-dev-tools').addEventListener('change',()=>renderPaperTools());
$('paper-reset-fields').addEventListener('click',()=>void submitPaperEdit('reset'));
$('paper-abstract-input').addEventListener('click',()=>openPaperDialog('input'));
$('paper-input-text').addEventListener('input',()=>{$('paper-dialog-save').disabled=paperTools.pending || !$('paper-input-text').value.trim();});
$('paper-dialog-save').addEventListener('click',()=>void submitPaperEdit('input'));
$('paper-dialog-cancel').addEventListener('click',()=>{if(!paperTools.pending)$('paper-tools-dialog').close();});
$('paper-tools-dialog').addEventListener('cancel',event=>{if(paperTools.pending)event.preventDefault();});
$('paper-tools-dialog').addEventListener('close',()=>{
  paperTools.kind=null;
  if(!paperTools.pending)renderPaperTools(true);
  renderReadingControls();
  if(!paperTools.pending && paperTools.focus?.isConnected)paperTools.focus.focus();
});
async function applyPaperResponse(result) {
  if(!result.paper || !uiNext.data || !uiNext.isCurrentEnvelope(result))return;
  const snapshot=structuredClone(uiNext.data),paper=result.paper;
  let journal;
  for(const group of snapshot.subjects)for(const source of group.journals){
    if(source.papers.some(item=>item.id===paper.id))journal=source;
    source.papers=source.papers.filter(item=>item.id!==paper.id);
  }
  for(const status of ['downloaded','trash']){
    journal ||= snapshot[status].papers.find(entry=>entry.paper.id===paper.id)?.journal;
    snapshot[status].papers=snapshot[status].papers.filter(entry=>entry.paper.id!==paper.id);
  }
  if(!paper.metadata_present || !journal)journal={key:'unmapped:Unassigned',name:'Unassigned',issn:null,eissn:null,source_type:'unmapped',group:null,papers:[]};
  if(paper.status==='candidate'){
    let target=snapshot.subjects.flatMap(group=>group.journals).find(source=>source.key===journal.key);
    if(!target){
      target={...journal,papers:[]};
      const unmapped=journal.source_type==='unmapped',name=unmapped?'Unmapped sources':journal.group ?? 'Ungrouped / virtual';
      let group=snapshot.subjects.find(group=>group.name===name && group.journals.some(source=>
        source.group===journal.group && (source.source_type==='unmapped')===unmapped));
      if(!group)snapshot.subjects.push(group={name,journals:[]});
      group.journals.push(target);
    }
    target.papers.push(paper);
  }else if(['downloaded','trash'].includes(paper.status))snapshot[paper.status].papers.push({paper,journal});
  snapshot.subjects=snapshot.subjects.map(group=>({...group,journals:group.journals.filter(source=>source.papers.length)})).filter(group=>group.journals.length);
  snapshot.revision=result.revision;
  uiNext.acceptEnvelope(snapshot,uiNext.workspaceEpoch,result.__allfoldResponseOrder);
  uiNext.data=snapshot;
  await applySnapshot(snapshot);
}
async function paperAction(action) {
  const paper=currentPaper();
  if(!paper || decisionPending || snapshotApplying || paperToolsBusy())return;
  const paperId=paper.id,workspaceId=uiNext.libraryIdentity;
  decisionPending=true;renderReadingControls();
  try {
    const result=await uiNext.request(`/api/ui-next/papers/${paperId}/${action}`,{workspace_id:workspaceId,expected_status:paper.status});
    await applyPaperResponse(result);
  } catch(error) {if(!error.stale)uiNext.notice(error.message);}
  finally {decisionPending=false;renderReadingControls();}
}
function removeFinishedJournal(key=selectedJournal()?.key) {
  const groupIndex=shelves.findIndex(group=>group.journals.some(journal=>journal.key===key));
  if(groupIndex<0)return;
  const group=shelves[groupIndex], row=rows[groupIndex], slot=group.journals.findIndex(journal=>journal.key===key), journal=group.journals[slot];
  const selectedKey=group.journals[row.sel]?.key;
  lists.get(journal.key)?.remove(); lists.delete(journal.key);
  for(const logical of logicalGroups)logical.journals=logical.journals.filter(j=>j.key!==journal.key);
  logicalGroups=logicalGroups.filter(g=>g.journals.length);
  for(const segment of group.segments)segment.journals=segment.journals.filter(j=>j.key!==journal.key);
  refreshShelfSegments(shelves);
  // Keep surviving cases at their current positions, then let their existing
  // gap springs close the removed slot. WHITE padding belongs at the tail.
  row.cases=new Map([...row.cases].filter(([i])=>i!==slot).map(([i,c])=>{
    if(i>slot){c.gap.x+=1;return [i-1,c];}return [i,c];
  }));
  if (group.journals.length) {
    const retained=group.journals.findIndex(journal=>journal.key===selectedKey);
    row.sel=retained>=0?retained:(slot<group.journals.length?slot:0);
  }
  else {
    shelves.splice(groupIndex,1); rows.splice(groupIndex,1);
    if(groupIndex<state.shelf)state.shelf--;
    else if(groupIndex===state.shelf)state.shelf=shelves.length ? state.shelf % shelves.length : 0;
    state.track=state.shelf; strip.x=strip.to=state.track; strip.v=0;
  }
  if (shelves.length) selectedRow().scroll.to=scrollTarget(selectedRow().sel,shelves[state.shelf]);
  // Removing a segment may change part/parts on a different shelf as well.
  archiveControlsKey='';
  AR.hover=-1;
  $('journal-ticks').dataset.group='';
}
function updateSnapshotCount() {
  const journals=shelves.flatMap(g => g.journals.filter(Boolean)), count=journals.reduce((n,j) => n+j.papers.length,0);
  $('snapshot-label').textContent=`${journals.length} JOURNALS / ${count} CANDIDATES / WORKSPACE`;
  $('downloaded-count').textContent=pad(downloadedPapers.size);$('trash-count').textContent=pad(trashPapers.size);
}
$('previous-paper').addEventListener('click',() => movePaper(-1));
$('next-paper').addEventListener('click',() => movePaper(1));
$('reject-paper').addEventListener('click',()=>void paperAction('reject'));
$('restore-paper').addEventListener('click',()=>void paperAction(currentPaper()?.metadata_present?'restore':'unexclude'));
$('clear-paper-metadata').addEventListener('click',()=>void paperAction('clear-metadata'));
$('paper-metadata-details').addEventListener('toggle',()=>{
  fillAbstractPlaceholder();
  if(decryption.active) decryption.refresh();
});

$('back').addEventListener('click', back);
$('previous-journal').addEventListener('click', () => moveJournal(-1));
$('next-journal').addEventListener('click', () => moveJournal(1));
$('previous-group').addEventListener('click', () => moveShelf(-1));
$('next-group').addEventListener('click', () => moveShelf(1));
document.addEventListener('keydown', event => {
  if (event.defaultPrevented || $('selected-view').closest('[inert]') || !inboxActive() || !state.ready || event.altKey || event.metaKey || event.ctrlKey) return;
  if(document.querySelector('dialog[open]'))return;
  if (event.key === 'Escape' && state.view === 'journal') { back(); event.preventDefault(); }
  else if (state.view === 'journal' && ['ArrowUp','ArrowDown'].includes(event.key)) {
    if (event.shiftKey || !inspection.target || inspection.time !== inspection.duration || inspection.removeAfter ||
        decisionPending || snapshotApplying || document.querySelector('dialog[open]') ||
        event.target.isContentEditable || event.target.closest('input,textarea,select,[contenteditable],.archive-widget-handle,#debug-split,#debug-bottom')) return;
    movePaper(event.key === 'ArrowUp' ? -1 : 1); event.preventDefault();
  }
  else if (event.target === canvas && state.view === 'selected') {
    const action = { ArrowUp: () => moveJournal(1), ArrowDown: () => moveJournal(-1),
      ArrowLeft: () => moveShelf(1), ArrowRight: () => moveShelf(-1), Enter: () => openView() }[event.key];
    if (action) { action(); event.preventDefault(); }
  }
});
canvas.addEventListener('wheel', event => {
  if (!state.ready || !shelves.length) return;
  event.preventDefault();
  if (state.view === 'journal') {
    if (inspection.target && inspection.time === inspection.duration && !inspection.removeAfter && directoryPoint(event)) {
      const layout = directoryLayout();
      if (layout) directoryScroll.to = clamp(directoryScroll.to + event.deltaY * 768 / Math.max(1,Math.hypot(selectedCoverQuad[1][0]-selectedCoverQuad[0][0],selectedCoverQuad[1][1]-selectedCoverQuad[0][1])), 0, layout.maxScroll);
      wake();
    }
    return;
  }
  if (performance.now() - lastWheel < 160) return;
  lastWheel = performance.now();
  if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) moveShelf(Math.sign(event.deltaX));
  else moveJournal(Math.sign(event.deltaY));
}, { passive: false });
// Same point-in-polygon hit testing as the existing Canvas adaptation.
function contains(q, x, y) {
  let inside = false;
  for (let i = 0, j = q.length - 1; i < q.length; j = i++) {
    const [xi, yi] = q[i], [xj, yj] = q[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function hit(event) {
  const r = canvas.getBoundingClientRect();
  return [...hitAreas].reverse().find(h => contains(h.quad, event.clientX - r.left, event.clientY - r.top));
}
canvas.addEventListener('pointermove', event => {
  if (state.view === 'journal') {
    canvas.style.cursor = directoryHit(event) ? 'pointer' : 'default'; return;
  }
  const h = hit(event), next = h && !h.empty && h.track === state.track ? h.index : -1;
  canvas.style.cursor = h && !h.empty ? 'pointer' : 'default';
  if (next !== AR.hover) { AR.hover = next; wake(); }
});
canvas.addEventListener('pointerleave', () => { AR.hover = -1; wake(); });
canvas.addEventListener('click', event => {
  if (!state.ready || !shelves.length) return;
  if (state.view === 'journal') {
    const paper = directoryHit(event); if (paper && inspection.time === inspection.duration && inspection.target) selectPaper(paper.id);
    return;
  }
  const h = hit(event);
  if (!h || h.empty) return;
  if (h.track === state.track && h.index === selectedRow().sel) openView();
  else selectJournal(h.group, h.index, h.track);
});
mediaQuery.addEventListener('change', event => {
  REDUCE_MOTION = event.matches;
  if (REDUCE_MOTION && state.view === 'journal') { stepInspection(0); syncInspectionPanel(); }
  wake();
});

async function image(url) { const img = new Image(); img.src = url; await img.decode(); return img; }
async function json(url) { const r = await fetch(url); if (!r.ok) throw new Error(`${url}: ${r.status}`); return r.json(); }
function coverPair(journal, source) {
  // Saved original-pixel crop, or the centered square for an uncropped cover.
  const square = document.createElement('canvas'); square.width = square.height = 512;
  const g = square.getContext('2d'); g.fillStyle = '#deddd5'; g.fillRect(0, 0, 512, 512);
  if (source) {
    const side = Math.min(source.naturalWidth, source.naturalHeight);
    const crop=journal.cover_detail?.crop || {x:(source.naturalWidth-side)/2,y:(source.naturalHeight-side)/2,size:side};
    g.drawImage(source,crop.x,crop.y,crop.size,crop.size,0,0,512,512);
  } else {
    g.strokeStyle = '#a9ab9f'; g.strokeRect(26, 26, 460, 460);
    g.fillStyle = INK; g.font = '500 26px "Geist Mono"';
    const words = journal.name.split(' '); let line = '', y = 180;
    for (const word of words) {
      if (g.measureText(`${line} ${word}`).width > 400) { g.fillText(line, 50, y); line = word; y += 40; }
      else line = line ? `${line} ${word}` : word;
    }
    g.fillText(line, 50, y); g.font = '18px "Geist Mono"';
    g.fillText(journal.key || 'UNMAPPED', 50, 420); g.fillStyle = MUTED; g.fillText('COVER UNAVAILABLE', 50, 455);
  }
  // RhinE draws blurred thumbnails under frost, and blends the sharp image in.
  const blur = document.createElement('canvas'); blur.width = blur.height = 128;
  const b = blur.getContext('2d'); b.filter = 'blur(14px)'; b.drawImage(square, -4, -4, 136, 136);
  return { image: square, blur };
}
function cacheCover(journal) {
  const token={journal};coverLoads.set(journal.key,token);
  token.promise=(async()=>{
    const detail=journal.cover_detail,previous=covers.get(journal.key);
    const available=['Uploaded','Downloaded'].includes(detail?.state);
    const url=available && journal.cover?journal.cover+(detail?.sha256?'?revision='+detail.sha256:''):null;
    const source=url?(previous?.sha256===detail?.sha256 && previous?.source || await image(url).catch(()=>null)):null;
    if(coverLoads.get(journal.key)!==token)return coverLoads.get(journal.key).promise;
    covers.set(journal.key,{...coverPair(journal,source),source,sha256:detail?.sha256});
    if(state.ready)wake();
  })();
  return token.promise;
}
window.addEventListener('journal-cover-changed',event=>{
  const {journalKey,cover}=event.detail;
  coverChanges.set(journalKey,{sequence:++coverSequence,cover});
  const pending=coverLoads.get(journalKey)?.journal;
  const journals=logicalGroups.flatMap(group=>group.journals).filter(journal=>journal.key===journalKey);
  if(pending && !journals.includes(pending))journals.push(pending);
  for(const journal of journals)journal.cover_detail=cover;
  const journal=pending || journals[0];
  if(journal)void cacheCover(journal);
});
function paperObjects() {
  return new Map([...shelves.flatMap(g=>g.journals.flatMap(j=>j.papers)),...downloadedPapers.values(),...trashPapers.values()].map(item=>{const p=item.paper || item;return [p.id,p];}));
}
function rebuildShelves(selection={issn:selectedJournal()?.key}) {
  const selectedKeys=new Set(shelves.map((shelf,i)=>shelf.journals[rows[i]?.sel]?.key));
  const cases=new Map(),scrolls=new Map();
  shelves.forEach((shelf,i)=>{
    for(const [slot,value] of rows[i].cases){const journal=shelf.journals[slot];if(journal)cases.set(journal.key,value);}
    const key=shelf.journals[rows[i].sel]?.key;
    if(key)scrolls.set(key,rows[i].scroll);
  });
  shelves=allocateShelves(logicalGroups,shelfCapacity);
  rows=shelves.map(shelf=>{
    const sel=Math.max(0,shelf.journals.findIndex(j=>selectedKeys.has(j.key)));
    const previous=scrolls.get(shelf.journals[sel].key);
    return {sel,scroll:previous?{...previous}:Spring(0,9),
      cases:new Map(shelf.journals.flatMap((j,i)=>cases.has(j.key)?[[i,cases.get(j.key)]]:[]))};
  });
  const index=shelves.findIndex(shelf=>shelf.journals.some(j=>j.key===selection?.issn));
  state.shelf=index>=0?index:Math.min(state.shelf,Math.max(0,shelves.length-1));
  if(index>=0)rows[index].sel=shelves[index].journals.findIndex(j=>j.key===selection.issn);
  state.track=state.shelf;strip.x=strip.to=state.track;strip.v=0;
  cancelRulerDrag();hideTickLabel();AR.hover=AR.hoverTick=AR.focusTick=-1;AR.ticks.clear();
  $('journal-ticks').dataset.group='';archiveControlsKey='';
}
function snapshotStructure(data) {
  const journal=value=>{const {papers,logicalGroupId,logicalGroupName,...metadata}=value || {};return metadata;};
  const entries=value=>value.papers.map(entry=>({id:(entry.paper || entry).id,status:(entry.paper || entry).status,
    metadata_present:(entry.paper || entry).metadata_present,...(entry.journal?{journal:journal(entry.journal)}:{})}));
  return JSON.stringify({workspace_id:data.workspace_id,subjects:data.subjects.map(group=>({...group,
    journals:group.journals.map(value=>({...journal(value),papers:entries(value)}))})),
    downloaded:{...data.downloaded,journals:data.downloaded.journals.map(journal),papers:entries(data.downloaded),titles:undefined},trash:entries(data.trash)});
}
let appliedStructure=null, collectionTimer=null;
function scheduleCollectionPoll(){
  clearTimeout(collectionTimer);
  const working=[...paperObjects().values()].some(paper=>['queued','running'].includes(paper.collection_status) || paper.cleanup_pending);
  if(working)collectionTimer=setTimeout(async()=>{
    try{await refreshWorkspace(undefined,{background:true});}catch(error){if(!error.stale)collectionTimer=setTimeout(scheduleCollectionPoll,1500);}
  },900);
}
async function applySnapshot(data,selection=window.inboxRun?.selection(),coverVersion=coverSequence,epoch=uiNext.workspaceEpoch) {
  const objects=paperObjects(), selected=state.pendingPaper, wasArray=Boolean(readerContext) || $('selected-view').dataset.workspaceLayout==='array';
  const structure=snapshotStructure(data), previousPaper=currentPaper()?structuredClone(currentPaper()):null;
  if(appliedStructure===structure && epoch===uiNext.workspaceEpoch && uiNext.isCurrentEnvelope(data)){
    const previous=previousPaper;
    const incoming=[...data.subjects.flatMap(group=>group.journals.flatMap(journal=>journal.papers)),
      ...data.downloaded.papers.map(entry=>entry.paper),...data.trash.papers.map(entry=>entry.paper)];
    for(const paper of incoming){const saved=objects.get(paper.id);if(saved)Object.assign(saved,paper);}
    for(const list of lists.values())for(const row of list.children){
      const paper=objects.get(row.dataset.paperId);if(paper)patchPaperRow(row,paper);
    }
    librarySnapshot={...data.downloaded,trash:data.trash};
    // Stable membership keeps lists, selection, expansion, paragraph DOM and editor drafts mounted.
    if(currentPaper() && JSON.stringify(previous)!==JSON.stringify(currentPaper()) && (state.view==='journal' || readerContext))renderPaper(previous);
    updateSnapshotCount();wake();scheduleCollectionPoll();return;
  }
  const scrolls=new Map([...lists].map(([key,list])=>[key,list.scrollTop]));
  const merge=paper=>{const existing=objects.get(paper.id);if(existing){Object.assign(existing,paper);return existing;}return paper;};
  for(const group of data.subjects)for(const journal of group.journals){
    const change=coverChanges.get(journal.key);
    if(change?.sequence>coverVersion)journal.cover_detail=change.cover;
    await cacheCover(journal);
  }
  if(epoch!==uiNext.workspaceEpoch || !uiNext.isCurrentEnvelope(data))return;
  appliedStructure=structure;
  for(const group of data.subjects)for(const journal of group.journals)journal.papers=journal.papers.map(merge);
  logicalGroups=data.subjects.map((group,id)=>{
    for(const journal of group.journals){journal.logicalGroupId=id;journal.logicalGroupName=group.name;}
    return {...group,id};
  });
  shelfCapacity=archiveDebug.values.shelfCapacity;
  rebuildShelves(selection);librarySnapshot={...data.downloaded,trash:data.trash};
  if(wasArray)state.view=shelves.length?'selected':'empty';
  downloadedPapers.clear();for(const entry of data.downloaded.papers){entry.paper=merge(entry.paper);downloadedPapers.set(entry.paper.id,entry);}
  trashPapers.clear();for(const entry of data.trash.papers){entry.paper=merge(entry.paper);trashPapers.set(entry.paper.id,entry);}
  for(const [key,list] of lists)if(!shelves.some(g=>g.journals.some(j=>j.key===key))){list.remove();lists.delete(key);}
  createLists();for(const [key,scroll]of scrolls)if(lists.has(key))lists.get(key).scrollTop=scroll;
  document.querySelector('.collection').hidden=!shelves.length;
  $('empty-inbox').hidden=shelves.length>0;
  if(readerContext){
    const current=readerContext.status==='candidates'?candidateEntries():readerContext.status==='trash'?[...trashPapers.values()]:[...downloadedPapers.values()];
    const entries=window.workspaceArray.readerEntries(current,data.downloaded.journals);
    if(entries.some(entry=>entry.paper.id===selected))readerContext.entries=entries;
    else {
      closeArrayReader(true);
      window.dispatchEvent(new Event('array-reader-empty'));
    }
  }
  if(!wasArray && state.view==='journal' && !shelves.some(g=>g.journals.some(j=>j.papers.some(p=>p.id===selected)))) {
    inspection.time=inspection.target=0;inspection.completionPending=false;state.pendingPaper=null;clearInspectionPanel();$('journal-view').hidden=true;$('journal-view').inert=true;$('selected-view').classList.remove('inspecting');state.view=shelves.length?'selected':'empty';
  }
  if(!wasArray && state.view!=='journal')state.view=shelves.length?'selected':'empty';
  completionSurface.dispose();
  $('selected-view').classList.remove('returning-complete');
  filePanel.hidden=!shelves.length;
  filePanel.inert=state.view==='journal';
  if(state.view==='journal' && !wasArray)syncInspectionPanel();else clearInspectionPanel();
  $('journal-ticks').dataset.group='';
  if(shelves.length)updateJournal();
  if(currentPaper() && (state.view==='journal' || readerContext)){renderPaper(previousPaper?.id===currentPaper().id?previousPaper:null);if(!readerContext)resetDirectory();}
  updateSnapshotCount();resize();syncNavigation();wake();
  if(inboxActive() && state.view!=='journal')$('mode-label').textContent='ARCHIVE / '+(shelves.length?'BROWSE':'COMPLETE');
  window.dispatchEvent(new Event('workspace-data-changed'));
  scheduleCollectionPoll();
  if(data.issues.length)uiNext.notice(data.issues.join(' · '));
}
function refreshSavedSettings() {
  if(settingsRefreshPending && window.inboxRun.available())void refreshWorkspace().catch(error=>uiNext.notice(error.message));
}
async function refreshWorkspace(selection,{background=false}={}) {
  settingsRefreshPending=false;
  const epoch=uiNext.workspaceEpoch;
  const work=(async()=>{
    try {
      const version=coverSequence,data=await uiNext.workspace();
      if(epoch!==uiNext.workspaceEpoch)return;
      await applySnapshot(data,selection,version,epoch);return data;
    } catch(error) {if(epoch===uiNext.workspaceEpoch && !error.stale)throw error;}
  })();
  if(background)return work;
  snapshotApplying=work;
  renderReadingControls();
  try{return await work;}finally{if(snapshotApplying===work){snapshotApplying=false;renderReadingControls();refreshSavedSettings();}}
}
window.addEventListener('workspace-reset',()=>{
  clearTimeout(collectionTimer);appliedStructure=null;
  uiNext.resetWorkspace();snapshotApplying=false;decisionPending=false;
  paperTools.pending=false;if($('paper-tools-dialog').open)$('paper-tools-dialog').close();
  closeArrayReader(true);clearInspectionPanel();
  paragraphLayout?.clear();decryption.reset(null,true);paperMetadata.open=false;
  for(const id of ['view-paper-title','view-paper-id','paper-position','paper-authors','paper-date','paper-source','paper-identifiers','paper-indexed-terms','paper-providers','paper-doi','paper-abstract'])$(id).replaceChildren();
  window.allfoldPaperDates.render(null,$('paper-dates'),$('paper-date-evidence'));
  $('paper-doi').removeAttribute('href');delete $('paper-detail').dataset.paperId;
  $('paper-metadata-summary').textContent='Infos';
  Object.assign(paperTools,{paperId:null,fields:null,loading:false,error:'',
    generation:paperTools.generation+1,diagnosticGeneration:paperTools.diagnosticGeneration+1});
  downloadedPapers.clear();trashPapers.clear();
  librarySnapshot={...librarySnapshot,papers:[],titles:{}};
  logicalGroups=[];shelves=[];rows=[];
  inspection.time=inspection.target=0;inspection.completionPending=false;state.pendingPaper=null;state.view='empty';
  for(const list of lists.values())list.remove();lists.clear();
  $('downloaded-count').textContent=$('trash-count').textContent=pad(0);$('journal-view').hidden=true;$('journal-view').inert=true;
  $('selected-view').classList.remove('inspecting');
  renderReadingControls();
});
async function load() {
  const coverVersion=coverSequence;
  try {
    const [data,meta,rail,layout]=await Promise.all([uiNext.workspace(),json('assets/journal/case.json'),json('assets/rail/rail.json'),uiNext.layout()]);
    journalMeta=meta;railMeta=rail;archiveLayout=layout;
    await document.fonts.load('600 25px "Geist Mono SemiBold"');
    await document.fonts.load('500 24px "Source Sans 3"');
    await document.fonts.ready;
    [arrayClear,arrayFrost]=await Promise.all(['clear','frost'].map(n=>image(`assets/journal/array-${n}.png`)));
    const rails=await Promise.all(['front','mid','back'].map(n=>image(`assets/rail/rail-${n}.png`)));
    railImages=Object.fromEntries(['front','mid','back'].map((n,i)=>[n,rails[i]]));
    inspectionFrames=await Promise.all(Array.from({length:60},(_,i)=>image(`assets/journal/inspect-${pad(i)}.png`)));
    await applySnapshot(data,undefined,coverVersion);state.ready=true;
    if(window.allfoldUIPreferences.archiveDisabled())window.inboxKept.setLayout('array');
    $('load-status').hidden=true;resize();wake();
    window.dispatchEvent(new Event('inbox-ready'));
  }catch(error){$('load-status').textContent=`读取失败：${error.message}`;uiNext.notice(error.message);}
}
let inboxScrollPosition=0;
function leaveInboxReview() {
  if(state.view!=='journal') return;
  decryption.reset(null,true);
  inspection.target=inspection.time=0;finishReturn();
}
function candidateEntries() {
  return logicalGroups.flatMap(group=>group.journals.flatMap(journal=>journal.papers.map(paper=>({paper,journal}))));
}
function closeArrayReader(snapshot=false) {
  if(!snapshot && (decisionPending || snapshotApplying || paperToolsBusy()))return false;
  if(readerContext){
    paragraphLayout?.clear();decryption.reset(null,true);
    readerContext=null;state.pendingPaper=null;
    window.allfoldPreprintLookup.select(null);
    window.allfoldPaperDates.render(null,$('paper-dates'),$('paper-date-evidence'));
    $('paper-detail').prepend(paperMetadata);
    $('paper-detail').prepend(paperTitle);
    paperMetadata.open=false;
    paperNavigation.hidden=false;
    reviewPanel.prepend(paperNavigation);
    $('journal-view').append(reviewPanel);
    decisionHost.append(...decisionButtons);
    $('array-decision-tools').hidden=true;
  }
  return true;
}
window.allfoldRefreshWorkspace=refreshWorkspace;
window.inboxKept={
  available:()=>state.ready && !decisionPending && !snapshotApplying && !paperToolsBusy() && !$('run-view').open &&
    (['selected','empty'].includes(state.view) || (state.view==='journal' && inspection.time===inspection.duration && inspection.target)),
  busy:()=>decisionPending || Boolean(snapshotApplying) || paperToolsBusy(),
  data:()=>librarySnapshot,
  entries:status=>[...(status==='trash'?trashPapers:downloadedPapers).values()],
  candidates:candidateEntries,
  setLayout(layout) {
    if(!['archive','array'].includes(layout) || (layout==='archive' && window.allfoldUIPreferences.archiveDisabled()) || !this.available())return false;
    leaveInboxReview();
    if(!closeArrayReader())return false;
    $('selected-view').dataset.workspaceLayout=layout;
    $('kept-view').hidden=$('kept-view').inert=layout!=='array';
    for(const node of document.querySelectorAll('#selected-view > .collection, #selected-view > .file-panel, #selected-view > #empty-inbox'))node.inert=layout==='array';
    if(layout==='array'){
      $('selected-view').style.removeProperty('height');
      clearInspectionPanel();
    }else {
      document.querySelector('.collection').hidden=!shelves.length;
      $('empty-inbox').hidden=Boolean(shelves.length);
      filePanel.hidden=!shelves.length;filePanel.inert=false;
      if(shelves.length)updateJournal();
      $('mode-label').textContent='ARCHIVE / '+(shelves.length?'BROWSE':'COMPLETE');
      resize();wake();
    }
    syncNavigation();return true;
  },
  suspend() {renderReadingControls();},
  openReader(entries,id,status,filter) {
    if(this.busy() || !arrayActive() || !entries.some(entry=>entry.paper.id===id)) return false;
    decryption.reset(null,true);
    clearInspectionPanel();
    if(!readerContext)paperMetadata.open=false;
    readerContext={entries,status,filter};state.pendingPaper=id;
    $('kept-reader-body').append(reviewPanel);
    $('array-paper-heading').append(paperTitle);
    $(status==='candidates'?'array-candidate-infos':'array-kept-infos').append(paperMetadata);
    $('paper-abstract-heading').append(paperNavigation);
    paperNavigation.hidden=false;
    $('array-decision-tools').hidden=false;
    $('array-decision-tools').append(...decisionButtons);
    renderPaper();wake();return true;
  },
  closeReader:closeArrayReader,
  openArchivePaper(id) {
    if(window.allfoldUIPreferences.archiveDisabled())return window.workspaceArray?.openPaper(id) || false;
    if(!inboxActive())return false;
    const group=shelves.findIndex(group=>group.journals.some(journal=>journal.papers.some(paper=>paper.id===id)));
    if(group<0)return false;
    const journal=shelves[group].journals.findIndex(journal=>journal.papers.some(paper=>paper.id===id));
    selectJournal(group,journal);openView(id);return true;
  },

};
new ResizeObserver(()=>{if(readerContext && arrayActive()) fillAbstractPlaceholder();}).observe($('kept-reader'));
window.inboxRun={
  available:()=>state.ready && !decisionPending && !snapshotApplying && !paperToolsBusy() && !window.workspaceArray?.workflowBusy() && !window.uiRun?.active() &&
    (inspection.time===0 || inspection.time===inspection.duration),
  selection:()=>({issn:selectedJournal()?.key,scroll:lists.get(selectedJournal()?.key)?.scrollTop || 0}),
  prepare:async(_papers,selection)=>{await refreshWorkspace(selection);},
};
workspaceSearch.register('papers',{
  label:'Paper',
  items:()=>[...candidateEntries(),...downloadedPapers.values(),...trashPapers.values()].map(({paper,journal})=>({
    id:paper.id,name:paper.title || paper.identity_label,detail:journal.name,keywords:paper.doi,
  })),
  select:item=>window.workspaceArray?.openPaper(item.id,{readKept:true}),
});
window.addEventListener('workspace-data-changed',workspaceSearch.refresh);
window.uiWorkspace={
  refresh:async selection=>{
    if(state.ready)return refreshWorkspace(selection);
    await load();if(!state.ready)throw new Error($('load-status').textContent);
  },
  ready:()=>state.ready,
};
window.addEventListener('focus',()=>{if(!window.allfoldWorkbench?.presentationChanging?.() && !configurationActive() && state.ready && !decisionPending && !paperToolsBusy())void refreshWorkspace().catch(error=>uiNext.notice(error.message));});
for(const name of ['settings-saved','login-state-changed'])
  window.addEventListener(name,()=>{settingsRefreshPending=true;refreshSavedSettings();});
window.addEventListener('pagehide',event=>{clearTimeout(collectionTimer);if(!event.persisted)paragraphLayout?.destroy();});
window.workspaceNavigation.register('workspace',{
  canNavigate:()=>!navigationBusy() && !window.workspaceArray?.navigationBusy?.(),
  canEnter:()=>state.ready,
  leave:()=>{
    window.workspaceArray?.leave();
    renderReadingControls();
    inboxScrollPosition=lists.get(selectedJournal()?.key)?.scrollTop || 0;
  },
  enter:()=>{
    refreshSavedSettings();
    if(arrayActive()){window.workspaceArray?.enter();return;}
    $('mode-label').textContent='ARCHIVE / '+(state.view==='journal'?'JOURNAL':shelves.length?'BROWSE':'COMPLETE');
    resize();const list=lists.get(selectedJournal()?.key);
    if(list)list.scrollTop=inboxScrollPosition;
    wake();
  },
});
load();
