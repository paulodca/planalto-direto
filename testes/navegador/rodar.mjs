#!/usr/bin/env node
// Checagens no navegador headless (Chrome ou Edge) via CDP, sem dependências (SPEC §14.3 e §14.4.1).
//   --casos (a) · --rodape --subcaminho (c) · --celular --home --rede (f) · --ancoras-cache (b, com --cache-html e --amostra)
// Opções: --raiz DIR (padrão docs/) · --navegador CAMINHO | PD_NAVEGADOR · --cache-html DIR | PD_CACHE_HTML
//         --amostra ARQ · --json ARQ · --so ID[,ID…] (filtra casos) · --verboso
// Saída: 0 PASS · 1 FAIL · 77 SKIP (última linha "SKIP: razão") · 2 erro de uso.
// Rede: todo pedido que não seja a 127.0.0.1 é abortado (Fetch.failRequest); a navegação para o Planalto é
// registrada com o fragmento (request.url + request.urlFragment). Nenhum pedido sai da máquina.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import {
  carregarCasos, idsFaltando, expectativa, infoDados, conferir, lerConfig, chavesDoCaso, RAIZ
} from '../js/casos_comum.mjs';

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const PLANALTO_HOST = 'www.planalto.gov.br';
const HOSTS_EXTERNOS_LINK = ['www.planalto.gov.br', 'docs.google.com', 'github.com'];
const RODAPE = 'Ferramenta não oficial, sem vínculo com a Presidência da República. Sempre confira na fonte.';
const espera = (ms) => new Promise((ok) => setTimeout(ok, ms));

/* ------------------------------------------------------------------ argumentos */

function lerArgs(argv) {
  const o = { checks: new Set(), raiz: path.join(RAIZ, 'docs'), navegador: process.env.PD_NAVEGADOR || '',
    cache: process.env.PD_CACHE_HTML || '', amostra: '', json: '', so: null, verboso: false };
  const CHECKS = ['casos', 'rodape', 'subcaminho', 'celular', 'home', 'rede', 'ancoras-cache'];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--') && CHECKS.includes(a.slice(2))) o.checks.add(a.slice(2));
    else if (a === '--tudo') CHECKS.filter((c) => c !== 'ancoras-cache').forEach((c) => o.checks.add(c));
    else if (a === '--raiz') o.raiz = path.resolve(argv[++i]);
    else if (a === '--navegador') o.navegador = argv[++i];
    else if (a === '--cache-html') o.cache = argv[++i];
    else if (a === '--amostra') o.amostra = path.resolve(argv[++i]);
    else if (a === '--json') o.json = path.resolve(argv[++i]);
    else if (a === '--so') o.so = new Set(argv[++i].split(','));
    else if (a === '--verboso') o.verboso = true;
    else if (a === '-h' || a === '--help') {
      console.log('uso: node testes/navegador/rodar.mjs [--casos] [--rodape] [--subcaminho] [--celular] [--home] [--rede] [--tudo]\n' +
        '       [--ancoras-cache --cache-html DIR --amostra ARQ] [--raiz DIR] [--navegador CAMINHO] [--json ARQ] [--so IDS]');
      process.exit(0);
    } else { console.error('argumento desconhecido: ' + a); process.exit(2); }
  }
  if (!o.checks.size) { console.error('nenhuma checagem pedida (use --casos, --rodape, ... ou --tudo)'); process.exit(2); }
  return o;
}

/* ------------------------------------------------------------------ navegador */

function candidatosNavegador() {
  const c = [];
  if (process.platform === 'win32') {
    const bases = [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA].filter(Boolean);
    for (const b of bases) c.push(path.join(b, 'Google', 'Chrome', 'Application', 'chrome.exe'));
    for (const b of bases) c.push(path.join(b, 'Microsoft', 'Edge', 'Application', 'msedge.exe'));
  } else if (process.platform === 'darwin') {
    c.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge');
  } else {
    c.push('/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge');
  }
  return c;
}

function acharNavegador(pedido) {
  if (pedido) return fs.existsSync(pedido) ? pedido : null;
  return candidatosNavegador().find((p) => fs.existsSync(p)) || null;
}

class CDP {
  constructor(ws) {
    this.ws = ws; this.n = 0; this.pend = new Map(); this.ouvintes = new Set();
    ws.addEventListener('message', (ev) => {
      const m = JSON.parse(typeof ev.data === 'string' ? ev.data : Buffer.from(ev.data).toString());
      if (m.id && this.pend.has(m.id)) {
        const { ok, falha, metodo } = this.pend.get(m.id); this.pend.delete(m.id);
        if (m.error) falha(new Error(metodo + ': ' + m.error.message)); else ok(m.result);
      } else if (m.method) {
        for (const f of this.ouvintes) { try { f(m.method, m.params || {}, m.sessionId); } catch (e) { console.error(e); } }
      }
    });
  }
  static async conectar(url) {
    const ws = new WebSocket(url);
    await new Promise((ok, falha) => { ws.addEventListener('open', ok, { once: true }); ws.addEventListener('error', falha, { once: true }); });
    return new CDP(ws);
  }
  enviar(metodo, params = {}, sessionId) {
    const id = ++this.n;
    const msg = { id, method: metodo, params };
    if (sessionId) msg.sessionId = sessionId;
    this.ws.send(JSON.stringify(msg));
    return new Promise((ok, falha) => this.pend.set(id, { ok, falha, metodo }));
  }
  ao(f) { this.ouvintes.add(f); return () => this.ouvintes.delete(f); }
  fechar() { try { this.ws.close(); } catch (e) { /* nada */ } }
}

