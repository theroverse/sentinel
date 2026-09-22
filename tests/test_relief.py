from __future__ import annotations

# O degrau 1 sem processo real: um psutil de mentirinha com as constantes de
# prioridade e um relogio injetado. A regra inteira (aplicar, devolver,
# recusar, lembrar) roda aqui sem ninguem perceber que esta sendo testada.

import datetime
import json
import sys

import pytest

from sentinel import orders as orders_mod
from sentinel import settings
from sentinel.relief import (
    ACTION_BOOST_SELF,
    ACTION_LOWER,
    ACTION_RESTORE,
    ACTION_RESTORE_SELF,
    NOTHING,
    OK,
    SKIP_COOLDOWN,
    SKIP_DENIED,
    SKIP_GONE,
    SKIP_HOUR,
    SKIP_NO_ACTUATOR,
    SKIP_NO_PREVIOUS,
    SKIP_PROTECTED,
    SKIP_SHADOW,
    JournalEntry,
    PriorityActuator,
    ReliefAgent,
)
from sentinel.stall import Culprit

# Numeros do Windows (o psutil expoe as classes de prioridade como flags da
# API). O fake tem de ser fiel ao formato, nao a plataforma.
NORMAL = 32
IDLE = 64
HIGH = 128
BELOW = 16384


class NoSuchProcess(Exception):
    pass


class AccessDenied(Exception):
    pass


class _CM:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


class FakeProc:
    def __init__(
        self,
        pid,
        name,
        *,
        raw=NORMAL,
        create_time=1000.0,
        deny_get=False,
        deny_set=False,
    ):
        self.pid = pid
        self._name = name
        self._raw = raw
        self._create_time = create_time
        self.deny_get = deny_get
        self.deny_set = deny_set
        self.sets: list = []

    def name(self) -> str:
        return self._name

    def create_time(self) -> float:
        return self._create_time

    def oneshot(self):
        return _CM()

    def nice(self, value=None):
        if value is None:
            if self.deny_get:
                raise AccessDenied(self.pid)
            return self._raw
        if self.deny_set:
            raise AccessDenied(self.pid)
        self.sets.append(value)
        self._raw = value
        return None


class FakePs:
    """So a superficie que `PriorityActuator` toca, com as constantes reais."""

    NORMAL_PRIORITY_CLASS = NORMAL
    IDLE_PRIORITY_CLASS = IDLE
    BELOW_NORMAL_PRIORITY_CLASS = BELOW
    ABOVE_NORMAL_PRIORITY_CLASS = 32768
    HIGH_PRIORITY_CLASS = HIGH
    REALTIME_PRIORITY_CLASS = 256
    NoSuchProcess = NoSuchProcess
    AccessDenied = AccessDenied

    def __init__(self, procs=()):
        self.procs = {p.pid: p for p in procs}

    def Process(self, pid):
        proc = self.procs.get(pid)
        if proc is None:
            raise NoSuchProcess(pid)
        return proc


class FakePsPosix(FakePs):
    """Sem as classes do Windows: la o rebaixamento e na escala do `nice`, e
    uma classe que nao existe nao pode virar numero inventado."""

    BELOW_NORMAL_PRIORITY_CLASS = None
    HIGH_PRIORITY_CLASS = None
    LINUX_NICE_VALUES = (-20, 39)


class Clock:
    """Relogio de teste: anda quando o teste manda, e so isso."""

    def __init__(self):
        self.now = datetime.datetime(
            2026, 9, 22, 12, 0, 0, tzinfo=datetime.timezone.utc
        )

    def __call__(self) -> datetime.datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + datetime.timedelta(seconds=seconds)


def culprit(name="chrome", pid=4242, metric="ram") -> Culprit:
    return Culprit(name=name, pid=pid, metric=metric)


def paths_of(tmp_path) -> settings.Paths:
    return settings.paths_for(tmp_path)


