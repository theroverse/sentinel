# Sentinel residente — vigilância autônoma, alívio reversível e base própria

Data: 2026-09-22
Status: aprovada para execução — fases A–F na ordem da seção 12; as decisões
abertas foram fechadas em 2026-09-22 e estão registradas na seção 13
Base: `sentinel/` v1.0.0 (CLI + testes verdes) e a fase 1 da GUI
(`2026-09-22-sentinel-gui-design.md`)

## 1. O que este documento pede

Cinco mudanças de natureza, não de grau:

1. Residente de bandeja, com notificação Windows.
2. Capacidade de **agir** sob estresse, não só relatar.
3. Monitorar **falha de aplicativo** e **processo órfão**, além de recurso.
4. Base local que responde antes de qualquer modelo.
5. Tutoriais assertivos e cirúrgicos, com motor **local** (sem IA paga).

## 2. Evidência medida (2026-09-22, build 26200, 338 processos)

`IsProcessInJob` + `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION |
PROCESS_SET_QUOTA)`, por processo, nesta máquina:

| condição | qtd | o que significa para o Sentinel |
|---|---|---|
| fora de job | 46 | teto de CPU/RAM aplicável |
| dentro de job | 148 | **não reassignável** — teto impossível |
| acesso negado | 143 | inalcançáveis — e o design decide não buscá-los (seção 5) |

Os 148 são os suspeitos de sempre: `msedgewebview2`×32, `chrome`×18,
`Qoder`×13, `claude`×11, `RuntimeBroker`×9, `dllhost`×8, `Notion`×7,
`Discord`×6, `OverwolfBrowser`×5. Chromium/Electron e UWP criam o próprio
job no `CreateProcess`; o Windows não expõe remoção nem reassignação.

Duas consequências que este design aceita em vez de disfarçar:

- **Não existe "tirar do job".** Um teto de job vale até o processo fechar.
  Não há `RemoveProcessFromJobObject`; destruir o job mata o processo.
- **Teto de RAM não é freio, é falha de alocação.** Passado o limite,
  `VirtualAlloc` retorna erro; o app pode quebrar em vez de desacelerar.

Portanto o teto por job é instrumento **cirúrgico e estreito**, não o
mecanismo central. O mecanismo central é o degrau 1 da seção 5.

## 3. O que alcança qualquer processo, e é reversível

| alavanca | API | alcance | reversível |
|---|---|---|---|
| classe de prioridade CPU | `SetPriorityClass` | processo do mesmo usuário sem elevação | sim, imediato |
| prioridade de I/O | `SetProcessInformation(ProcessIoPriorityInfo)` | idem | sim |
| afinidade de núcleos | `SetProcessAffinityMask` | idem | sim |
| teto de CPU | `JobObjectCpuRateControlInformation` | só elegível (seção 2) | não |
| teto de memória | `JOB_OBJECT_LIMIT_PROCESS_MEMORY` | só elegível | não, e derruba app |
| encerrar árvore | `TerminateProcess` (já existe) | elevação p/ outros usuários | não |

Sob travamento, o que se quer é **ceder o escalonador**: rebaixar
`BELOW_NORMAL_PRIORITY_CLASS` + I/O `VeryLow` faz a máquina voltar a
responder sem matar o trabalho do usuário. É o único degrau que funciona
em Chrome, Qoder e Discord — os que mais travam.

## 4. Como saber que "está travando" sem perguntar à GUI

Índice de estagnação (**stall**), calculado no daemon a cada amostra. Cada
sinal é local, barato e já acessível por `psutil`/ctypes:

| sinal | fonte | por que é sinal de travamento |
|---|---|---|
| auto-inanição | desvio entre `sleep(2.0)` pedido e o decorrido real | se o próprio daemon não é escalado, nada mais é |
| thrash de memória | taxa de `swap_memory().sin/ sout` + commit perto do limite | o paginador virou o gargalo |
| disco saturado | `io_busy_percent ≥ 95` sustentado | todo mundo esperando I/O |
| janela pendurada | `SendMessageTimeoutW(..., SMTO_ABORTIFHUNG)` no thread de UI do culpado | é o mesmo teste do "não responde" do Gerenciador de Tarefas |
| recurso em crítico | o que o `detector` já calcula | condição necessária, nunca suficiente sozinha |

