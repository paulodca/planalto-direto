# Planalto Direto

## O que é

O **Planalto Direto** é um atalho para a legislação federal publicada no portal do Planalto
(`planalto.gov.br/ccivil_03`). Você digita a citação como escreveria numa peça — `clt 477`,
`lei 8.036/90 art 3`, `Del5452`, `lc 150 art 7`, `art 7 xxix cf`, `adct 76`, "aviso prévio
proporcional" — e o seu navegador é levado à página da lei no Planalto, já no artigo quando há
âncora conferida.

- Site: <https://paulodca.github.io/planalto-direto/>
- É um site estático (GitHub Pages), sem servidor de aplicação, sem cookies e sem analytics.
  O site é gerado e publicado pelo GitHub Actions a partir de `base/`, `fontes/` e `modelos/`;
  as páginas geradas não ficam no repositório.
- O site guarda só o **índice** das normas (número, ano, ementa, rótulo, caminho da página) e os
  **nomes das âncoras**. Nenhum texto de lei é copiado: quem abre a lei é o seu navegador, direto
  no Planalto.
- Cada norma tem uma página própria (`lei/8036-1990/`, `dl/5452-1943/`, `cf/1988/`…), que funciona
  sem JavaScript.
- Rotas curtas também funcionam: `/planalto-direto/clt/477`, `/planalto-direto/lei/8036/3`.

## Aviso

Ferramenta não oficial, sem vínculo com a Presidência da República. Sempre confira na fonte.

- A situação de vigência **não** é verificada pelo Planalto Direto, salvo quando há um aviso
  curado e conferido na própria página do Planalto.
- O link pode levar ao "texto compilado" ou ao "texto com histórico" (onde trechos riscados são
  redação antiga). A página de cada norma mostra as duas versões, quando existem.

## Como gerar o site

Quem publica o site é o GitHub Actions (`.github/workflows/pages.yml`): a cada push na `main` que
mexa em `base/`, `fontes/`, `modelos/`, `build/`, `pd/` ou `docs/` (ou por disparo manual), ele roda
o estágio B, confere o determinismo com `--verificar` e publica `docs/` no Pages. O que o estágio B
gera em `docs/` está no `.gitignore` e **não** vai para o git; as fontes de `docs/` (`config.js`,
`assets/`, `.nojekyll`, `favicon.svg`) continuam versionadas.

O build local continua possível, para testar antes do push. Requisitos: Python 3.12 ou mais novo (só a biblioteca padrão). Rode tudo **a partir da raiz do
repositório**, sempre com `python -P`.

```
python -P build/gerar_site.py
```

O estágio B lê `base/`, `fontes/`, `modelos/` e `docs/config.js` e gera, dentro de `docs/`:
`dados/` (índice dividido por tipo e milhar, âncoras por norma, apelidos, áreas e avisos), uma
página por norma, `index.html`, `404.html`, `opensearch.xml`, `robots.txt`, `sitemap.xml` e
`.gerado`. A saída é determinística: a mesma base produz os mesmos bytes.

- `--verificar`: gera em memória e compara com `docs/`, sem gravar (sai com código 1 se diferir).
- `--so-dados`: gera só `docs/dados/`.
- `--base`, `--fontes`, `--modelos`, `--saida`, `--config`: outras pastas de entrada e saída.
- Limpeza segura: só são apagados os arquivos listados em `docs/.gerado` pela execução anterior.
  Os arquivos escritos à mão (`docs/config.js`, `docs/.nojekyll`, `docs/favicon.svg`,
  `docs/assets/`) nunca são tocados.
- Se algum alvo de `fontes/` não existir na base, ou a base tiver um formato inválido, nada é
  gravado e o comando sai com código 1.

### Configuração

Tudo o que pode mudar fica num só arquivo, `docs/config.js`: a base do Planalto
(`PLANALTO_BASE`), o endereço do site (`SITE_URL`, `SITE_PATH`), o repositório (`REPO_URL`), o
formulário de sugestões (`SUGESTAO_URL`, `SUGESTAO_CAMPO`), a meta de verificação do buscador
(`GOOGLE_VERIFICACAO`) e as esperas da tela de transição. Depois de editar, rode o estágio B para
testar; no push, o Actions gera e publica o site.

### Curadoria (`fontes/`)

- `apelidos.json`: siglas e nomes populares (CLT, CPC, "lei de greve"…), listas curtas
  ("lei de licitações"), assuntos e consultas fora do escopo. Arrays em ordem de chave da norma.