def set_shadow(tmp_path, on: bool) -> None:
    """Grava pela API do proprio modulo: `orders shadow --on` faz isso."""
    orders_mod.save(paths_of(tmp_path), orders_mod.Orders(shadow=on))


def make_agent(tmp_path, ps, *, overrides=None, clock=None, self_pid=7777):
    return ReliefAgent(
        paths=paths_of(tmp_path),
        actuator=ps if isinstance(ps, PriorityActuator) else PriorityActuator(ps),
        overrides=overrides or {},
        clock=clock or Clock(),
        self_pid=self_pid,
    )


def open_episode(agent, target=None, *, suspect=False, ref=""):
    return agent.track(
        target or culprit(), episode_open=True, suspect=suspect, ref=ref
    )


def journal_rows(tmp_path) -> list:
    return json.loads(journal_path(tmp_path).read_text(encoding="utf-8"))["entries"]


def journal_path(tmp_path):
    return paths_of(tmp_path).relief_state


# -- o toque ---------------------------------------------------------------


def test_lower_moves_to_below_normal_and_keeps_the_previous_value(tmp_path):
    """Rebaixar sem lembrar o que tinha antes nao e reversao, e chute."""
    proc = FakeProc(4242, "chrome", raw=NORMAL)
    agent = make_agent(tmp_path, FakePs([proc]))

    results = open_episode(agent)

    assert [r.reason for r in results] == [OK]
    assert proc.nice() == BELOW
    entry = agent.pending()[0]
    assert (entry.pid, entry.from_raw, entry.to_raw) == (4242, NORMAL, BELOW)
    assert entry.create_time == 1000.0


def test_level_names_come_from_the_psutil_constants():
    """O log diz 'abaixo-do-normal', nao '16384' — e a tabela nao pode ter
    numero de API chutado a mao."""
    actuator = PriorityActuator(FakePs([]))

    assert actuator.level_name(BELOW) == "abaixo-do-normal"
    assert actuator.level_name(NORMAL) == "normal"
    assert actuator.level_name(HIGH) == "alta"


def test_unnamed_class_still_reads_as_a_number():
    """Classe que nao conhecemos: o log diz o numero em vez de mentir com um
    nome emprestado."""
    actuator = PriorityActuator(FakePs([]))

    assert actuator.level_name(4096) == "classe 4096"
    assert actuator.level_name(None) == "-"


def test_same_pid_is_acted_on_once_per_episode(tmp_path):
    """O intervalo rapido de 0,5 s nao pode gerar vinte tentativas: o mesmo
    alvo, no mesmo episodio, uma intervencao."""
    proc = FakeProc(4242, "chrome")
    agent = make_agent(tmp_path, FakePs([proc]))

    first = open_episode(agent)
    later = [open_episode(agent) for _ in range(5)]

    assert [r.reason for r in first] == [OK]
    assert later == [[], [], [], [], []]
    assert proc.sets == [BELOW]


def test_end_of_episode_restores_what_it_lowered(tmp_path):
    """Spec 5: o degrau 1 se desfaz sozinho, no fim do episodio."""
    proc = FakeProc(4242, "chrome", raw=NORMAL)
    agent = make_agent(tmp_path, FakePs([proc]))
    open_episode(agent)

    results = agent.track(None, episode_open=False, suspect=False)

    assert [r.reason for r in results] == [OK]
    assert proc.nice() == NORMAL
    assert agent.pending() == []


def test_culprit_change_returns_the_old_one_before_touching_the_new(tmp_path):
    """App reiniciado dentro do travamento: o pid velho nao pode ficar
    rebaixado com um dueno que ja nao existe. Depois do cooldown, claro — a
    mesma regra de sempre vale pro novo."""
    clock = Clock()
    old = FakeProc(11, "chrome")
    new = FakeProc(22, "chrome")
    agent = make_agent(tmp_path, FakePs([old, new]), clock=clock)
    open_episode(agent, culprit(pid=11))
    agent.track(None, episode_open=False, suspect=False)
    clock.advance(settings.RELIEF_APP_COOLDOWN_S + 1)

    results = open_episode(agent, culprit(name="other", pid=22))

    assert [r.action for r in results if r.reason == OK] == [ACTION_LOWER]
    assert old.nice() == NORMAL
    assert new.nice() == BELOW


