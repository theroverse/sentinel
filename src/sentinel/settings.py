from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------
# Identidade / versao
# --------------------------------------------------------------------------
# Bump junto com sentinel.__version__; `sentinel --version` le daqui.
APP_NAME = "sentinel"

# --------------------------------------------------------------------------
# Layout de saida (o "territorio" proprio do Sentinel no disco do usuario)
# --------------------------------------------------------------------------
# Tudo que o Sentinel escreve fica numa pasta oculta na raiz escolhida
# (--dir, padrao: pasta atual). Nada sai da maquina.
OUTPUT_DIRNAME = ".sentinel"

EVENTS_FILENAME = "events.jsonl"

DAEMON_PID_FILENAME = "daemon.pid"

DAEMON_LOG_FILENAME = "daemon.log"

# Kill-switch sem GUI: a existencia deste arquivo basta para o daemon
# suprimir a parte autonoma (registrar anomalia, e na fase D agir). Nao e
# config nem limiar -- e um interruptor, entao mora no disco e nao no
# config.json, que e opcional e pode estar quebrado (nesse caso o
# interruptor viraria enfeite).
PAUSED_FILENAME = "paused"

# Base de conhecimento local (sqlite, stdlib): o que o Sentinel ja sabe
# sobre esta maquina e o que ja funcionou contra cada anomalia. Fica no
# mesmo territorio `.sentinel/` e nunca sai dela.
KB_DB_FILENAME = "kb.db"

# Versao do schema da base. Subir quando mudar tabela; `kbstore` faz
# `PRAGMA user_version` e recria o que faltar — sem apagar o historico do
# usuario.
KB_SCHEMA_VERSION = 1

# Schema atual gravado em cada linha do events.jsonl. Guardado por linha
# (nao so no nome do arquivo) pra permitir migracao futura sem quebrar
# leituras antigas.
#
# v2: anomalias que nao nascem de limiar (`orphan_tree`, `app_failure`,
# `stall`) passam a existir no mesmo arquivo, com `label` + `detail` no lugar
# de `value`/`threshold`. O leitor e tolerante por construcao (tudo via
# `.get()`), entao as linhas v1 ja em disco continuam legiveis e o
# historico nao e reescrito — campo novo nunca quebrar arquivo velho.
EVENT_SCHEMA_VERSION = 2

# --------------------------------------------------------------------------
# Amostragem (sensor + daemon)
# --------------------------------------------------------------------------
# Intervalo entre amostras do loop de vigilancia, em segundos.
SAMPLE_INTERVAL_S = 2.0

# Tamanho da janela deslizante (numero de amostras) que o detector ve por
# vez que avalia uma regra. 30 amostras * 2s ~= 60s de historia.
SAMPLE_WINDOW = 30

# O detector fica mudo ate acumular este numero de amostras — evita
# falso-positivo no boot do daemon, quando as medias ainda nao
# representam nada (e o proprio pico de partida do processo).
MIN_SAMPLES_BEFORE_DETECT = 10

# --------------------------------------------------------------------------
# Limiares de anomalia (percentuais 0-100, salvo indicacao)
# --------------------------------------------------------------------------
# Cada metrica tem warning/critical e quantas amostras CONSECUTIVAS em
# warning disparam. sustained=1 significa "imediato" (nao espera janela).
#
# Sao padroes sensatos pra uma estacao de trabalho Windows comum;
# qualquer um pode ser sobrescrito por config do usuario (ver `--dir` e a
# leitura opcional de .sentinel/config.json em settings.load_overrides).

# CPU total: sustained pra nao pegar um pico de 1 leitura (compilando,
# abrindo um app).
CPU_WARNING = 85.0
CPU_CRITICAL = 95.0
CPU_SUSTAINED = 5

# Memoria: warning sustained; critical imediato (RAM em 93% ja e dor).
RAM_WARNING = 80.0
RAM_CRITICAL = 93.0
RAM_SUSTAINED = 5
RAM_CRITICAL_IMMEDIATE = True