- `areas.json`: as áreas da página inicial (Trabalho e Processo do Trabalho primeiro).
- `avisos.json`: avisos curados. Um aviso só aparece no site depois de conferido por
  `testes/confere_avisos.py` contra uma cópia local da página do Planalto (campo `conferido_em`).
- `caminhos.json`: substituições de caminho conferidas à mão.

### Base (`base/`)

`base/` é a base pública (índice e âncoras) da qual o site é gerado. Ela é montada pelo estágio A
(`build/montar_base.py`), que roda só na máquina do mantenedor, com insumos privados passados por
argumento ou variável de ambiente; o atualizador (abaixo) acrescenta normas novas a ela.

## Como testar

```
python -P -B -m unittest discover -s testes/py -t .
python -P -B testes/rodar_tudo.py --rapido
python -P -B testes/rodar_tudo.py
```

`testes/rodar_tudo.py` imprime uma tabela `checagem | PASS/FAIL/SKIP | detalhe` e sai com código
diferente de zero se houver FAIL. SKIP não é aprovação. As checagens:

| id | o que confere |
|---|---|
| U0 | todo script de entrada responde `--help` com `python -P`, de outra pasta |
| U1 | unitários Python |
| U2 | determinismo (`gerar_site.py --verificar`; `montar_base.py --verificar` quando há insumos) |
| U3 | atualizador offline contra as páginas locais |
| J1 | `node --test` sobre o resolvedor `docs/assets/nucleo.js` |
| (a) | casos de busca no navegador (Chrome ou Edge sem interface) |
| (b) | amostra de links contra as páginas locais do Planalto (estático e no navegador) |
| (b2) | avisos conferidos (`testes/confere_avisos.py`) |
| (c) | rodapé visível, marcas proibidas, links sob o subcaminho |
| (d) | vazamento (`testes/vazamento.py`) |
| (e) | Semgrep (`testes/semgrep.py`) |
| (f) | celular, página inicial leve, nenhuma requisição a terceiros |

Os insumos privados entram só por argumento ou variável de ambiente, nunca por caminho fixo:
`--cache-html` / `PD_CACHE_HTML` (cópia local das páginas do Planalto), `--termos-proibidos` /
`PD_TERMOS_PROIBIDOS`, `--lista-privada` / `PD_LISTA_PRIVADA` (várias, separadas por `;`),
`--ancoras` / `PD_ANCORAS`, `--navegador` / `PD_NAVEGADOR`. Sem o insumo, a checagem dá SKIP.

Saídas de teste ficam em `testes/.saida/`, que o git ignora.

## Atualizar o índice

Veja [`atualizador/LEIAME.md`](atualizador/LEIAME.md).

## Passo a passo do mantenedor

Os comandos abaixo usam variáveis de ambiente. Os valores (caminhos da sua máquina) ficam só na
sua máquina, num script fora do repositório; nunca no repositório.

### Build e publicação

1. Numa sessão fora do repositório, defina `PD_SNAPSHOT`, `PD_ANCORAS`, `PD_ANCORAS_TODAS`,
   `PD_COMPILADOS`, `PD_LISTA_PRIVADA` (para as checagens, a lista privada e o mapa de compilados,
   separados por `;`), `PD_CACHE_HTML` e `PD_TERMOS_PROIBIDOS`.
2. Confira a identidade local do git: `git config user.name` = `paulodca` e
   `git config user.email` = `307681474+paulodca@users.noreply.github.com`. Nunca use um e-mail
   pessoal nos commits.
3. `python -P -B build/montar_base.py --relatorio <arquivo fora do repositório>`
   (o estágio A exige `PD_CACHE_HTML`).
4. `python -P -B build/gerar_site.py` (build local, para as checagens; o site publicado é gerado
   pelo Actions)
5. `python -P -B testes/confere_avisos.py --gravar --data AAAA-MM-DD` e de novo o passo 4. Os
   avisos que não passarem ficam fora do site e aparecem na lista de pendentes.
6. `python -P -B testes/rodar_tudo.py` com `--cache-html`, `--termos-proibidos`,
   `--lista-privada` e `--ancoras` (ou as variáveis acima), mais `--semgrep-registro` (baixa os
   pacotes `p/python`, `p/javascript` e `p/secrets` do registro, sem métricas e sem enviar código). Tudo PASS, ou SKIP só do Semgrep com a
   razão registrada.