def test_two_names_in_one_episode_swap_without_a_gap(tmp_path):
    """O culpado trocou de nome (o indexador virou o navegador): devolve o
    anterior no mesmo ciclo em que aplica no novo, senao o primeiro fica
    rebaixado para sempre."""
    first = FakeProc(11, "chrome")
    second = FakeProc(22, "opera")
    agent = make_agent(tmp_path, FakePs([first, second]))
    open_episode(agent, culprit(name="chrome", pid=11))

    results = open_episode(agent, culprit(name="opera", pid=22))

    assert [(r.action, r.reason) for r in results] == [
        (ACTION_RESTORE, OK),
        (ACTION_LOWER, OK),
    ]
    assert first.nice() == NORMAL
    assert second.nice() == BELOW


# -- guardas ---------------------------------------------------------------


def test_protected_culprit_is_refused_even_though_the_index_named_it(tmp_path):
    """O indice ja filtra, e a recusa repetida aqui e de proposito: o degrau
    nao depende da bondade do modulo vizinho."""
    proc = FakeProc(9, "svchost")
    agent = make_agent(tmp_path, FakePs([proc]))

    results = open_episode(agent, culprit(name="svchost", pid=9))

    assert [r.reason for r in results] == [SKIP_PROTECTED]
    assert proc.nice() == NORMAL
    assert agent.pending() == []


def test_self_names_are_refused_too(tmp_path):
    agent = make_agent(tmp_path, FakePs([FakeProc(5, "python.exe")]))

    results = open_episode(agent, culprit(name="python.exe", pid=5))

    assert [r.reason for r in results] == [SKIP_PROTECTED]


def test_hour_limit_counts_decisions_not_wins(tmp_path):
    """O teto existe pra limitar a ousadia, e ela continua ousando mesmo
    quando o processo escapa."""
    ps = FakePs([FakeProc(i, f"app{i}") for i in range(1, 5)])
    agent = make_agent(tmp_path, ps, overrides={"RELIEF_HOUR_LIMIT": 2})

    open_episode(agent, culprit(name="app1", pid=1), )
    agent.track(None, episode_open=False, suspect=False)
    open_episode(agent, culprit(name="app2", pid=2))
    agent.track(None, episode_open=False, suspect=False)
    refused = open_episode(agent, culprit(name="app3", pid=3))

    assert [r.reason for r in refused] == [SKIP_HOUR]


def test_cooldown_is_per_app_name_not_per_pid(tmp_path):
    """PID e reciclado no Windows; o app que travou ha dois minutos e o mesmo
    que vai travar de novo agora, com outro numero."""
    clock = Clock()
    first = FakeProc(1, "chrome")
    second = FakeProc(2, "chrome")
    agent = make_agent(tmp_path, FakePs([first, second]), clock=clock)
    open_episode(agent, culprit(name="chrome", pid=1))
    agent.track(None, episode_open=False, suspect=False)

    within = open_episode(agent, culprit(name="chrome", pid=2))
    assert [r.reason for r in within] == [SKIP_COOLDOWN]
    assert second.nice() == NORMAL

    clock.advance(settings.RELIEF_APP_COOLDOWN_S + 1)
    # A recusa anterior ja decidiu por este pid no episodio: sem fechar o
    # episodio, a idempotencia manda mais do que o relogio.
    agent._decided = 0
    after = open_episode(agent, culprit(name="chrome", pid=2))
    assert [r.reason for r in after] == [OK]
    assert second.nice() == BELOW