async function lancarNavegador(exe) {
  const perfil = fs.mkdtempSync(path.join(os.tmpdir(), 'pd-perfil-'));
  const args = ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${perfil}`, '--no-first-run',
    '--disable-extensions', '--disable-background-networking', '--disable-component-update', '--disable-sync',
    '--no-default-browser-check', '--disable-default-apps', '--disable-features=Translate,OptimizationHints,MediaRouter',
    '--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1', 'about:blank'];
  const proc = spawn(exe, args, { stdio: 'ignore' });
  const arq = path.join(perfil, 'DevToolsActivePort');
  let linhas = null;
  for (let i = 0; i < 200 && !linhas; i++) {
    await espera(100);
    if (fs.existsSync(arq)) { const t = fs.readFileSync(arq, 'utf8').trim().split(/\r?\n/); if (t.length >= 2) linhas = t; }
  }
  if (!linhas) { proc.kill(); throw new Error('o navegador não abriu a porta de depuração'); }
  const cdp = await CDP.conectar(`ws://127.0.0.1:${linhas[0]}${linhas[1]}`);
  return {
    cdp, proc,
    async fechar() {
      try { await Promise.race([cdp.enviar('Browser.close'), espera(3000)]); } catch (e) { /* nada */ }
      cdp.fechar(); try { proc.kill(); } catch (e) { /* nada */ }
      for (let i = 0; i < 10; i++) { try { fs.rmSync(perfil, { recursive: true, force: true }); break; } catch (e) { await espera(300); } }
    }
  };
}

/* ------------------------------------------------------------------ servidor */

async function subirServidor(args) {
  const py = process.env.PD_PYTHON || 'python';
  const proc = spawn(py, ['-P', '-B', path.join(RAIZ, 'testes', 'servidor.py'), ...args], { stdio: ['ignore', 'pipe', 'inherit'] });
  const porta = await new Promise((ok, falha) => {
    let buf = '';
    proc.stdout.on('data', (d) => { buf += d; const m = /^(\d+)\s*$/m.exec(buf); if (m) ok(+m[1]); });
    proc.on('exit', (c) => falha(new Error('servidor saiu com ' + c)));
    setTimeout(() => falha(new Error('servidor não respondeu')), 15000);
  });
  return { porta, fechar: () => { try { proc.kill(); } catch (e) { /* nada */ } } };
}

/* ------------------------------------------------------------------ página (aba) */

