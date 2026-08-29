const fs = require('fs');

const data = JSON.parse(fs.readFileSync(
  'C:/Users/Rafael/Documents/MultiTool/HomeChats/Chat-8/repo-clone/src/data/all_posts.json', 'utf8'
));

// Правильная транслитерация
const map = {
  'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e',
  'ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m',
  'н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u',
  'ф':'f','х':'kh','ц':'ts','ч':'ch','ш':'sh','щ':'shch',
  'ъ':'','ы':'y','ь':'','э':'e','ю':'yu','я':'ya'
};

const seen = new Set();

data.forEach(p => {
  const date = p.date.split(' ')[0];
  const words = p.text
    ? p.text.trim().split(/\s+/).slice(0, 4).join(' ')
    : 'post-' + p.id;
  let s = '';
  for (const ch of words.toLowerCase()) {
    if (map[ch] !== undefined) {
      s += map[ch];
    } else if (/[a-z0-9-]/.test(ch)) {
      s += ch;
    }
  }
  s = s.replace(/\s+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '').substring(0, 50);
  let slug = date + '-' + s;
  if (seen.has(slug)) {
    slug = slug + '-' + p.id;
  }
  seen.add(slug);
  p.slug = slug;
});

// Проверка на кириллицу
const bad = data.filter(p => /[а-яё]/.test(p.slug));
console.log('Кириллица: ' + bad.length);

// Проверка на bslo
const bslo = data.filter(p => p.slug.includes('bslo'));
console.log('bslo: ' + bslo.length);
if (bslo.length > 0) {
  bslo.slice(0, 3).forEach(p => {
    console.log('  id=' + p.id + ' slug=' + p.slug);
    const txt = (p.text || '').toLowerCase().slice(0, 40);
    const chars = [...txt].map(ch => ch + '(' + ch.charCodeAt(0) + ')=' + (map[ch] || '?')).join(' ');
    console.log('  chars: ' + chars);
  });
}

console.log('Примеры:');
console.log('  ' + data[0].slug);
console.log('  ' + data[1].slug);
console.log('  ' + data[2].slug);

fs.writeFileSync(
  'C:/Users/Rafael/Documents/MultiTool/HomeChats/Chat-8/repo-clone/src/data/all_posts.json',
  JSON.stringify(data)
);
fs.writeFileSync(
  'C:/Users/Rafael/Documents/MultiTool/HomeChats/Chat-8/repo-clone/download/all_posts_full.json',
  JSON.stringify(data)
);
fs.writeFileSync(
  'C:/Users/Rafael/Documents/MultiTool/HomeChats/Chat-8/repo-clone/astro-site/src/data/all_posts.json',
  JSON.stringify(data)
);