const fs = require('fs');
const path = require('path');
const src = 'C:\\Users\\Rafael\\Documents\\MultiTool\\HomeChats\\Chat-8\\repo-clone\\astro-site\\public\\images\\albums';
const dst = 'C:\\Users\\Rafael\\Documents\\MultiTool\\HomeChats\\Chat-8\\repo-clone\\worklog\\albums';

fs.readdirSync(src).forEach(dir => {
  const srcDir = path.join(src, dir);
  if (!fs.statSync(srcDir).isDirectory()) return;
  const dstDir = path.join(dst, dir);
  fs.mkdirSync(dstDir, { recursive: true });
  const files = fs.readdirSync(srcDir);
  files.forEach(f => {
    const s = path.join(srcDir, f);
    const d = path.join(dstDir, f);
    if (fs.statSync(s).isFile()) fs.copyFileSync(s, d);
  });
  console.log(dir + ': ' + files.length + ' files');
});
console.log('DONE');