def test_guards_count_shadow_decisions(tmp_path):
    """O sombra ensaia a regra inteira: uma decisao que nao consome o proprio
    teto ensinaria ao usuario que o Sentinel para de intervir quando nao
    devia."""
    set_shadow(tmp_path, True)
    ps = FakePs([FakeProc(i, f"app{i}") for i in range(1, 4)])
    agent = make_agent(tmp_path, ps, overrides={"RELIEF_HOUR_LIMIT": 1})

    open_episode(agent, culprit(name="app1", pid=1))
    refused = open_episode(agent, culprit(name="app2", pid=2))

    assert [r.reason for r in refused] == [SKIP_HOUR]


def test_no_agent_call_means_no_action(tmp_path):
    """Quem checa o `paused` e o loop (testado em test_daemon): sem chamada,
    nada acontece e nada fica no journal."""
    proc = FakeProc(4242, "chrome")
    agent = make_agent(tmp_path, FakePs([proc]))

    assert agent.track(None, episode_open=False, suspect=False) == []
    assert proc.nice() == NORMAL
    assert agent.pending() == []


# -- os limites do mundo ---------------------------------------------------


def test_access_denied_is_declared_not_retried(tmp_path):
    """Outra sessao, ou elevada: o limite vira palavra, nao contorno."""
    proc = FakeProc(4242, "chrome", deny_set=True)
    agent = make_agent(tmp_path, FakePs([proc]))

    results = open_episode(agent)

    assert [r.reason for r in results] == [SKIP_DENIED]
    assert agent.pending() == []


def test_gone_pid_is_skipped_without_blame(tmp_path):
    agent = make_agent(tmp_path, FakePs([]))

    results = open_episode(agent)

    assert [r.reason for r in results] == [SKIP_GONE]
    assert agent.pending() == []


def test_recycled_pid_is_never_restored_to_a_stranger(tmp_path):
    """`create_time` e a prova de identidade: mesmo numero, outra vida, e nao
    ha a quem devolver."""
    stranger = FakeProc(4242, "notepad", raw=HIGH, create_time=999999.0)
    agent = make_agent(tmp_path, FakePs([stranger]))
    agent._entries = [
        JournalEntry(
            pid=4242, name="chrome", create_time=1000.0,
            at="2026-09-22T12:00:00+00:00", from_raw=NORMAL, to_raw=BELOW,
        )
    ]
    agent._decided = 4242

    results = agent.track(None, episode_open=False, suspect=False)

    assert [r.reason for r in results] == [SKIP_GONE]
    assert stranger.nice() == HIGH
    assert agent.pending() == []


def test_restore_without_previous_value_acts_nowhere(tmp_path):
    """Chutar 'normal' subiria a prioridade de algo que ja estava rebaixado
    antes de nos — e nao e evento de historico."""
    proc = FakeProc(4242, "chrome", raw=IDLE)
    agent = make_agent(tmp_path, FakePs([proc]))
    agent._entries = [
        JournalEntry(
            pid=4242, name="chrome", create_time=1000.0,
            at="2026-09-22T12:00:00+00:00", from_raw=None, to_raw=BELOW,
        )
    ]
    agent._decided = 4242

    results = agent.track(None, episode_open=False, suspect=False)

    assert results == []
    assert proc.nice() == IDLE


def test_missing_psutil_says_so_instead_of_blaming_the_process(tmp_path, monkeypatch):
    """Sem a alavanca, todo pid pareceria "inalcancavel" — e isso inocentaria
    o degrau de um motivo que e dele."""
    monkeypatch.setitem(sys.modules, "psutil", None)
    agent = ReliefAgent(
        paths=paths_of(tmp_path),
        actuator=PriorityActuator(),
        clock=Clock(),
        self_pid=7777,
    )

    results = open_episode(agent)

    assert results[0].reason == SKIP_NO_ACTUATOR


# -- o sombra --------------------------------------------------------------


