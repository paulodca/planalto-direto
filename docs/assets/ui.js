/* Planalto Direto — interface: busca, transição, rotas curtas e "ir ao artigo".
 * Sem innerHTML com dado (tudo por createElement/textContent), sem estilo inline, sem terceiros.
 * Toda navegação para o Planalto passa por PD.ir; a navegação interna, por redirecionarRota.
 */
(function () {
  'use strict';

  var cfg = window.PD_CONFIG || {};
  var doc = document;
  var corpo = doc.body;
  var metaRaiz = doc.querySelector('meta[name="pd-raiz"]');
  var raiz = metaRaiz ? metaRaiz.getAttribute('content') || './' : './';
  var PD = window.PD = window.PD || {};

  /* ---------------------------------------------------------------- navegação */

  PD.ir = function (url) {
    if (typeof url === 'string' && cfg.PLANALTO_BASE && url.indexOf(cfg.PLANALTO_BASE) === 0) {
      location.assign(url);
      return true;
    }
    console.error('Planalto Direto: navegação recusada (fora do Planalto):', url);
    return false;
  };

  function redirecionarRota(destino, substituir) {
    var u;
    try { u = new URL(destino, location.href); } catch (e) { return false; }
    if (u.origin !== location.origin) { console.error('Planalto Direto: rota externa recusada:', destino); return false; }
    if (substituir) location.replace(u.href); else location.assign(u.href);
    return true;
  }

  function enc(s) { return encodeURIComponent(s); }

  function espera(chave, padrao) {
    var n = parseInt(cfg[chave], 10);
    return isNaN(n) || n < 0 ? padrao : n;
  }

  /* ---------------------------------------------------------------- dados */

  var memo = {};
  function obterJson(rel) {
    if (!memo[rel]) {
      memo[rel] = fetch(raiz + 'dados/' + rel, { credentials: 'same-origin' }).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status + ' em ' + rel);
        return r.json();
      }).catch(function (e) { delete memo[rel]; throw e; });
    }
    return memo[rel];
  }

  var fonte = {
    manifesto: function () { return obterJson('manifesto.json'); },
    shard: function (nome) {
      return fonte.manifesto().then(function (m) {
        var s = m && m.shards && m.shards[nome];
        return obterJson(nome + '.json' + (s && s.sha ? '?v=' + s.sha : ''));
      });
    },
    ancorasIndice: function () { return obterJson('ancoras.json').then(function (x) { return (x && x.normas) || []; }); },
    ancoras: function (k) { return obterJson('a/' + k + '.json').catch(function () { return null; }); },
    apelidos: function () { return obterJson('apelidos.json'); },
    avisos: function () { return obterJson('avisos.json').then(function (x) { return (x && x.avisos) || []; }); }
  };

  var promessaNucleo = null;
  function carregarNucleo() {
    if (window.PDNucleo) return Promise.resolve(window.PDNucleo);
    if (!promessaNucleo) {
      promessaNucleo = new Promise(function (ok, falha) {
        var s = doc.createElement('script');
        s.src = raiz + 'assets/nucleo.js';
        s.onload = function () { window.PDNucleo ? ok(window.PDNucleo) : falha(new Error('núcleo ausente')); };
        s.onerror = function () { promessaNucleo = null; falha(new Error('falha ao carregar o núcleo')); };
        doc.head.appendChild(s);
      });
    }
    return promessaNucleo;
  }

  var preparado = false;
  function prepararCarga() {
    if (preparado) return;
    preparado = true;
    carregarNucleo().catch(function () { preparado = false; });
    ['manifesto.json', 'apelidos.json', 'avisos.json', 'ancoras.json'].forEach(function (r) {
      obterJson(r).catch(function () { /* tenta de novo na consulta */ });
    });
  }

  /* ---------------------------------------------------------------- DOM */

  function el(tag, classe, texto) {
    var e = doc.createElement(tag);
    if (classe) e.className = classe;
    if (texto !== undefined && texto !== null) e.textContent = texto;
    return e;
  }

  function link(href, texto, classe) {
    var a = el('a', classe, texto);
    a.href = href;
    if (/^https?:/.test(href)) a.rel = 'noopener';
    return a;
  }

  function limpar(no) { while (no.firstChild) no.removeChild(no.firstChild); }

  function linkSugestao(consulta) {
    if (cfg.SUGESTAO_URL && cfg.SUGESTAO_CAMPO) {
      return { href: cfg.SUGESTAO_URL + '&' + cfg.SUGESTAO_CAMPO + '=' + enc(consulta), aviso: 'Sugerir esta busca (formulário, sem login)' };
    }
    return {
      href: (cfg.REPO_URL || '') + '/issues/new?title=' + enc('Sugestão: ' + consulta) + '&body=' +
        enc('Busquei: ' + consulta + '\n\nO que eu esperava encontrar:\n') + '&labels=sugestao',
      aviso: 'Sugerir no GitHub (precisa de conta no GitHub)'
    };
  }
  PD.linkSugestao = linkSugestao;

  function blocoSugestao(consulta) {
    if (cfg.SUGESTAO_ATIVA !== 'sim') return doc.createDocumentFragment();  // desligado no config.js
    var s = linkSugestao(consulta);
    var p = el('p', 'sugestao');
    p.appendChild(link(s.href, s.aviso));
    return p;
  }

  function rotuloVersao(v) { return window.PDNucleo ? window.PDNucleo.rotuloVersao(v) : v; }
  function rotuloAlt(v) { return v === 'c' ? 'texto compilado' : 'com histórico'; }

  function blocoAvisos(avisos) {
    var f = doc.createDocumentFragment();
    (avisos || []).forEach(function (a) {
      var d = el('div', 'aviso');
      d.setAttribute('data-aviso', a.id);
      d.appendChild(el('p', null, a.texto));
      if (a.fonte) d.appendChild(el('p', 'nota', 'Fonte: ' + a.fonte));
      f.appendChild(d);
    });
    return f;
  }

  function blocoDica(dica) {
    return el('p', 'dica', 'Sem âncora para este ponto: na página do Planalto, use Ctrl+F "' + dica + '".');
  }

  function paginaDe(k) { return raiz + window.PDNucleo.paginaNorma(k); }

  var SIGLA = { lei: 'Lei', lc: 'LC', dl: 'Decreto-Lei', mp: 'MP', ec: 'EC', ld: 'Lei Delegada', ecr: 'ECR' };
  function rotuloChave(k) {
    var m = /^([a-z]+)-(\d+)([a-z]?)-(\d{4})$/.exec(k);
    return m ? (SIGLA[m[1]] || m[1]) + ' ' + m[2] + (m[3] ? '-' + m[3].toUpperCase() : '') + '/' + m[4] : k;
  }

  function blocoOutras(outras) {
    if (!outras || !outras.length) return null;
    var p = el('p', 'nota', 'Outras normas com este número: ');
    outras.forEach(function (k, i) {
      if (i) p.appendChild(doc.createTextNode(', '));
      p.appendChild(link(paginaDe(k), rotuloChave(k)));
    });
    return p;
  }

  /** Destaca, só com nós de texto, as palavras da consulta (sem diferenciar acento e caixa). */
  function realce(texto, consulta) {
    var f = doc.createDocumentFragment();
    var termos = (consulta || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
      .split(/[^a-z0-9]+/).filter(function (w) { return w.length >= 3; });
    if (!termos.length) { f.appendChild(doc.createTextNode(texto)); return f; }
    var dobrado = Array.prototype.map.call(texto, function (ch) {
      var d = ch.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
      return d.length === 1 ? d : ch;
    }).join('');
    var marcas = new Array(texto.length);
    termos.forEach(function (t) {
      var i = dobrado.indexOf(t);
      while (i >= 0) {
        for (var x = i; x < i + t.length; x++) marcas[x] = true;
        i = dobrado.indexOf(t, i + t.length);
      }
    });
    var ini = 0;
    for (var i = 0; i <= texto.length; i++) {
      if (i === texto.length || !!marcas[i] !== !!marcas[ini]) {
        if (i > ini) {
          var pedaco = texto.slice(ini, i);
          f.appendChild(marcas[ini] ? el('mark', null, pedaco) : doc.createTextNode(pedaco));
        }
        ini = i;
      }
    }
    return f;
  }

  /* ---------------------------------------------------------------- resultado */

  var resultadoEl = doc.getElementById('resultado');
  var temporizador = null;
  var sequencia = 0;

  function cancelarTimer() { if (temporizador) { clearTimeout(temporizador); temporizador = null; } }

  function marcar(R) {
    var r0 = R.refs && R.refs[0];
    var i0 = R.itens && R.itens[0];
    var d0 = r0 ? r0.destino : i0 ? i0.destino : null;
    resultadoEl.setAttribute('data-tipo', R.tipo);
    resultadoEl.setAttribute('data-url', d0 ? d0.url : '');
    resultadoEl.setAttribute('data-alt', d0 && d0.alt ? d0.alt.url : '');
    resultadoEl.setAttribute('data-refs', (R.refs || []).map(function (r) { return r.destino.url; }).join(' '));
    resultadoEl.setAttribute('data-k', (R.refs || []).map(function (r) { return r.k; }).join(' '));
    resultadoEl.setAttribute('data-itens', (R.itens || []).map(function (i) { return i.k; }).join(' '));
    resultadoEl.setAttribute('data-avisos', (R.avisos || []).map(function (a) { return a.id; }).join(' '));
    resultadoEl.setAttribute('data-outras', r0 && r0.outras ? r0.outras.join(' ') : '');
    resultadoEl.setAttribute('data-mensagem', R.mensagem || '');
  }

  function blocoRef(ref, comNome) {
    var d = ref.destino;
    var box = el('div', 'item');
    if (comNome) box.appendChild(el('p', null, ref.nomeCurto + (ref.rotuloPedido ? ' ' + ref.rotuloPedido : '') + ' — ' + rotuloVersao(d.versao)));
    var p = el('p');
    p.appendChild(link(d.url, d.url));
    box.appendChild(p);
    if (d.alt) {
      var pa = el('p', 'nota', 'Outra versão: ');
      pa.appendChild(link(d.alt.url, rotuloAlt(d.alt.versao)));
      box.appendChild(pa);
    }
    if (ref.nota) box.appendChild(el('p', 'nota', ref.nota));
    if (d.nota) box.appendChild(el('p', 'nota', d.nota));
    if (d.dica) box.appendChild(blocoDica(d.dica));
    return box;
  }

  function renderExato(R, ref) {
    var box = el('div', 'transicao');
    box.appendChild(el('p', 'abrindo', window.PDNucleo.textoTransicao(ref)));
    box.appendChild(blocoRef(ref, false));
    box.appendChild(blocoAvisos(R.avisos));
    var outras = blocoOutras(ref.outras);
    if (outras) box.appendChild(outras);
    return box;
  }

  function renderLista(R, max, consulta, comRealce) {
    var f = doc.createDocumentFragment();
    if (R.mensagem) f.appendChild(el('p', 'nota', R.mensagem));
    f.appendChild(blocoAvisos(R.avisos));
    var ol = el('ol', 'lista');
    (R.itens || []).slice(0, max).forEach(function (it) {
      var li = el('li', 'item');
      li.appendChild(el('strong', null, it.nomeCurto !== it.nome ? it.nomeCurto + ' — ' + it.nome : it.nome));
      var ementa = it.ementa || 'Ementa não disponível no índice do Planalto.';
      if (ementa.length > 160) ementa = ementa.slice(0, 159).replace(/\s+\S*$/, '') + '…';
      var pe = el('p', 'ementa');
      if (comRealce) pe.appendChild(realce(ementa, consulta)); else pe.textContent = ementa;
      li.appendChild(pe);
      var pl = el('p');
      pl.appendChild(link(it.destino.url, 'Abrir no Planalto'));
      pl.appendChild(doc.createTextNode(' · '));
      pl.appendChild(link(raiz + it.paginaNorma, 'Página da norma'));
      li.appendChild(pl);
      if (it.destino.nota) li.appendChild(el('p', 'nota', it.destino.nota));
      if (it.destino.dica) li.appendChild(blocoDica(it.destino.dica));
      ol.appendChild(li);
    });
    f.appendChild(ol);
    return f;
  }

  function ehVoltar() {
    try {
      var n = performance.getEntriesByType && performance.getEntriesByType('navigation')[0];
      return !!(n && n.type === 'back_forward');
    } catch (e) { return false; }
  }

  function irPara(consulta, url) {
    if (corpo.classList.contains('pg-home')) {
      try { history.replaceState(null, '', '?q=' + enc(consulta) + '&ir=0'); } catch (e) { /* segue */ }
    }
    PD.ir(url);
  }

  /**
   * Executa a consulta e mostra o resultado.
   * modo: 'normal' (transição com espera), 'pressa' (navega já) ou 'parado' (não navega).
   */
  function executar(consulta, modo) {
    if (!resultadoEl) return;
    cancelarTimer();
    var minha = ++sequencia;
    limpar(resultadoEl);
    resultadoEl.className = '';
    resultadoEl.setAttribute('data-estado', 'carregando');
    ['data-tipo', 'data-url', 'data-alt', 'data-refs', 'data-k', 'data-itens', 'data-avisos', 'data-outras', 'data-mensagem']
      .forEach(function (a) { resultadoEl.removeAttribute(a); });
    var carregando = el('p', 'nota', 'Procurando…');
    resultadoEl.appendChild(carregando);
    var demora = setTimeout(function () { carregando.textContent = 'Carregando o índice…'; }, 400);
    carregarNucleo().then(function (N) {
      return N.resolver(consulta, fonte, cfg);
    }).then(function (R) {
      clearTimeout(demora);
      if (minha !== sequencia) return;
      mostrar(R, consulta, modo);
    }).catch(function (e) {
      clearTimeout(demora);
      if (minha !== sequencia) return;
      console.error(e);
      limpar(resultadoEl);
      resultadoEl.appendChild(el('p', 'nota', 'Não consegui carregar o índice. Verifique a conexão e tente de novo.'));
      resultadoEl.setAttribute('data-tipo', 'erro');
      resultadoEl.setAttribute('data-estado', 'pronto');
    });
  }

  function mostrar(R, consulta, modo) {
    limpar(resultadoEl);
    marcar(R);
    var primeiro = null;
    if (R.tipo === 'exato') {
      var ref = R.refs[0];
      var box = renderExato(R, ref);
      resultadoEl.appendChild(box);
      primeiro = ref.destino.url;
      if (modo === 'normal') {
        var ms = ref.destino.dica ? espera('ESPERA_DICA_MS', 3000) : espera('ESPERA_MS', 1200);
        var cancelar = el('button', 'cancelar', 'Cancelar');
        cancelar.type = 'button';
        cancelar.addEventListener('click', function () {
          cancelarTimer();
          cancelar.disabled = true;
          cancelar.textContent = 'Redirecionamento cancelado';
        });
        box.appendChild(cancelar);
        temporizador = setTimeout(function () { temporizador = null; irPara(consulta, primeiro); }, ms);
      }
    } else if (R.tipo === 'artigo_nao_encontrado') {
      var r = R.refs[0];
      var t = el('div', 'transicao');
      t.appendChild(el('p', 'nota', R.mensagem));
      t.appendChild(blocoRef(r, true));
      t.appendChild(blocoAvisos(R.avisos));
      resultadoEl.appendChild(t);
    } else if (R.tipo === 'multiplo') {
      var lista = el('ol', 'lista');
      R.refs.forEach(function (rf) {
        var li = el('li');
        li.appendChild(blocoRef(rf, true));
        lista.appendChild(li);
      });
      if (R.mensagem) resultadoEl.appendChild(el('p', 'nota', R.mensagem));
      resultadoEl.appendChild(lista);
      resultadoEl.appendChild(blocoAvisos(R.avisos));
      primeiro = R.refs[0].destino.url;
    } else if (R.tipo === 'lista') {
      resultadoEl.appendChild(renderLista(R, 10, consulta, false));
      primeiro = R.itens.length ? R.itens[0].destino.url : null;
    } else if (R.tipo === 'texto') {
      resultadoEl.appendChild(renderLista(R, 20, consulta, true));
      resultadoEl.appendChild(blocoSugestao(consulta));
      primeiro = R.itens.length ? R.itens[0].destino.url : null;
    } else {
      resultadoEl.appendChild(el('p', 'nota', R.mensagem || 'Nada encontrado.'));
      resultadoEl.appendChild(blocoSugestao(consulta));
    }
    resultadoEl.setAttribute('data-estado', 'pronto');
    if (modo === 'pressa' && primeiro && R.tipo !== 'artigo_nao_encontrado') irPara(consulta, primeiro);
  }

  PD.executar = executar;

  /* ---------------------------------------------------------------- páginas */

  function lerParametros() {
    var p = new URLSearchParams(location.search);
    return { q: (p.get('q') || '').trim(), pressa: p.get('pressa') === '1', ir: p.get('ir') };
  }

  function ligarBusca(form, entrada) {
    if (!form || !entrada) return;
    ['keydown', 'input', 'pointerdown', 'touchstart'].forEach(function (ev) {
      form.addEventListener(ev, prepararCarga, { passive: true });
    });
    form.addEventListener('submit', function (e) {
      if (!resultadoEl) return;
      e.preventDefault();
      prepararCarga();
      var q = (entrada.value || '').trim();
      if (!q) { entrada.focus(); return; }
      var pressa = !!(e.submitter && e.submitter.name === 'pressa');
      try { history.pushState(null, '', (form.getAttribute('action') || './') + '?q=' + enc(q) + (pressa ? '&pressa=1' : '')); } catch (x) { /* segue */ }
      executar(q, pressa ? 'pressa' : 'normal');
    });
  }

  function iniciarHome() {
    var form = doc.querySelector('form.busca');
    var entrada = doc.getElementById('q');
    ligarBusca(form, entrada);
    var p = lerParametros();
    if (p.q) {
      if (entrada) entrada.value = p.q;
      prepararCarga();
      var guarda = p.ir === '0' || ehVoltar();
      executar(p.q, guarda ? 'parado' : p.pressa ? 'pressa' : 'normal');
    } else if (entrada && window.matchMedia && window.matchMedia('(pointer: fine)').matches) {
      entrada.focus();
    }
    window.addEventListener('popstate', function () {
      var pp = lerParametros();
      if (entrada) entrada.value = pp.q;
      if (pp.q) executar(pp.q, 'parado');
      else if (resultadoEl) { cancelarTimer(); limpar(resultadoEl); resultadoEl.removeAttribute('data-estado'); }
    });
    window.addEventListener('pageshow', function (e) { if (e.persisted) cancelarTimer(); });
  }

  function iniciarNorma() {
    var form = doc.querySelector('form.ir-artigo');
    var mini = doc.querySelector('form.busca-mini');
    if (!form || !mini) return;
    var campo = form.querySelector('#art');
    var busca = mini.querySelector('input[name="q"]');
    form.hidden = false;
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var v = (campo && campo.value || '').trim();
      if (!v || !busca) return;
      var base = form.getAttribute('data-consulta-base') || '';
      var consulta = /^(adct|art)\b/i.test(v) ? base + ' ' + v : base + ' art ' + v;
      busca.value = consulta;
      mini.submit();
    });
  }

  function iniciar404() {
    var entrada = doc.getElementById('q');
    var irRota = function (N) {
      var q = N.rotaParaConsulta(location.pathname, cfg.SITE_PATH || '/');
      if (q) redirecionarRota((cfg.SITE_PATH || '/') + '?q=' + enc(q), true);
    };
    if (window.PDNucleo) irRota(window.PDNucleo);
    else carregarNucleo().then(irRota).catch(function () { /* fica a página 404 */ });
    if (entrada && window.matchMedia && window.matchMedia('(pointer: fine)').matches) entrada.focus();
  }

  function ajustarSugestaoSobre() {
    if (cfg.SUGESTAO_ATIVA !== 'sim' || !(cfg.SUGESTAO_URL && cfg.SUGESTAO_CAMPO)) return;
    var a = doc.querySelector('.sobre a.sugestao');
    if (!a) return;
    var s = linkSugestao('');
    a.href = s.href;
    a.textContent = 'Sugerir uma lei ou apelido (formulário, sem login)';
  }

  if (corpo.classList.contains('pg-404')) iniciar404();
  else if (corpo.classList.contains('pg-norma')) iniciarNorma();
  else iniciarHome();
  ajustarSugestaoSobre();
})();
