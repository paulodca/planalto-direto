// Unitários do nucleo.js com entradas sintéticas (sem texto de lei).
import test from 'node:test';
import assert from 'node:assert/strict';
import { Nucleo as N, escolherDados, fonteDisco } from './casos_comum.mjs';

const BASE = 'https://www.planalto.gov.br/ccivil_03/';
const cfg = { PLANALTO_BASE: BASE };

test('API exportada (§9.1)', () => {
  for (const f of ['normalizar', 'prepararApelidos', 'analisar', 'resolver', 'escolherDestino', 'montarUrl',
    'codificarFragmento', 'nomeNorma', 'buscarTexto', 'rotaParaConsulta']) assert.equal(typeof N[f], 'function', f);
  assert.equal(N.VERSAO, 1);
});

test('codificarFragmento = quote(safe="")', () => {
  assert.equal(N.codificarFragmento("a§b!'()*~ç"), 'a%C2%A7b%21%27%28%29%2A~%C3%A7');
  assert.equal(N.codificarFragmento('art477..'), 'art477..');
  assert.equal(N.codificarFragmento('art8§1'), 'art8%C2%A71');
  assert.equal(N.montarUrl(BASE, 'leis/x.htm', null), BASE + 'leis/x.htm');
  assert.equal(N.montarUrl(BASE, 'leis/x.htm', 'art1-a_b'), BASE + 'leis/x.htm#art1-a_b');
});

test('nomeNorma (§5.6)', () => {
  assert.equal(N.nomeNorma('lei', 8036, '', '', 1990), 'Lei nº 8.036/1990');
  assert.equal(N.nomeNorma('dl', 5452, '', '', 1943), 'Decreto-Lei nº 5.452/1943');
  assert.equal(N.nomeNorma('lei', 5467, 'a', '', 1968), 'Lei nº 5.467-A/1968');
  assert.equal(N.nomeNorma('mp', 2158, '', '35', 2001), 'Medida Provisória nº 2.158-35/2001');
  assert.equal(N.nomeNorma('lei', 605, '', '', 1949), 'Lei nº 605/1949');
  assert.equal(N.nomeNorma('cf', 1988, '', '', 1988), 'Constituição Federal de 1988');
});

test('ordemPublica: apelido, tipo, ano DESC, chave', () => {
  const g = ['lei-5452-1968', 'dl-5452-1943', 'mp-100-1989', 'mp-100-2002'];
  assert.deepEqual(N.ordemPublica(g, new Set()), ['lei-5452-1968', 'dl-5452-1943', 'mp-100-2002', 'mp-100-1989']);
  assert.deepEqual(N.ordemPublica(['lei-5452-1968', 'dl-5452-1943'], new Set(['dl-5452-1943'])), ['dl-5452-1943', 'lei-5452-1968']);
  assert.deepEqual(N.ordemPublica([{ k: 'cf-1988' }, { k: 'ec-1-1992' }], []).map((x) => x.k), ['ec-1-1992', 'cf-1988']);
});

test('normalizar (§9.2)', () => {
  assert.equal(N.normalizar('Art. 5º, LV'), 'ART 5 , lv');
  assert.equal(N.normalizar('art477'), 'ART 477');
  assert.equal(N.normalizar('lei 8.036/90'), 'lei 8036/90');
  assert.equal(N.normalizar('§ 1º-A'), '§ 1-a');
  assert.equal(N.normalizar('parágrafo único'), 'PU');
  assert.equal(N.normalizar('lei n. 8.036, de 11 de maio de 1990'), 'lei n. 8036 , ANO=1990');
  assert.equal(N.normalizar('arte inconstitucionalidade'), 'arte inconstitucionalidade');
  assert.equal(N.normalizar('L10.741'), 'ARQ#0');
  assert.equal(N.normalizar('x c/c y'), 'x & y');
});