Regras do índice:

- `stall = True` quando (auto-inanição **ou** thrash **ou** disco saturado)
  **e** ao menos um processo candidato em crítico sustentado. Recurso alto
  sozinho **não** é estagnação — build rodando é só build rodando.
- Janela pendurada sozinha também não age: abre a sugestão, não o degrau.
- Sob suspeita, o daemon **encurta o próprio intervalo** (2,0 s → 0,5 s)
  enquanto durar, e roda em `HIGH_PRIORITY_CLASS` para não ser a vítima da
  própria vigilância.
- Todo sinal entra no evento, para o tutorial poder citar *o que* foi
  medido em vez de dizer "o sistema está lento".

## 5. Escada de ação, e quem autoriza o quê

A decisão não passa pela GUI porque, no cenário que você descreveu, a GUI
não abre. Ela passa por **ordens permanentes** concedidas antes, por app,
no console — e por um padrão que não autoriza nada.

| degrau | ação | quando automático | reversão |
|---|---|---|---|
| 0 | registrar + notificar | sempre | — |
| 1 | rebaixar prioridade CPU/I-O/afinidade | **ligado desde o início**, em `stall`, culpado elegível e não protegido — sem crachá (decisão do usuário, 2026-09-22) | ao fim do episódio, o Sentinel devolve sozinho |
| 2 | teto de CPU por job | só com ordem permanente por app, e só se elegível | ao fechar o app |
| 3 | encerrar árvore | só com ordem permanente **explícita e nomeada** por app | n/a |
| — | teto de RAM | **nunca automático** — oferecido no tutorial, com o risco escrito | — |

O degrau 1 é o único que funciona onde o travamento acontece (Chrome,
Qoder, Discord, Electron — todos dentro de job, inalcançáveis ao teto) e o
único que se desfaz sozinho. Ele deixa o app lento de propósito; nunca
perde trabalho aberto. É a escolha que ataca o "aviso atrasado" sem exigir
confiança antecipada em algo irreversível.

Guardas do caminho autônomo:

- `PROTECTED_PROCESS_NAMES`, `is_self` e serviços do Windows ficam de fora
  em todos os degraus; serviço nunca morre por PID (só `net stop`, sugerido).
- Teto de intervenções por hora e cooldown por app: um app que renasce
  quebrando não vira loop de morte.
- **Kill-switch que funciona sem GUI**: item no menu da bandeja + arquivo
  `.sentinel/paused`. O daemon checa o arquivo a cada ciclo.
- **Modo sombra existe, mas não é o padrão**: é uma chave (`sentinel
  orders shadow --on`, e o item correspondente no menu da bandeja) que faz
  os degraus serem calculados e registrados como `would_act` sem tocar no
  sistema. O degrau 1 age desde o primeiro dia; os degraus 2 e 3 esperam
  crachá por app, então não há o que "ligar" neles antes de conceder.
- Toda intervenção autônoma gera linha no `daemon.log`, evento próprio no
  `events.jsonl` e uma resolução automática do tipo `action=...` — o
  histórico é auditável, que é o que permite confiar no degrau 3 depois.

### Alcance sem elevação

Decisão de 2026-09-22: **o Sentinel roda inteiro como usuário comum** —
daemon, bandeja e console. Nada pede UAC, em nenhum momento, por nenhum
motivo. Consequência medida (seção 2): os 143 processos inalcançáveis ficam
inalcançáveis. A decomposição deles mostra que isso quase nada custa ao
design — 86 são `svchost`, e o resto é interno do kernel e helpers de
serviço, todos na lista de protegidos que a escada já recusa tocar.

O gap real é estreito e nomeado: **um app que você mesmo rodou como
administrador** escapa aos degraus (nenhuma das três alavancas da seção 3
funciona sem elevação contra ele). Nesta máquina, hoje, isso é `winget` em
três instâncias. Nesses casos a interface **declara o limite em vez de
fingir que tentou**: o card diz "este processo pertence a outra sessão
elevada; o Sentinel não o alcança sem admin", e oferece o comando pronto
(`sentinel relief <pid>` numa janela elevada, ou o caminho manual). Não há
prompt, não há fallback silencioso, não há botão que pisca sem efeito.

