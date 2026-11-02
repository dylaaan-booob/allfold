import {build} from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const projectRoot=fileURLToPath(new URL('../',import.meta.url));
export async function buildUI(root=projectRoot) {
  const source=path.join(root,'frontend/ui');
  const output=path.join(root,'src/allfold/web/static/ui_next');
  // Only this generated delivery directory is replaced; dangling symlinks are rejected too.
  let stat;
  try {stat=fs.lstatSync(output);} catch(error) {if(error.code!=='ENOENT')throw error;}
  if(stat?.isSymbolicLink())throw Error('UI output must not be a symlink');
  fs.rmSync(output,{recursive:true,force:true});
  fs.cpSync(source,output,{recursive:true,filter:file=>!file.endsWith('.ts') && file!==path.join(source,'kept.js')});
  await build({entryPoints:[path.join(source,'kept.js')],outfile:path.join(output,'kept-app.js'),
    bundle:true,format:'esm',target:'es2022',legalComments:'eof',external:['*.woff2'],
    banner:{js:'// RhinE MIT + Blog Theme MIT adaptation. See SOURCES.md and licenses/.'}});
}
if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url))await buildUI();