const AP = {
  apelidos: [
    { alvo: 'dl-5452-1943', sigla: 'CLT', termos: ['clt'], nota: '' },
    { alvo: 'dl-9001-1941', sigla: 'LCPX', termos: ['lcp'], nota: '' },
    { alvo: 'lei-9002-2002', sigla: 'CC', termos: ['cc'], nota: '' },
    { alvo: 'lei-9003-2015', sigla: 'LBI', termos: ['lei brasileira de inclusão'], nota: '' },
    { alvo: 'lei-9004-2008', sigla: 'Estágio', termos: ['estágio'], nota: '' }
  ],
  listas: [], assuntos: [],
  fora_escopo: [{ padrao: '\\bdecreto\\b(?!\\s*-?\\s*lei)', mensagem: 'Decretos fora.' },
    { padrao: '^(nr|norma regulamentadora)\\s*-?\\s*\\d*$', mensagem: 'NR fora.' }]
};
const apc = N.prepararApelidos(AP);

test('analisar: apelido antes dos marcadores; sobra; fora de escopo', () => {
  let a = N.analisar('art 186 cc', apc);
  assert.equal(a.grupos.length, 1);
  assert.equal(a.grupos[0].norma.via, 'apl');
  assert.deepEqual(a.grupos[0].arts[0].comps, ['186']);
  a = N.analisar('lei brasileira de inclusão', apc);
  assert.equal(a.sobra, false);
  assert.ok(!a.tokens.includes('INC'));
  a = N.analisar('estágio probatório', apc);
  assert.equal(a.sobra, true);
  assert.equal(N.analisar('lcp', apc).grupos[0].norma.via, 'apl');
  assert.equal(N.analisar('lcp 150', apc).grupos[0].norma.tsig, 'lc');
  assert.equal(N.analisar('decreto 3048', apc).fora, 'Decretos fora.');
  assert.equal(N.analisar('NR-15', apc).fora, 'NR fora.');
  assert.equal(N.analisar('decreto-lei 5452', apc).fora, null);
  assert.ok(!N.analisar('arte', apc).tokens.includes('ART'));
});

test('analisar: concordância à direita, intervalo, dispositivos', () => {
  let a = N.analisar('arts. 5º, LV, e 93, IX, da CLT', apc);
  assert.deepEqual(a.grupos[0].arts.map((x) => x.comps), [['5', 'LV'], ['93', 'IX']]);
  a = N.analisar('art. 818 da CLT c/c art. 373 do CC', apc);
  assert.deepEqual(a.grupos.map((g) => g.arts.map((x) => x.comps[0])), [['818'], ['373']]);
  a = N.analisar('clt 477 a 483', apc);
  assert.deepEqual(a.grupos[0].arts[0].intervalo, ['477', '483']);
  a = N.analisar('clt 11-A §1', apc);
  assert.deepEqual(a.grupos[0].arts[0].comps, ['11-A', '§1']);
  a = N.analisar('clt 477 § 1º-A inciso II alínea b item 3', apc);
  assert.deepEqual(a.grupos[0].arts[0].comps, ['477', '§1-A', 'II', 'b', '3']);
  a = N.analisar('§ 4º do art. 477 da CLT', apc);
  assert.deepEqual(a.grupos[0].arts[0].comps, ['477', '§4']);
  a = N.analisar('cf adct 76', N.prepararApelidos({ apelidos: [{ alvo: 'cf-1988', sigla: 'CF', termos: ['cf'] }] }));
  assert.equal(a.grupos.length, 1);
  assert.equal(a.grupos[0].arts[0].parte, 'adct');
  a = N.analisar('mp 2158-35', apc);
  assert.equal(a.grupos[0].norma.numero, 2158);
  assert.equal(a.grupos[0].norma.reed, '35');
  a = N.analisar('Del0001', apc);
  assert.equal(a.grupos[0].norma.arq.slug, 'del0001');
  assert.equal(N.analisar('https://www.planalto.gov.br/ccivil_03/Leis/L8036consol.htm', apc).caminho, 'leis/l8036consol.htm');
});

const REG = { k: 'dl-9999-1943', a: 1943, l: '', n: 9999, u: 'decreto-lei/H.htm', c: 'decreto-lei/C.htm' };
const ANC = {
  k: 'dl-9999-1943', h: 'decreto-lei/H.htm', c: 'decreto-lei/C.htm',
  corpo: {
    '10': { c: 'c10', h: 'h10' },
    '10|§1': { h: 'h10p1' },
    '20': { h: 'h20' },
    '30|§1': { c: 'c30p1' },
    '30': { c: 'c30', h: 'h30' },
    '8': { c: 'c8' },
    '8|§1': { c: 'c8§1', h: 'h8§1' }
  }
};