# Disco (volume principal): cheio nao e transitorio, entao imediato.
DISK_WARNING = 85.0
DISK_CRITICAL = 95.0
DISK_SUSTAINED = 1
DISK_CRITICAL_IMMEDIATE = True

# IO wait (disk busy %): gargalo de disco, sustained mais longo porque
# variavel natural de leitura/escrita.
IO_WARNING = 70.0
IO_CRITICAL = 90.0
IO_SUSTAINED = 8

# Rede: nao tem critical. Banda alta nao e falha, e contexto pra
# correlacao nos tutoriais. Warning = fracao do p95 historico (ver
# detector.NET_RELATIVE_TO_P95).
NET_WARNING_RATIO = 0.8
NET_SUSTAINED = 3

# Quantas amostras recentes o detector mantem pra estimar o p95 de rede
# usado como referencia relativa (NET_WARNING_RATIO * p95).
NET_BASELINE_WINDOW = 120

# --------------------------------------------------------------------------
# Indice de estagnacao ("stall"): a maquina esta travando, nao so ocupada
# --------------------------------------------------------------------------
# O recurso alto sozinho nao e estagnacao — build rodando e build rodando. O
# que distingue os dois e o atraso que a maquina passa a ter pra si mesma.
# Cada sinal abaixo e uma daquelas cinco perguntas do spec residente,
# respondida com numero local. Nenhum deles age: quem decide mexer no
# sistema e `relief` (fase D2), lendo o que o `stall` mediu.

# Auto-inanicao: o `sleep(interval)` pedido levou este fator vezes o proprio
# valor para acontecer. Se o daemon nao consegue nem dormir pelo tempo
# pedido, a maquina parou de escalar quem quer que seja — inclusive ele.
#
# Mede-se o `sleep()`, nao o ciclo inteiro: dentro do ciclo moram o scan de
# processos e a consulta ao Event Log (que lanca `wevtutil`), e nenhum dos
# dois e fome da maquina — sao trabalho nosso. Confundir os dois faria o
# indice acusar o Sentinel de travar o Windows a cada 60 segundos.
STALL_STARVE_FACTOR = 2.0

# Thrash de paginacao. `swap_activity_ps` e o delta por segundo dos
# contadores cumulativos `sin`+`sout` do psutil, na unidade que o psutil da
# plataforma devolve — por isso o numero e sobrescrevivel por config, e nao
# absoluto.
#
# No Windows esses dois contadores nao significam nada: o proprio psutil diz
# que ficam em 0 (medido: sin=0 sout=0). La quem carrega o sinal e o
# STALL_SWAP_PERCENT abaixo, porque `swap_memory().percent` no Windows e a
# carga de commit, nao o arquivo de paginacao em si.
STALL_SWAP_RATE_PS = 256.0

# No Windows o "swap" do psutil e o pagefile, e o percentual dele E a carga
# de commit (pagefile usado / limite de commit). 90% e o ponto em que o
# Windows comeca a recusar reserva de memoria — a diferenca entre lento e
# parado.
STALL_SWAP_PERCENT = 90.0

# Disco saturado: todo mundo esperando I/O. Sustentado porque um pico isolado
# de 100% e um fsync, nao uma estagnacao.
STALL_DISK_BUSY = 95.0
STALL_DISK_SUSTAINED = 3

# Quantas amostras CONSECUTIVAS um sinal pontual (inanicao, thrash) precisa
# ver pra valer. Um tick isolado de paginacao pesada e o fsync de um
# navegador; dois ja sao tendencia. O disco tem teto proprio, mais longo, e o
# culpado em critico tambem.
STALL_SIGNAL_SUSTAINED = 2

