# Atualizador do índice

O atualizador lê os índices (quadros) de normas do Planalto e mescla em `base/normas.jsonl` as normas novas e as alteradas. Depois disso, regenera o site localmente com `build/gerar_site.py`, para você conferir e testar. O site publicado não vem do seu commit: as páginas geradas em `docs/` ficam fora do git, e o GitHub Actions (`.github/workflows/pages.yml`) gera e publica o site a cada push que muda `base/`.

Ele usa só a biblioteca padrão do Python (3.12 ou mais novo). Não precisa de `pip install`.

## O que ele faz e o que não faz

- **Lê só os 65 índices** de `atualizador/lista_branca.json`: 59 quadros de normas e 6 páginas de navegação.
- **Nunca apaga.** Uma norma que sumiu do índice só aparece no relatório.
- **Não recalcula as normas que já estão na base.** A identidade de uma norma é o caminho dela no índice. Numa norma existente, só o rótulo e a ementa podem mudar, e toda mudança vai para o relatório.
- **Normas novas entram sem âncora.** O link abre a página da norma sem fragmento e mostra a dica "Ctrl+F". As âncoras só chegam quando o build completo roda de novo.
- **É gentil com o servidor:**
  - faz no máximo 1 requisição por segundo, com uma pequena variação aleatória, e no máximo 80 por execução (`--max-req`);
  - guarda as páginas num cache por 20 horas (`--cache-horas`);
  - para depois de 3 falhas seguidas, esperando 5 s e depois 10 s entre as tentativas.
- **Desconfia do que recebe.** Uma página com `TSPD` (o bloqueio anti-robô do Planalto) conta como falha, sempre. Também conta como falha, sempre, uma página sem `</html>`. Uma execução que traria mais de 500 normas novas é recusada; use `--aceitar-muitas` se isso for legítimo.
- **Regra dos 70%.** Uma página menor que 70% da **leitura anterior do próprio atualizador** conta como falha. A comparação usa o corpo cru guardado em `cache/` da pasta de estado (só corpo válido entra ali). O campo `bytes` de `base/indices.json` **não** é usado, porque a base inicial veio de HTML reformatado e o tamanho não é comparável. Sem leitura anterior (a primeira execução, um estado novo, ou o GitHub Actions, cuja pasta de estado é temporária), a regra dos 70% não se aplica: o relatório e a saída trazem só um aviso com a lista dos índices. Para que a regra valha, mantenha a mesma pasta `--estado` entre as execuções. Se um índice encolheu de verdade (mais de 30%), o atualizador vai parar nele em toda execução: confira a página no navegador e, se estiver certa, apague o arquivo dela em `cache/` da pasta de estado para aceitar o novo tamanho.
- **Uma execução por vez.** O arquivo `coleta.lock` fica na pasta de estado enquanto a execução roda.

A base do Planalto (`PLANALTO_BASE`) é lida de `docs/config.js`. Ela não está escrita em nenhum outro lugar.

## Rodar numa máquina no Brasil

O Planalto costuma barrar acessos de fora do Brasil. É o caso das máquinas do GitHub Actions, que ficam nos EUA. Por isso, o jeito confiável de atualizar é rodar o atualizador num computador com IP brasileiro.

Rode tudo **a partir da raiz do repositório**, com `python -P`. A pasta `.estado/` já está no `.gitignore`.

PowerShell (Windows):

```powershell
python -P atualizador\atualizar.py --estado .estado --modo ano-corrente
python -P testes\rodar_tudo.py --rapido
```

Bash (Linux/macOS):

```bash
python3 -P atualizador/atualizar.py --estado .estado --modo ano-corrente
python3 -P testes/rodar_tudo.py --rapido
```

**Leia o relatório** em `.estado/relatorios/atualizacao-AAAA-MM-DD.md`. A versão `.json` traz os mesmos dados. Ali estão:
- as normas novas, com nome, ementa e link;
- as alteradas, mostrando o antes e o depois;
- as que sumiram do índice;
- os conflitos;
- os quadros novos que o atualizador encontrou.

Se estiver tudo certo, faça o commit só de `base/` (e da lista branca, se ela mudou). O que o estágio B gera em `docs/` está no `.gitignore` e não vai para o git:

```bash
git add base atualizador/lista_branca.json
git commit -m "Atualização do índice"
git push
```

O push dispara o workflow "Publicar o site (Pages)", que gera o site a partir de `base/` e o publica. No GitHub, o Pages precisa estar configurado uma vez em **Settings → Pages → Build and deployment → Source: GitHub Actions**.

### Quando rodar cada modo