Se um cenário descoberto aparecer de verdade, a regra de revisita é a
palavra do usuário: reabre-se esta seção, não se contorna em código.

## 6. Bandeja e notificação

`gui/SentinelTray.ps1` (WinForms, zero dependência nova):

- `NotifyIcon` com o `.ico` já gerado; menu: abrir console, pausar ações
  automáticas, ver últimas anomalias, sair.
- Toast WinRT (`ToastNotificationManager`, AppId próprio) para anomalia
  nova e para **relato de ação autônoma** — quem avisa depois do fato é o
  degrau 1/2/3, e o texto diz isso.
- Vive de ler `.sentinel/events.jsonl` (watch de arquivo, sem IPC com o
  daemon). O daemon continua sendo a única autoridade de regra; se a
  bandeja morre, a vigilância e as ações seguem.
- Honestidade: sob travamento total, nada renderiza — o toast pode chegar
  atrasado. É exatamente por isso que o alívio (degrau 1) não espera o
  toast nem o clique.
- **Sem UAC, inclusive no login automático.** Atalho no `Startup` ou
  `Run` do próprio usuário, não tarefa agendada elevada: ambos carregam a
  bandeja e o daemon sem prompt, porque nada aqui precisa de admin (seção
  5). A bandeja nunca oferece "reiniciar como administrador".

## 7. Falha de aplicativo e processo órfão

Dois tipos novos de anomalia, ambos locais:

- **`app_failure`** — Event Log `Application`, IDs **1000 (Application
  Error)** e **1002 (Application Hang)**, lidos por `wevtutil qe` com filtro
  XPath e janela de tempo. Traz módulo culpado, código de exceção e versão
  do app — evidência que nenhum `psutil` dá.
  - O **1001 (Windows Error Reporting) ficou de fora por medição**, não por
    gosto: na varredura desta máquina ele é o espelho do 1000/1002 (mesmo
    app, segundos depois) e, quando vem sozinho, é diagnóstico — os
    registros dominantes do log são `RADAR_PRE_LEAK_64`, `crashpad_log` e
    `StoreAgentInstallFailure1`. Contar 1001 inflaciona uma queda em duas
    anomalias e chama vazamento de leak de "crash".
  - 1002 só vale com provedor `Application Hang`: `Microsoft-Windows-Winlogon`
    também publica 1002, e não é travamento de app.
  - A leitura vai em `/f:xml`, não `/f:text`: com o Windows em pt-BR o texto
    vem traduzido ("Nome do Evento", "Assinatura do problema") e em cp850;
    o XML traz os `Data Name` do manifest (`AppName`, `ExceptionCode`,
    `ProcessId`), iguais em qualquer idioma, e chega em UTF-8. Ler rótulo
    traduzido quebra calado num Windows em outra língua.
  - Ler o log `Application` não é operação privilegiada (verificado nesta
    máquina em shell de usuário comum) — o que mantém a decisão "sem
    elevação" de pé também aqui.
- **`orphan_tree`** — processo cujo `ppid` não resolve para processo vivo.
  No Windows não há reparente: o filho continua apontando para um PID morto
  (ou reutilizado). O Sentinel mapeia a árvore completa do pai desaparecido
  antes de qualquer coisa, grava o mapa no evento e só então oferece ação.

Isso exige **histórico de árvore**: o daemon passa a guardar, por ciclo, o
conjunto `{pid, ppid, name, create_time}` dos processos não-sistema, para
poder dizer *quem* morreu e *quem ficou*. É o pré-requisito do degrau 3 ser
seguro (matar a árvore certa) e do relatório de órfão ser preciso.

`EVENT_SCHEMA_VERSION` sobe para 2; o leitor mantém tolerância às linhas
`schema: 1` já em disco (campo novo nunca quebra histórico).

## 8. Base de conhecimento local, consultada primeiro

`.sentinel/kb.db` em `sqlite3` (stdlib, sem dependência nova). Implementado
em `kbstore.py` (2026-09-22), quatro tabelas:

