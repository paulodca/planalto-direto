// Utilidades comuns aos testes de casos (node:test e navegador): carga dos casos, escolha dos dados,
// fonte em disco e comparação entre o esperado (testes/casos.json) e o observado.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

export const RAIZ = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const require = createRequire(import.meta.url);
export const Nucleo = require(path.join(RAIZ, 'docs', 'assets', 'nucleo.js'));

export const IDS_OBRIGATORIOS = [
  ...Array.from({ length: 15 }, (_, i) => String(i + 1)),
  'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'M1', 'M2', 'M3', 'M4', 'C1', 'C2', 'C3', 'L1', 'L2', 'L3',
  'R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'P1', 'P2', 'P3', 'P4',
  'N1', 'N2', 'N3', 'N4', 'X1', 'X2', 'X3', 'X4', 'X5', 'X6'
];
export const NORMAS_BASE_REAL = 21024;

/** Lê docs/config.js com a mesma regra de linha do pd.config (§4.2). */
export function lerConfig(arq = path.join(RAIZ, 'docs', 'config.js')) {
  const cfg = {};
  const re = /^\s*([A-Z_]+)\s*:\s*"((?:[^"\\]|\\.)*)"\s*,?\s*$/;
  for (const linha of fs.readFileSync(arq, 'utf8').split('\n')) {
    const m = re.exec(linha.replace(/\r$/, ''));
    if (m) cfg[m[1]] = m[2];
  }
  return cfg;
}

/** Casos com `igual_a` expandido (herda as expectativas do caso citado). */
export function carregarCasos(arq = path.join(RAIZ, 'testes', 'casos.json')) {
  const lista = JSON.parse(fs.readFileSync(arq, 'utf8'));
  const porId = Object.fromEntries(lista.map((c) => [c.id, c]));
  return lista.map((c) => {
    if (!c.igual_a) return c;
    const base = porId[c.igual_a];
    if (!base) throw new Error(`caso ${c.id}: igual_a inexistente ${c.igual_a}`);
    const { id, consulta, rota, na, ...esperado } = base;
    return { ...esperado, ...c, consulta: c.consulta ?? (c.rota ? undefined : consulta) };
  });
}

export function idsFaltando(casos) {
  const presentes = new Set(casos.map((c) => String(c.id).split('.')[0]));
  return IDS_OBRIGATORIOS.filter((id) => !presentes.has(id));
}

/** Pasta de dados: PD_DADOS, senão docs/dados (se gerado), senão a fixture. */
export function escolherDados() {
  if (process.env.PD_DADOS) return path.resolve(process.env.PD_DADOS);
  const real = path.join(RAIZ, 'docs', 'dados');
  if (fs.existsSync(path.join(real, 'manifesto.json'))) return real;
  return path.join(RAIZ, 'testes', 'fixtures', 'dados_min');
}

export function fonteDisco(dir) {
  const ler = (p) => JSON.parse(fs.readFileSync(path.join(dir, p), 'utf8'));
  return {
    manifesto: async () => ler('manifesto.json'),
    shard: async (n) => ler(n + '.json'),
    ancorasIndice: async () => ler('ancoras.json').normas,
    ancoras: async (k) => (fs.existsSync(path.join(dir, 'a', k + '.json')) ? ler('a/' + k + '.json') : null),
    apelidos: async () => ler('apelidos.json'),
    avisos: async () => ler('avisos.json').avisos || []
  };
}

/** Informações do conjunto de dados usadas pelas regras de leitura do §14.2. */
export async function infoDados(dir) {
  const f = fonteDisco(dir);
  const man = await f.manifesto();
  const ap = await f.apelidos();
  const avisos = await f.avisos();
  const chaves = new Set();
  for (const nome of Object.keys(man.shards)) for (const r of await f.shard(nome)) chaves.add(r.k);
  return {
    dir, man, real: man.normas >= NORMAS_BASE_REAL, chaves,
    desempate: ap.desempate || {}, alvosApelido: new Set((ap.apelidos || []).map((a) => a.alvo)),
    avisosPublicados: new Set(avisos.map((a) => a.id))
  };
}

export function esperadoComDesempate(itens, grupo, info) {
  if (!grupo || !itens || !itens.length) return itens;
  const pref = info.desempate[grupo];
  if (!pref || info.alvosApelido.has(itens[0])) return itens;
  return [pref, ...itens.filter((k) => k !== pref)];
}

/** Expectativa efetiva: aplica a regra dos avisos (se_aviso/sem_aviso) e o desempate. */
export function expectativa(caso, info) {
  let e = { ...caso };
  if (caso.se_aviso && !info.avisosPublicados.has(caso.se_aviso)) e = { ...e, ...(caso.sem_aviso || {}) };
  if (e.itens && e.grupo) e.itens = esperadoComDesempate(e.itens, e.grupo, info);
  return e;
}

/** Chaves que o caso exige nos dados (para pular casos fora da fixture). */
export function chavesDoCaso(e) {
  const ks = [];
  if (e.k) ks.push(e.k);
  for (const r of e.refs || []) if (r.k) ks.push(r.k);
  for (const k of e.itens || []) ks.push(k);
  for (const k of e.outras || []) ks.push(k);
  for (const k of e.outras_contem || []) ks.push(k);
  return ks;
}