7. Antes de qualquer push, nesta ordem:
   1. `git add` explícito das pastas do projeto
      (`git add README.md LICENSE .gitignore .github pd build modelos fontes base atualizador docs testes`),
      nunca `git add -A`; o `.gitignore` deixa de fora o que o estágio B gera em `docs/`;
   2. `git status --porcelain` e conferir que não entrou nada inesperado (relatório, arquivo
      `.jsonl` privado, amostra de teste);
   3. `python -P -B testes/vazamento.py --historico` com os termos, a lista privada e as âncoras → PASS;
   4. `git commit`;
   5. de novo `testes/vazamento.py --historico` (pega o commit recém-criado e seus metadados) → PASS.
8. O primeiro push é um único commit com a base completa (junte o histórico local num commit só),
   para que a ordem em que as âncoras foram geradas não fique visível. Pushes seguintes de âncoras
   novas: um commit por lote.
9. No GitHub, uma vez só e **antes do primeiro push**: **Settings → Pages → Build and deployment →
   Source: GitHub Actions** (não use "Deploy from a branch": o `docs/` do git não tem as páginas
   geradas). Se o push sair antes, ligue o Pages e rode **Actions → "Publicar o site (Pages)" →
   Run workflow**.
10. `git push`. O workflow "Publicar o site (Pages)" roda a cada push e publica o site.
11. Quando chegarem âncoras novas, repita os passos 3 a 10.

### Atualização numa máquina no Brasil

O passo a passo está em [`atualizador/LEIAME.md`](atualizador/LEIAME.md). O workflow
"Atualizar índice (manual)" do GitHub Actions só roda quando acionado à mão; se o Planalto barrar
o acesso, ele termina sem publicar nada. Com "publicar", ele faz o commit só de `base/` e chama o
workflow do Pages em seguida (um push feito com o token padrão do Actions não dispara outros
workflows sozinho).

### Google Search Console

1. Em search.google.com/search-console → **Adicionar propriedade** → **Prefixo do URL** →
   `https://paulodca.github.io/planalto-direto/`.
2. Verificação por **tag HTML**: copie só o valor do `content` da meta tag para
   `GOOGLE_VERIFICACAO` em `docs/config.js`, faça commit e push, espere o workflow do Pages
   publicar (2 a 3 min) e clique em **Verificar**.
3. **Sitemaps** → enviar `https://paulodca.github.io/planalto-direto/sitemap.xml`. (O `robots.txt`
   do subcaminho é gerado só por completude: os robôs leem o da raiz do domínio.)
4. **Inspeção de URL** em 3 páginas (a inicial, `dl/5452-1943/`, `lei/8036-1990/`) →
   "Solicitar indexação".
5. Depois de 1 a 2 semanas, em **Páginas**, confira "Rastreada, mas não indexada"; páginas de leis
   sem ementa podem ficar de fora, e isso é esperado.

### Formulário de sugestões (sem login)

1. Crie um formulário em branco: "Planalto Direto — sugestões".
2. Pergunta 1, resposta curta: "O que você buscou?" (obrigatória). Pergunta 2, parágrafo:
   "O que você esperava encontrar?" (opcional).
3. Em **Configurações → Respostas**: não coletar e-mails; "Limitar a 1 resposta" desligado (ligado,
   exige login); em contas Workspace, desligue "Restringir a usuários da organização".
4. Menu **⋮ → Gerar link pré-preenchido**, escreva `TESTE` na pergunta 1 e copie o link. Ele
   termina em `…/viewform?usp=pp_url&entry.1234567890=TESTE`:
   - a parte até `usp=pp_url` vai para `SUGESTAO_URL`;
   - `entry.1234567890` vai para `SUGESTAO_CAMPO`, em `docs/config.js`.
5. Commit e push (o workflow do Pages publica o `config.js` novo). Teste uma busca sem resultado: "Sugerir esta busca" abre o formulário já
   preenchido. Sem formulário configurado, o link de sugestão abre uma issue no GitHub (exige conta).

## Licença e dados

- Código: licença MIT (veja [`LICENSE`](LICENSE)).
- Fonte do nome no topo das páginas: Questrial, licença SIL Open Font License 1.1, cortada só com
  as letras usadas (`docs/assets/marca.woff2`; licença em
  [`docs/assets/marca-OFL.txt`](docs/assets/marca-OFL.txt)).
- Dados: metadados públicos (número, data, ementa, endereço das páginas e nomes das âncoras) do
  portal da legislação da Presidência da República,
  <https://www.planalto.gov.br/ccivil_03/>. O texto das leis não é copiado; a fonte é sempre o
  Planalto.

## Autoria

paulodca