- `anomaly_type` — quem a base conhece. A chave carrega a camada:
  `fp:<fingerprint>` (1), `causa:<metrica>+<causa>` (2), `metrica:<metrica>`
  (3). Com `occurrences`/`last_seen`, então `sentinel kb` consegue dizer onde
  ainda não há resposta.
- `option` — o conteúdo da seção 9 (`title/why/steps/proof/risk/reversible`
  + `action` JSON), com `origin` ∈ {`curado`, `aprendido`}.
- `type_option` — qual opção pertence a qual tipo, e em que ordem curada.
- `outcome` — o que foi tentado, desfecho, fonte, quando, **contra qual
  fingerprint**.

A **assinatura de causa** (`cause_of`) é o que faz a camada 2 existir: no
`app_failure` é o módulo que falhou (a mesma DLL derruba apps diferentes),
no `orphan_tree` é o pai que morreu, e numa anomalia de limiar é o processo
mais caro da amostra.

Ordem de busca no `fix`, e ela é o ponto do pedido:

1. fingerprint exato na base
2. métrica + assinatura de causa
3. métrica genérica (o `kb.py` migrado — seed idempotente, `INSERT OR
   IGNORE`, porque editar o texto curado não pode apagar o ranking aprendido)
4. **só então** o modelo, e o resultado vira entrada na base (`learn`), nos
   dois níveis que prestam depois: fingerprint e causa.

**Regra da camada esgotada** — sem ela a 4 nunca rodaria, já que a 3 cobre
todas as métricas conhecidas: se *toda* opção de uma camada já foi recusada
contra *este* fingerprint, a camada cala e a busca desce. Recusa de um
processo não silencia a resposta de outro; a contagem é por fingerprint. É a
versão persistente do "descarte o que falhou" do ciclo interativo.

**Ranking**: `fixed` desc, `not_fixed` asc, ordem curada como empate — e só
com as contagens deste fingerprint. Uma vitória contra o chrome não
embaralha a resposta sobre o blender.

**Tokens**: o texto curado traz `{proc}`, `{pid}`, `{rss}`, `{cpu}`,
`{value}`, `{threshold}`, `{span}`, `{module}`, `{code}`, `{parent}`,
`{orphan_count}`, e o `kb.bind` preenche na **leitura**, nunca no seed — a
mesma linha serve duas máquinas porque o número vem do evento. O `bind` é
regex em vez de `str.format` porque texto de modelo contém `{}` de código,
e um tutorial não pode quebrar por causa disso.

`sentinel fix --explain-source` mostra a camada, a causa reconhecida e o que
pesou no ranking. `sentinel kb [--json]` mostra o inventário: tipos, opções,
quantas aprenderam de modelo, desfechos por tipo — a meta mensurável
("com uso, a camada 4 quase nunca roda") só é meta se alguém puder medir.

## 9. Tutorial assertivo, não página de suporte

Formato novo de opção — o campo `why` deixa de ser adjetivo:

```python
{
  "title": "Rebaixar a prioridade do Chrome até você fechar a aba",
  "why": "O Chrome segura 3,2 GB e 18 threads de render. Ele não vai "
         "parar sozinho: enquanto estiver escalando antes do resto, o "
         "clique continua demorando. Rebaixar a classe de prioridade "
         "não fecha nada nem perde trabalho — só faz o escalonador "
         "servir o resto primeiro.",
  "do": ["..."],
  "proof": "Abra e clique em uma janela qualquer. Se responder no "
           "toque, o gargalo era este. O Sentinel mede de novo em 30 s.",
  "risk": "O app fica mais lento de propósito.",
  "reversible": True,
  "action": {"type": "relief_priority", "level": "below_normal"},
}
```

Regras de redação da base: imperativo, nomeia o processo medido no evento,
explica o mecanismo (não "tente limpar a RAM", e sim por que aquilo libera),
diz como você vai saber que funcionou, e declara reversibilidade. Proibido:
"geralmente", "pode ser", "recomendamos", passo único que só abre uma
janela de configurações sem dizer o que mudar ali.

**Nome do campo de passos: `steps`, não `do`.** O rascunho acima escreveu
`do`; a implementação de 2026-09-22 manteve `steps` porque ele já é o
contrato entre o prompt, o `parse_options`, o `events.jsonl` e a GUI — e o
ponto da seção é o conteúdo (mecanismo, prova, risco), não a grafia de uma
chave. Onde o spec diz `do`, leia `steps`.

