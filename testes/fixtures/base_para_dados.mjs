#!/usr/bin/env node
// Conversor SÓ DE TESTE: testes/fixtures/base_min/ -> testes/fixtures/dados_min/ no formato de docs/dados (SPEC §6.3).
// Não é o estágio B: serve para testar o nucleo.js antes da integração.
// Uso: node testes/fixtures/base_para_dados.mjs [--base DIR] [--fontes DIR] [--saida DIR]
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const RAIZ = path.resolve(AQUI, '..', '..');

function args(argv) {
  const o = { base: path.join(AQUI, 'base_min'), fontes: path.join(RAIZ, 'fontes'), saida: path.join(AQUI, 'dados_min') };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--base') o.base = path.resolve(argv[++i]);
    else if (a === '--fontes') o.fontes = path.resolve(argv[++i]);
    else if (a === '--saida') o.saida = path.resolve(argv[++i]);
    else if (a === '-h' || a === '--help') { console.log('uso: node testes/fixtures/base_para_dados.mjs [--base DIR] [--fontes DIR] [--saida DIR]'); process.exit(0); }
    else { console.error('argumento desconhecido: ' + a); process.exit(2); }
  }
  return o;
}

// JSON compacto com chaves em ordem (igual a json.dumps(sort_keys=True, ensure_ascii=False, separators=(',',':'))).
function compacto(v) {
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return '[' + v.map(compacto).join(',') + ']';
  return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + compacto(v[k])).join(',') + '}';
}

const TIPOS = ['lei', 'lc', 'dl', 'mp', 'ec', 'ld', 'ecr', 'cf'];
function ordemChave(k) {
  if (k === 'cf-1988') return [7, 1988, '', 1988];
  const m = /^(lei|lc|dl|mp|ec|ld|ecr)-(\d+)([a-z]?)-(\d{4})$/.exec(k);
  return [TIPOS.indexOf(m[1]), +m[2], m[3], +m[4]];
}
function cmp(a, b) { for (let i = 0; i < a.length; i++) { if (a[i] < b[i]) return -1; if (a[i] > b[i]) return 1; } return 0; }
const porChave = (a, b) => cmp(ordemChave(a), ordemChave(b));

function lerJson(p, padrao) {
  if (!fs.existsSync(p)) return padrao;
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function gravar(p, texto) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, texto + '\n', 'utf8');
}

function sha12(p) { return crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex').slice(0, 12); }

function main() {
  const o = args(process.argv.slice(2));
  const arqNormas = path.join(o.base, 'normas.jsonl');
  if (!fs.existsSync(arqNormas)) { console.log('SKIP: fixture base_min ausente'); process.exit(77); }
  const normas = fs.readFileSync(arqNormas, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
  normas.sort((a, b) => porChave(a.k, b.k));
  const chaves = new Set(normas.map((n) => n.k));

  // limpa a saída anterior (só arquivos .json desta pasta)
  if (fs.existsSync(o.saida)) fs.rmSync(o.saida, { recursive: true, force: true });
  fs.mkdirSync(path.join(o.saida, 'a'), { recursive: true });

  const shards = {};
  for (const n of normas) {
    const nome = n.tsig === 'cf' ? 'n-cf-00' : `n-${n.tsig}-${String(Math.floor(n.numero / 1000)).padStart(2, '0')}`;
    const r = { a: n.ano, k: n.k, l: n.letra, n: n.numero, u: n.caminho };
    if (n.caminho_compilado) r.c = n.caminho_compilado;
    if (n.data) r.d = n.data;
    if (n.ementa) r.e = n.ementa;
    if (n.reed) r.r = n.reed;
    (shards[nome] = shards[nome] || []).push(r);
  }
  const manShards = {};
  for (const nome of Object.keys(shards).sort()) {
    const p = path.join(o.saida, nome + '.json');
    gravar(p, compacto(shards[nome]));
    manShards[nome] = { qtd: shards[nome].length, sha: sha12(p) };
  }

  const dirAnc = path.join(o.base, 'ancoras');
  const comAnc = fs.existsSync(dirAnc) ? fs.readdirSync(dirAnc).filter((f) => f.endsWith('.json')).map((f) => f.slice(0, -5)) : [];
  comAnc.sort(porChave);
  for (const k of comAnc) gravar(path.join(o.saida, 'a', k + '.json'), compacto(lerJson(path.join(dirAnc, k + '.json'))));
  gravar(path.join(o.saida, 'ancoras.json'), compacto({ normas: comAnc, versao: 1 }));

  // apelidos: fontes/apelidos.json filtrado às chaves da fixture
  const ap = lerJson(path.join(o.fontes, 'apelidos.json'), { versao: 1, apelidos: [], listas: [], assuntos: [], fora_escopo: [] });
  const desemp = lerJson(path.join(o.base, 'desempate.json'), { grupos: {} });
  const apOut = {
    versao: ap.versao || 1,
    apelidos: (ap.apelidos || []).filter((a) => chaves.has(a.alvo)),
    listas: (ap.listas || []).map((l) => ({ ...l, alvos: l.alvos.filter((k) => chaves.has(k)) })).filter((l) => l.alvos.length),
    assuntos: (ap.assuntos || []).map((l) => ({ ...l, alvos: l.alvos.filter((k) => chaves.has(k)) })).filter((l) => l.alvos.length),
    fora_escopo: ap.fora_escopo || [],
    desempate: desemp.grupos || {}
  };
  gravar(path.join(o.saida, 'apelidos.json'), compacto(apOut));

  const areas = lerJson(path.join(o.fontes, 'areas.json'), { versao: 1, areas: [] });
  gravar(path.join(o.saida, 'areas.json'), compacto({
    versao: areas.versao || 1,
    areas: (areas.areas || []).map((a) => ({ ...a, itens: a.itens.filter((i) => chaves.has(i.k)) })).filter((a) => a.itens.length)
  }));

  // avisos: só os conferidos (conferido_em preenchido), sem prova nem conferido_em, em ordem de id
  const av = lerJson(path.join(o.fontes, 'avisos.json'), { versao: 1, avisos: [] });
  const avisos = (av.avisos || []).filter((a) => a.conferido_em && chaves.has(a.alvo.k))
    .map((a) => ({ id: a.id, alvo: a.alvo, estado: a.estado, texto: a.texto, fonte: a.fonte, ir_para: a.ir_para || '' }))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  gravar(path.join(o.saida, 'avisos.json'), compacto({ avisos, versao: av.versao || 1 }));

  const gerado = normas.reduce((m, n) => (n.desde > m ? n.desde : m), '');
  const baseSha = crypto.createHash('sha256').update(fs.readFileSync(arqNormas)).digest('hex').slice(0, 12);
  gravar(path.join(o.saida, 'manifesto.json'), compacto({ base_sha: baseSha, gerado, normas: normas.length, shards: manShards, versao: 1 }));
  console.log(`dados_min: ${normas.length} normas, ${comAnc.length} com âncoras, ${Object.keys(manShards).length} fatias, ${avisos.length} avisos`);
}

main();