# Ciclos seguidos com um culpado elegivel em critico sustentado. Condicao
# necessaria do indice (spec 4): recurso alto sem candidato em critico nao e
# estagnacao, e carga de trabalho de alguem que pediu por ela.
STALL_CULPRIT_SUSTAINED = 2

# Amostragem sob estagnacao: o daemon encurta o proprio intervalo pra ver o
# episodio passar por dentro, e pra saber a hora exata em que acabou.
SAMPLE_INTERVAL_FAST_S = 0.5

# --------------------------------------------------------------------------
# Degrau 1 ("relief"): o teto reversivel que age enquanto a maquina trava
# --------------------------------------------------------------------------
# O unico degrau que funciona onde o travamento acontece e que se desfaz
# sozinho: rebaixar a prioridade do culpado que o indice de estagnacao
# sustentou. Nada aqui pede elevacao, e nada aqui mata processo.
#
# Ligado desde o primeiro dia (decisao do usuario, 2026-09-22) -- o que o
# segura nao e uma autorizacao, sao as guardas abaixo e o arquivo `paused`.

# Quantas intervencoes cabem numa janela de uma hora. Um app que renasce
# travando nao pode virar loop de intervencao continua: o teto desliga o
# degrau ate a janela virar.
RELIEF_HOUR_LIMIT = 3

# Segundos que um mesmo app (por NOME) fica protegido de novo alivio depois
# de um. Nome, nao pid: pid e reciclado no Windows e o app que travou agora
# e o mesmo que travou ha dois minutos, com outro numero.
RELIEF_APP_COOLDOWN_S = 600

# Quanto o nice sobe no POSIX (la maior numero = menos prioridade). No
# Windows o degrau e uma constante de classe de prioridade, e este valor nao
# e usado.
RELIEF_NICE_STEP = 10

# Diario das intervencoes: o que foi aplicado, em qual pid/instancia, e o
# valor anterior. E o que permite devolver ao fim do episodio, e tambem o
# que sobrevive a um daemon morto no meio -- sem ele, um crash deixaria um
# app rebaixado para sempre sem ninguem sabendo a quem devolver.
RELIEF_STATE_FILENAME = "relief.json"
RELIEF_JOURNAL_MAX = 50

# Ordens permanentes do caminho autonomo. Comeca com uma chave so (modo
# sombra); a fase E acrescenta as ordens por app.
ORDERS_FILENAME = "orders.json"


# --------------------------------------------------------------------------
# Falha de aplicativo (Event Log `Application`, lido por wevtutil local)
# --------------------------------------------------------------------------
# So 1000 (Application Error) e 1002 (Application Hang). O 1001 do WER fica
# de fora por evidencia medida, nao por preferencia: ele e o espelho do
# 1000/1002 (mesmo app, segundos depois) e, quando vem sozinho, costuma ser
# diagnostico (RADAR_PRE_LEAK_64, crashpad_log) e nao queda do app.
APP_FAILURE_LOG = "Application"
APP_FAILURE_EVENT_IDS = (1000, 1002)
APP_FAILURE_PROVIDERS = frozenset({"application error", "application hang"})

# Janela de tempo da consulta, em segundos. Estreita de proposito: uma
# consulta com `timediff(@SystemTime)` largo faria o daemon replayear
# quedas antigas na primeira leitura apos o boot.
APP_FAILURE_WINDOW_S = 300.0

# De quanto em quanto tempo o daemon reconsulta o log. Mais barato que a
# amostra de recurso (2 s) porque cada consulta lana um processo filho.
APP_FAILURE_QUERY_INTERVAL_S = 60.0

APP_FAILURE_QUERY_LIMIT = 25
APP_FAILURE_TIMEOUT_S = 5.0

# Teto do conjunto "ja contei esta linha" no leitor. Sem teto, um daemon que
# roda semanas so acumula memoria a cada queda de app.
APP_FAILURE_SEEN_MAX = 512