// raiz de status proibida (I4), montada por partes para o próprio fonte não casar com o padrão
const STATUS_PROIBIDO = new RegExp('revo' + 'gad', 'i');

function contem(a, b) { return String(a || '').toLowerCase().includes(String(b).toLowerCase()); }

/**
 * Compara. `obs`: {tipo, url, alt, refs:[{k,url}], ks:[k], itens:[k], avisos:[id], mensagem, texto,
 * transicao, notas, outras:[k], nome, rotuloPedido}. Devolve a lista de divergências (vazia = PASS).
 */
export function conferir(e, obs, base) {
  const erros = [];
  const abs = (u) => (u == null ? u : base + u);
  const tipos = Array.isArray(e.tipo) ? e.tipo : e.tipo ? [e.tipo] : [];
  if (tipos.length && !tipos.includes(obs.tipo)) erros.push(`tipo ${obs.tipo} ≠ ${tipos.join('|')}`);
  if (e.k && (obs.ks || [])[0] !== e.k) erros.push(`k ${(obs.ks || [])[0]} ≠ ${e.k}`);
  if (e.url && obs.url !== abs(e.url)) erros.push(`url ${obs.url} ≠ ${abs(e.url)}`);
  if (e.alt && obs.alt !== abs(e.alt)) erros.push(`alt ${obs.alt} ≠ ${abs(e.alt)}`);
  for (const proib of e.url_nao_contem || []) {
    const u = obs.url || '';
    const i = u.indexOf(proib);
    if (i >= 0 && (i + proib.length === u.length)) erros.push(`url termina com o proibido ${proib}`);
  }
  if (e.refs) {
    if ((obs.refs || []).length !== e.refs.length) erros.push(`refs: ${(obs.refs || []).length} ≠ ${e.refs.length}`);
    e.refs.forEach((r, i) => {
      const o = (obs.refs || [])[i] || {};
      if (r.k && o.k && o.k !== r.k) erros.push(`ref ${i}: k ${o.k} ≠ ${r.k}`);
      if (r.url && o.url !== abs(r.url)) erros.push(`ref ${i}: url ${o.url} ≠ ${abs(r.url)}`);
    });
  }
  if (e.itens) {
    const ini = (obs.itens || []).slice(0, e.itens.length);
    if (ini.join(' ') !== e.itens.join(' ')) erros.push(`itens [${ini}] não começam com [${e.itens}]`);
  }
  if (e.avisos) for (const id of e.avisos) if (!(obs.avisos || []).includes(id)) erros.push(`aviso ${id} ausente`);
  if (e.sem_avisos && (obs.avisos || []).length) erros.push(`avisos inesperados: ${obs.avisos}`);
  if (e.mensagem_contem && !contem(obs.mensagem, e.mensagem_contem)) erros.push(`mensagem "${obs.mensagem}" sem "${e.mensagem_contem}"`);
  if (e.transicao_contem && !contem(obs.transicao, e.transicao_contem)) erros.push(`transição "${obs.transicao}" sem "${e.transicao_contem}"`);
  if (e.nota_contem && !contem(obs.notas, e.nota_contem)) erros.push(`nota "${obs.notas}" sem "${e.nota_contem}"`);
  if (e.outras && (obs.outras || []).join(' ') !== e.outras.join(' ')) erros.push(`outras [${obs.outras}] ≠ [${e.outras}]`);
  for (const k of e.outras_contem || []) if (!(obs.outras || []).includes(k)) erros.push(`outras sem ${k}`);
  if (e.nome && !contem(obs.nome, e.nome)) erros.push(`nome "${obs.nome}" ≠ "${e.nome}"`);
  if (e.rotulo_pedido && obs.rotuloPedido !== undefined && obs.rotuloPedido !== e.rotulo_pedido) erros.push(`pedido "${obs.rotuloPedido}" ≠ "${e.rotulo_pedido}"`);
  if (STATUS_PROIBIDO.test(obs.texto || '')) erros.push('o texto exibido contém a raiz de status proibida (I4)');
  return erros;
}

/** Observação a partir de um Resultado do nucleo (J1). */
export function observarResultado(R) {
  const r0 = (R.refs || [])[0];
  const i0 = (R.itens || [])[0];
  const d0 = r0 ? r0.destino : i0 ? i0.destino : null;
  const notas = [R.mensagem, ...(R.refs || []).flatMap((r) => [r.nota, r.destino && r.destino.nota])].filter(Boolean).join(' | ');
  return {
    tipo: R.tipo, url: d0 ? d0.url : undefined, alt: d0 && d0.alt ? d0.alt.url : undefined,
    refs: (R.refs || []).map((r) => ({ k: r.k, url: r.destino.url })), ks: (R.refs || []).map((r) => r.k),
    itens: (R.itens || []).map((i) => i.k), avisos: (R.avisos || []).map((a) => a.id), mensagem: R.mensagem || '',
    transicao: r0 ? Nucleo.textoTransicao(r0) : '', notas, outras: r0 ? r0.outras : [], nome: r0 ? r0.nome : '',
    rotuloPedido: r0 ? r0.rotuloPedido : undefined,
    texto: JSON.stringify({ m: R.mensagem, r: (R.refs || []).map((r) => [r.nome, r.nota, r.destino.nota]), a: R.avisos })
  };
}
