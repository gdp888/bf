const https = require('https');
const fs = require('fs');
const path = require('path');
const token = '92c6b73b92c6b73b92c6b73b059185f49b992c692c6b73bf85616bdc64586db266255e4';
const ownerId = '-223846998';

function get(url) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => { try { resolve(JSON.parse(data)); } catch(e) { resolve({error: e.message}); } });
    }).on('error', reject);
  });
}

(async () => {
  // Get album descriptions
  const albumResp = await get('https://api.vk.com/method/photos.getAlbums?owner_id=' + ownerId + '&need_system=1&need_cover=1&photo_sizes=1&v=5.131&access_token=' + token);
  const albumMeta = {};
  if (albumResp.response?.items) {
    for (const a of albumResp.response.items) {
      albumMeta[a.id] = { description: a.description || '', thumb_id: a.thumb_id };
    }
  }

  const albums = [
    { id: 308733178, title: 'Отчеты по сборам' },
    { id: 301563721, title: 'Время_Вместе' },
    { id: 300582930, title: 'Наше участие' },
    { id: 300476473, title: 'Детское Царство' },
    { id: 300257960, title: 'наши подопечные' },
    { id: 300244899, title: 'наши любимые особенные детки' },
    { id: 300244669, title: 'Праздники' },
    { id: 300236577, title: 'Main album' },
    { id: -6, title: 'Logo pictures' }
  ];

  const result = { albums: [] };

  for (const album of albums) {
    process.stdout.write('Fetching: ' + album.title + '... ');

    let allPhotos = [];
    let offset = 0;
    while (true) {
      const resp = await get('https://api.vk.com/method/photos.get?owner_id=' + ownerId + '&album_id=' + album.id + '&photo_sizes=1&rev=1&offset=' + offset + '&count=100&v=5.131&access_token=' + token);
      if (resp.error) {
        console.log('ERROR:', JSON.stringify(resp.error));
        break;
      }
      const items = resp.response?.items || [];
      allPhotos = allPhotos.concat(items);
      if (items.length < 100) break;
      offset += 100;
    }

    const photos = allPhotos.map(p => {
      const sizes = p.sizes || [];
      const preferredTypes = ['w', 'z', 'y', 'base', 'x'];
      let best = { url: '', width: 0, height: 0 };
      for (const t of preferredTypes) {
        const found = sizes.find(s => s.type === t);
        if (found) { best = { url: found.url, width: found.width, height: found.height }; break; }
      }
      if (!best.url && sizes.length) {
        const last = sizes[sizes.length - 1];
        best = { url: last.url, width: last.width, height: last.height };
      }
      return {
        id: p.id,
        date: p.date,
        text: p.text || '',
        url: best.url,
        width: best.width,
        height: best.height,
        user_id: p.user_id
      };
    });

    const meta = albumMeta[album.id] || {};
    result.albums.push({
      id: album.id,
      title: album.title,
      description: meta.description || '',
      thumb_id: meta.thumb_id || null,
      photos: photos,
      photo_count: photos.length
    });

    console.log(photos.length + ' photos');
  }

  const outPath = path.join(__dirname, 'src', 'data', 'albums.json');
  fs.writeFileSync(outPath, JSON.stringify(result, null, 2));
  console.log('\nSaved to ' + outPath);

  let total = 0;
  for (const a of result.albums) {
    console.log(a.title + ': ' + a.photos.length + ' photos');
    total += a.photos.length;
  }
  console.log('TOTAL: ' + total + ' photos');
})();