def test_shadow_records_the_decision_and_touches_nothing(tmp_path):
    """Spec 5: o sombra decide e grava a decisao como nao aplicada — unica
    maneira de ver o que o Sentinel faria antes de confiar nele."""
    set_shadow(tmp_path, True)
    proc = FakeProc(4242, "chrome")
    agent = make_agent(tmp_path, FakePs([proc]))

    results = open_episode(agent, ref="evt-20260922-120000-abcd")

    assert results[0].reason == SKIP_SHADOW
    assert results[0].shadow is True
    assert results[0].ref == "evt-20260922-120000-abcd"
    assert proc.nice() == NORMAL
    assert agent.pending() == []
    assert journal_rows(tmp_path)[0]["shadow"] is True


def test_shadow_switch_takes_effect_on_the_next_cycle(tmp_path):
    """`sentinel orders shadow on` nao pede reinicio de nada: o arquivo e
    relido a cada decisao, como o `paused`."""
    agent = make_agent(tmp_path, FakePs([FakeProc(1, "a")]))
    assert agent.shadow() is False

    set_shadow(tmp_path, True)

    assert agent.shadow() is True


def test_shadow_end_of_episode_still_restores(tmp_path):
    """Sombra segura o proximo passo, nao desfaz o ultimo: o que foi aplicado
    antes de ligar continua tendo de voltar."""
    proc = FakeProc(1, "a")
    agent = make_agent(tmp_path, FakePs([proc]))
    open_episode(agent, culprit(name="a", pid=1))
    set_shadow(tmp_path, True)

    results = agent.track(None, episode_open=False, suspect=False)

    assert [r.reason for r in results] == [OK]
    assert proc.nice() == NORMAL


# -- o proprio daemon ------------------------------------------------------


def test_suspect_episode_boosts_the_daemon_and_clear_returns_it(tmp_path):
    """Spec 4: sob travamento o vigia nao pode ser a vitima."""
    self_proc = FakeProc(7777, "sentinel", raw=NORMAL)
    agent = make_agent(tmp_path, FakePs([self_proc]))

    boosted = agent.track(None, episode_open=False, suspect=True)

    assert [r.reason for r in boosted] == [OK]
    assert boosted[0].action == ACTION_BOOST_SELF
    assert self_proc.nice() == HIGH

    cleared = agent.track(None, episode_open=False, suspect=False)

    assert cleared[0].action == ACTION_RESTORE_SELF
    assert self_proc.nice() == NORMAL


def test_self_boost_is_not_journaled(tmp_path):
    """O boost morre com o daemon: registrar "devolver pro pid X" apontando
    pro proprio processo seria lixo esperando o dia em que um estranho herda o
    numero."""
    agent = make_agent(tmp_path, FakePs([FakeProc(7777, "sentinel")]))

    agent.track(None, episode_open=False, suspect=True)

    assert agent._entries == []


def test_boost_without_a_high_class_is_not_a_failure(tmp_path):
    """POSIX nao tem HIGH_PRIORITY_CLASS: aqui nao ha boost, e nao ha
    fracasso."""
    agent = make_agent(tmp_path, PriorityActuator(FakePsPosix([])))

    assert agent.track(None, episode_open=False, suspect=True) == []


# -- vida do daemon --------------------------------------------------------


def test_journal_survives_a_new_agent(tmp_path):
    """O journal e o que sobe depois do crash: sem ele, o rebaixamento fica
    ate o usuario fechar o app, sem nada dizendo por que."""
    proc = FakeProc(4242, "chrome")
    ps = FakePs([proc])
    make_agent(tmp_path, ps)
    open_episode(make_agent(tmp_path, ps))

    revived = make_agent(tmp_path, ps)
    assert [row["pid"] for row in journal_rows(tmp_path)] == [4242]

    results = revived.recover()

    assert [r.reason for r in results] == [OK]
    assert proc.nice() == NORMAL
    assert revived.pending() == []


