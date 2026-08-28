const https = require('https');
const fs = require('fs');
const path = require('path');

const albumsJson = path.join(__dirname, 'src', 'data', 'albums.json');
const outDir = path.join(__dirname, 'public', 'images', 'albums');

const d = JSON.parse(fs.readFileSync(albumsJson, 'utf-8'));

// Slugify album name
function slugify(t) {
  const map = { 'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z',
    'и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r',
    'с':'s','т':'t','у':'u','ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh',
    'щ':'shch','ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya',
    'А':'a','Б':'b','В':'v','Г':'g','Д':'d','Е':'e','Ё':'e','Ж':'zh','З':'z',
    'И':'i','Й':'y','К':'k','Л':'l','М':'m','Н':'n','О':'o','П':'p','Р':'r',
    'С':'s','Т':'t','У':'u','Ф':'f','Х':'kh','Ц':'ts','Ч':'ch','Ш':'sh',
    'Щ':'shch','Ъ':'','Ы':'y','Ь':'','Э':'e','Ю':'yu','Я':'ya' };
  return t.replace(/[^a-zA-Z0-9\u0400-\u04FF\s-]/g, '').trim()
    .split('').map(c => map[c] || c).join('')
    .replace(/\s+/g, '-').replace(/-+/g, '-').toLowerCase();
}

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, res => {
      res.pipe(file);
      file.on('finish', () => { file.close(); resolve(); });
    }).on('error', err => { fs.unlink(dest, () => {}); reject(err); });
  });
}

(async () => {
  let total = 0;
  let success = 0;
  let fail = 0;

  for (const album of d.albums) {
    const albumDir = path.join(outDir, slugify(album.title) || 'album-' + album.id);
    fs.mkdirSync(albumDir, { recursive: true });
    
    // Save album metadata JSON
    const metaFile = path.join(albumDir, '_album.json');
    fs.writeFileSync(metaFile, JSON.stringify({
      id: album.id,
      title: album.title,
      description: album.description,
      thumb_id: album.thumb_id
    }, null, 2));

    for (const photo of album.photos) {
      total++;
      const ext = path.extname(new URL(photo.url).pathname) || '.jpg';
      const fileName = photo.id + ext;
      const filePath = path.join(albumDir, fileName);
      
      if (fs.existsSync(filePath)) {
        success++;
        continue;
      }

      process.stdout.write('[' + total + '/462] ' + album.title + '/' + fileName + '... ');
      try {
        await download(photo.url, filePath);
        success++;
        console.log('OK');
      } catch (e) {
        fail++;
        console.log('FAIL: ' + e.message);
      }
    }
  }

  console.log('\nDone: ' + success + ' downloaded, ' + fail + ' failed');
})();