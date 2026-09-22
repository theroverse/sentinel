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
# v2: anomalias que nao nascem de limiar (`orphan_tree`, `app_failure`)
# passam a existir no mesmo arquivo, com `label` + `detail` no lugar de
# `value`/`threshold`. O leitor e tolerante por construcao (tudo via
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
    def config(self) -> Path:
        return self.output_dir / "config.json"

    @property
    def kb_db(self) -> Path:
        return self.output_dir / KB_DB_FILENAME

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
