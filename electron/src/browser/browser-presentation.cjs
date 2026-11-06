'use strict';
// Owns native presentation only. Pages and their Session remain BrowserRuntime resources.
class BrowserPresentation {
  constructor(hostWindow) {
    this.host=hostWindow;this.visible=false;this.suspended=false;this.bounds=null;
    this.sequence=-1;this.selected=null;this.mounted=null;this.focusPending=false;
    this.resize=()=>{this.detach();this.bounds=null;this.requestLayout();};
    this.closed=()=>{this.detach();this.host=null;};
    this.navigation=event=>{if(event.isMainFrame && !event.isSameDocument)this.reset();};
    this.documentReset=()=>this.reset();
    hostWindow?.on('resize',this.resize);
    hostWindow?.on('closed',this.closed);
    hostWindow?.webContents.on('did-start-navigation',this.navigation);
    // The outgoing document can still publish layout while its replacement loads.
    hostWindow?.webContents.on('did-navigate',this.documentReset);
    hostWindow?.webContents.on('render-process-gone',this.documentReset);
  }
  send(channel,value) {
    if(this.host && !this.host.isDestroyed())this.host.webContents.send(channel,value);
  }
  requestLayout(){this.send('browser:layout');}
  initializeView(view) {
    if(!this.host || this.host.isDestroyed())return;
    const [width,height]=this.host.getContentSize();
    // Background pages need a real layout viewport before a task reveals them.
    view.setBounds({x:0,y:0,width,height});
  }
  show(){this.send('browser:presentation',{visible:true});}
  reset(){this.detach();this.visible=false;this.bounds=null;this.sequence=-1;this.focusPending=false;}
  select(tab,{focus=false}={}) {
    if(this.selected!==tab)this.detach();
    this.selected=tab || null;this.focusPending=focus;this.apply();
  }
  update(value) {
    if(!value || typeof value!=='object' || Array.isArray(value)
      || Object.keys(value).some(key=>!['sequence','visible','suspended','bounds'].includes(key))
      || !Number.isSafeInteger(value.sequence) || value.sequence<0
      || typeof value.visible!=='boolean' || typeof value.suspended!=='boolean')throw Error('Invalid Browser presentation');
    const bounds=value.bounds;
    if(bounds!==null && (!bounds || typeof bounds!=='object' || Array.isArray(bounds)
      || Object.keys(bounds).sort().join(',')!=='height,width,x,y'
      || !['x','y','width','height'].every(key=>typeof bounds[key]==='number' && Number.isFinite(bounds[key]) && bounds[key]>=0 && bounds[key]<=32768)))
      throw Error('Invalid Browser bounds');
    if(value.sequence<=this.sequence)return false;
    this.sequence=value.sequence;this.visible=value.visible;this.suspended=value.suspended;
    this.bounds=bounds?{...bounds}:null;this.apply();return true;
  }
  detach() {
    if(!this.mounted)return;
    this.mounted.view.setVisible(false);
    if(this.host && !this.host.isDestroyed())this.host.contentView.removeChildView(this.mounted.view);
    this.mounted=null;
  }
  apply() {
    if(!this.host || this.host.isDestroyed() || !this.visible || this.suspended || !this.bounds
      || !this.selected || this.selected.view.webContents.isDestroyed()){this.detach();return;}
    const [width,height]=this.host.getContentSize(),rect=this.bounds,zoom=this.host.webContents.getZoomFactor();
    // Renderer bounds are CSS pixels; host page zoom converts them to DIP without DPR scaling.
    const x=Math.ceil(rect.x*zoom),y=Math.ceil(rect.y*zoom);
    const right=Math.min(width,Math.floor((rect.x+rect.width)*zoom)),bottom=Math.min(height,Math.floor((rect.y+rect.height)*zoom));
    if(x>=right || y>=bottom){this.detach();return;}
    const tab=this.selected;
    tab.view.setBounds({x,y,width:right-x,height:bottom-y});
    if(this.mounted!==tab){this.detach();this.host.contentView.addChildView(tab.view);this.mounted=tab;}
    tab.view.setVisible(true);
    if(this.focusPending){this.focusPending=false;tab.view.webContents.focus();}
  }
  dispose(){
    this.detach();this.host?.removeListener('resize',this.resize);this.host?.removeListener('closed',this.closed);
    this.host?.webContents.removeListener('did-start-navigation',this.navigation);
    this.host?.webContents.removeListener('did-navigate',this.documentReset);
    this.host?.webContents.removeListener('render-process-gone',this.documentReset);
    this.host=null;this.selected=null;
  }
}
module.exports={BrowserPresentation};