Como o texto curado nomeia o processo medido sem virar frase genérica, cada
opção carrega tokens (`{proc}`, `{pid}`, `{rss}`, `{value}`…) que o `bind`
preenche na leitura com o número daquele evento (seção 8). Uma opção do
catálogo que não tem como preencher o seu token é um buraco visível — e há
teste pra isso, não revisão de volante.

## 10. Motor local, compartilhado com a Athena

Não é um segundo Ollama. É **um servidor para os dois** — a Athena já tem o
único cliente Ollama do monorepo (`athena/src/athena/summarizer/ollama_client.py`:
`/api/generate`, `/api/chat`, `/api/embeddings`, sonda `GET /api/tags`,
stdlib `urllib`) e o modelo padrão dela é `llama3.2`. O Sentinel usa o mesmo
servidor, a mesma porta e **o mesmo modelo**: puxar um modelo diferente pra
economizar um prompt seria gastar 2 GB de disco alheio à toa.

Forma do código: cópia própria (~120 linhas), não import da Athena. O
monorepo já é assim por decisão (`system/process.py` existe quatro vezes);
importar `athena.settings` criaria acoplamento entre satélites que não se
conhecem. A cópia traz três diferenças deliberadas:

| | Athena hoje | Sentinel |
|---|---|---|
| variáveis | `ATHENA_OLLAMA_HOST/MODEL` | `SENTINEL_OLLAMA_HOST/MODEL` |
| host remoto | aceita o que a env mandar | **recusa fora de loopback, no código** |
| Ollama ausente | cai em `claude -p` no modo `auto` | **não cai**: a base curada responde e diz de onde veio |

`local_model.py` substitui `claude_client.py` no caminho crítico:

- Transporte: Ollama `POST http://127.0.0.1:11434/api/generate`
  (`stream: false`), e um transporte OpenAI-compatível
  (`/v1/chat/completions`) para LM Studio/llama.cpp server.
- **Invariante de privacidade reforçada**: host fora de `127.0.0.1`/`::1`/
  `localhost` é recusado no código, não na config. Timeout curto. Sem
  telemetria, sem chamada de descoberta.
- Ausência do motor é estado normal: o `fix` roda na base curada e diz de
  onde veio. Nada na interface finge que há IA.
- `claude -p` sai do caminho do Sentinel. Se ficar, é opt-in explícito e
  rotulado como saída de rede — o que hoje é a única exceção à política
  local e deixa de ser.
- Modelo padrão: **`llama3.2`** (o da Athena). O trabalho é formatar até 3
  opções com `why`, não raciocinar sobre o disco.

### Provisionamento: instalar e puxar só o que falta

Medição desta máquina (2026-09-22): `where ollama` vazio e `127.0.0.1:11434`
recusando conexão — **o Ollama não está instalado**, então hoje o
`--backend auto` da Athena cai em `claude -p`. E ninguém instala hoje: o
Genesis, que é o preparador de máquina, não tem uma linha sobre Ollama.

`sentinel model setup` faz o ciclo, idempotente, na ordem:

1. **Sonda** `GET /api/version` no loopback → se responde, nada a instalar.
2. **Instala se faltar**: `winget install -e --id Ollama.Ollama --silent
   --accept-package-agreements --accept-source-agreements`. Verificado no
   manifest: v0.34.2, instaladora **Inno** (`OllamaSetup.exe`) em escopo de
   usuário (`%LOCALAPPDATA%\Programs\Ollama`) — **sem UAC**, o que mantém de
   pé a decisão "sem elevação" da seção 5.
3. **Garante o servidor**: se instalado mas mudo, `ollama serve` em segundo
   plano; o Sentinel não compete pelo controle do serviço com a GUI do
   Ollama, só espera a porta responder.
4. **Puxa o modelo só se não existir**: `ollama list` → se `llama3.2` não
   estiver lá, `ollama pull llama3.2`. É download grande (~2 GB): pede
   confirmação explícita, mostra o tamanho e fala a origem
   (`ollama.com`/GitHub), porque é o único instante em que o Sentinel toca a
   rede por um motivo que não é o usuário mandando.