test('escolherDestino: sem pedido abre o compilado; alternativa', () => {
  const d = N.escolherDestino(REG, null, null, [], cfg);
  assert.equal(d.url, BASE + 'decreto-lei/C.htm');
  assert.equal(d.versao, 'c');
  assert.equal(d.alt.url, BASE + 'decreto-lei/H.htm');
  const sem = N.escolherDestino({ ...REG, c: undefined }, null, null, [], cfg);
  assert.equal(sem.url, BASE + 'decreto-lei/H.htm');
  assert.equal(sem.alt, null);
});

test('escolherDestino: nível mais fundo vale mais que a versão', () => {
  const d = N.escolherDestino(REG, ANC, { parte: 'corpo', comps: ['10', '§1'] }, [], cfg);
  assert.equal(d.url, BASE + 'decreto-lei/H.htm#h10p1');
  assert.equal(d.profundidade, 2);
  assert.equal(d.alt.url, BASE + 'decreto-lei/C.htm#c10');
  const d2 = N.escolherDestino(REG, ANC, { parte: 'corpo', comps: ['10', '§2'] }, [], cfg);
  assert.equal(d2.url, BASE + 'decreto-lei/C.htm#c10');
  assert.match(d2.nota, /§ 2º não tem âncora própria; abrindo no art\. 10\./);
  const d3 = N.escolherDestino(REG, ANC, { parte: 'corpo', comps: ['20'] }, [], cfg);
  assert.equal(d3.url, BASE + 'decreto-lei/H.htm#h20');
  assert.equal(d3.alt.url, BASE + 'decreto-lei/C.htm');
  const d4 = N.escolherDestino(REG, ANC, { parte: 'corpo', comps: ['77'] }, [], cfg);
  assert.equal(d4.url, BASE + 'decreto-lei/C.htm');
  assert.equal(d4.fragmento, null);
  assert.equal(d4.dica, 'Art. 77');
  const d5 = N.escolherDestino(REG, ANC, { parte: 'adct', comps: ['5'] }, [], cfg);
  assert.equal(d5.dica, 'Art. 5 do ADCT');
});

test('escolherDestino: aviso com ir_para (§8.3), comparação exata', () => {
  const avisos = [{ id: 'x', alvo: { k: 'dl-9999-1943', parte: 'corpo', disp: '8|pu' }, estado: 'atencao', texto: 't', fonte: 'f', ir_para: '8|§1' }];
  const d = N.escolherDestino(REG, ANC, { parte: 'corpo', comps: ['8', 'pu'] }, avisos, cfg);
  assert.equal(d.url, BASE + 'decreto-lei/C.htm#c8%C2%A71');
  const semAviso = N.escolherDestino(REG, ANC, { parte: 'corpo', comps: ['8', 'pu'] }, [], cfg);
  assert.equal(semAviso.url, BASE + 'decreto-lei/C.htm#c8');
  assert.match(semAviso.nota, /parágrafo único não tem âncora própria/);
  const outro = N.escolherDestino(REG, ANC, { parte: 'corpo', comps: ['8', 'pu', 'I'] }, avisos, cfg);
  assert.equal(outro.url, BASE + 'decreto-lei/C.htm#c8');
});

test('rotaParaConsulta (§10.5)', () => {
  const S = '/planalto-direto/';
  assert.equal(N.rotaParaConsulta('/planalto-direto/clt/477', S), 'clt 477');
  assert.equal(N.rotaParaConsulta('/planalto-direto/lei/8036/3', S), 'lei 8036 art 3');
  assert.equal(N.rotaParaConsulta('/planalto-direto/lei/8036-1990/3', S), 'lei 8036/1990 art 3');
  assert.equal(N.rotaParaConsulta('/planalto-direto/cf/adct/76', S), 'cf adct 76');
  assert.equal(N.rotaParaConsulta('/planalto-direto/Del5452', S), 'Del5452');
  assert.equal(N.rotaParaConsulta('/planalto-direto/clt/477/%C2%A72', S), 'clt 477 §2');
  assert.equal(N.rotaParaConsulta('/planalto-direto/x/%E0%A4%A', S), 'x %E0%A4%A');
  assert.equal(N.rotaParaConsulta('/planalto-direto/', S), null);
  assert.equal(N.rotaParaConsulta('/planalto-direto/index.html', S), null);
  assert.equal(N.rotaParaConsulta('/outro/clt/477', S), null);
});

