# Sentinel — Console WebView2 (dark grafite + Vermelho Vigia)

Data: 2026-09-22 · Branch: `feat/sentinel-gui` (a abrir) · Status: aprovado pelo autor

## Problema

O Sentinel hoje é só terminal: `sentinel.py watch/status/events/fix/kill`
imprimem texto e o ciclo de correção exige um tty (`confirm()` no stdin).
Numa janela WebView2 não existe stdin interativo, então a GUI não pode
"conversar" com o CLI do jeito que ele está — e o usuário não tem superfície
para ver o que o daemon detectou enquanto trabalhava.

## Decisões (aprovadas em brainstorming)

1. **PowerShell + WebView2**, host sem moldura como os irmãos
   (`vector/gui/VectorHost.ps1`, `genesis/gui/WizardHost.ps1`): a página é
   cliente fino, sem Node, sem bundler, sem servidor. Compile em
   `Sentinel.exe` via ps2exe.
2. **Dashboard-first**, não wizard linear. O visitante abre, olha e age; não
   há "passo 1 de 5". A barra lateral troca de vista, não avança fluxo.
3. **Cor primária `#B3121B`** ("Vermelho Vigia & Grafite") — escolha
   vinculativa do autor, que rejeitou `#FF3B30` (era laranja-amarelado, não
   vermelho). Nenhuma irmã ocupa o vermelho profundo: Thero `#f4652c`,
   Athena `#eb445b`, Vector `#EC4899`, Zeus `#a3e635`, Genesis/Nexo
   `#22d3ee`/`#8b5cf6`. Campo neutro grafite, sem matiz.
4. **Code-first** (sem imagem de referência; ambição no contrato de design e
   auditoria no finish).
5. **Mock first**: a primeira entrega traz `gui/sentinel/mock.js` com as
   formas exatas dos dados reais, para aprovar visual e fluxo **antes** da
   ponte. A fiação no CLI real é a fase seguinte, não este entregável.
6. **Escopo v1 = console completo**: HUD de métricas, árvore de eventos com
   detalhe, tutor de correção, processos, log do daemon.

## Arquitetura

```
Sentinel.exe (ps2exe)
  gui/SentinelHost.ps1      Form sem moldura + WebView2 + ponte
  gui/webview2/*.dll          Loader do SDK (copiado dos irmaos)
  gui/sentinel/               index.html, style.css, app.js, mock.js, assets/
  src/sentinel/*.py           motor — unica fonte de verdade de regra
```

- **Regras ficam no Python.** A GUI nunca reinterpreta limiar, severidade,
  dedupe ou proteção de processo: ela mostra o que o motor decidiu e pede
  permissão para o que o motor recusaria.
- **Privacidade**: sem telemetria, sem asset hospedado, sem fonte web. A
  única saída de rede continua sendo o `claude -p` explícito, disparado por
  ação do usuário, nunca pelo daemon.
- Ponte JS→PS sempre com `JSON.stringify(payload)` (regra já provada em
  Vector/Genesis: objeto cru chega `[object Object]`).

## Fases

### Fase 0 — endpoints JSON no CLI (pré-requisito da ponte)

O caminho interativo (`fix`, `kill`) não tem tty dentro da WebView. Antes de
fiação qualquer, o CLI ganha modo máquina, com testes:

| comando | devolve |
|---|---|
| `sentinel metrics --json` | última amostra: cpu/ram/disk/io/net + top_cpu/top_mem + status do daemon |
| `sentinel events --json` (já existe) | eventos + resoluções |
| `sentinel status --json` | running/pid/last_heartbeat |
| `sentinel fix <id> --plan --json` | opções (claude ou kb) sem perguntar nada |
| `sentinel fix <id> --resolve --option N --outcome fixed\|not_fixed --json` | grava resolution sem tty |
| `sentinel fix <id> --dismiss --json` | grava `outcome=dismissed` sem tty (o desfecho já existe em `tutor.RESPONSE_DISMISS`; falta a porta não-interativa) |
| `sentinel kill <pid> --yes --json` | `{killed, failed, refused_reason}` |

`--yes` nunca substitui a recusa estrutural: processo protegido, `self` e
sessão não-interativa continuam recusando no Python.

### Fase 1 — GUI mock (esta entrega)

Vistas, tokens, componentes, movimento e estados vazios/cheios sobre
`mock.js`. Sem ponte: os botões que exigiriam o motor mostram o gesto e um
aviso honesto "modo demonstração — dados simulados".

### Fase 2 — ponte

`postMessage` → host → `python sentinel.py … --json` → `AddScriptToExecute
OnDocumentCreated`/callback de resposta. Substituir `mock.js` pelo adapter,
sem rede desenhar.

O adapter tem que fornecer o que o mock hoje fixa, ou a interface mente:
`source` de cada rodada de tutoria (`claude` | `kb` — a badge "base local"
do mock é hardcoded, `renderTutor`), `protected`/`self` calculados por
`processctl` em vez de flag no JSON, e o `--dismiss` da tabela acima.

**Eventos schema 2 (incidentes) não cabem no molde do `renderDetail`.**
`app_failure` e `orphan_tree` chegam sem `value`, `threshold`, `window` nem
`top_processes`; trazem `label` (uma linha) e `detail`. A ficha deles troca
os dois primeiros campos por:

| linha | de onde vem |
|---|---|
| O que houve | `label`, em texto corrente — nunca "0,0 vs 0,0" |
| Espécie | `metric` (`app_failure` → falha de app, `orphan_tree` → árvore órfã) |
| Assinatura | `detail.exception_code` + `detail.module` (crash) ou a árvore indentada por `depth` (órfão) |
| Repetições | `occurrences` — é o que distingue "quebrou hoje" de "loop de queda" |

`top_processes` ausente ⇒ nenhum botão "Encerrar …" na ficha: um incidente
não tem processo mais caro, e oferecer matar um PID que não está ali seria a
interface mentindo. A tabela da árvore mostra pid/ppid/name/depth tal como
gravado, sem inventar consumo.

### Fase 3 — build

`scripts/make-exe-icon.ps1` (SVG → `.ico`), `scripts/build-payload.ps1`,
`Sentinel.exe` + pastas irmãs. Revisão de acabamento numa máquina com
Windows real.

## Motion

Um único momento autoral: varredura de radar (~600 ms, uma vez) quando um
anúncio de anomalia entra na lista, mais a mudança de matiz do medidor
(~140 ms). `prefers-reduced-motion` desliga os dois. Sem entrada animada,
sem reveal de scroll — é superfície de tarefa.

## Verificação prevista

`node --check` nos JS, parser do PowerShell no host, detector mecânico do
impeccable uma vez, os 60 pytest do CLI continuando verdes, e o `## Finish`
de `DESIGN.md` reescrito com o que foi e o que não foi de fato verificado
(hospedagem WebView2 real exige execução no alvo).