| modo | o que lê | quando usar |
|---|---|---|
| `ano-corrente` (padrão) | os quadros que cobrem o ano corrente: leis do ano, MPs da faixa, leis complementares e emendas constitucionais (4 a 6 requisições) | toda semana, ou todo dia |
| `todos` | os 65 índices (cerca de 1,5 min) | uma vez por mês |

Também dá para ler índices específicos da lista branca:

```bash
python -P atualizador/atualizar.py --estado .estado --indice LEIS/LCP/Quadro_Lcp.htm
```

### Ano novo e quadros novos

Na virada do ano, o Planalto cria quadros novos, por exemplo o de leis do novo ano e o de MPs de uma nova faixa de anos. O atualizador procura esses quadros nas páginas de navegação.

- **Sem a opção `--aceitar-novos-indices`:** os quadros encontrados só aparecem no relatório.
- **Com a opção:** os quadros são lidos e acrescentados a `atualizador/lista_branca.json`. Confira o relatório e inclua `atualizador/lista_branca.json` no commit.

## Opções

| opção | efeito |
|---|---|
| `--estado DIR` | pasta de estado com `cache/`, `coleta.lock`, `relatorios/` e `log.jsonl` (padrão: `.estado/`) |
| `--modo ano-corrente\|todos` | quais índices ler (veja a tabela acima) |
| `--indice CAMINHO ...` | lê só estes índices; precisam estar na lista branca |
| `--simular` | lê e mescla em memória, sem gravar nada além do relatório |
| `--sem-regerar` | grava `base/` sem rodar o estágio B |
| `--aceitar-novos-indices` | lê os quadros novos e os acrescenta à lista branca |
| `--aceitar-muitas` | aceita mais de 500 normas novas numa execução |
| `--remover-lock-velho` | remove um `coleta.lock` com mais de 3 horas (sobra de uma execução interrompida) |
| `--cache-horas N` | validade do cache, em horas (padrão: 20) |
| `--max-req N` | teto de requisições por execução (padrão: 80) |
| `--offline-cache-raiz DIR` | lê os índices de uma cópia em disco, no formato `DIR/www.planalto.gov.br/ccivil_03/...`, sem rede |
| `--base DIR` | pasta da base pública (padrão: `base/`) |
| `--hoje AAAA-MM-DD` | data da execução; o padrão é a data do dia |

## Códigos de saída

| código | significado | o que fazer |
|---|---|---|
| 0 | ok, com ou sem novidade | ler o relatório; fazer o commit se houver mudança |
| 2 | **parada** (3 falhas seguidas, bloqueio TSPD, página truncada ou teto de requisições); **nada foi gravado** | tentar mais tarde, de uma máquina no Brasil |
| 3 | outra execução em andamento, ou lock velho | esperar; se tiver certeza de que nada está rodando, usar `--remover-lock-velho` |
| 4 | erro de dados: um gate falhou (chave repetida, ementa com status, mais de 500 normas novas, esquema) e nada foi gravado | ler o relatório e decidir |

## GitHub Actions

O workflow `.github/workflows/atualizar.yml` só roda quando é disparado à mão: **Actions → "Atualizar índice (manual)" → Run workflow**. Ele não tem agendamento.

- Na execução, escolha o modo. Marque "publicar" só se quiser que o próprio workflow faça o commit e o push de `base/`, com a identidade `github-actions[bot]`.
- Um push feito com o token padrão do Actions (`GITHUB_TOKEN`) **não** dispara o gatilho `push` de outros workflows. Por isso, quando há commit novo, o job `pages` do `atualizar.yml` chama `.github/workflows/pages.yml` diretamente (`workflow_call`), passando o commit que acabou de ser enviado. Sem commit novo, nada é publicado.
- A pasta de estado do Actions é temporária: lá a regra dos 70% nunca se aplica (só o aviso); `TSPD` e `</html>` continuam valendo.
- Se o Planalto barrar o IP do GitHub, o passo "Atualizar" sai com código 2 e nada é publicado.
- O relatório fica disponível como artefato da execução.

## Teste de aceitação sem rede

Com uma cópia local dos índices, rode:

```bash
python -P atualizador/atualizar.py --offline-cache-raiz DIR --modo todos --simular
```

O comando relê os 59 quadros da cópia e compara o resultado com a base. Como a cópia não é leitura anterior do próprio atualizador, a regra dos 70% não se aplica (aparece só o aviso). A comparação usa o caminho, o número, a letra e o ano de cada norma:
- a igualdade precisa ser de pelo menos 99,9%;
- a ementa, depois da limpeza, pode diferir em no máximo 0,5% das normas.

Se algum desses limites não for atendido, o comando sai com código 4. As diferenças vão para o relatório.