5. **Relata** o que encontrou pronto e o que fez — `already installed,
   model present` é uma resposta tão boa quanto `installed`.

Guardas, e elas importam mais que o conforto:

- **Nada disso roda no daemon.** O provisionamento é comando de terminal,
  disparado por você (ou pela bandeja, que só reexecuta o `sentinel model
  setup` já escrito). Um processo residente que baixa 2 GB sozinho é
  exatamente a traição de confiança que este projeto evita.
- A nota de versão do Ollama 0.34 avisa de um primeiro uso com escolha
  *"sign in or continue locally"*: o fluxo sem interação tem que cair em
  **local**, e o Sentinel não abre a GUI de conta em nome de ninguém.
- Instalação não é pré-requisito de vigilância: sem Ollama, o Sentinel segue
  100% funcional na base curada (`kb`), e o `fix --explain-source` mostra
  que veio de lá.

Segundo passo, fora do escopo do Sentinel mas registrado aqui: o Genesis
deveria ganhar `Install-Ollama.ps1` com o mesmo padrão idempotente que ele
já usa para o Claude Code (`Test-CommandExists` → instala). Se só o Sentinel
souber provisionar, uma máquina nova precisa abrir o Sentinel para entregar
o backend que a Athena usa.

## 11. Impacto no que já existe

- **CLI**: `sentinel tray`, `sentinel orders list|grant|revoke|shadow`,
  `sentinel pause|resume`, `sentinel kb stats`, `sentinel model status|setup`
  (sonda, instalação, `pull` — seção 10), flags `--json` da fase 0 da spec da
  GUI, `sentinel relief <pid> [--restore]`.
- **daemon**: árvore por ciclo, índice de stall, executor de degraus,
  leitura do `paused`, prioridade própria alta. Roda como usuário comum.
- **`SentinelHost.ps1`**: o prompt `YesNo` de reabrir como administrador
  (linhas 130–146) sai. Fica a detecção de `IsAdmin`, só que reorientada:
  ela alimenta a declaração de alcance da seção 5, não um convite à
  elevação. A bandeja (`SentinelTray.ps1`) nasce sem qualquer
  `-Verb RunAs`.
- **events**: tipos novos (`app_failure`, `orphan_tree`, `relief_applied`),
  schema 2. A linha de incidente **não** tem `value`/`threshold`: tem
  `label` (uma frase, pro log e pro CLI) e `detail` (o mapa da árvore, ou o
  módulo + código de exceção da queda). Nem uma nem outra se disfarçam de
  limiar com zero preenchido.
- **daemon.log**: linha `ANOMALIA <metric> <sev> occ=N status=... id=... ::
  <label>` — o `:: <label>` no fim mantém os pares `chave=valor`
  interpretáveis e ainda dá de ler o que aconteceu sem abrir o JSONL.
- **GUI** (fase 1 já aprovada): vista "Ações automáticas" com as ordens
  permanentes, a chave de modo sombra e o histórico do que foi feito sem
  pedir; o card do tutorial passa a mostrar `why`/`prova`/`risco`; um
  processo elevado inalcançável aparece com o limite declarado, não com um
  botão morto.
- **testes**: fake de `winreg`/ctypes para os degraus; o stall index e o
  ranking da base são testáveis sem Windows real, como o resto já é.

## 12. Ordem de execução proposta

| fase | entrega | risco |
|---|---|---|
| A | falha de app + órfão + schema 2 + testes | nenhum (só lê) |
| B | `kb.db`, formato assertivo, reescrita do conteúdo, ranking | nenhum |
| C | bandeja + toast + pause/resume | baixo |
| D | stall index + degrau 1 **já ligado** + guardas (rate limit, cooldown, `paused`) + chave de modo sombra | médio |
| E | degraus 2 e 3, ordens permanentes por crachá, teto por job | **alto — precisa da sua revisão das guardas** |
| F | `local_model.py` + `sentinel model setup` (sonda/instala/puxa) + vistas novas da GUI | médio (rede + instalação de terceiro, ambas sob confirmação) |

Cada fase fecha com pytest verde e o detector do impeccable na GUI.

## 13. Decisões fechadas (2026-09-22)

Registradas aqui porque são o que a implementação não pode reabrir sozinha.