class Aba {
  constructor(nav, sessao, alvo) {
    this.cdp = nav.cdp; this.s = sessao; this.alvo = alvo;
    this.externos = []; this.planalto = []; this.servirPlanalto = null; this.semCharset = false;
    this.rede = new Map(); this.contarRede = false;
    this.cdp.ao((m, p, sid) => {
      if (sid !== this.s) return;
      if (m === 'Fetch.requestPaused') this.pausado(p);
      else if (this.contarRede && m === 'Network.requestWillBeSent') this.rede.set(p.requestId, { url: p.request.url, tipo: p.type, bytes: 0 });
      else if (this.contarRede && m === 'Network.dataReceived') { const r = this.rede.get(p.requestId); if (r) r.bytes += p.dataLength; }
      else if (this.contarRede && m === 'Network.responseReceived') { const r = this.rede.get(p.requestId); if (r) r.tipo = p.type; }
    });
  }
  static async abrir(nav) {
    const { targetId } = await nav.cdp.enviar('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await nav.cdp.enviar('Target.attachToTarget', { targetId, flatten: true });
    const aba = new Aba(nav, sessionId, targetId);
    await aba.env('Page.enable');
    await aba.env('Runtime.enable');
    await aba.env('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
    return aba;
  }
  env(m, p) { return this.cdp.enviar(m, p || {}, this.s); }
  async pausado(p) {
    const req = p.request;
    let u;
    try { u = new URL(req.url); } catch (e) { u = null; }
    if (!u || u.hostname === '127.0.0.1' || u.protocol === 'data:') {
      return this.env('Fetch.continueRequest', { requestId: p.requestId }).catch(() => {});
    }
    const completa = req.url + (req.urlFragment || '');
    this.externos.push({ url: completa, host: u.hostname, tipo: p.resourceType, t: Date.now() });
    if (u.hostname === PLANALTO_HOST && p.resourceType === 'Document') {
      this.planalto.push({ url: completa, t: Date.now() });
      if (this.servirPlanalto) {
        const r = this.servirPlanalto(u);
        if (r) return this.env('Fetch.fulfillRequest', { requestId: p.requestId, ...r }).catch(() => {});
      }
    }
    return this.env('Fetch.failRequest', { requestId: p.requestId, errorReason: 'BlockedByClient' }).catch(() => {});
  }
  async avaliar(expr) {
    const r = await this.env('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error('avaliação falhou: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
    return r.result.value;
  }
  async ir(url) { this.planalto = []; await this.env('Page.navigate', { url }); }
  async aguardar(expr, ms = 15000, passo = 100) {
    const fim = Date.now() + ms;
    while (Date.now() < fim) {
      try { const v = await this.avaliar(expr); if (v) return v; } catch (e) { /* navegação em curso */ }
      await espera(passo);
    }
    return null;
  }
  async fechar() { try { await this.cdp.enviar('Target.closeTarget', { targetId: this.alvo }); } catch (e) { /* nada */ } }
}

const EXPR_PRONTO = `(() => { const r = document.querySelector('#resultado');
  return !!r && r.getAttribute('data-estado') === 'pronto' && document.body.classList.contains('pg-home'); })()`;
const EXPR_LER = `(() => { const r = document.querySelector('#resultado'); const g = (a) => r.getAttribute(a) || '';
  const ab = r.querySelector('.abrindo');
  return { tipo: g('data-tipo'), url: g('data-url'), alt: g('data-alt'), refs: g('data-refs'), k: g('data-k'),
    itens: g('data-itens'), avisos: g('data-avisos'), outras: g('data-outras'), mensagem: g('data-mensagem'),
    transicao: ab ? ab.textContent : '', texto: r.textContent, sugestao: !!r.querySelector('.sugestao a[href]'),
    href: location.href }; })()`;

function observarDom(d) {
  const sp = (s) => (s ? s.split(' ').filter(Boolean) : []);
  const urls = sp(d.refs), ks = sp(d.k);
  return {
    tipo: d.tipo, url: d.url, alt: d.alt || undefined, refs: urls.map((u, i) => ({ k: ks[i], url: u })), ks,
    itens: sp(d.itens), avisos: sp(d.avisos), mensagem: d.mensagem, transicao: d.transicao, notas: d.texto,
    outras: sp(d.outras), nome: d.texto, texto: d.texto
  };
}

/* ------------------------------------------------------------------ checagens */

async function checarCasos(ctx) {
  const { aba, site, cfg, info } = ctx;
  const itens = [];
  const casos = carregarCasos();
  const faltam = idsFaltando(casos);
  if (faltam.length) itens.push({ id: 'ids', ok: false, detalhe: 'IDs faltando: ' + faltam.join(', ') });
  const esperaMs = +cfg.ESPERA_MS || 1200, esperaDica = +cfg.ESPERA_DICA_MS || 3000;
  for (const caso of casos) {
    if (ctx.o.so && !ctx.o.so.has(caso.id) && !ctx.o.so.has(String(caso.id).split('.')[0])) continue;
    if (caso.na || caso.so === 'js') { itens.push({ id: caso.id, ok: true, na: caso.na || 'só J1' }); continue; }
    const e = expectativa(caso, info);
    const faltamK = chavesDoCaso(e).filter((k) => !info.chaves.has(k));
    if (faltamK.length && !info.real) { itens.push({ id: caso.id, ok: true, na: 'fora da fixture: ' + faltamK.join(', ') }); continue; }
    const alvo = caso.rota ? `http://127.0.0.1:${ctx.porta}${caso.rota}` : `${site}?q=${encodeURIComponent(caso.consulta)}`;
    const t0 = Date.now();
    await aba.ir(alvo);
    const pronto = await aba.aguardar(EXPR_PRONTO, 20000);
    if (!pronto) { itens.push({ id: caso.id, ok: false, detalhe: 'resultado não ficou pronto' }); continue; }
    const tPronto = Date.now();
    const d = await aba.avaliar(EXPR_LER);
    const erros = conferir(e, observarDom(d), cfg.PLANALTO_BASE);
    if (e.sugestao && !d.sugestao) erros.push('bloco de sugestão ausente');
    if (d.tipo === 'exato') {
      const lim = (d.texto.includes('Ctrl+F') ? esperaDica : esperaMs) + 3000;
      const fim = Date.now() + lim;
      while (Date.now() < fim && !aba.planalto.length) await espera(50);
      const nav = aba.planalto[0];
      if (!nav) erros.push('não navegou para o Planalto');
      else {
        if (nav.url !== d.url) erros.push(`navegou para ${nav.url} ≠ data-url ${d.url}`);
        if (nav.t - tPronto < Math.min(esperaMs, 1000) - 250) erros.push(`navegou cedo demais (${nav.t - tPronto} ms)`);
      }
    }
    if (e.pagina) {
      await aba.ir(`${site}${e.pagina}`);
      const ok = await aba.aguardar(`document.readyState === 'complete' && !!document.querySelector('main')`, 10000);
      if (!ok) erros.push('página da norma não carregou');
      else {
        if (e.pagina_contem && !(await aba.avaliar(`document.body.textContent.includes(${JSON.stringify(e.pagina_contem)})`))) erros.push(`página sem "${e.pagina_contem}"`);
        if (e.pagina_seletor && !(await aba.avaliar(`!!document.querySelector(${JSON.stringify(e.pagina_seletor)})`))) erros.push(`página sem ${e.pagina_seletor}`);
        if (await aba.avaliar(`new RegExp('revo' + 'gad', 'i').test(document.body.textContent.replace(document.querySelector('.ementa')?.textContent || '', ''))`)) erros.push('página com a raiz de status proibida (I4)');
      }
    }
    itens.push({ id: caso.id, ok: !erros.length, detalhe: erros.join('; '), ms: tPronto - t0 });
    if (ctx.o.verboso) console.log(`  ${erros.length ? 'FAIL' : 'ok  '} ${caso.id} ${erros.join('; ')}`);
  }
  // "Estou com pressa": navega na hora
  await aba.ir(`${site}?q=${encodeURIComponent('clt 477')}&pressa=1`);
  await aba.aguardar(EXPR_PRONTO, 15000);
  const tP = Date.now();
  while (Date.now() < tP + 1500 && !aba.planalto.length) await espera(25);
  const pressaOk = aba.planalto.length && aba.planalto[0].t - tP < 600;
  itens.push({ id: 'pressa', ok: !!pressaOk, detalhe: pressaOk ? '' : 'não navegou imediatamente' });
  // guarda do "voltar": com ir=0 mostra a transição e não navega
  await aba.ir(`${site}?q=${encodeURIComponent('clt 477')}&ir=0`);
  await aba.aguardar(EXPR_PRONTO, 15000);
  await espera(esperaDica + 500);
  itens.push({ id: 'ir=0', ok: aba.planalto.length === 0, detalhe: aba.planalto.length ? 'navegou apesar de ir=0' : '' });
  // botão de submit com pressa, pelo formulário (pushState + navegação imediata)
  await aba.ir(site);
  await aba.aguardar(`document.readyState === 'complete'`);
  await aba.avaliar(`(() => { const q = document.getElementById('q'); q.value = 'lei 8036 art 3';
    q.dispatchEvent(new Event('input', {bubbles: true}));
    document.querySelector('form.busca').requestSubmit(document.querySelector('button[name=pressa]')); return 1; })()`);
  await aba.aguardar(EXPR_PRONTO, 15000);
  const tF = Date.now();
  while (Date.now() < tF + 1500 && !aba.planalto.length) await espera(25);
  const formOk = aba.planalto.length && aba.planalto[0].url.endsWith('leis/l8036consol.htm#art3.');
  itens.push({ id: 'formulario-pressa', ok: !!formOk, detalhe: formOk ? '' : 'envio pelo botão "Estou com pressa" não navegou para o caso 7' });
  // "Ir ao artigo" na página da norma (§9.7): leva à transição do caso 1
  await aba.ir(site + 'dl/5452-1943/');
  await aba.aguardar(`document.readyState === 'complete'`);
  const visivel = await aba.avaliar(`(() => { const f = document.querySelector('form.ir-artigo'); return !!f && !f.hidden; })()`);
  let irArt = '';
  if (visivel) {
    await aba.avaliar(`(() => { document.getElementById('art').value = '477'; document.querySelector('form.ir-artigo').requestSubmit(); return 1; })()`);
    if (await aba.aguardar(EXPR_PRONTO, 15000)) irArt = (await aba.avaliar(EXPR_LER)).url;
  }
  const esperadoArt = cfg.PLANALTO_BASE + 'decreto-lei/del5452compilado.htm#art477..';
  itens.push({ id: 'ir-ao-artigo', ok: visivel && irArt === esperadoArt,
    detalhe: !visivel ? 'formulário continua escondido' : irArt === esperadoArt ? '' : `data-url ${irArt || '(sem resultado)'}` });
  return itens;
}

const EXPR_RODAPE = `(() => { const f = document.querySelector('footer.rodape'); if (!f) return {ok:false, motivo:'sem footer.rodape'};
  const cs = getComputedStyle(f), r = f.getBoundingClientRect();
  const H = document.documentElement;
  return { ok: true, texto: f.textContent.trim(), filhos: f.children.length, altura: r.height, display: cs.display,
    visibility: cs.visibility, opacity: cs.opacity, fonte: parseFloat(cs.fontSize), clip: cs.clip, position: cs.position,
    dentro: r.top >= -1 && r.bottom <= Math.max(H.scrollHeight, H.clientHeight) + 1 && r.left >= -1 }; })()`;

async function checarRodape(ctx) {
  const { aba, site, porta } = ctx;
  const itens = [];
  const paginas = [['home', site], ['norma', site + 'dl/5452-1943/'], ['404', `http://127.0.0.1:${porta}/planalto-direto/nao-existe-xyz`],
    ['transicao', `${site}?q=${encodeURIComponent('clt 477')}&ir=0`]];
  for (const [nome, url] of paginas) {
    // a 404 com JS ligado vira busca (rota curta); o rodapé é conferido na página 404 estática
    if (nome === '404') await aba.env('Emulation.setScriptExecutionDisabled', { value: true });
    await aba.ir(url);
    await aba.aguardar(`document.readyState === 'complete'`, 10000);
    if (nome === 'transicao') await aba.aguardar(EXPR_PRONTO, 15000);
    const r = await aba.avaliar(EXPR_RODAPE);
    const erros = [];
    if (!r.ok) erros.push(r.motivo);
    else {
      if (r.texto !== RODAPE) erros.push('texto diferente: ' + r.texto);
      if (r.filhos) erros.push('rodapé com marcação interna');
      if (!(r.altura > 0)) erros.push('altura 0');
      if (r.display === 'none' || r.visibility !== 'visible' || r.opacity !== '1') erros.push(`invisível (${r.display}/${r.visibility}/${r.opacity})`);
      if (r.fonte < 14) erros.push('fonte < 14px');
      if (r.position !== 'static') erros.push('position ' + r.position);
      if (!r.dentro) erros.push('fora do documento');
    }
    if (nome === '404') {
      if (!(await aba.avaliar(`document.body.classList.contains('pg-404')`))) erros.push('não é a página 404');
      await aba.env('Emulation.setScriptExecutionDisabled', { value: false });
    }
    itens.push({ id: 'rodape:' + nome, ok: !erros.length, detalhe: erros.join('; ') });
  }
  // contraste WCAG (texto ≥ 4,5:1) em cada par cor/fundo usado, nos temas claro e escuro (§11)
  const paginasContraste = [['home', site], ['norma', site + 'dl/5452-1943/'], ['transicao', `${site}?q=${encodeURIComponent('clt 9999')}&ir=0`],
    ['lista', `${site}?q=${encodeURIComponent('5452')}&ir=0`], ['texto', `${site}?q=${encodeURIComponent('aviso prévio proporcional')}&ir=0`],
    ['avisos', `${site}?q=${encodeURIComponent('art. 790-B da CLT')}&ir=0`]];
  for (const tema of ['light', 'dark']) {
    await aba.env('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: tema }] });
    for (const [nome, url] of paginasContraste) {
      await aba.ir(url);
      await aba.aguardar(`document.readyState === 'complete'`, 10000);
      if (url.includes('?q=')) await aba.aguardar(EXPR_PRONTO, 20000);
      const r = await aba.avaliar(EXPR_CONTRASTE);
      const ruins = r.pares.filter((p) => p.razao < 4.5);
      itens.push({ id: `contraste:${tema}:${nome}`, ok: !ruins.length && r.pares.length > 0,
        detalhe: ruins.length ? ruins.slice(0, 5).map((p) => `${p.onde} ${p.cor}/${p.fundo} ${p.razao.toFixed(2)}`).join('; ')
          : `${r.pares.length} pares, mínimo ${r.min.toFixed(2)}:1` });
    }
  }
  await aba.env('Emulation.setEmulatedMedia', { features: [] });
  return itens;
}

const EXPR_CONTRASTE = `(() => {
  const rgba = (s) => { const m = /rgba?\\(([^)]+)\\)/.exec(s); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
  const fundo = (el) => { for (let e = el; e; e = e.parentElement) { const b = rgba(getComputedStyle(e).backgroundColor); if (b && b[3] > 0.5) return b; }
    const h = rgba(getComputedStyle(document.documentElement).backgroundColor); return h && h[3] > 0.5 ? h : [255, 255, 255, 1]; };
  const pares = new Map();
  for (const el of document.querySelectorAll('body *')) {
    if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName) || el.closest('.sr')) continue;
    const temTexto = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!temTexto) continue;
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (cs.visibility !== 'visible' || cs.display === 'none' || !r.width || !r.height || el.disabled) continue;
    const c = rgba(cs.color), b = fundo(el);
    if (!c) continue;
    const l1 = lum(c), l2 = lum(b), razao = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const chave = cs.color + '|' + b.join(',');
    if (!pares.has(chave) || pares.get(chave).razao > razao)
      pares.set(chave, { cor: cs.color, fundo: 'rgb(' + b.slice(0, 3).join(',') + ')', razao, onde: el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).split(' ')[0] : '') });
  }
  const lista = [...pares.values()];
  return { pares: lista, min: Math.min(...lista.map((p) => p.razao)) }; })()`;

const EXPR_LINKS = `(() => Array.from(document.querySelectorAll('[href],[src],[action]')).map((e) => {
  const bruto = e.getAttribute('href') ?? e.getAttribute('src') ?? e.getAttribute('action');
  let abs = null; try { abs = new URL(bruto, location.href).href; } catch (x) {}
  return { tag: e.tagName.toLowerCase(), bruto, abs }; }))()`;

async function checarSubcaminho(ctx) {
  const { aba, site, porta, cfg } = ctx;
  const origem = `http://127.0.0.1:${porta}`;
  const itens = [];
  await aba.env('Emulation.setScriptExecutionDisabled', { value: true });
  const paginas = [['home', site], ['dl', site + 'dl/5452-1943/'], ['cf', site + 'cf/1988/'], ['404', `${origem}/planalto-direto/a/b/c/nao-existe`]];
  const vistos = new Map();
  try {
    for (const [nome, url] of paginas) {
      await aba.ir(url);
      await aba.aguardar(`document.readyState === 'complete'`, 10000);
      const links = await aba.avaliar(EXPR_LINKS);
      const erros = [];
      for (const l of links) {
        if (!l.abs) { erros.push('URL inválida: ' + l.bruto); continue; }
        const u = new URL(l.abs);
        if (u.protocol === 'mailto:') continue;
        if (cfg.SITE_URL && l.abs.startsWith(cfg.SITE_URL)) {
          // canonical/og:url absolutos: valem se a mesma rota existe no site de teste
          l.abs = site + l.abs.slice(cfg.SITE_URL.length);
        } else if (u.origin !== origem) {
          if (!HOSTS_EXTERNOS_LINK.includes(u.hostname)) erros.push(`link externo não permitido: ${l.abs}`);
          continue;
        }
        if (!l.abs.startsWith(origem + '/planalto-direto/')) { erros.push(`fora do subcaminho: ${l.bruto}`); continue; }
        const semHash = l.abs.split('#')[0];
        if (!vistos.has(semHash)) {
          const r = await fetch(semHash, { method: 'GET', redirect: 'manual' });
          vistos.set(semHash, r.status);
        }
        const st = vistos.get(semHash);
        if (st !== 200) erros.push(`${l.bruto} → ${st}`);
      }
      if (nome === '404') {
        const f = await aba.avaliar(`(() => { const f = document.querySelector('form.busca') || document.querySelector('form');
          return f ? { action: f.action, metodo: (f.method || 'get').toLowerCase(), campo: !!f.querySelector('input[name=q]') } : null; })()`);
        if (!f || f.action !== origem + '/planalto-direto/' || f.metodo !== 'get' || !f.campo) erros.push('formulário do 404 não leva à home com ?q=');
      }
      itens.push({ id: 'subcaminho:' + nome, ok: !erros.length, detalhe: erros.slice(0, 10).join('; '), links: links.length });
    }
  } finally {
    await aba.env('Emulation.setScriptExecutionDisabled', { value: false });
  }
  // o formulário do 404 chega à home e a busca roda
  await aba.ir(`${origem}/planalto-direto/a/b/c/nao-existe`);
  await aba.aguardar(EXPR_PRONTO, 15000);
  const aposRota = await aba.avaliar(`location.pathname + location.search`);
  itens.push({ id: 'subcaminho:404-rota', ok: /^\/planalto-direto\/\?q=/.test(aposRota), detalhe: aposRota });
  // opensearch.xml
  const xml = await (await fetch(site + 'opensearch.xml')).text();
  const tpl = /template="([^"]+)"/.exec(xml)?.[1] || '';
  const img = /<Image[^>]*>([^<]+)<\/Image>/.exec(xml)?.[1] || '';
  const okXml = tpl === cfg.SITE_URL + '?q={searchTerms}' && img.startsWith(cfg.SITE_URL);
  itens.push({ id: 'subcaminho:opensearch', ok: okXml, detalhe: okXml ? '' : `template=${tpl} image=${img}` });
  return itens;
}

async function checarCelular(ctx) {
  const { aba, site } = ctx;
  const itens = [];
  await aba.env('Emulation.setDeviceMetricsOverride', { width: 360, height: 740, deviceScaleFactor: 3, mobile: true });
  await aba.env('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 5 });
  try {
    for (const [nome, url] of [['home', site], ['norma', site + 'dl/5452-1943/'], ['transicao', `${site}?q=${encodeURIComponent('5452')}&ir=0`]]) {
      await aba.ir(url);
      await aba.aguardar(`document.readyState === 'complete'`, 10000);
      if (nome === 'transicao') await aba.aguardar(EXPR_PRONTO, 15000);
      await espera(200);
      const r = await aba.avaliar(`(() => { const q = document.getElementById('q');
        const bs = Array.from(document.querySelectorAll('button, .botao-grande')).filter((b) => b.offsetParent !== null)
          .map((b) => ({ t: b.textContent.trim(), h: b.getBoundingClientRect().height }));
        return { sw: document.documentElement.scrollWidth, fq: q ? parseFloat(getComputedStyle(q).fontSize) : 0, bs }; })()`);
      const erros = [];
      if (r.sw > 360) erros.push('rolagem horizontal: scrollWidth ' + r.sw);
      if (r.fq < 16) erros.push('fonte do #q < 16px: ' + r.fq);
      for (const b of r.bs) if (b.h < 44) erros.push(`botão "${b.t}" com ${b.h}px`);
      itens.push({ id: 'celular:' + nome, ok: !erros.length, detalhe: erros.join('; ') });
    }
  } finally {
    await aba.env('Emulation.clearDeviceMetricsOverride');
    await aba.env('Emulation.setTouchEmulationEnabled', { enabled: false });
  }
  return itens;
}

async function checarHome(ctx) {
  const { nav, site } = ctx;
  const itens = [];
  const aba = await Aba.abrir(nav);
  try {
    await aba.env('Network.enable');
    await aba.env('Network.setCacheDisabled', { cacheDisabled: true });
    aba.contarRede = true;
    const dados = () => [...aba.rede.values()].filter((r) => /\/dados\//.test(r.url));
    // carga fria
    aba.rede.clear();
    await aba.ir(site);
    await aba.aguardar(`document.readyState === 'complete'`, 10000);
    await espera(1000);
    await aba.avaliar(`document.getElementById('q').focus(), 1`);
    await espera(1000);
    const carga = [...aba.rede.values()];
    const bytes = carga.filter((r) => ['Document', 'Script', 'Stylesheet'].includes(r.tipo)).reduce((s, r) => s + r.bytes, 0);
    const proibidos = carga.filter((r) => /nucleo\.js|\/dados\//.test(r.url)).map((r) => r.url);
    itens.push({ id: 'home:orcamento', ok: bytes <= 80 * 1024, detalhe: `${(bytes / 1024).toFixed(1)} KB de HTML+CSS+JS` });
    itens.push({ id: 'home:sob-demanda', ok: !proibidos.length, detalhe: proibidos.join(' ') });
    // tempo de DOMContentLoaded (melhor de 3)
    let melhor = Infinity;
    for (let i = 0; i < 3; i++) {
      await aba.ir(site);
      await aba.aguardar(`document.readyState === 'complete'`, 10000);
      const t = await aba.avaliar(`performance.getEntriesByType('navigation')[0].domContentLoadedEventEnd`);
      melhor = Math.min(melhor, t);
    }
    itens.push({ id: 'home:dcl', ok: melhor < 500, detalhe: `${melhor.toFixed(0)} ms` });
    // consultas: pedidos a dados/
    for (const q of ['clt 477', 'mp 100']) {
      await aba.ir(site);
      await aba.aguardar(`document.readyState === 'complete'`, 10000);
      aba.rede.clear();
      await aba.avaliar(`document.getElementById('q').focus(), 1`);
      await aba.env('Input.insertText', { text: q });
      await aba.avaliar(`document.querySelector('form.busca').requestSubmit(), 1`);
      await aba.aguardar(EXPR_PRONTO, 20000);
      await espera(300);
      const ds = dados();
      const kb = ds.reduce((s, r) => s + r.bytes, 0) / 1024;
      itens.push({ id: `home:dados(${q})`, ok: ds.length <= 8 && kb <= 700, detalhe: `${ds.length} pedidos, ${kb.toFixed(0)} KB` });
    }
  } finally {
    aba.contarRede = false;
    await aba.fechar();
  }
  return itens;
}

async function checarRede(ctx) {
  const { aba, site, cfg, todasAbas } = ctx;
  const itens = [];
  await aba.env('Emulation.setScriptExecutionDisabled', { value: true });
  try {
    await aba.ir(site + 'dl/5452-1943/');
    await aba.aguardar(`document.readyState === 'complete'`, 10000);
    const href = await aba.avaliar(`document.querySelector('.botao-grande')?.getAttribute('href') || ''`);
    itens.push({ id: 'rede:sem-js', ok: href.startsWith(cfg.PLANALTO_BASE), detalhe: href });
  } finally {
    await aba.env('Emulation.setScriptExecutionDisabled', { value: false });
  }
  const externos = todasAbas.flatMap((a) => a.externos);
  const hosts = [...new Set(externos.map((x) => x.host))];
  const ruins = externos.filter((x) => x.host !== PLANALTO_HOST || x.tipo !== 'Document');
  itens.push({ id: 'rede:hosts', ok: !ruins.length, detalhe: `hosts externos pedidos: ${hosts.join(', ') || '(nenhum)'}` +
    (ruins.length ? '; indevidos: ' + ruins.slice(0, 5).map((x) => `${x.tipo} ${x.url}`).join(' ') : '') });
  return itens;
}

/* ---- (b) no Chrome: âncoras contra as páginas guardadas localmente (§14.4.1) */

const EXPR_ANCORA = `(() => { const raw = location.hash.slice(1); let d; try { d = decodeURIComponent(raw); } catch (e) { return {ok:false, motivo:'decode'}; }
  if (!raw) return { ok: scrollY === 0, semFragmento: true, scrollY, url: location.href, cs: document.characterSet };
  const el = document.getElementsByName(d)[0] || document.getElementById(d);
  if (!el) return {ok:false, motivo:'sem elemento', d, url: location.href, cs: document.characterSet};
  const r = el.getBoundingClientRect(), H = document.documentElement;
  const noFim = scrollY + innerHeight >= H.scrollHeight - 2;
  const alvo = document.querySelector(':target') === el;
  let riscado = false, txt = '';
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  w.currentNode = el;
  let n = el.firstChild && el.firstChild.nodeType === 3 && el.firstChild.textContent.trim() ? el.firstChild : null;
  while (!n) { const x = w.nextNode(); if (!x) break; if (x.textContent.trim()) n = x; }
  if (n) { txt = n.textContent.trim().slice(0, 12);
    for (let p = n.parentElement; p; p = p.parentElement) { if (getComputedStyle(p).textDecorationLine.includes('line-through')) { riscado = true; break; } } }
  return {ok: alvo || Math.abs(r.top) <= 4 || noFim, alvo, top: r.top, scrollY, url: location.href, riscado, cs: document.characterSet}; })()`;

function servirCache(dirCache, comCharset) {
  return (u) => {
    const prefixo = '/ccivil_03/';
    if (!u.pathname.startsWith(prefixo)) return null;
    const rel = decodeURIComponent(u.pathname.slice(prefixo.length));
    if (rel !== rel.toLowerCase()) {
      const destino = `${u.origin}${prefixo}${encodeURI(rel.toLowerCase())}${u.search}`;
      return { responseCode: 301, responseHeaders: [{ name: 'Location', value: destino }, { name: 'Content-Length', value: '0' }], body: '' };
    }
    const arq = path.join(dirCache, PLANALTO_HOST, 'ccivil_03', ...rel.split('/'));
    if (!fs.existsSync(arq)) return { responseCode: 404, responseHeaders: [{ name: 'Content-Type', value: 'text/plain' }], body: Buffer.from('404').toString('base64') };
    const dados = fs.readFileSync(arq);
    const m = /charset\s*=\s*["']?([\w-]+)/i.exec(dados.subarray(0, 4096).toString('latin1'));
    const utf8 = m && /^utf-?8$/i.test(m[1]);
    const tipo = comCharset ? `text/html; charset=${utf8 ? 'utf-8' : 'windows-1252'}` : 'text/html';
    return { responseCode: 200, responseHeaders: [{ name: 'Content-Type', value: tipo }], body: dados.toString('base64') };
  };
}

async function checarAncorasCache(ctx) {
  const { aba, site, o } = ctx;
  const itens = [];
  const amostra = JSON.parse(fs.readFileSync(o.amostra, 'utf8'));
  const links = Array.isArray(amostra) ? amostra : amostra.links || [];
  const testar = async (rotulo, urlSite, esperado, comCharset) => {
    aba.servirPlanalto = servirCache(o.cache, comCharset);
    await aba.ir(urlSite);
    const ok = await aba.aguardar(`location.hostname === '${PLANALTO_HOST}' && document.readyState === 'complete'`, 20000);
    if (!ok) return { id: rotulo, ok: false, detalhe: 'não chegou à página do Planalto' };
    await espera(300);
    const r = await aba.avaliar(EXPR_ANCORA);
    const erros = [];
    if (!r.ok) erros.push(r.motivo || `âncora fora da tela (top ${r.top})`);
    const frag = esperado.includes('#') ? '#' + esperado.split('#')[1] : '';
    if (frag && !r.url.endsWith(frag)) erros.push(`URL final ${r.url} sem ${frag}`);
    if (r.riscado) erros.push('texto seguinte riscado');
    return { id: rotulo, ok: !erros.length, detalhe: erros.join('; '), charset: r.cs };
  };
  try {
    // controle positivo (método válido com <a name> e §)
    const ctrl = ctx.cfg.PLANALTO_BASE + 'decreto-lei/del5452compilado.htm#art8%C2%A71';
    for (const cc of [true, false]) {
      const r = await testar(`controle${cc ? '' : ':sem-charset'}`, ctrl, ctrl, cc);
      itens.push(r);
      if (!r.ok && cc) { itens.push({ id: 'metodo', ok: false, detalhe: 'método inválido: o controle positivo falhou' }); return itens; }
    }
    for (const l of links) {
      if (l.na) { itens.push({ id: l.consulta, ok: true, na: l.na }); continue; }
      for (const cc of [true, false]) {
        const urlSite = `${site}?q=${encodeURIComponent(l.consulta)}&pressa=1`;
        const r = await testar(`${l.consulta}${cc ? '' : ' [sem charset]'}`, urlSite, l.url, cc);
        const nav = aba.planalto[0];
        if (nav && nav.url !== l.url) { r.ok = false; r.detalhe = [r.detalhe, `pediu ${nav.url} ≠ ${l.url}`].filter(Boolean).join('; '); }
        itens.push(r);
        if (o.verboso) console.log(`  ${r.ok ? 'ok  ' : 'FAIL'} ${r.id} ${r.detalhe || ''}`);
      }
    }
  } finally {
    aba.servirPlanalto = null;
  }
  return itens;
}

/* ------------------------------------------------------------------ principal */

function sair(estado, detalhe, itens, o) {
  const cod = { PASS: 0, FAIL: 1, SKIP: 77 }[estado];
  if (o && o.json) {
    fs.mkdirSync(path.dirname(o.json), { recursive: true });
    fs.writeFileSync(o.json, JSON.stringify({ id: 'navegador', estado, detalhe, itens }, null, 1) + '\n', 'utf8');
  }
  if (estado === 'SKIP') console.log('SKIP: ' + detalhe);
  else console.log(`${estado}: ${detalhe}`);
  process.exit(cod);
}

async function main() {
  const o = lerArgs(process.argv.slice(2));
  if (!fs.existsSync(path.join(o.raiz, 'index.html')) || !fs.existsSync(path.join(o.raiz, 'dados', 'manifesto.json'))) {
    sair('SKIP', 'site não gerado (falta index.html ou dados/manifesto.json em --raiz)', [], o);
  }
  if (o.checks.has('ancoras-cache')) {
    if (!o.cache || !fs.existsSync(path.join(o.cache, PLANALTO_HOST))) sair('SKIP', 'páginas do Planalto guardadas localmente não fornecidas (--cache-html ou PD_CACHE_HTML)', [], o);
    if (!o.amostra || !fs.existsSync(o.amostra)) sair('SKIP', 'amostra não fornecida (--amostra; gere com testes/links_amostra.mjs)', [], o);
  }
  const exe = acharNavegador(o.navegador);
  if (!exe) sair('SKIP', 'Chrome/Edge não encontrado (use --navegador ou PD_NAVEGADOR)', [], o);
  const cfg = lerConfig();
  const info = await infoDados(path.join(o.raiz, 'dados'));
  const srv = await subirServidor(['--raiz', o.raiz, '--prefixo', '/planalto-direto/', '--porta', '0']);
  const site = `http://127.0.0.1:${srv.porta}/planalto-direto/`;
  let nav = null;
  const itens = [];
  try {
    nav = await lancarNavegador(exe);
    const aba = await Aba.abrir(nav);
    const ctx = { o, nav, aba, site, porta: srv.porta, cfg, info, todasAbas: [aba] };
    const ordem = [['casos', checarCasos], ['rodape', checarRodape], ['subcaminho', checarSubcaminho], ['celular', checarCelular],
      ['home', checarHome], ['ancoras-cache', checarAncorasCache], ['rede', checarRede]];
    for (const [nome, f] of ordem) {
      if (!o.checks.has(nome)) continue;
      const t0 = Date.now();
      const r = await f(ctx);
      for (const it of r) itens.push({ checagem: nome, ...it });
      const falhas = r.filter((x) => !x.ok);
      console.log(`${falhas.length ? 'FAIL' : 'PASS'} ${nome}: ${r.length - falhas.length}/${r.length} ok (${((Date.now() - t0) / 1000).toFixed(1)} s)` +
        (r.some((x) => x.na) ? `, ${r.filter((x) => x.na).length} N/A` : ''));
      for (const x of falhas) console.log(`   ✗ ${x.id}: ${x.detalhe}`);
    }
    await aba.fechar();
  } finally {
    if (nav) await nav.fechar();
    srv.fechar();
  }
  const falhas = itens.filter((x) => !x.ok);
  const base = info.real ? 'base real' : 'fixture (pré-integração)';
  sair(falhas.length ? 'FAIL' : 'PASS', `${itens.length - falhas.length}/${itens.length} itens ok; dados: ${base}`, itens, o);
}

main().catch((e) => { console.error(e); console.log('FAIL: erro de execução: ' + e.message); process.exit(1); });