# --------------------------------------------------------------------------
# Deduplicacao de eventos
# --------------------------------------------------------------------------
# Duas anomalias com o mesmo fingerprint num raio destes segundos viram
# UMA linha (atualiza value/occurrences) em vez de poluir o log.
DEDUPE_WINDOW_S = 300

# --------------------------------------------------------------------------
# Ciclo de tutoria
# --------------------------------------------------------------------------
# Maximo de opcoes de solucao que o tutorial deve conter (regra do
# prompt e do fallback do kb).
MAX_FIX_OPTIONS = 3

# --------------------------------------------------------------------------
# Motor de modelo local (Ollama / servidor OpenAI-compativel)
# --------------------------------------------------------------------------
# O Sentinel nao instala nem baixa nada: quem prove o motor e o usuario (ou
# o Genesis). Estes valores so dizem ONDE perguntar. A ausencia do motor e
# um estado normal — a base curada (`kb`) responde sozinha.
#
# Ordem de resolucao: variavel de ambiente > `.sentinel/config.json` >
# padrao aqui.
OLLAMA_HOST_ENV = "SENTINEL_OLLAMA_HOST"
OLLAMA_MODEL_ENV = "SENTINEL_OLLAMA_MODEL"

# Endereco padrao do Ollama na maquina. Nao e "o" endereco: qualquer host de
# loopback serve, e o servidor OpenAI-compativel do LM Studio / llama.cpp
# usa a mesma porta por convencao.
DEFAULT_MODEL_BASE = "http://127.0.0.1:11434"

# Nome do modelo servido. Aqui nao ha download nem tag de registry: e o id
# que o motor local anuncia (`ollama list` / `GET /v1/models`). O peso que
# se pretende usar e o Qwen3-Coder-Next em GGUF Q2_K — a quantizacao e uma
# propriedade do arquivo que o usuario carregou, nao uma escolha deste
# cliente, por isso nao aparece no nome.
DEFAULT_MODEL_NAME = "qwen3-coder-next"

# Invariante de privacidade, aplicada no codigo e nao na config: um
# `SENTINEL_OLLAMA_HOST` apontando pra outra maquina e recusado, com ou sem
# env var que o peca. O Sentinel fala com um motor na propria maquina — o
# dia que ele puder falar com um remoto, "nada sai da maquina" deixa de ser
# verdade e a frase no README passa a ser mentira.
MODEL_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

# Tempode espera do `generate`: um Q2_K em CPU escreve devagar, e um timeout
# curto de mais faz o motor parecer ausente quando ele so esta trabalhando.
MODEL_TIMEOUT_S = 60.0

# A sonda de `sentinel model status` tem que responder na hora: ela roda em
# terminal, as vezes com o motor desligado, e nao ha nada a esperar.
MODEL_PROBE_TIMEOUT_S = 2.0

# Saida maxima e temperatura. Um tutorial de 3 opcoes assertivas passa facil
# de 600 tokens; cortar no meio perde o `proof` da ultima opcao, que e a
# parte que diz se funcionou. Temperatura baixa porque a saida e estrutural
# (JSON), nao criativa.
MODEL_MAX_TOKENS = 1400
MODEL_TEMPERATURE = 0.2

# --------------------------------------------------------------------------
# Processo / servico (processctl)
# --------------------------------------------------------------------------
# Quantos "mais caros" listar como suspeitos num evento / em `status`.
TOP_PROCESSES = 5

# PIDs de nucleos do Windows que NUNCA podem ser encerrados. Comparado por
# nome (case-insensitive) porque um PID de sistema muda a cada boot, mas o
# nome nao. `kill` recusa qualquer alvo cuja base do nome bata aqui, e o
# daemon tambem nunca se auto-considera suspeita.
PROTECTED_PROCESS_NAMES = frozenset(
    {
        "system",
        "system idle process",
        "registry",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "svchost.exe",
        "winlogon.exe",
        "dwm.exe",
    }
)

