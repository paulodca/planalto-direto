/* Planalto Direto — núcleo do resolvedor de citações.
 * Sem DOM e sem fetch: roda no navegador (window.PDNucleo) e no Node (module.exports).
 * Os dados chegam por uma "fonte" injetada (a interface usa fetch; os testes leem do disco).
 * Nenhum fragmento é montado por regra: toda âncora vem de a/<k>.json, verificada no build.
 */
(function (raiz, fabrica) {
  var api = fabrica();
  if (typeof module === 'object' && module.exports) { module.exports = api; } else { raiz.PDNucleo = api; }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* ------------------------------------------------------------------ tipos e chaves */

  var TIPOS = ['lei', 'lc', 'dl', 'mp', 'ec', 'ld', 'ecr', 'cf'];
  var POS_TIPO = {};
  TIPOS.forEach(function (t, i) { POS_TIPO[t] = i; });
  var NOME_TIPO = {
    lei: 'Lei', lc: 'Lei Complementar', dl: 'Decreto-Lei', mp: 'Medida Provisória',
    ec: 'Emenda Constitucional', ld: 'Lei Delegada', ecr: 'Emenda Constitucional de Revisão',
    cf: 'Constituição Federal'
  };
  var CHAVE_CF = 'cf-1988';
  var CHAVE_RE = /^(lei|lc|dl|mp|ec|ld|ecr)-(\d+)([a-z]?)-(\d{4})$/;

  function partesChave(k) {
    if (k === CHAVE_CF) return ['cf', 1988, '', 1988];
    var m = CHAVE_RE.exec(k);
    if (!m) throw new Error('chave inválida: ' + k);
    return [m[1], parseInt(m[2], 10), m[3], parseInt(m[4], 10)];
  }

  function chaveValida(k) { return k === CHAVE_CF || CHAVE_RE.test(k); }

  function cmpTupla(a, b) {
    for (var i = 0; i < a.length; i++) {
      if (a[i] < b[i]) return -1;
      if (a[i] > b[i]) return 1;
    }
    return 0;
  }

  /** Ordem canônica de chave: (posição do tipo, número, letra, ano). */
  function ordemChave(k) {
    var p = partesChave(k);
    return [POS_TIPO[p[0]], p[1], p[2], p[3]];
  }

  function kDe(x) { return typeof x === 'string' ? x : x.k; }

  function temAlvo(alvos, k) {
    if (!alvos) return false;
    if (typeof alvos.has === 'function') return alvos.has(k);
    return alvos.indexOf(k) >= 0;
  }

  /** Ordem pública (§7.6): alvo de apelido primeiro; tipo; ano DESC; ordem canônica de chave. */
  function ordemPublica(lista, alvosApelido) {
    var cop = lista.slice();
    function chave(x) {
      var k = kDe(x), p = partesChave(k);
      return [temAlvo(alvosApelido, k) ? 0 : 1, POS_TIPO[p[0]], -p[3]].concat(ordemChave(k));
    }
    return cop.sort(function (a, b) { return cmpTupla(chave(a), chave(b)); });
  }

  function milhar(n) {
    var s = String(n);
    return n >= 1000 ? s.replace(/\B(?=(\d{3})+(?!\d))/g, '.') : s;
  }

  /** "Lei nº 8.036/1990", "Medida Provisória nº 2.158-35/2001", "Constituição Federal de 1988". */
  function nomeNorma(tsig, numero, letra, reed, ano) {
    if (tsig === 'cf') return 'Constituição Federal de 1988';
    return NOME_TIPO[tsig] + ' nº ' + milhar(numero) + (letra ? '-' + String(letra).toUpperCase() : '') +
      (reed ? '-' + reed : '') + '/' + ano;
  }

  function tsigDe(k) { return k === CHAVE_CF ? 'cf' : k.slice(0, k.indexOf('-')); }

  function nomeRegistro(r) { return nomeNorma(tsigDe(r.k), r.n, r.l || '', r.r || '', r.a); }

  function paginaNorma(k) { return k.replace('-', '/') + '/'; }

  /* ------------------------------------------------------------------ URL e fragmento */

  /** Igual a urllib.parse.quote(s, safe='') do Python. */
  function codificarFragmento(s) {
    return encodeURIComponent(s).replace(/[!'()*]/g, function (c) {
      return '%' + c.charCodeAt(0).toString(16).toUpperCase();
    });
  }

  function montarUrl(base, caminho, ancora) {
    return (base || '') + caminho + (ancora ? '#' + codificarFragmento(ancora) : '');
  }

  /* ------------------------------------------------------------------ normalização (§9.2) */

  var URL_RE = /(?:https?:\/\/)?(?:www\.)?planalto\.gov\.br\/ccivil_03\/([^\s?#]+)/i;

  /** Passos 2 a 5. */
  function normBase(s) {
    s = String(s == null ? '' : s).toLowerCase().replace(/[ \s]+/g, ' ');
    s = s.replace(/[º°ª]/g, '');
    s = s.replace(/(\d)\s?o(?=[\s,.;)]|$)/g, '$1');
    s = s.normalize('NFD').replace(/[̀-ͯ]/g, '');
    s = s.replace(/[–—]/g, '-');
    s = s.replace(/["'“”‘’«»()[\]{}]/g, ' ');
    s = s.replace(/,/g, ' , ').replace(/;/g, ' ; ');
    return s;
  }

  function semMilhar(s) {
    return s.replace(/\b(\d{1,3}(?:\.\d{3})+)\b/g, function (m) { return m.replace(/\./g, ''); });
  }

  function colapsar(s) { return s.replace(/\s+/g, ' ').trim(); }

  /** Termos de apelido: passos 2 a 5, 12 e 15. */
  function normTermo(t) { return colapsar(semMilhar(normBase(t))); }

  /** Normalização completa (passos 2 a 15), sem a troca de apelidos (que precisa da tabela). */
  function normalizar(s) {
    var r = etapasFinais(normBase(s));
    return r.texto;
  }

  var PREFIXO_ARQ = { l: 'lei', lei: 'lei', del: 'dl', dl: 'dl', lcp: 'lc', lc: 'lc', mpv: 'mp', mp: 'mp',
    emc: 'ec', ec: 'ec', ecr: 'ecr', ldl: 'ld' };
  var ARQ_RE = /^(l|lei|del|dl|lcp|lc|mpv|mp|emc|ec|ecr|ldl)0*(\d{1,3}(?:\.\d{3})+|\d+)(?:-?([a-z]))?(?:-(\d+))?(cons|consol|consolidado|compilado|compilada|orig|consimpressao|impressao)?(?:\.html?)?$/;
  var ARQ_CF_RE = /^constituicao(compilado)?(\.htm)?$/;

  /** Lê um token de nome de arquivo (regra A do §9.3). */
  function lerArq(tok) {
    var t = String(tok).replace(/[.:]+$/, '');
    if (t.indexOf('/') >= 0) {
      if (!/\.html?$/.test(t)) return null;
      t = t.split('/').pop();
    }
    if (ARQ_CF_RE.test(t)) return { cf: true, tsig: 'cf', numero: 1988, letra: '', reed: '', slug: t.replace(/\.html?$/, '') };
    var m = ARQ_RE.exec(t);
    if (!m) return null;
    return {
      cf: false, tsig: PREFIXO_ARQ[m[1]], numero: parseInt(m[2].replace(/\./g, ''), 10),
      letra: m[3] || '', reed: m[4] || '', slug: t.replace(/\.html?$/, '')
    };
  }

  /** Passos 6 a 15 sobre uma cadeia já com os apelidos protegidos. */
  function etapasFinais(s) {
    s = s.replace(/c\/c/g, ' & ');
    s = s.replace(/§§/g, '§');
    s = s.replace(/§\s*(\d+)(?:\s*-\s*([a-z])\b)?/g, function (m, n, l) {
      return l ? ' § ' + n + '-' + l + ' ' : ' § ' + n + ' ';
    });
    s = s.replace(/paragrafo unico|par\.? unico|\bp\.\s?u\.?|\bpu\b/g, ' PU ');
    s = s.replace(/\b(?:paragrafo|par\.)\s*(\d+)/g, ' § $1 ');
    s = s.replace(/\bcaput\b/g, ' CAPUT ');
    s = s.replace(/\b(?:incisos?\b|inc\.|inc\b)\s*/g, ' INC ');
    s = s.replace(/\b(?:alineas?\b|al\.)\s*/g, ' ALI ');
    s = s.replace(/\bitem\b\s*/g, ' ITEM ');
    s = s.replace(/\b(?:arts?|artigos?)\b\.?\s*/g, ' ART ');
    s = s.replace(/\bart(?=\d)/g, ' ART ');
    var arqs = [];
    s = s.split(' ').map(function (tok) {
      if (!tok || /^[A-Z]/.test(tok)) return tok;
      var info = lerArq(tok);
      if (!info) return tok;
      arqs.push(info);
      return 'ARQ#' + (arqs.length - 1);
    }).join(' ');
    s = semMilhar(s);
    s = s.replace(/\bde\s+\d{1,2}\s*(?:de\s+[a-z]+|\.\s*\d{1,2})\s*(?:de\s+|\.\s*)(\d{2,4})\b/g, ' ANO=$1 ');
    s = s.replace(/(\d+[a-z]?)\s*\/\s*(\d{2}|\d{4})\b/g, ' $1/$2 ');
    return { texto: colapsar(s), arqs: arqs };
  }

  /* ------------------------------------------------------------------ apelidos */

  var TERMOS_TIPO = ['lei', 'lc', 'lcp', 'dl', 'del', 'mp', 'mpv', 'ec', 'emenda', 'ld', 'ecr'];

  function escaparRe(s) { return s.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&'); }

  function prepararApelidos(ap) {
    ap = ap || {};
    var entradas = [], termoIdx = {}, alvosApelido = new Set(), siglaDe = {}, termosDe = {};
    function addTermo(t, idx, alvos) {
      var n = normTermo(t);
      if (!n) return;
      alvos.forEach(function (k) { (termosDe[k] = termosDe[k] || []).push(n); });
      if (!Object.prototype.hasOwnProperty.call(termoIdx, n)) termoIdx[n] = idx;
    }
    (ap.apelidos || []).forEach(function (a) {
      var idx = entradas.length;
      entradas.push({ tipo: 'apelido', alvo: a.alvo, sigla: a.sigla || '', nome: a.nome || '', nota: a.nota || '' });
      alvosApelido.add(a.alvo);
      if (!Object.prototype.hasOwnProperty.call(siglaDe, a.alvo) && a.sigla) siglaDe[a.alvo] = a.sigla;
      (a.termos || []).forEach(function (t) { addTermo(t, idx, [a.alvo]); });
    });
    (ap.listas || []).forEach(function (l) {
      var idx = entradas.length;
      entradas.push({ tipo: 'lista', alvos: (l.alvos || []).slice(), nota: l.nota || '' });
      (l.termos || []).forEach(function (t) { addTermo(t, idx, l.alvos || []); });
    });
    var termos = Object.keys(termoIdx).sort(function (a, b) {
      return b.length - a.length || (a < b ? -1 : a > b ? 1 : 0);
    });
    var re = null;
    if (termos.length) {
      var alts = termos.map(function (t) {
        var e = escaparRe(t);
        return TERMOS_TIPO.indexOf(t) >= 0 ? e + '(?!\\s*-?\\s*\\d)' : e;
      });
      re = new RegExp('(^|[^\\w§])(' + alts.join('|') + ')(?!\\w)', 'g');
    }
    var assuntos = (ap.assuntos || []).map(function (s) {
      return { alvos: (s.alvos || []).slice(), termos: (s.termos || []).map(normTermo).filter(Boolean) };
    });
    var fora = [];
    (ap.fora_escopo || []).forEach(function (f) {
      try { fora.push({ re: new RegExp(f.padrao), mensagem: f.mensagem || '' }); } catch (e) { /* padrão inválido em JS: ignorado */ }
    });
    return {
      entradas: entradas, termoIdx: termoIdx, re: re, alvosApelido: alvosApelido, siglaDe: siglaDe,
      termosDe: termosDe, assuntos: assuntos, fora: fora, desempate: ap.desempate || {}
    };
  }

  var cacheApc = typeof WeakMap === 'function' ? new WeakMap() : null;
  function apcDe(ap) {
    if (!ap || typeof ap !== 'object' || !cacheApc) return prepararApelidos(ap);
    var c = cacheApc.get(ap);
    if (!c) { c = prepararApelidos(ap); cacheApc.set(ap, c); }
    return c;
  }

  /** Troca cada termo de apelido por um token protegido APL#n (passo 5a). */
  function trocarApelidos(s, apc) {
    var achados = [];
    if (!apc || !apc.re) return { texto: s, achados: achados };
    var t = s.replace(apc.re, function (m, pre, termo) {
      var idx = apc.termoIdx[termo];
      achados.push(idx);
      return pre + ' APL#' + idx + ' ';
    });
    return { texto: t, achados: achados };
  }

  /* ------------------------------------------------------------------ tokens (§9.3) */

  var ROMANO_RE = /^M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})$/;
  function romanoValido(t) { return !!t && ROMANO_RE.test(t.toUpperCase()); }

  var CONECTIVOS = new Set(['a', 'o', 'e', 'de', 'da', 'do', 'das', 'dos', 'n', 'no', 'numero', 'na', 'nas', 'em',
    'as', 'ao', 'aos']);
  var MARCAS = { ART: 'ART', '§': '§', PU: 'PU', CAPUT: 'CAPUT', INC: 'INC', ALI: 'ALI', ITEM: 'ITEM',
    '&': '&', ',': ',', ';': ';' };
  var TIPO_LONGO = [
    [['emenda', 'constitucional', 'de', 'revisao'], 'ecr'],
    [['emenda', 'constitucional'], 'ec'],
    [['lei', 'complementar'], 'lc'],
    [['lei', 'delegada'], 'ld'],
    [['decreto', 'lei'], 'dl'],
    [['medida', 'provisoria'], 'mp']
  ];
  var TIPO_CURTO = { lei: 'lei', lc: 'lc', lcp: 'lc', dl: 'dl', del: 'dl', 'decreto-lei': 'dl', mp: 'mp', mpv: 'mp',
    ec: 'ec', emenda: 'ec', ld: 'ld', ecr: 'ecr' };

  function classe(t) {
    if (/^APL#\d+$/.test(t)) return 'APL';
    if (/^ARQ#\d+$/.test(t)) return 'ARQ';
    if (/^ANO=\d{2,4}$/.test(t)) return 'ANO';
    if (Object.prototype.hasOwnProperty.call(MARCAS, t)) return MARCAS[t];
    if (t === 'adct') return 'ADCT';
    if (/^\d+$/.test(t)) return 'NUM';
    if (/^\d+-?[a-z]$/.test(t)) return 'NUMLET';
    if (/^\d+-\d+$/.test(t)) return 'NUMHIF';
    if (/^\d+[a-z]?\/\d{2,4}$/.test(t)) return 'NUMANO';
    if (/^[ivxlc]+$/.test(t) && romanoValido(t)) return 'ROM';
    if (/^[a-z]$/.test(t)) return 'LET';
    return 'PAL';
  }

  function tokenizar(texto) {
    var brutos = texto.split(' ').map(function (t) {
      if (/^(?:APL|ARQ)#\d+$/.test(t) || /^ANO=/.test(t)) return t;
      return t.replace(/^[.:]+|[.:]+$/g, '');
    }).filter(function (t) { return t && !/^[-/.:]+$/.test(t); });
    var out = [];
    for (var i = 0; i < brutos.length; i++) {
      var feito = false;
      for (var j = 0; j < TIPO_LONGO.length && !feito; j++) {
        var seq = TIPO_LONGO[j][0], ok = true;
        for (var x = 0; x < seq.length; x++) { if (brutos[i + x] !== seq[x]) { ok = false; break; } }
        if (ok) { out.push({ c: 'TIPO', v: seq.join(' '), tsig: TIPO_LONGO[j][1] }); i += seq.length - 1; feito = true; }
      }
      if (feito) continue;
      var b = brutos[i];
      if (Object.prototype.hasOwnProperty.call(TIPO_CURTO, b)) { out.push({ c: 'TIPO', v: b, tsig: TIPO_CURTO[b] }); continue; }
      out.push({ c: classe(b), v: b });
    }
    return out;
  }

  function ehNum(t) { return !!t && (t.c === 'NUM' || t.c === 'NUMLET'); }
  function ehNumQualquer(t) { return !!t && (t.c === 'NUM' || t.c === 'NUMLET' || t.c === 'NUMHIF' || t.c === 'NUMANO'); }
  function temLetra(t) { return /[a-z]/.test(t.v) && (t.c === 'PAL' || t.c === 'LET' || t.c === 'ROM'); }

  /* ------------------------------------------------------------------ dispositivos canônicos */

  function canonArt(v) {
    var m = /^0*(\d+)-?([a-z])?$/.exec(String(v));
    if (!m) return String(v);
    return (m[1] || '0') + (m[2] ? '-' + m[2].toUpperCase() : '');
  }

  function canonPar(v) { return '§' + canonArt(v); }

  var NIVEL_COMP = { par: 1, pu: 1, inc: 2, ali: 3, item: 4 };
  function tipoComp(c) {
    if (c === 'pu') return 'pu';
    if (c.charAt(0) === '§') return 'par';
    if (/^[IVXLCDM]+$/.test(c)) return 'inc';
    if (/^[a-z]$/.test(c)) return 'ali';
    if (/^\d+$/.test(c)) return 'item';
    return 'art';
  }

  function ordinal(n) {
    var m = /^(\d+)(-[A-Z])?$/.exec(n);
    if (!m) return n;
    var v = parseInt(m[1], 10);
    return (v < 10 ? m[1] + 'º' : milhar(v)) + (m[2] || '');
  }

  function rotuloComp(c, solto, ehArtigo) {
    var t = ehArtigo ? 'art' : tipoComp(c);
    if (t === 'pu') return 'parágrafo único';
    if (t === 'par') return '§ ' + ordinal(c.slice(1));
    if (t === 'inc') return solto ? 'inciso ' + c : c;
    if (t === 'ali') return 'alínea "' + c + '"';
    if (t === 'item') return 'item ' + c;
    return 'art. ' + ordinal(c);
  }

  /** 'art. 477, § 2º, I' (com " do ADCT" na parte adct). */
  function rotuloComps(comps, parte) {
    if (!comps || !comps.length) return '';
    var s = comps.map(function (c, i) { return rotuloComp(c, false, i === 0); }).join(', ');
    return parte === 'adct' ? s.replace(/^(art\. [^,]+)/, '$1 do ADCT') : s;
  }

  function rotuloFalta(comps) {
    var primeiro = comps[0], t = tipoComp(primeiro);
    var txt = comps.map(function (c, i) { return rotuloComp(c, i === 0); }).join(', ');
    return (t === 'ali' ? 'A ' : 'O ') + txt;
  }

  /* ------------------------------------------------------------------ análise (§9.4) */

  function lerDisps(T, i, nivel) {
    var comps = [];
    for (;;) {
      var t = T[i];
      if (!t) break;
      var u = T[i + 1];
      if (t.c === '§') {
        t.usado = true;
        if (ehNum(u)) { u.usado = true; comps.push(canonPar(u.v)); i += 2; nivel = 'par'; continue; }
        i++; continue;
      }
      if (t.c === 'PU') { t.usado = true; comps.push('pu'); i++; nivel = 'par'; continue; }
      if (t.c === 'CAPUT') { t.usado = true; i++; continue; }
      if (t.c === 'INC') {
        t.usado = true;
        if (u && u.c === 'ROM') { u.usado = true; comps.push(u.v.toUpperCase()); i += 2; nivel = 'inc'; continue; }
        i++; continue;
      }
      if (t.c === 'ALI') {
        t.usado = true;
        if (u && /^[a-z]$/.test(u.v) && (u.c === 'LET' || u.c === 'ROM')) { u.usado = true; comps.push(u.v); i += 2; nivel = 'ali'; continue; }
        i++; continue;
      }
      if (t.c === 'ITEM') {
        t.usado = true;
        if (u && u.c === 'NUM') { u.usado = true; comps.push(String(parseInt(u.v, 10))); i += 2; nivel = 'item'; continue; }
        i++; continue;
      }
      if (t.c === 'ROM' && (nivel === 'art' || nivel === 'par')) {
        t.usado = true; comps.push(t.v.toUpperCase()); i++; nivel = 'inc'; continue;
      }
      if ((t.c === 'LET' || (t.c === 'ROM' && t.v.length === 1)) && (nivel === 'inc' || nivel === 'par')) {
        if (t.v === 'o' || t.v === 'e' || (t.v === 'a' && ehNumQualquer(u))) break;
        t.usado = true; comps.push(t.v); i++; nivel = 'ali'; continue;
      }
      if (t.c === ',' && u) {
        var segue = u.c === '§' || u.c === 'PU' || u.c === 'INC' || u.c === 'ALI' || u.c === 'ITEM' ||
          u.c === 'CAPUT' || (u.c === 'ROM' && (nivel === 'art' || nivel === 'par'));
        if (segue) { t.usado = true; i++; continue; }
      }
      break;
    }
    return { comps: comps, i: i };
  }

  function lerAlvos(T, i) {
    var alvos = [];
    for (;;) {
      var t = T[i], alvo = null;
      if (ehNum(t)) {
        t.usado = true;
        alvo = { comps: [canonArt(t.v)] };
        i++;
        if (T[i] && T[i].v === 'a' && ehNum(T[i + 1])) {
          T[i].usado = true; T[i + 1].usado = true;
          alvo.intervalo = [canonArt(t.v), canonArt(T[i + 1].v)];
          i += 2;
        }
      } else if (t && t.c === 'NUMHIF') {
        t.usado = true;
        var p = t.v.split('-');
        alvo = { comps: [canonArt(p[0])], intervalo: [canonArt(p[0]), canonArt(p[1])] };
        i++;
      } else {
        break;
      }
      var r = lerDisps(T, i, 'art');
      alvo.comps = alvo.comps.concat(r.comps);
      i = r.i;
      alvos.push(alvo);
      var j = i;
      if (T[j] && T[j].c === ',') j++;
      if (T[j] && T[j].v === 'e' && T[j].c === 'LET') j++;
      if (j > i && T[j] && (ehNum(T[j]) || T[j].c === 'NUMHIF')) {
        for (var x = i; x < j; x++) T[x].usado = true;
        i = j;
        continue;
      }
      break;
    }
    return { alvos: alvos, i: i };
  }

  function normaDeTipo(tsig, tok) {
    var v = tok.v, m;
    if (tok.c === 'NUMANO') {
      m = /^(\d+)([a-z]?)\/(\d{2,4})$/.exec(v);
      return { via: 'tipo', tsig: tsig, numero: parseInt(m[1], 10), letra: m[2] || '', reed: '', ano: m[3], letraPedida: !!m[2] };
    }
    if (tok.c === 'NUMHIF') {
      m = /^(\d+)-(\d+)$/.exec(v);
      return { via: 'tipo', tsig: tsig, numero: parseInt(m[1], 10), letra: '', reed: tsig === 'mp' ? m[2] : '', ano: null, letraPedida: false };
    }
    m = /^(\d+)-?([a-z])?$/.exec(v);
    return { via: 'tipo', tsig: tsig, numero: parseInt(m[1], 10), letra: m[2] || '', reed: '', ano: null, letraPedida: !!m[2] };
  }

  function preVarredura(T) {
    for (var i = 0; i < T.length; i++) {
      var t = T[i];
      if (t.c === 'APL' || t.c === 'ARQ' || t.c === 'ADCT' || t.c === 'NUMANO') return true;
      if (t.c === 'TIPO') {
        var j = i + 1;
        while (T[j] && (T[j].v === 'n' || T[j].v === 'no' || T[j].v === 'numero')) j++;
        if (ehNumQualquer(T[j])) return true;
      }
    }
    return false;
  }

  function lerSegmento(T, ctx) {
    var itens = [], ultimo = null, pend = [], ano = null, i = 0;
    function anterior(k) { for (var x = k - 1; x >= 0; x--) { if (T[x].c !== ',') return T[x]; } return null; }
    function empurrarArts(alvos) {
      if (!alvos.length) return;
      if (pend.length) {
        var a0 = alvos[0];
        var resto = a0.comps.slice(1).concat(pend);
        resto.sort(function (x, y) { return NIVEL_COMP[tipoComp(x)] - NIVEL_COMP[tipoComp(y)]; });
        a0.comps = [a0.comps[0]].concat(resto);
        pend = [];
      }
      alvos.forEach(function (a) { itens.push({ k: 'art', alvo: a }); });
      ultimo = 'art';
    }
    while (i < T.length) {
      var t = T[i];
      if (t.c === 'APL') {
        t.usado = true;
        itens.push({ k: 'norma', norma: { via: 'apl', idx: parseInt(t.v.slice(4), 10) } });
        ultimo = 'norma'; i++; continue;
      }
      if (t.c === 'ARQ') {
        t.usado = true;
        var info = ctx.arqs[parseInt(t.v.slice(4), 10)];
        itens.push({ k: 'norma', norma: { via: 'arq', arq: info, ano: null } });
        ultimo = 'norma'; i++; continue;
      }
      if (t.c === 'ADCT') {
        t.usado = true;
        itens.push({ k: 'norma', norma: { via: 'adct' } });
        ultimo = 'norma'; i++; continue;
      }
      if (t.c === 'TIPO') {
        t.usado = true;
        var j = i + 1;
        while (T[j] && (T[j].v === 'n' || T[j].v === 'no' || T[j].v === 'numero') && T[j].c !== 'APL') j++;
        if (ehNumQualquer(T[j])) {
          for (var x = i + 1; x <= j; x++) T[x].usado = true;
          itens.push({ k: 'norma', norma: normaDeTipo(t.tsig, T[j]) });
          ultimo = 'norma'; i = j + 1; continue;
        }
        i++; continue;
      }
      if (t.c === 'NUMANO') {
        t.usado = true;
        var mm = /^(\d+)([a-z]?)\/(\d{2,4})$/.exec(t.v);
        itens.push({ k: 'norma', norma: { via: 'numano', numero: parseInt(mm[1], 10), letra: mm[2] || '', ano: mm[3] } });
        ultimo = 'norma'; i++; continue;
      }
      if (t.c === 'ANO') { t.usado = true; ano = t.v.slice(4); i++; continue; }
      if (t.c === 'ART') {
        t.usado = true;
        var r = lerAlvos(T, i + 1);
        empurrarArts(r.alvos);
        i = Math.max(r.i, i + 1); continue;
      }
      if (t.c === 'NUM' || t.c === 'NUMLET' || t.c === 'NUMHIF') {
        var ant = anterior(i);
        if (ultimo === 'norma' && t.c === 'NUM' && ant && ant.v === 'de' && /^\d{4}$/.test(t.v) &&
            +t.v > 1800 && +t.v < 2100 && ano === null) {
          t.usado = true; ano = t.v; i++; continue;
        }
        if (ctx.numSolto && t.c !== 'NUMHIF') {
          ctx.numSolto = false; t.usado = true;
          var mn = /^(\d+)-?([a-z])?$/.exec(t.v);
          itens.push({ k: 'norma', norma: { via: 'num', numero: parseInt(mn[1], 10), letra: mn[2] || '', ano: null } });
          ultimo = 'norma'; i++; continue;
        }
        var r2 = lerAlvos(T, i);
        empurrarArts(r2.alvos);
        i = Math.max(r2.i, i + 1); continue;
      }
      if (t.c === '§' || t.c === 'PU' || t.c === 'INC' || t.c === 'ALI' || t.c === 'ITEM' || t.c === 'CAPUT') {
        var r3 = lerDisps(T, i, 'pre');
        pend = pend.concat(r3.comps);
        i = Math.max(r3.i, i + 1); continue;
      }
      if (t.c === ',') { t.usado = true; i++; continue; }
      if (CONECTIVOS.has(t.v) && (t.c === 'PAL' || t.c === 'LET')) { t.usado = true; i++; continue; }
      i++;
    }
    return { itens: itens, ano: ano };
  }

  function vincular(segs, apc) {
    var grupos = [];
    var porSeg = segs.map(function (seg) {
      var temAdct = seg.itens.some(function (it) { return it.k === 'norma' && it.norma.via === 'adct'; });
      var itens = seg.itens.filter(function (it) {
        if (!temAdct || it.k !== 'norma' || it.norma.via !== 'apl') return true;
        var e = apc.entradas[it.norma.idx];
        return !(e && e.tipo === 'apelido' && e.alvo === CHAVE_CF);
      });
      var gs = [], soltos = [];
      var primeiroNorma = itens.length && itens[0].k === 'norma';
      itens.forEach(function (it, p) {
        if (it.k === 'norma') {
          if (seg.ano && (it.norma.via === 'tipo' || it.norma.via === 'num' || it.norma.via === 'arq' || it.norma.via === 'numano') && !it.norma.ano) {
            it.norma.ano = seg.ano;
          }
          gs.push({ norma: it.norma, arts: [], pos: p });
        }
      });
      itens.forEach(function (it, p) {
        if (it.k !== 'art') return;
        if (!gs.length) { soltos.push(it.alvo); return; }
        var alvo = null, x;
        if (primeiroNorma) {
          for (x = gs.length - 1; x >= 0; x--) { if (gs[x].pos < p) { alvo = gs[x]; break; } }
        } else {
          for (x = 0; x < gs.length; x++) { if (gs[x].pos > p) { alvo = gs[x]; break; } }
          if (!alvo) alvo = gs[gs.length - 1];
        }
        alvo.arts.push(it.alvo);
      });
      return { gs: gs, soltos: soltos };
    });
    porSeg.forEach(function (s, idx) {
      if (!s.soltos.length) return;
      var dest = null, x;
      for (x = idx + 1; x < porSeg.length && !dest; x++) { if (porSeg[x].gs.length) dest = porSeg[x].gs[0]; }
      for (x = idx - 1; x >= 0 && !dest; x--) { if (porSeg[x].gs.length) dest = porSeg[x].gs[porSeg[x].gs.length - 1]; }
      if (dest) dest.arts = s.soltos.concat(dest.arts);
    });
    porSeg.forEach(function (s) {
      s.gs.forEach(function (g) {
        var parte = g.norma.via === 'adct' ? 'adct' : 'corpo';
        g.arts.forEach(function (a) { a.parte = parte; });
        grupos.push({ norma: g.norma, arts: g.arts });
      });
    });
    return grupos;
  }

  /**
   * Análise pura da consulta (sem dados de normas).
   * Devolve {via:'url', caminho} ou {via:'consulta', grupos, normaForte, sobra, fora, normalizada, apls}.
   */
  function analisar(consulta, apc) {
    apc = apc || prepararApelidos({});
    var bruto = String(consulta == null ? '' : consulta);
    var mu = URL_RE.exec(bruto);
    if (mu) return { via: 'url', caminho: mu[1].toLowerCase() };
    var base = normBase(bruto);
    var ap = trocarApelidos(base, apc);
    var fin = etapasFinais(ap.texto);
    var T = tokenizar(fin.texto);
    var forte = preVarredura(T);
    var ctx = { arqs: fin.arqs, numSolto: !forte };
    var crus = [[]];
    T.forEach(function (t) {
      if (t.c === '&' || t.c === ';') { t.usado = true; crus.push([]); } else { crus[crus.length - 1].push(t); }
    });
    var segs = crus.map(function (seg) { return lerSegmento(seg, ctx); });
    var grupos = vincular(segs, apc);
    var sobra = T.some(function (t) { return !t.usado && temLetra(t) && !CONECTIVOS.has(t.v); });
    var foraTexto = colapsar(semMilhar(base));
    var fora = null;
    if (!forte) {
      for (var f = 0; f < apc.fora.length; f++) {
        if (apc.fora[f].re.test(foraTexto)) { fora = apc.fora[f].mensagem; break; }
      }
    }
    var temLetras = T.some(function (t) { return /[a-z]/.test(t.v) && t.c !== 'ANO'; });
    return {
      via: 'consulta', grupos: grupos, normaForte: forte, sobra: sobra, fora: fora, temLetras: temLetras,
      normalizada: fin.texto, tokens: T.map(function (t) { return t.c === 'TIPO' ? 'TIPO:' + t.tsig : t.v; }),
      apls: ap.achados
    };
  }

  /* ------------------------------------------------------------------ escolha do destino (§8.5) */

  function avisoCasa(a, k, parte, comps) {
    if (!a || !a.alvo || a.alvo.k !== k) return false;
    if ((a.alvo.parte || 'corpo') !== parte) return false;
    var d = a.alvo.disp || '';
    if (!d) return true;
    if (!comps) return false;
    var dc = d.split('|');
    if (dc.length > comps.length) return false;
    for (var i = 0; i < dc.length; i++) { if (dc[i] !== comps[i]) return false; }
    return true;
  }

  function avisosDaRef(avisos, k, pedido) {
    return (avisos || []).filter(function (a) {
      return avisoCasa(a, k, pedido ? (pedido.parte || 'corpo') : 'corpo', pedido ? pedido.comps : null) &&
        (pedido || !(a.alvo.disp || ''));
    }).map(function (a) { return { id: a.id, estado: a.estado, texto: a.texto, fonte: a.fonte }; });
  }

  function temProp(o, k) { return !!o && Object.prototype.hasOwnProperty.call(o, k); }

  function escolherDestino(reg, anc, pedido, avisos, cfg) {
    var base = (cfg && cfg.PLANALTO_BASE) || '';
    var u = reg.u, c = reg.c || '';
    var temAlt = !!c && c.toLowerCase() !== u.toLowerCase();
    function pagina(v, frag) {
      return { url: montarUrl(base, v === 'c' ? c : u, frag), versao: v, fragmento: frag || null };
    }
    var vPrinc = c ? 'c' : 'h', vOutra = vPrinc === 'c' ? 'h' : 'c';
    if (!pedido || !pedido.comps || !pedido.comps.length) {
      var p0 = pagina(vPrinc, null);
      return { url: p0.url, versao: p0.versao, fragmento: null, profundidade: 0,
        alt: temAlt ? pagina(vOutra, null) : null, dica: null, nota: null };
    }
    var parte = pedido.parte || 'corpo';
    var comps = pedido.comps.slice();
    (avisos || []).forEach(function (a) {
      if (a && a.ir_para && a.alvo && a.alvo.k === reg.k && (a.alvo.parte || 'corpo') === parte &&
          (a.alvo.disp || '') === pedido.comps.join('|')) {
        comps = a.ir_para.split('|');
      }
    });
    var mapa = (anc && anc[parte]) || {};
    var achou = null, d, ch;
    for (d = comps.length; d >= 1 && !achou; d--) {
      ch = comps.slice(0, d).join('|');
      if (!temProp(mapa, ch)) continue;
      var e = mapa[ch];
      if (e && e.c && c) achou = { v: 'c', frag: e.c, d: d };
      else if (e && e.h) achou = { v: 'h', frag: e.h, d: d };
    }
    if (achou) {
      var p = pagina(achou.v, achou.frag);
      var outra = achou.v === 'c' ? 'h' : 'c', alt = null;
      if (temAlt) {
        var fa = null;
        for (d = achou.d; d >= 1; d--) {
          ch = comps.slice(0, d).join('|');
          if (temProp(mapa, ch) && mapa[ch] && mapa[ch][outra]) { fa = mapa[ch][outra]; break; }
        }
        alt = pagina(outra, fa);
      }
      var nota = achou.d < comps.length
        ? rotuloFalta(comps.slice(achou.d)) + ' não tem âncora própria; abrindo no ' + rotuloComps(comps.slice(0, achou.d), parte) + '.'
        : null;
      return { url: p.url, versao: p.versao, fragmento: p.fragmento, profundidade: achou.d, alt: alt, dica: null, nota: nota };
    }
    var p1 = pagina(vPrinc, null);
    return { url: p1.url, versao: p1.versao, fragmento: null, profundidade: 0,
      alt: temAlt ? pagina(vOutra, null) : null,
      dica: 'Art. ' + comps[0] + (parte === 'adct' ? ' do ADCT' : ''), nota: null };
  }

  /* ------------------------------------------------------------------ texto livre (§9.6) */

  var STOP = new Set(('a o e de da do das dos em no na nos nas para por com sobre que se ao aos lei leis dispoe ' +
    'outras providencias altera da-se institui um uma').split(' '));

  function radical(w) {
    if (w.length > 4 && w.charAt(w.length - 1) === 's') w = w.slice(0, -1);
    if (w.length > 3) {
      var f = w.slice(-2);
      if (f === 'oe' || f === 'ae') w = w.slice(0, -2) + 'ao';
      else if (f === 'ai') w = w.slice(0, -2) + 'al';
      else if (f === 'ei') w = w.slice(0, -2) + 'el';
    }
    return w;
  }

  function tokensTexto(s) {
    return semMilhar(normBase(s)).split(/[^a-z0-9]+/).filter(function (w) {
      return w && !STOP.has(w);
    }).map(radical);
  }

  var cacheIndice = typeof WeakMap === 'function' ? new WeakMap() : null;

  function indiceTexto(registros, apc) {
    var porApc = cacheIndice && cacheIndice.get(registros);
    if (porApc && porApc.apc === apc) return porApc.ind;
    var df = new Map();
    var docs = registros.map(function (r) {
      var extra = (apc && apc.termosDe[r.k]) || [];
      var set = new Set(tokensTexto((r.e || '') + ' ' + nomeRegistro(r) + ' ' + extra.join(' ')));
      set.forEach(function (t) { df.set(t, (df.get(t) || 0) + 1); });
      return { r: r, set: set };
    });
    var ind = { docs: docs, df: df, N: registros.length };
    if (cacheIndice) cacheIndice.set(registros, { apc: apc, ind: ind });
    return ind;
  }

  function contemTermo(texto, termo) {
    return new RegExp('(^|[^a-z0-9])' + escaparRe(termo) + '(?![a-z0-9])').test(texto);
  }

  function alvosDoTopo(q, apc) {
    var topo = [];
    function add(k) { if (topo.indexOf(k) < 0) topo.push(k); }
    if (!apc) return topo;
    var base = normBase(q);
    trocarApelidos(base, apc).achados.forEach(function (idx) {
      var e = apc.entradas[idx];
      if (!e) return;
      if (e.tipo === 'apelido') add(e.alvo); else e.alvos.forEach(add);
    });
    var n = colapsar(semMilhar(base));
    apc.assuntos.forEach(function (s) {
      if (s.termos.some(function (t) { return contemTermo(n, t); })) s.alvos.forEach(add);
    });
    return topo;
  }

  function itemDe(r, apc, cfg, destino) {
    return {
      k: r.k, nome: nomeRegistro(r), nomeCurto: nomeCurtoDe(r, apc), ementa: r.e || '',
      paginaNorma: paginaNorma(r.k), destino: destino || escolherDestino(r, null, null, [], cfg)
    };
  }

  function nomeCurtoDe(r, apc) {
    return (apc && temProp(apc.siglaDe, r.k)) ? apc.siglaDe[r.k] : nomeRegistro(r);
  }

  function buscarTexto(q, registros, apc, cfg) {
    registros = registros || [];
    var ind = indiceTexto(registros, apc);
    var Q = Array.from(new Set(tokensTexto(q)));
    var porK = new Map();
    registros.forEach(function (r) { porK.set(r.k, r); });
    var topo = alvosDoTopo(q, apc).filter(function (k) { return porK.has(k); });
    var alvos = apc ? apc.alvosApelido : new Set();
    var achados = [];
    if (Q.length) {
      var minimo = Math.max(1, Math.ceil(Q.length / 2));
      var idf = {};
      Q.forEach(function (t) { var d = ind.df.get(t) || 0; idf[t] = d ? Math.log(1 + ind.N / d) : 0; });
      ind.docs.forEach(function (doc) {
        var n = 0, s = 0;
        for (var i = 0; i < Q.length; i++) { if (doc.set.has(Q[i])) { n++; s += idf[Q[i]]; } }
        if (n >= minimo && n > 0) achados.push({ r: doc.r, s: s - 0.02 * doc.set.size });
      });
    }
    achados.sort(function (a, b) {
      if (b.s !== a.s) return b.s - a.s;
      var aa = temAlvo(alvos, a.r.k) ? 0 : 1, ab = temAlvo(alvos, b.r.k) ? 0 : 1;
      if (aa !== ab) return aa - ab;
      if (b.r.a !== a.r.a) return b.r.a - a.r.a;
      return cmpTupla(ordemChave(a.r.k), ordemChave(b.r.k));
    });
    var vistos = new Set(), saida = [];
    topo.forEach(function (k) { vistos.add(k); saida.push(porK.get(k)); });
    achados.forEach(function (a) { if (!vistos.has(a.r.k)) { vistos.add(a.r.k); saida.push(a.r); } });
    return saida.slice(0, 20).map(function (r) { return itemDe(r, apc, cfg); });
  }

  /* ------------------------------------------------------------------ resolução (§9.5) */

  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function nomeShard(tsig, numero) { return tsig === 'cf' ? 'n-cf-00' : 'n-' + tsig + '-' + pad2(Math.floor(numero / 1000)); }

  function casaAno(a, ano) {
    if (!ano) return true;
    var s = String(ano);
    if (s.length === 4) return a === parseInt(s, 10);
    if (s.length === 2) return a % 100 === parseInt(s, 10);
    return false;
  }

  function slugDe(caminho) {
    return String(caminho || '').split('/').pop().replace(/\.html?$/i, '').toLowerCase();
  }

  function criarContexto(fonte, man, apPub, apc, avisos, cfg) {
    var shards = {}, ancs = {}, indiceAnc = null;
    var ctx = {
      fonte: fonte, man: man || { shards: {} }, apc: apc, avisos: avisos || [], cfg: cfg,
      desempate: (apPub && apPub.desempate) || {},
      shard: function (nome) {
        if (!temProp(ctx.man.shards, nome)) return Promise.resolve([]);
        if (!shards[nome]) shards[nome] = Promise.resolve(fonte.shard(nome)).then(function (x) { return x || []; });
        return shards[nome];
      },
      doNumero: function (tsig, numero) {
        return ctx.shard(nomeShard(tsig, numero)).then(function (rs) {
          return rs.filter(function (r) { return r.n === numero && tsigDe(r.k) === tsig; });
        });
      },
      todosDoNumero: function (numero) {
        var suf = '-' + pad2(Math.floor(numero / 1000));
        var nomes = Object.keys(ctx.man.shards).filter(function (n) { return /^n-[a-z]+-\d+$/.test(n) && n.slice(-suf.length) === suf && n !== 'n-cf-00'; }).sort();
        return Promise.all(nomes.map(ctx.shard)).then(function (ls) {
          var out = [];
          ls.forEach(function (rs) { rs.forEach(function (r) { if (r.n === numero && r.k !== CHAVE_CF) out.push(r); }); });
          return out;
        });
      },
      todos: function () {
        var nomes = Object.keys(ctx.man.shards).sort();
        return Promise.all(nomes.map(ctx.shard)).then(function (ls) { return [].concat.apply([], ls); });
      },
      registro: function (k) {
        if (!chaveValida(k)) return Promise.resolve(null);
        var p = partesChave(k);
        return ctx.shard(nomeShard(p[0], p[1])).then(function (rs) {
          for (var i = 0; i < rs.length; i++) { if (rs[i].k === k) return rs[i]; }
          return null;
        });
      },
      ancoras: function (k) {
        if (!indiceAnc) {
          indiceAnc = Promise.resolve(fonte.ancorasIndice()).then(function (l) { return new Set(l || []); });
        }
        return indiceAnc.then(function (set) {
          if (!set.has(k)) return null;
          if (!ancs[k]) ancs[k] = Promise.resolve(fonte.ancoras(k)).catch(function () { return null; });
          return ancs[k];
        });
      }
    };
    return ctx;
  }

  function ordenar(ctx, regs, grupo) {
    var alvos = ctx.apc.alvosApelido;
    var ord = ordemPublica(regs, alvos);
    var pref = grupo && temProp(ctx.desempate, grupo) ? ctx.desempate[grupo] : null;
    if (pref && ord.length && !temAlvo(alvos, ord[0].k)) {
      var i = -1;
      for (var x = 0; x < ord.length; x++) { if (ord[x].k === pref) { i = x; break; } }
      if (i > 0) ord.unshift(ord.splice(i, 1)[0]);
    }
    return ord;
  }

  function outrasDe(ctx, reg, letraPedida) {
    var p = partesChave(reg.k);
    return ctx.todosDoNumero(p[1]).then(function (rs) {
      var outras = rs.filter(function (r) {
        if (r.k === reg.k) return false;
        if ((r.l || '') === (reg.l || '')) return true;
        return !letraPedida && !reg.l && tsigDe(r.k) === p[0];
      });
      return ordenar(ctx, outras, 'num:' + p[1] + (reg.l || '')).map(function (r) { return r.k; });
    });
  }

  function descrNada(tsig, numero, letra) {
    return (NOME_TIPO[tsig] || 'Norma') + ' nº ' + milhar(numero) + (letra ? '-' + letra.toUpperCase() : '');
  }

  /** Resolve uma NORMA da análise em {exato}, {lista} ou {nada}. */
  function resolverNorma(ctx, nm) {
    var apc = ctx.apc;
    if (nm.via === 'apl') {
      var e = apc.entradas[nm.idx];
      if (!e) return Promise.resolve({ nada: 'Apelido sem alvo.' });
      if (e.tipo === 'apelido') {
        return ctx.registro(e.alvo).then(function (r) {
          return r ? { exato: r, outras: [], nota: e.nota || '' } : { nada: 'A norma deste apelido não está no índice.' };
        });
      }
      return Promise.all(e.alvos.map(ctx.registro)).then(function (rs) {
        rs = rs.filter(Boolean);
        return rs.length ? { lista: rs, mensagem: e.nota || '', curada: true } : { nada: 'Nenhuma norma desta lista está no índice.' };
      });
    }
    if (nm.via === 'adct') {
      return ctx.registro(CHAVE_CF).then(function (r) { return r ? { exato: r, outras: [] } : { nada: 'A Constituição não está no índice.' }; });
    }
    if (nm.via === 'arq') return resolverArq(ctx, nm.arq, nm.ano);
    if (nm.via === 'tipo') return resolverTipo(ctx, nm);
    if (nm.via === 'numano') return resolverNumAno(ctx, nm);
    if (nm.via === 'num') return resolverNumSolto(ctx, nm);
    return Promise.resolve({ nada: 'Consulta não reconhecida.' });
  }

  function comOutras(ctx, r, letraPedida, extra) {
    return outrasDe(ctx, r, letraPedida).then(function (o) {
      var res = { exato: r, outras: o };
      if (extra) res.nota = extra;
      return res;
    });
  }

  function resolverTipo(ctx, nm) {
    return ctx.doNumero(nm.tsig, nm.numero).then(function (mesmos) {
      var cand;
      if (nm.letraPedida) cand = mesmos.filter(function (r) { return (r.l || '') === nm.letra; });
      else {
        cand = mesmos.filter(function (r) { return !r.l; });
        if (!cand.length) cand = mesmos;
      }
      var semAno = cand;
      if (nm.ano) cand = cand.filter(function (r) { return casaAno(r.a, nm.ano); });
      var d = descrNada(nm.tsig, nm.numero, nm.letraPedida ? nm.letra : '');
      if (!cand.length) {
        if (nm.ano && semAno.length) {
          return { nada: 'Sem ' + d + ' de ' + nm.ano + '. Há: ' + ordenar(ctx, semAno, null).map(nomeRegistro).join('; ') + '.' };
        }
        return { nada: 'Não encontrei ' + d + ' no índice do Planalto Direto.' };
      }
      if (cand.length === 1) return comOutras(ctx, cand[0], nm.letraPedida);
      return { lista: ordenar(ctx, cand, nm.tsig + ':' + nm.numero + (nm.letraPedida ? nm.letra : '')) };
    });
  }

  function resolverArq(ctx, a, ano) {
    if (a.cf) return ctx.registro(CHAVE_CF).then(function (r) { return r ? { exato: r, outras: [] } : { nada: 'A Constituição não está no índice.' }; });
    return ctx.doNumero(a.tsig, a.numero).then(function (rs) {
      var cand = rs.filter(function (r) { return slugDe(r.u) === a.slug || (r.c && slugDe(r.c) === a.slug); });
      if (ano) {
        var ca = cand.filter(function (r) { return casaAno(r.a, ano); });
        if (ca.length) cand = ca;
      }
      if (cand.length === 1) return comOutras(ctx, cand[0], !!cand[0].l);
      if (cand.length > 1) return { lista: ordenar(ctx, cand, a.tsig + ':' + a.numero + (cand[0].l || '')) };
      return resolverTipo(ctx, { tsig: a.tsig, numero: a.numero, letra: a.letra, letraPedida: !!a.letra, ano: ano || null });
    });
  }

  function resolverNumAno(ctx, nm) {
    return ctx.todosDoNumero(nm.numero).then(function (rs) {
      rs = rs.filter(function (r) { return (r.l || '') === (nm.letra || '') && casaAno(r.a, nm.ano); });
      var leis = rs.filter(function (r) { return tsigDe(r.k) === 'lei'; });
      var cand = leis.length ? leis : rs;
      if (!cand.length) return { nada: 'Sem norma nº ' + milhar(nm.numero) + (nm.letra ? '-' + nm.letra.toUpperCase() : '') + ' de ' + nm.ano + ' no índice.' };
      if (cand.length === 1) return comOutras(ctx, cand[0], !!nm.letra);
      return { lista: ordenar(ctx, cand, 'num:' + nm.numero + (nm.letra || '')) };
    });
  }

  function resolverNumSolto(ctx, nm) {
    return ctx.todosDoNumero(nm.numero).then(function (rs) {
      var cand = rs.filter(function (r) { return (r.l || '') === (nm.letra || ''); });
      if (nm.ano) cand = cand.filter(function (r) { return casaAno(r.a, nm.ano); });
      var resto = nm.letra ? [] : rs.filter(function (r) { return r.l && (!nm.ano || casaAno(r.a, nm.ano)); });
      if (!cand.length && !resto.length) return { nada: 'Nenhuma norma com o nº ' + milhar(nm.numero) + ' no índice.' };
      var ord = ordenar(ctx, cand, 'num:' + nm.numero + (nm.letra || ''));
      return { lista: ord.concat(ordemPublica(resto, ctx.apc.alvosApelido)) };
    });
  }

  function resolverUrl(ctx, caminho) {
    caminho = caminho.replace(/^\/+/, '');
    var arquivo = caminho.split('/').pop();
    var tsig = null;
    if (/(^|\/)decreto-lei\//.test(caminho)) tsig = 'dl';
    else if (/(^|\/)mpv\//.test(caminho)) tsig = 'mp';
    else if (/(^|\/)lcp\//.test(caminho)) tsig = 'lc';
    else if (/(^|\/)emc\//.test(caminho)) tsig = 'ec';
    else if (/(^|\/)ecr\//.test(caminho)) tsig = 'ecr';
    else if (/(^|\/)ldl\//.test(caminho)) tsig = 'ld';
    else if (/^constituicao\/constituicao/.test(caminho)) tsig = 'cf';
    if (tsig === 'cf') return resolverArq(ctx, { cf: true });
    var info = lerArq(arquivo);
    if (!tsig) tsig = info && !info.cf ? info.tsig : 'lei';
    var numero = info && !info.cf ? info.numero : null;
    if (numero === null) {
      var m = /^0*(\d+)/.exec(arquivo);
      if (m) numero = parseInt(m[1], 10);
    }
    if (numero === null || isNaN(numero)) return Promise.resolve({ nada: 'Não reconheci a norma deste endereço do Planalto.' });
    return ctx.doNumero(tsig, numero).then(function (rs) {
      var exatos = rs.filter(function (r) {
        return r.u.toLowerCase() === caminho || (r.c && r.c.toLowerCase() === caminho);
      });
      if (exatos.length === 1) return comOutras(ctx, exatos[0], !!exatos[0].l);
      if (exatos.length > 1) return { lista: ordenar(ctx, exatos, tsig + ':' + numero) };
      var slug = slugDe(arquivo);
      var a = info && !info.cf ? info : { cf: false, tsig: tsig, numero: numero, letra: '', reed: '', slug: slug };
      a = { cf: false, tsig: tsig, numero: numero, letra: a.letra || '', reed: a.reed || '', slug: slug };
      return resolverArq(ctx, a, null);
    });
  }

  function rotuloVersao(v) {
    return v === 'c' ? 'texto compilado' : 'texto com histórico (trechos riscados são redação antiga)';
  }

  function rotuloAlternativo(v) { return v === 'c' ? 'texto compilado' : 'com histórico'; }

  function textoTransicao(ref) {
    return 'Abrindo ' + ref.nomeCurto + (ref.rotuloPedido ? ' ' + ref.rotuloPedido : '') + ' — ' + rotuloVersao(ref.destino.versao);
  }

  function montarRef(ctx, reg, art, outras, notaNorma) {
    var pedido = art ? { parte: art.parte || 'corpo', comps: art.comps.slice() } : null;
    var pAnc = pedido ? ctx.ancoras(reg.k) : Promise.resolve(null);
    return pAnc.then(function (anc) {
      var destino = escolherDestino(reg, anc, pedido, ctx.avisos, ctx.cfg);
      var notas = [];
      if (notaNorma) notas.push(notaNorma);
      if (art && art.intervalo) notas.push('Intervalo: abrindo o ' + rotuloComp(art.intervalo[0], false, true) + '.');
      var ref = {
        k: reg.k, nome: nomeRegistro(reg), nomeCurto: nomeCurtoDe(reg, ctx.apc), pedido: pedido,
        rotuloPedido: pedido ? rotuloComps(pedido.comps, pedido.parte) : '', destino: destino, outras: outras || []
      };
      if (notas.length) ref.nota = notas.join(' ');
      return {
        ref: ref, avisos: avisosDaRef(ctx.avisos, reg.k, pedido),
        naoEncontrado: !!(pedido && anc && !destino.fragmento)
      };
    });
  }

  function juntarAvisos(listas) {
    var vistos = {}, out = [];
    listas.forEach(function (l) { l.forEach(function (a) { if (!vistos[a.id]) { vistos[a.id] = 1; out.push(a); } }); });
    return out;
  }

  function resultadoLista(ctx, consulta, res, arts) {
    var art = arts && arts.length ? arts[0] : null;
    return Promise.all(res.lista.map(function (r) {
      if (!art) return itemDe(r, ctx.apc, ctx.cfg);
      return montarRef(ctx, r, art, [], null).then(function (m) { return itemDe(r, ctx.apc, ctx.cfg, m.ref.destino); });
    })).then(function (itens) {
      var avisos = juntarAvisos(res.lista.map(function (r) {
        return avisosDaRef(ctx.avisos, r.k, art ? { parte: art.parte || 'corpo', comps: art.comps } : null);
      }));
      var R = { tipo: 'lista', consulta: consulta, itens: itens, avisos: avisos };
      if (res.mensagem) R.mensagem = res.mensagem;
      return R;
    });
  }

  function resultadoTexto(ctx, consulta) {
    return ctx.todos().then(function (regs) {
      var itens = buscarTexto(consulta, regs, ctx.apc, ctx.cfg);
      if (!itens.length) return { tipo: 'nada', consulta: consulta, mensagem: 'Nada encontrado para “' + consulta + '”.', avisos: [] };
      return { tipo: 'texto', consulta: consulta, itens: itens, avisos: [] };
    });
  }

  /** Resolve a consulta. fonte: {manifesto, shard, ancorasIndice, ancoras, apelidos, avisos}. */
  function resolver(consulta, fonte, cfg) {
    cfg = cfg || {};
    consulta = String(consulta == null ? '' : consulta).trim();
    return Promise.all([fonte.manifesto(), fonte.apelidos(), fonte.avisos()]).then(function (d) {
      var apPub = d[1] || {};
      var apc = apcDe(apPub);
      var ctx = criarContexto(fonte, d[0], apPub, apc, d[2] || [], cfg);
      if (!consulta) return { tipo: 'nada', consulta: consulta, mensagem: 'Digite uma citação, como “clt 477”.', avisos: [] };
      var an = analisar(consulta, apc);
      var pendentes;
      if (an.via === 'url') {
        pendentes = [resolverUrl(ctx, an.caminho).then(function (res) { return { res: res, arts: [] }; })];
      } else {
        if (an.fora) return { tipo: 'fora_escopo', consulta: consulta, mensagem: an.fora, avisos: [] };
        if (an.sobra || !an.grupos.length) {
          if (!an.temLetras && !an.grupos.length) return { tipo: 'nada', consulta: consulta, mensagem: 'Nada encontrado para “' + consulta + '”.', avisos: [] };
          return resultadoTexto(ctx, consulta);
        }
        pendentes = an.grupos.map(function (g) {
          return resolverNorma(ctx, g.norma).then(function (res) { return { res: res, arts: g.arts }; });
        });
      }
      return Promise.all(pendentes).then(function (rs) {
        for (var i = 0; i < rs.length; i++) {
          if (rs[i].res.lista) return resultadoLista(ctx, consulta, rs[i].res, rs[i].arts);
        }
        var nadas = rs.filter(function (x) { return x.res.nada; }).map(function (x) { return x.res.nada; });
        var refsP = [];
        rs.forEach(function (x) {
          if (!x.res.exato) return;
          if (!x.arts.length) refsP.push(montarRef(ctx, x.res.exato, null, x.res.outras, x.res.nota));
          else x.arts.forEach(function (a) { refsP.push(montarRef(ctx, x.res.exato, a, x.res.outras, x.res.nota)); });
        });
        if (!refsP.length) return { tipo: 'nada', consulta: consulta, mensagem: nadas.join(' ') || 'Nada encontrado.', avisos: [] };
        return Promise.all(refsP).then(function (ms) {
          var R = { consulta: consulta, refs: ms.map(function (m) { return m.ref; }), avisos: juntarAvisos(ms.map(function (m) { return m.avisos; })) };
          if (ms.length === 1) {
            if (ms[0].naoEncontrado) {
              R.tipo = 'artigo_nao_encontrado';
              R.mensagem = 'Não encontrei o art. ' + ms[0].ref.pedido.comps[0] +
                (ms[0].ref.pedido.parte === 'adct' ? ' do ADCT' : '') + ' na tabela de âncoras de ' + ms[0].ref.nome + '. Ele pode não existir.';
            } else {
              R.tipo = 'exato';
            }
          } else {
            R.tipo = 'multiplo';
          }
          if (nadas.length) R.mensagem = (R.mensagem ? R.mensagem + ' ' : '') + nadas.join(' ');
          return R;
        });
      });
    });
  }

  /* ------------------------------------------------------------------ rotas curtas (§10.5) */

  function rotaParaConsulta(pathname, sitePath) {
    var p;
    try { p = decodeURIComponent(pathname); } catch (e) { p = pathname; }
    if (typeof p !== 'string' || typeof sitePath !== 'string' || p.indexOf(sitePath) !== 0) return null;
    p = p.slice(sitePath.length).replace(/(^|\/)index\.html$/, '').replace(/^\/+|\/+$/g, '');
    var seg = p.split('/').filter(Boolean);
    if (!seg.length) return null;
    var t = seg[0].toLowerCase();
    if (TIPOS.indexOf(t) >= 0 && seg.length > 1) {
      var resto = seg.length > 2 ? ' art ' + seg.slice(2).join(' ') : '';
      var m = /^(\d+)([a-z])?-(\d{4})$/i.exec(seg[1]);
      if (m) return t + ' ' + m[1] + (m[2] ? m[2].toLowerCase() : '') + '/' + m[3] + resto;
      if (/^\d+[a-z]?$/i.test(seg[1])) return t + ' ' + seg[1] + resto;
    }
    return seg.join(' ');
  }

  return {
    normalizar: normalizar, prepararApelidos: prepararApelidos, analisar: analisar, resolver: resolver,
    escolherDestino: escolherDestino, montarUrl: montarUrl, codificarFragmento: codificarFragmento,
    nomeNorma: nomeNorma, buscarTexto: buscarTexto, rotaParaConsulta: rotaParaConsulta, VERSAO: 1,
    // auxiliares (aditivos; usados pela interface e pelos testes)
    ordemPublica: ordemPublica, ordemChave: ordemChave, nomeRegistro: nomeRegistro, paginaNorma: paginaNorma,
    rotuloVersao: rotuloVersao, rotuloAlternativo: rotuloAlternativo, textoTransicao: textoTransicao,
    rotuloComps: rotuloComps, normTermo: normTermo, tokensTexto: tokensTexto, TIPOS: TIPOS.slice()
  };
});
