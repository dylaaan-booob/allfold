'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const root = path.resolve(__dirname, '../..');
const roots = ['electron/src', 'electron/scripts', 'frontend/ui', 'tools'];
const excludedDirectories = new Set(['node_modules', 'vendor', 'third-party', 'dist', 'build', '.cache']);
// Retained third-party engine; its source and notice are recorded in UI SOURCES.
const excludedFiles = new Set([path.join(root, 'frontend/ui/justice.js')]);
const extensions = new Set(['.js', '.cjs', '.mjs']);
const files = [];

function collect(directory) {
  for (const entry of fs.readdirSync(directory, {withFileTypes: true})) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory() && !excludedDirectories.has(entry.name)) collect(file);
    else if (entry.isFile() && extensions.has(path.extname(file)) && !excludedFiles.has(file)) files.push(file);
  }
}

for (const directory of roots) collect(path.join(root, directory));
for (const file of files.sort()) {
  const result = spawnSync(process.execPath, ['--check', file], {stdio: 'inherit'});
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
console.log(`JavaScript syntax checked: ${files.length} project files`);
