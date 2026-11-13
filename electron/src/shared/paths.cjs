'use strict';
const path=require('node:path');
const ELECTRON_ROOT=path.resolve(__dirname,'../..');
const PROJECT_ROOT=path.dirname(ELECTRON_ROOT);
module.exports={ELECTRON_ROOT,PROJECT_ROOT,
  THIRD_PARTY_DIR:path.join(ELECTRON_ROOT,'third-party'),
  PRELOAD_DIR:path.join(ELECTRON_ROOT,'src/preload'),
  NATIVE_UI_DIR:path.join(ELECTRON_ROOT,'src/native-ui')};