// Fonte sintética mínima para a resolução.
function fonteSintetica() {
  const shards = {
    'n-lei-00': [
      { a: 1949, e: 'Repouso semanal sintético.', k: 'lei-605-1949', l: '', n: 605, u: 'leis/L0605.htm' },
      { a: 1990, e: 'Ementa sintética de teste.', k: 'lei-777-1990', l: '', n: 777, u: 'leis/l777.htm' },
      { a: 1991, e: 'Outra ementa.', k: 'lei-777a-1991', l: 'a', n: 777, u: 'leis/l777a.htm' }
    ],
    'n-dl-00': [{ a: 1969, e: 'Decreto-lei sintético.', k: 'dl-605-1969', l: '', n: 605, u: 'Decreto-Lei/Del0605.htm' }],
    'n-mp-00': [{ a: 2013, e: 'Medida sintética.', k: 'mp-605-2013', l: '', n: 605, u: 'mpv/mpv605.htm' }]
  };
  const man = { normas: 5, shards: Object.fromEntries(Object.entries(shards).map(([k, v]) => [k, { qtd: v.length, sha: 'x' }])) };
  return {
    manifesto: async () => man, shard: async (n) => shards[n], ancorasIndice: async () => [], ancoras: async () => null,
    apelidos: async () => ({ ...AP, desempate: { 'num:605': 'dl-605-1969' } }), avisos: async () => []
  };
}

test('resolver: TIPO+NUM exato com outras; número solto sempre lista; desempate', async () => {
  const f = fonteSintetica();
  let R = await N.resolver('lei 605', f, cfg);
  assert.equal(R.tipo, 'exato');
  assert.deepEqual(R.refs[0].outras, ['dl-605-1969', 'mp-605-2013']);
  R = await N.resolver('605', f, cfg);
  assert.equal(R.tipo, 'lista');
  assert.deepEqual(R.itens.map((i) => i.k), ['dl-605-1969', 'lei-605-1949', 'mp-605-2013']);
  R = await N.resolver('777', f, cfg);
  assert.equal(R.tipo, 'lista');
  assert.equal(R.itens[0].k, 'lei-777-1990');
  R = await N.resolver('lei 777', f, cfg);
  assert.equal(R.tipo, 'exato');
  assert.deepEqual(R.refs[0].outras, ['lei-777a-1991']);
  R = await N.resolver('lei 777-A', f, cfg);
  assert.equal(R.refs[0].k, 'lei-777a-1991');
  R = await N.resolver('lei 605/1950', f, cfg);
  assert.equal(R.tipo, 'nada');
  assert.match(R.mensagem, /Sem Lei nº 605 de 1950\. Há: Lei nº 605\/1949/);
  R = await N.resolver('decreto 605', f, cfg);
  assert.equal(R.tipo, 'fora_escopo');
  R = await N.resolver('lei 999', f, cfg);
  assert.equal(R.tipo, 'nada');
  R = await N.resolver('https://www.planalto.gov.br/ccivil_03/Leis/L0605.htm', f, cfg);
  assert.equal(R.tipo, 'exato');
  assert.equal(R.refs[0].destino.url, BASE + 'leis/L0605.htm');
});

test('buscarTexto: sem assuntos, a Lei 12.506 entre os 3 primeiros (dados de teste)', async () => {
  const dir = escolherDados();
  const f = fonteDisco(dir);
  const man = await f.manifesto();
  const regs = [];
  for (const n of Object.keys(man.shards)) regs.push(...(await f.shard(n)));
  if (!regs.some((r) => r.k === 'lei-12506-2011')) return;
  const ap = await f.apelidos();
  const semAssuntos = N.prepararApelidos({ ...ap, assuntos: [] });
  const itens = N.buscarTexto('aviso prévio proporcional', regs, semAssuntos, cfg);
  assert.ok(itens.slice(0, 3).some((i) => i.k === 'lei-12506-2011'), itens.slice(0, 5).map((i) => i.k).join(' '));
  const comAssuntos = N.buscarTexto('aviso prévio proporcional', regs, N.prepararApelidos(ap), cfg);
  assert.equal(comAssuntos[0].k, 'lei-12506-2011');
  assert.ok(comAssuntos.length <= 20);
});