# Nomes (substring, case-insensitive) de processos proprio do Sentinel:
# nunca sao alvo de kill (evita matarem o daemon/CLI um ao outro).
SELF_PROCESS_HINTS = ("sentinel", "python", "py.exe")

# Processos que nunca sao "culpados" por consumo: o System Idle Process
# representa CPU NAO usada e, em maquinas multi-core, aparece como o maior
# 'cpu%' da lista (ex.: 8 cores ociosas = 800%). Deixa de ser ruido em
# top_processes e em fingerprints se for excluido na coleta.
NON_CULPRIT_PROCESS_NAMES = frozenset({"system idle process", "idle"})

# --------------------------------------------------------------------------
# Ambiente
# --------------------------------------------------------------------------
# Variavel que, definida, força modo nao-interativo (o ciclo do tutor e o
# confirm de kill se comportam como em sessao de agente: nunca bloqueiam).
NONINTERACTIVE_ENV_VAR = "SENTINEL_NONINTERACTIVE"


# --------------------------------------------------------------------------
# Resolucao de caminhos + overrides de config
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Paths:
    """Caminhos dentro do territorio `.sentinel/` de uma raiz.

    Instanciado por `paths_for`. Mantem a matematica de caminhos num lugar
    so, em vez de cada modulo concatenar OUTPUT_DIRNAME por conta propria.
    """

    root: Path

    @property
    def output_dir(self) -> Path:
        return self.root / OUTPUT_DIRNAME

    @property
    def events(self) -> Path:
        return self.output_dir / EVENTS_FILENAME

    @property
    def pid(self) -> Path:
        return self.output_dir / DAEMON_PID_FILENAME

    @property
    def daemon_log(self) -> Path:
        return self.output_dir / DAEMON_LOG_FILENAME

    @property
    def paused(self) -> Path:
        """O kill-switch: enquanto este arquivo existir, o daemon nao registra
        anomalia nova (nem, a partir da fase D, age). Uma linha com o ISO de
        quando pausou; o conteudo e diagnostico, a existencia e o comando."""
        return self.output_dir / PAUSED_FILENAME

    @property
    def config(self) -> Path:
        return self.output_dir / "config.json"

    @property
    def kb_db(self) -> Path:
        return self.output_dir / KB_DB_FILENAME

    @property
    def relief_state(self) -> Path:
        """Diario do degrau 1: o que esta aplicado agora, e a quem devolver."""
        return self.output_dir / RELIEF_STATE_FILENAME

    @property
    def orders(self) -> Path:
        return self.output_dir / ORDERS_FILENAME

    def ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir


def paths_for(root: Path | str) -> Paths:
    """Resolve o territorio `.sentinel/` a partir de uma raiz (padrao cwd)."""
    return Paths(root=Path(root).resolve())


def load_overrides(paths: Paths) -> dict:
    """Le `.sentinel/config.json` (opcional) e devolve um dict de
    overrides de limiar. Ausencia ou JSON quebrado viram `{}` silencioso:
    o Sentinel roda com os padroes em vez de estourar por um config mal
    formado. Chaves desconhecidas sao ignoradas aqui (validadas no uso).

    Usa `utf-8-sig` pra tolerar BOM: o Notepad e o `Set-Content -Encoding
    utf8` do Windows PowerShell 5.1 gravam um BOM no inicio, e um json.loads
    estrito reprovaria o arquivo inteiro por causa dele — silenciosamente
    os limiares voltariam ao padrao e ninguem entenderia por que.
    """
    if not paths.config.is_file():
        return {}

    try:
        data = json.loads(paths.config.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}

    return data if isinstance(data, dict) else {}


def threshold(name: str, overrides: dict, default: float) -> float:
    """Le um limiar de `overrides` (chave `name`), caindo em `default` se
    ausente ou nao-numerico. Centraliza o coercion pra nao espalhar float()
    try/except pelos modulos de regra.
    """
    value = overrides.get(name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)
