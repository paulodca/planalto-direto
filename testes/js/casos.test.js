// J1: os casos de testes/casos.json contra o nucleo.js e os dados (docs/dados real; senão a fixture dados_min).
// Na fixture, um caso cuja chave esperada não está nos dados é pulado (com o motivo); nos dados reais, nunca.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  Nucleo, carregarCasos, idsFaltando, escolherDados, fonteDisco, infoDados, expectativa, chavesDoCaso,
  conferir, observarResultado, lerConfig
} from './casos_comum.mjs';

const cfg = lerConfig();
const dir = escolherDados();
const info = await infoDados(dir);
const fonte = fonteDisco(dir);
const casos = carregarCasos();

test(`casos.json tem todos os IDs obrigatórios (dados: ${info.real ? 'base real' : 'fixture'}, ${info.man.normas} normas)`, () => {
  assert.deepEqual(idsFaltando(casos), []);
});

for (const caso of casos) {
  const nome = `caso ${caso.id}: ${caso.consulta ?? caso.rota}`;
  if (caso.na) { test(nome, { skip: 'N/A: ' + caso.na }, () => {}); continue; }
  if (caso.so === 'navegador' && !caso.rota) { test(nome, { skip: 'só no navegador' }, () => {}); continue; }
  const e = expectativa(caso, info);
  const faltam = chavesDoCaso(e).filter((k) => !info.chaves.has(k));
  if (faltam.length && !info.real) { test(nome, { skip: 'fora da fixture: ' + faltam.join(', ') }, () => {}); continue; }
  test(nome, async () => {
    const consulta = caso.rota ? Nucleo.rotaParaConsulta(caso.rota, cfg.SITE_PATH) : caso.consulta;
    assert.ok(consulta, 'rota sem consulta');
    const R = await Nucleo.resolver(consulta, fonte, cfg);
    const erros = conferir(e, observarResultado(R), cfg.PLANALTO_BASE);
    if (e.ementa_nao_contem) {
      const k = R.refs && R.refs[0] && R.refs[0].k;
      const man = await fonte.manifesto();
      let ementa = null;
      for (const n of Object.keys(man.shards)) for (const r of await fonte.shard(n)) if (r.k === k) ementa = r.e || '';
      if (ementa === null) erros.push('registro não achado');
      else if (ementa.toLowerCase().includes(e.ementa_nao_contem)) erros.push(`ementa contém "${e.ementa_nao_contem}"`);
    }
    if (e.sem_marcas) {
      const an = Nucleo.analisar(consulta, Nucleo.prepararApelidos(await fonte.apelidos()));
      if (an.tokens.some((t) => t === 'ART' || t === 'INC')) erros.push(`marcas espúrias: ${an.tokens}`);
    }
    assert.deepEqual(erros, []);
  });
}

// Ramo "sem aviso" (§14.2): os casos com se_aviso, resolvidos como se o aviso não estivesse publicado.
for (const caso of casos.filter((c) => c.se_aviso && !c.na)) {
  const e = expectativa(caso, { ...info, avisosPublicados: new Set() });
  const faltam = chavesDoCaso(e).filter((k) => !info.chaves.has(k));
  test(`caso ${caso.id} sem o aviso ${caso.se_aviso}`, { skip: faltam.length && !info.real ? 'fora da fixture' : false }, async () => {
    const semAviso = { ...fonte, avisos: async () => (await fonte.avisos()).filter((a) => a.id !== caso.se_aviso) };
    const R = await Nucleo.resolver(caso.consulta, semAviso, cfg);
    assert.deepEqual(conferir(e, observarResultado(R), cfg.PLANALTO_BASE), []);
  });
}
