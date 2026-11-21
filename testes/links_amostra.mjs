#!/usr/bin/env node
// Gera a amostra de links da checagem (b) com o próprio nucleo.js sobre docs/dados (SPEC §14.4).
// Só entram páginas presentes nas páginas do Planalto guardadas localmente (--cache-html DIR | PD_CACHE_HTML).
// Uso: node testes/links_amostra.mjs --cache-html DIR [--saida ARQ] [--dados DIR] [--json ARQ]
// Saída: [{consulta, url, estrato}] (+ itens {consulta, na} para os casos fora do cache local).
import fs from 'node:fs';
import path from 'node:path';
import {
  Nucleo as N, RAIZ, carregarCasos, escolherDados, fonteDisco, lerConfig
} from './js/casos_comum.mjs';

const SEMENTE = 20261121;
const ESTRATOS = [['compilado', 10], ['historico-com-compilado', 10], ['paragrafo', 10], ['inciso-alinea', 5],
  ['cf', 3], ['adct', 2], ['sem-compilado', 5], ['sem-fragmento', 5]];

function args(argv) {
  const o = { cache: process.env.PD_CACHE_HTML || '', saida: path.join(RAIZ, 'testes', '.saida', 'amostra.json'), dados: '', json: '' };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--cache-html') o.cache = argv[++i];
    else if (a === '--saida') o.saida = path.resolve(argv[++i]);
    else if (a === '--dados') o.dados = path.resolve(argv[++i]);
    else if (a === '--json') o.json = path.resolve(argv[++i]);
    else if (a === '-h' || a === '--help') { console.log('uso: node testes/links_amostra.mjs --cache-html DIR [--saida ARQ] [--dados DIR] [--json ARQ]'); process.exit(0); }
    else { console.error('argumento desconhecido: ' + a); process.exit(2); }
  }
  return o;
}

function relatar(o, estado, detalhe, itens) {
  if (o.json) {
    fs.mkdirSync(path.dirname(o.json), { recursive: true });
    fs.writeFileSync(o.json, JSON.stringify({ id: 'links_amostra', estado, detalhe, itens }, null, 1) + '\n', 'utf8');
  }
  console.log((estado === 'SKIP' ? 'SKIP: ' : estado + ': ') + detalhe);
  process.exit({ PASS: 0, FAIL: 1, SKIP: 77 }[estado]);
}

