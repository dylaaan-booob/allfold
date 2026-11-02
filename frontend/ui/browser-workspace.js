'use strict';
document.getElementById('browser-open').addEventListener('click',async()=>{
  try {
    if(!window.allfoldDesktop)throw Error('请在 Electron 桌面应用中使用 Browser');
    await window.allfoldDesktop.showBrowser();
  } catch(error) {window.uiNext.notice(error.message);}
});