1. **Motor local: Ollama, e o Sentinel provisiona.** Não é um Ollama do
   Sentinel — é o Ollama da máquina, o mesmo que a Athena usa, com o mesmo
   modelo (`llama3.2`). `sentinel model setup` instala se faltar e puxa o
   modelo se ele não estiver lá; nunca roda sozinho, nunca no daemon
   (seção 10). Nenhum modelo pago, nenhuma chamada externa de inferência.
   Medições de 2026-09-22 que sustentam isso: Ollama **ausente** desta máquina
   (`where ollama` vazio, `11434` recusando), **nenhum** código no monorepo o
   instala hoje, e o instalador é Inno em escopo de usuário — cabe na regra
   "sem elevação".
2. **Degrau 1 ligado desde o início, sem crachá.** Rebaixar prioridade sob
   stall é a resposta ao "aviso atrasado": funciona onde o travamento
   acontece e se desfaz sozinho. Os degraus 2 e 3 exigem crachá por app, e
   o **padrão das ordens permanentes nasce vazio** — nada de teto nem
   fechamento sem concessão explícita.
3. **Sem elevação, em nenhum componente.** Nem o prompt `YesNo` do console,
   nem tarefa agendada elevada, nem `-Verb RunAs` na bandeja. Base medida
   para aceitar o alcance: os 143 inalcançáveis são 86 `svchost` + interno
   do kernel + helpers de serviço — todos já na lista de protegidos que a
   escada recusa tocar. O gap real é app alheio rodado como admin (hoje,
   três instâncias de `winget` nesta máquina), e a resposta a ele é
   **declarar o limite**, não escalar.
   *Gatilho de revisita:* aparecer um cenário descoberto de verdade — aí se
   reabre a seção 5 com você no comando; ninguém contorna a regra em código.
4. **Residente: PowerShell WinForms** (`NotifyIcon` + toast WinRT), sem
   dependência nova; o daemon continua sendo a única autoridade de regra.

O que segue em aberto, e só bloqueia a fase E: a revisão das guardas do
caminho autônomo (rate limit por hora, cooldown por app, semântica do
crachá) antes de qualquer degrau irreversível ligar.

### 13.1 Reescopo registrado (2026-09-22, depois da fase B)

Palavra do usuário, na ordem em que chegou. Nada aqui é invenção de
implementação; é o escopo sendo corrigido por quem manda na máquina.

1. **A bandeja e o toast (seção 6) saem do caminho.** "Você pode parar de
   mexer na bandeja? Parece que tá dando trabalho, pula essa parte." O
   kill-switch continua existindo — ele nunca dependeu da bandeja para
   funcionar, e essa era justamente a exigência da seção 5: `.sentinel/paused`
   gravado por `sentinel pause`, lido pelo daemon a cada ciclo, sobrevivendo a
   reboot e a daemon morto. `SentinelTray.ps1` não é escrito agora; se um dia
   voltar, é a mesma interface de arquivo + CLI, sem nada novo no daemon.
2. **O provisionamento do motor (seção 10) sai do Sentinel.** "O runtime eu
   cuido, você só precisa se comunicar com ele quando necessário." Cai o
   `sentinel model setup` (sonda/instala/puxa); o Ollama pode continuar
   compartilhado com a Athena, mas a instalação e o `pull` não são mais
   responsabilidade nem superfície de código do Sentinel.
3. **O modelo é o que o usuário escolher** — `qwen3-coder-next` em GGUF,
   quantização `Q2_K` — e não o `llama3.2` da seção 10. Nome e host ficam em
   `SENTINEL_OLLAMA_MODEL` / `SENTINEL_OLLAMA_HOST`, com o invariante de
   privacidade intacto: host fora de loopback é recusado no código.
4. **Consequência boa e deliberada:** sem o `claude -p` no caminho, a política
   "só local" deixa de ter a única exceção que ela tinha. O Sentinel passa a
   não ter nenhuma saída de rede em nenhum modo — inclusive no `fix`.
5. **Motor ausente continua estado normal**, como já dizia a seção 10: a base
   curada responde e o `fix --explain-source` diz de onde veio. A diferença é
   que agora "ausente" é a situação desta máquina até o usuário ligar o dele.