// gerador determinístico (mulberry32)
function gerador(semente) {
  let a = semente >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
function embaralhar(lista, rnd) {
  const a = lista.slice();
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
  return a;
}

function dispParaTexto(comps) {
  const [art, ...resto] = comps;
  const partes = ['art ' + art];
  for (const c of resto) {
    if (c === 'pu') partes.push('parágrafo único');
    else if (c.startsWith('§')) partes.push('§ ' + c.slice(1));
    else if (/^[IVXLCDM]+$/.test(c)) partes.push('inciso ' + c);
    else if (/^[a-z]$/.test(c)) partes.push('alínea ' + c);
    else if (/^\d+$/.test(c)) partes.push('item ' + c);
  }
  return partes.join(' ');
}

function consultaNorma(r) {
  if (r.k === 'cf-1988') return 'cf';
  const t = r.k.slice(0, r.k.indexOf('-'));
  return `${t} ${r.n}${r.l || ''}/${r.a}`;
}

async function main() {
  const o = args(process.argv.slice(2));
  if (!o.cache || !fs.existsSync(path.join(o.cache, 'www.planalto.gov.br'))) relatar(o, 'SKIP', 'páginas do Planalto guardadas localmente não fornecidas (--cache-html ou PD_CACHE_HTML)', []);
  const cfg = lerConfig();
  const dir = o.dados || escolherDados();
  const fonte = fonteDisco(dir);
  const noCache = (url) => {
    const rel = url.slice(cfg.PLANALTO_BASE.length).split('#')[0];
    return fs.existsSync(path.join(o.cache, 'www.planalto.gov.br', 'ccivil_03', ...rel.toLowerCase().split('/')));
  };
  const saida = [], na = [], usados = new Set();

  // 1) casos exatos de casos.json
  for (const c of carregarCasos()) {
    if (c.na || c.tipo !== 'exato' || c.so === 'js') continue;
    const consulta = c.rota ? N.rotaParaConsulta(c.rota, cfg.SITE_PATH) : c.consulta;
    if (!consulta) continue;
    const R = await N.resolver(consulta, fonte, cfg);
    if (R.tipo !== 'exato') { na.push({ consulta, na: `resultado ${R.tipo}` }); continue; }
    const url = R.refs[0].destino.url;
    if (!noCache(url)) { na.push({ consulta, na: 'fora do cache local' }); continue; }
    if (usados.has(url)) continue;
    usados.add(url);
    saida.push({ consulta, url, estrato: 'caso ' + c.id });
  }

  // 2) amostra estratificada e determinística
  const man = await fonte.manifesto();
  const regs = new Map();
  for (const nome of Object.keys(man.shards).sort()) for (const r of await fonte.shard(nome)) regs.set(r.k, r);
  const comAnc = await fonte.ancorasIndice();
  const candidatos = Object.fromEntries(ESTRATOS.map(([e]) => [e, []]));
  const base = cfg.PLANALTO_BASE;
  for (const k of comAnc) {
    const r = regs.get(k);
    if (!r) continue;
    const anc = await fonte.ancoras(k);
    for (const parte of ['corpo', 'adct']) {
      for (const [disp, v] of Object.entries((anc && anc[parte]) || {})) {
        const comps = disp.split('|');
        const ultimo = comps[comps.length - 1];
        const item = { k, parte, comps, r };
        if (k === 'cf-1988') { candidatos[parte === 'adct' ? 'adct' : 'cf'].push(item); continue; }
        if (v.c && r.c && noCache(base + r.c)) candidatos.compilado.push({ ...item, versao: 'c' });
        if (v.h && !v.c && r.c && noCache(base + r.u)) candidatos['historico-com-compilado'].push({ ...item, versao: 'h' });
        if (disp.includes('§')) candidatos.paragrafo.push(item);
        if (comps.length > 1 && (/^[IVXLCDM]+$/.test(ultimo) || /^[a-z]$/.test(ultimo))) candidatos['inciso-alinea'].push(item);
        if (!r.c) candidatos['sem-compilado'].push(item);
      }
    }
  }
  const setAnc = new Set(comAnc);
  for (const r of regs.values()) if (!setAnc.has(r.k) && noCache(base + (r.c || r.u))) candidatos['sem-fragmento'].push({ k: r.k, r, comps: null });

  const rnd = gerador(SEMENTE);
  const faltas = [];
  for (const [estrato, qtd] of ESTRATOS) {
    let n = 0;
    for (const it of embaralhar(candidatos[estrato], rnd)) {
      if (n >= qtd) break;
      const consulta = it.comps
        ? (it.parte === 'adct' ? `adct ${dispParaTexto(it.comps).slice(4)}` : `${consultaNorma(it.r)} ${dispParaTexto(it.comps)}`)
        : consultaNorma(it.r);
      const R = await N.resolver(consulta, fonte, cfg);
      if (R.tipo !== 'exato' || R.refs[0].k !== it.k) continue;
      const d = R.refs[0].destino;
      if (it.comps && (!d.fragmento || d.profundidade !== it.comps.length)) continue;
      if (it.versao && d.versao !== it.versao) continue;
      if (!it.comps && d.fragmento) continue;
      if (!noCache(d.url) || usados.has(d.url)) continue;
      usados.add(d.url);
      saida.push({ consulta, url: d.url, estrato });
      n++;
    }
    if (n < qtd) faltas.push(`${estrato}: ${n}/${qtd}`);
  }
  const amostra = [...saida, ...na];
  fs.mkdirSync(path.dirname(o.saida), { recursive: true });
  fs.writeFileSync(o.saida, JSON.stringify(amostra, null, 1) + '\n', 'utf8');
  const estado = faltas.length ? 'FAIL' : 'PASS';
  relatar(o, estado, `${saida.length} links (${na.length} N/A fora do cache local: ${na.map((x) => x.consulta).join('; ')})` +
    (faltas.length ? `; estratos incompletos: ${faltas.join(', ')}` : ''), amostra);
}

main().catch((e) => { console.error(e); console.log('FAIL: ' + e.message); process.exit(1); });