def test_recover_says_nothing_about_a_target_that_no_longer_exists(tmp_path):
    """O processo morreu com o daemon: nao houve intervencao a devolver, e
    gravar uma linha disso seria historico inventado."""
    proc = FakeProc(4242, "chrome")
    ps = FakePs([proc])
    open_episode(make_agent(tmp_path, ps))

    revived = make_agent(tmp_path, FakePs([]))

    assert revived.recover() == []
    assert revived.pending() == []


def test_shut_down_leaves_nothing_behind(tmp_path):
    """Ctrl+C no meio do travamento: a prioridade do usuario nao sai junto."""
    a = FakeProc(1, "a")
    b = FakeProc(2, "b")
    self_proc = FakeProc(7777, "sentinel")
    agent = make_agent(tmp_path, FakePs([a, b, self_proc]))
    open_episode(agent, culprit(name="a", pid=1))
    agent._decided = 0
    open_episode(agent, culprit(name="b", pid=2))
    agent.track(None, episode_open=False, suspect=True)

    results = agent.shut_down()

    assert {r.action for r in results} == {ACTION_RESTORE, ACTION_RESTORE_SELF}
    assert (a.nice(), b.nice(), self_proc.nice()) == (NORMAL, NORMAL, NORMAL)
    assert agent.pending() == []
    assert agent._decided == 0


# -- o arquivo -------------------------------------------------------------


def test_journal_is_written_atomically_and_round_trips(tmp_path):
    """Escrita atomica e o preco: o daemon que assume o posto le o que o
    anterior deixou sem ver um JSON pela metade."""
    agent = make_agent(tmp_path, FakePs([FakeProc(4242, "chrome")]))
    open_episode(agent)

    rows = journal_rows(tmp_path)

    assert rows[0]["action"] == ACTION_LOWER
    assert rows[0]["reverted"] is False
    assert rows[0]["from_raw"] == NORMAL
    assert not journal_path(tmp_path).with_name("relief.json.tmp").exists()
    assert journal_path(tmp_path).read_text(encoding="utf-8").count("\n") == 1


def test_unreadable_journal_is_empty_not_fatal(tmp_path):
    """Um config quebrado ja custaria os limiares; um journal ilegivel nao
    pode custar tambem a vigilancia."""
    paths = paths_of(tmp_path)
    paths.ensure_output_dir()
    journal_path(tmp_path).write_text("{ isto nao e json", encoding="utf-8")

    agent = make_agent(tmp_path, FakePs([FakeProc(4242, "chrome")]))

    assert agent._entries == []
    assert [r.reason for r in open_episode(agent)] == [OK]


def test_bom_in_the_journal_does_not_erase_history(tmp_path):
    """O Notepad e o `Set-Content` do PowerShell 5.1 gravam BOM: sem tolerar,
    o daemon acordaria sem saber o que deixou rebaixado."""
    proc = FakeProc(4242, "chrome")
    agent = make_agent(tmp_path, FakePs([proc]))
    open_episode(agent)
    path = journal_path(tmp_path)
    path.write_text("\ufeff" + path.read_text(encoding="utf-8"), encoding="utf-8")

    revived = make_agent(tmp_path, FakePs([proc]))

    assert [entry.pid for entry in revived.pending()] == [4242]


def test_journal_is_capped(tmp_path):
    """O teto de linhas existe porque o journal e lido no start: um arquivo
    que cresce para sempre seria o preco de um diagnostico."""
    ps = FakePs([FakeProc(i, f"app{i}") for i in range(1, 9)])
    agent = make_agent(tmp_path, ps, overrides={"RELIEF_HOUR_LIMIT": 99, "RELIEF_APP_COOLDOWN_S": 0})
    for i in range(1, 9):
        open_episode(agent, culprit(name=f"app{i}", pid=i))
        agent.track(None, episode_open=False, suspect=False)
        agent._decided = 0

    assert len(journal_rows(tmp_path)) <= settings.RELIEF_JOURNAL_MAX
    assert len(agent._entries) <= settings.RELIEF_JOURNAL_MAX


# -- o caminho digitado ----------------------------------------------------


def test_manual_lower_bypasses_the_guards_but_not_the_refusals(tmp_path):
    """`sentinel relief <pid>`: quem autorizou foi voce, entao o teto e o
    cooldown saem de cena — servico do Windows nao."""
    agent = make_agent(tmp_path, FakePs([FakeProc(1, "chrome"), FakeProc(2, "svchost")]))
    agent._entries = [
        JournalEntry(
            pid=9, name="app", create_time=1.0,
            at=datetime.datetime(2026, 9, 22, 11, 59, tzinfo=datetime.timezone.utc).isoformat(),
            from_raw=NORMAL, to_raw=BELOW,
        )
    ] * (settings.RELIEF_HOUR_LIMIT + 2)

    applied = agent.apply_manual(1)
    refused = agent.apply_manual(2)

    assert applied.reason == OK
    assert applied.ref == "manual"
    assert refused.reason == SKIP_PROTECTED


def test_manual_action_is_not_journaled(tmp_path):
    """Dois processos escrevendo o mesmo journal fariam um dos dois perder
    historico; a prova do caminho manual fica no `events.jsonl`."""
    agent = make_agent(tmp_path, FakePs([FakeProc(1, "chrome")]))

    agent.apply_manual(1)

    assert agent._entries == []
    assert not journal_path(tmp_path).exists()


def test_manual_restore_needs_a_recorded_previous_value(tmp_path):
    agent = make_agent(tmp_path, FakePs([FakeProc(1, "chrome", raw=IDLE)]))

    result = agent.restore_manual(1, None)

    assert result.reason == SKIP_NO_PREVIOUS
    assert result.label().startswith("NAO FEZ pid 1")


def test_manual_restore_moves_back_to_the_recorded_value(tmp_path):
    agent = make_agent(tmp_path, FakePs([FakeProc(1, "chrome", raw=BELOW)]))

    result = agent.restore_manual(1, NORMAL)

    assert result.reason == OK
    assert result.action == ACTION_RESTORE
    assert result.to_level == "normal"


# -- a linha que o usuario le ----------------------------------------------


def test_refusal_reads_as_a_refusal(tmp_path):
    """`FEZ ... [cooldown-do-app]` seria a pior mentira possivel num log as
    2h da manha: tres verbos, tres fatos."""
    agent = make_agent(
        tmp_path, FakePs([FakeProc(1, "chrome")]), overrides={"RELIEF_HOUR_LIMIT": 0}
    )

    line = open_episode(agent, culprit(name="chrome", pid=1))[0].label()

    assert line.startswith("NAO FEZ chrome (pid 1)")
    assert SKIP_HOUR in line


def test_applied_lower_reads_as_done(tmp_path):
    agent = make_agent(tmp_path, FakePs([FakeProc(1, "chrome")]))

    line = open_episode(agent, culprit(name="chrome", pid=1))[0].label()

    assert line == "FEZ chrome (pid 1): prioridade -> abaixo-do-normal [ok]"


def test_shadow_reads_as_intention(tmp_path):
    set_shadow(tmp_path, True)
    agent = make_agent(tmp_path, FakePs([FakeProc(1, "chrome")]))

    line = open_episode(agent, culprit(name="chrome", pid=1))[0].label()

    assert line.startswith("SERIA chrome (pid 1)")


def test_worth_logging_drops_the_non_events(tmp_path):
    """`nada-a-fazer` e o barulho de todo ciclo em que nada mudou; gravar isso
    lotaria o historico de nao-acontecimentos."""
    agent = make_agent(tmp_path, FakePs([]))

    assert agent.track(None, episode_open=False, suspect=False) == []
