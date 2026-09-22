from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass, field

from sentinel import orders as orders_mod
from sentinel import settings
from sentinel.processctl import is_protected, is_self


# ---------------------------------------------------------------------------
# O degrau 1: rebaixar quem travou a maquina, e devolver depois
# ---------------------------------------------------------------------------
# O indice de estagnacao (`stall`) mede e nomeia o culpado. Este modulo e o
# unico degrau da escada que age sem cracha, e age com a alavanca mais fraca
# que existe: prioridade. Rebaixar nao limita quanto o processo usa, limita a
# ORDEM em que ele e atendido -- e isso basta pra devolver o clique de quem
# esta olhando a maquina travar, sem perder nenhum trabalho aberto.
#
# Por que so este degrau esta ligado desde o inicio (spec 5):
#  - funciona onde o travamento acontece (Chrome, Electron, Discord: todos
#    inalcanceis ao teto de CPU por job, que pedira elevacao);
#  - se desfaz sozinho, no fim do episodio;
#  - nao pede administracao, em nenhum caminho.
#
# O que protege nao e confianca, sao guardas: teto de intervencoes por hora,
# cooldown por NOME de app (pid e reciclado no Windows), recusa a processo
# protegido e a si mesmo, o arquivo `paused` que o daemon checa antes de
# chamar, e o modo sombra (`orders.json`), que decide e grava sem tocar.
#
# Toda decisao sai daqui como `ReliefResult` e vira tres coisas: linha no
# `daemon.log`, evento proprio no `events.jsonl` (`kind: intervention`) e
# entrada no journal (`.sentinel/relief.json`). O historico auditavel e o que
# permite, um dia, confiar no degrau 3.

ACTION_LOWER = "priority_below_normal"
ACTION_RESTORE = "priority_restored"
ACTION_BOOST_SELF = "priority_boost_self"
ACTION_RESTORE_SELF = "priority_restore_self"

# Alvos do alivio, em palavras, porque o numero cru (`16384`) nao diz nada a
# quem le log as 2h da manha. A tabela e montada das constantes do proprio
# psutil: numero de API chutado aqui seria um tutorial mentindo.
_LEVEL_BELOW_NORMAL = "abaixo-do-normal"

_LEVEL_CONSTANTS = (
    ("ociosa", "IDLE_PRIORITY_CLASS"),
    (_LEVEL_BELOW_NORMAL, "BELOW_NORMAL_PRIORITY_CLASS"),
    ("normal", "NORMAL_PRIORITY_CLASS"),
    ("acima-do-normal", "ABOVE_NORMAL_PRIORITY_CLASS"),
    ("alta", "HIGH_PRIORITY_CLASS"),
    ("tempo-real", "REALTIME_PRIORITY_CLASS"),
)

# Motivos de recusa. Cada um e uma frase no log e um campo no evento.
OK = "ok"
SKIP_SHADOW = "modo-sombra"
SKIP_HOUR = "teto-de-uma-hora"
SKIP_COOLDOWN = "cooldown-do-app"
SKIP_PROTECTED = "processo-protegido"
SKIP_GONE = "processo-inalcancavel"
SKIP_DENIED = "sem-alcance"
SKIP_NO_ACTUATOR = "sem-alavanca"
SKIP_NO_PREVIOUS = "sem-valor-anterior"
NOTHING = "nada-a-fazer"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat()


def _parse_iso(value) -> datetime.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class ReliefResult:
    """O que o degrau decidiu, e o que aconteceu depois disso.

    Em modo sombra `applied` e False e `shadow` e True: a decisao continua
    gravada, que e exatamente o proposito do sombra.
    """

    action: str
    reason: str
    pid: int = 0
    name: str = ""
    from_level: str = "-"
    to_level: str = "-"
    from_raw: object = None
    to_raw: object = None
    shadow: bool = False
    ref: str = ""

    @property
    def applied(self) -> bool:
        return self.reason == OK

    @property
    def worth_logging(self) -> bool:
        """Resultado que merece linha e evento.

        `nada-a-fazer` e o barulho de todo ciclo em que nada mudou (o alvo ja
        esta rebaixado, ou nao havia alvo): gravar isso lotaria o historico de
        nao-acontecimentos.
        """
        return self.reason != NOTHING

    def to_detail(self) -> dict:
        return {
            "action": self.action,
            "target": {"pid": self.pid, "name": self.name},
            # Os dois numeros crus vao junto com os nomes: `sentinel relief
            # <pid> --restore` devolve exatamente o que estava la antes, e um
            # evento sem `from_raw` nao deixa o que fazer a quem chegou
            # depois -- nem pro proprio Sentinel.
            "priority": {
                "from": self.from_level,
                "from_raw": self.from_raw,
                "to": self.to_level,
                "to_raw": self.to_raw,
            },
            "reason": self.reason,
            "shadow": self.shadow,
        }

    def label(self) -> str:
        """Uma linha do que aconteceu, pra quem le sem abrir o JSONL.

        Tres verbos, porque tres fatos: `FEZ` aplicou, `SERIA` e o sombra, e
        `NAO FEZ` barrado numa guarda ou num pid que sumiu. Uma recusa lida
        como "FEZ" seria o pior tipo de mentira num log as 2h da manha.
        """
        who = f"{self.name} (pid {self.pid})" if self.name else f"pid {self.pid}"
        if self.shadow:
            prefix = "SERIA"
        elif self.applied:
            prefix = "FEZ"
        else:
            prefix = "NAO FEZ"
        if self.action == ACTION_LOWER:
            if self.to_level == "-":
                return f"{prefix} {who}: [{self.reason}]"
            return (
                f"{prefix} {who}: prioridade -> {self.to_level} [{self.reason}]"
            )
        if self.action == ACTION_RESTORE:
            if self.to_level == "-":
                # Nenhum nivel pra mostrar = nenhum valor anterior. Dizer
                # "devolvida (- -> -)" seria a linha mentindo pro log.
                return f"{prefix} {who}: sem o que devolver [{self.reason}]"
            return (
                f"{prefix} {who}: prioridade devolvida "
                f"({self.from_level} -> {self.to_level}) [{self.reason}]"
            )
        return f"{prefix} {who}: {self.action} [{self.reason}]"


@dataclass
class JournalEntry:
    """Uma intervencao registrada, com o valor que o processo tinha antes."""

    pid: int
    name: str
    create_time: float
    at: str
    action: str = ACTION_LOWER
    from_raw: object = None
    to_raw: object = None
    reverted: bool = False
    shadow: bool = False

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "name": self.name,
            "create_time": self.create_time,
            "from_raw": self.from_raw,
            "to_raw": self.to_raw,
            "at": self.at,
            "action": self.action,
            "reverted": self.reverted,
            "shadow": self.shadow,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JournalEntry":
        return cls(
            pid=int(data.get("pid", 0) or 0),
            name=str(data.get("name", "")),
            create_time=float(data.get("create_time", 0.0) or 0.0),
            at=str(data.get("at", "")),
            action=str(data.get("action", ACTION_LOWER)),
            from_raw=data.get("from_raw"),
            to_raw=data.get("to_raw"),
            reverted=bool(data.get("reverted", False)),
            shadow=bool(data.get("shadow", False)),
        )


class PriorityActuator:
    """A unica alavanca do degrau 1: a prioridade do processo.

    psutil injetavel, como no resto do pacote -- nenhum teste desta fase ve
    processo real, e sem psutil o degrau devolve `sem-alavanca` em vez de
    estourar o loop de vigilancia.
    """

    def __init__(self, psutil_module=None) -> None:
        self._ps = psutil_module

    def module(self):
        if self._ps is None:
            try:
                import psutil as psutil_module  # type: ignore[no-redef]
            except Exception:
                return None
            self._ps = psutil_module
        return self._ps

    @property
    def available(self) -> bool:
        return self.module() is not None

    def level_name(self, raw) -> str:
        """Nome da classe de prioridade, montado das constantes do psutil."""
        if raw is None:
            return "-"
        ps = self.module()
        if ps is not None:
            for name, constant in _LEVEL_CONSTANTS:
                if getattr(ps, constant, None) == raw:
                    return name
        return f"classe {raw}"

    def priority_class(self, constant: str):
        ps = self.module()
        return getattr(ps, constant, None) if ps is not None else None

    def _target_raw(self, current) -> object:
        """O valor de 'abaixo do normal' na plataforma atual."""
        ps = self.module()
        below = self.priority_class("BELOW_NORMAL_PRIORITY_CLASS")
        if below is not None:
            return below
        # POSIX: la nice maior = menos prioridade. O teto vem do proprio
        # psutil quando ele o anuncia; 39 e o fim da escala do Linux na
        # contagem do psutil.
        range_max = getattr(ps, "LINUX_NICE_VALUES", (None, None))[1]
        ceiling = range_max if isinstance(range_max, int) else 39
        base = current if isinstance(current, int) else 0
        return min(base + settings.RELIEF_NICE_STEP, ceiling)

    # -- operacoes -----------------------------------------------------

    def inspect(self, pid: int) -> dict | None:
        """`{name, create_time, raw}`, ou None se o pid nao esta mais ali.

        `create_time` e o que prova que o pid de agora e o mesmo processo de
        antes: sem ele, devolver a prioridade poderia acertar um estranho que
        herdou o numero.
        """
        ps = self.module()
        if ps is None:
            return None
        try:
            proc = ps.Process(pid)
            with proc.oneshot():
                return {
                    "name": proc.name(),
                    "create_time": float(proc.create_time()),
                    "raw": proc.nice(),
                }
        except Exception:
            return None

    def lower(self, pid: int) -> tuple[str, object, object]:
        """Rebaixa. Devolve (motivo, valor anterior, valor aplicado)."""
        return self.set_level(pid, None)

    def set_level(self, pid: int, raw) -> tuple[str, object, object]:
        """Move o processo para `raw` (None = 'abaixo do normal' da plataforma)."""
        ps = self.module()
        if ps is None:
            return SKIP_NO_ACTUATOR, None, None
        try:
            proc = ps.Process(pid)
            current = proc.nice()
        except ps.NoSuchProcess:
            return SKIP_GONE, None, None
        except ps.AccessDenied:
            # Outra sessao, ou elevada: o limite e declarado, nao contornado.
            return SKIP_DENIED, None, None
        except Exception:
            return SKIP_GONE, None, None
        target = self._target_raw(current) if raw is None else raw
        if current == target:
            return NOTHING, current, target
        try:
            proc.nice(target)
        except ps.AccessDenied:
            return SKIP_DENIED, current, target
        except Exception:
            return SKIP_GONE, current, target
        return OK, current, target


@dataclass
class ReliefAgent:
    """O dono do degrau 1 num daemon: decide, aplica, devolve, lembra.

    `actuator` e `clock` injetaveis, entao a regra inteira roda em teste sem
    processo real e relogio de parede. O journal (`.sentinel/relief.json`) e o
    que sobrevive ao daemon: sem ele, um crash no meio de um episodio deixaria
    um app rebaixado ate o usuario fecha-lo, sem nada dizendo por que.
    """

    paths: settings.Paths
    actuator: PriorityActuator | None = None
    overrides: dict = field(default_factory=dict)
    clock: object = _utcnow
    self_pid: int = 0

    _entries: list = field(default_factory=list, init=False, repr=False)
    _decided: int = field(default=0, init=False, repr=False)
    _self_entry: JournalEntry | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.actuator is None:
            self.actuator = PriorityActuator()
        if not self.self_pid:
            self.self_pid = os.getpid()
        self._entries = self._load_journal()

    # -- guardas -------------------------------------------------------

    def _th(self, name: str, default: int) -> float:
        return settings.threshold(name, self.overrides, float(default))

    def _now(self) -> datetime.datetime:
        return self.clock()

    def _counts_as_intervention(self, entry: JournalEntry) -> bool:
        """O que as guardas contam.

        Entra a decisao em modo sombra tambem: o sombra existe pra ensaiar a
        regra inteira, e uma decisao que nao consome o proprio teto ensinaria
        ao usuario que o Sentinel para de intervir quando nao devia. Boost do
        proprio daemon nao conta, porque contar contra si mesmo desligaria o
        degrau 1 na hora em que ele mais serve.
        """
        return entry.action == ACTION_LOWER

    def _refusal(self, name: str) -> str:
        """A primeira guarda que barra, com o motivo no nome.

        As duas contam decisoes, nao apenas toques bem-sucedidos: o cooldown
        existe porque o app que travou ha dois minutos e o mesmo que vai
        travar de novo agora, com outro pid.
        """
        cooldown = self._th("RELIEF_APP_COOLDOWN_S", settings.RELIEF_APP_COOLDOWN_S)
        hour = self._th("RELIEF_HOUR_LIMIT", settings.RELIEF_HOUR_LIMIT)
        cutoff = self._now() - datetime.timedelta(seconds=3600.0)
        recent_total = 0
        last_for_app: datetime.datetime | None = None
        for entry in self._entries:
            if not self._counts_as_intervention(entry):
                continue
            stamp = _parse_iso(entry.at)
            if stamp is None or stamp < cutoff:
                continue
            recent_total += 1
            if entry.name == name and (last_for_app is None or stamp > last_for_app):
                last_for_app = stamp
        if last_for_app is not None:
            if (self._now() - last_for_app).total_seconds() < cooldown:
                return SKIP_COOLDOWN
        if recent_total >= hour:
            return SKIP_HOUR
        return ""

    # -- sombra --------------------------------------------------------

    def shadow(self) -> bool:
        """Relido a cada decisao, como o `paused`: o interruptor tem de valer
        no ciclo seguinte a `sentinel orders shadow on`, sem reiniciar nada."""
        return orders_mod.load(self.paths).shadow

    # -- journal -------------------------------------------------------

    def _load_journal(self) -> list:
        path = self.paths.relief_state
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return []
        rows = data.get("entries") if isinstance(data, dict) else None
        out: list = []
        for row in rows or ():
            if not isinstance(row, dict):
                continue
            try:
                out.append(JournalEntry.from_dict(row))
            except (TypeError, ValueError):
                continue
        return out[-settings.RELIEF_JOURNAL_MAX :]

    def _save_journal(self) -> None:
        payload = {
            "schema": 1,
            "written_at": _iso(self._now()),
            "entries": [entry.to_dict() for entry in self._entries],
        }
        path = self.paths.relief_state
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(tmp, path)
        except OSError:
            # Sem journal o degrau ainda age, mas perde a reversao automatica
            # no fim do episodio -- e a prioridade volta quando o processo
            # fecha. Nao vale derrubar a vigilancia por diagnostico.
            pass

    def _remember(self, entry: JournalEntry) -> None:
        self._entries.append(entry)
        self._entries = self._entries[-settings.RELIEF_JOURNAL_MAX :]
        self._save_journal()

    def pending(self) -> list:
        """Intervencoes de alvo que ainda nao foram devolvidas."""
        return [
            entry
            for entry in self._entries
            if not entry.reverted and entry.action == ACTION_LOWER
        ]

    # -- ciclo ---------------------------------------------------------

    def track(self, culprit, *, episode_open: bool, suspect: bool, ref: str = "") -> list:
        """Um ciclo do daemon, com o resultado do indice de estagnacao.

        Devolve os `ReliefResult`s que merecem ser gravados. A decisao e
        idempotente: o mesmo alvo, dentro do mesmo episodio, uma intervencao
        so -- o intervalo rapido de 0,5 s daria vinte tentativas por segundo
        se nao fosse.
        """
        results = [self._track_self(suspect, ref=ref)]

        name = str(getattr(culprit, "name", "") or "")
        pid = int(getattr(culprit, "pid", 0) or 0)

        if not episode_open or not name or not pid:
            results.append(self._end_of_episode(ref=ref))
            return [r for r in results if r.worth_logging]

        if is_protected(name) or is_self(name):
            # O indice ja filtra, e isto aqui e a mesma recusa escrita duas
            # vezes de proposito: o dia que o chamador mudar, o degrau nao
            # pode depender da bondade do outro modulo.
            self._decided = pid
            results.append(
                ReliefResult(ACTION_LOWER, SKIP_PROTECTED, pid=pid, name=name, ref=ref)
            )
            return [r for r in results if r.worth_logging]

        if pid == self._decided:
            return [r for r in results if r.worth_logging]

        shadow = self.shadow()
        refusal = self._refusal(name)
        if refusal:
            self._decided = pid
            results.append(
                ReliefResult(
                    ACTION_LOWER, refusal, pid=pid, name=name,
                    to_level=_LEVEL_BELOW_NORMAL, shadow=shadow, ref=ref,
                )
            )
            return [r for r in results if r.worth_logging]

        # O culpado trocou de pid dentro do episodio (app reiniciado): devolve
        # o anterior antes de encostar no novo, senao o primeiro fica rebaixado
        # com um dueno que ja nao existe.
        results.append(self._end_of_episode(ref=ref))
        self._decided = pid
        results.append(self._apply(pid, name, shadow=shadow, ref=ref))
        return [r for r in results if r.worth_logging]

    def _apply(self, pid: int, name: str, *, shadow: bool, ref: str) -> ReliefResult:
        if shadow:
            self._remember(
                JournalEntry(
                    pid=pid, name=name, create_time=0.0, at=_iso(self._now()),
                    reverted=True, shadow=True,
                )
            )
            return ReliefResult(
                ACTION_LOWER, SKIP_SHADOW, pid=pid, name=name,
                to_level=_LEVEL_BELOW_NORMAL, shadow=True, ref=ref,
            )
        actuator = self.actuator
        if not actuator.available:
            # Sem psutil todo pid parece "nao alcancavel", e isso inocentaria
            # o degrau de dizer que nao havia o que fazer quando o que falta
            # e a alavanca.
            return ReliefResult(
                ACTION_LOWER, SKIP_NO_ACTUATOR, pid=pid, name=name,
                to_level=_LEVEL_BELOW_NORMAL, shadow=shadow, ref=ref,
            )
        info = actuator.inspect(pid)
        if info is None:
            return ReliefResult(ACTION_LOWER, SKIP_GONE, pid=pid, name=name, ref=ref)
        if is_protected(info["name"]) or is_self(info["name"]):
            return ReliefResult(
                ACTION_LOWER, SKIP_PROTECTED, pid=pid, name=name,
                from_level=actuator.level_name(info["raw"]), ref=ref,
            )
        reason, before, after = actuator.lower(pid)
        if reason not in (OK, NOTHING):
            return ReliefResult(
                ACTION_LOWER, reason, pid=pid, name=name,
                from_level=actuator.level_name(info["raw"]),
                to_level=_LEVEL_BELOW_NORMAL, ref=ref,
            )
        if reason == OK:
            self._remember(
                JournalEntry(
                    pid=pid,
                    name=name,
                    create_time=info["create_time"],
                    at=_iso(self._now()),
                    from_raw=before,
                    to_raw=after,
                )
            )
        return ReliefResult(
            ACTION_LOWER, reason, pid=pid, name=name,
            from_level=actuator.level_name(before),
            to_level=actuator.level_name(after),
            from_raw=before, to_raw=after, ref=ref,
        )

    def _end_of_episode(self, *, ref: str = "") -> ReliefResult:
        """Devolve o alvo do episodio que acabou (ou que trocou de pid)."""
        decided, self._decided = self._decided, 0
        if not decided:
            return ReliefResult(ACTION_RESTORE, NOTHING, pid=decided)
        entry = next(
            (e for e in reversed(self._entries) if e.pid == decided and not e.reverted),
            None,
        )
        if entry is None:
            # Nada aplicado pra este pid (recusa, sombra, ou ja morto): nao ha
            # o que devolver, e dizer isso em voz alta seria mentira.
            return ReliefResult(ACTION_RESTORE, NOTHING, pid=decided)
        result = self._restore(entry)
        result.ref = ref
        return result

    def _restore(self, entry: JournalEntry) -> ReliefResult:
        actuator = self.actuator
        if entry.from_raw is None:
            # Sem valor anterior nao ha para onde voltar: chutar 'normal'
            # poderia subir a prioridade de algo que ja estava rebaixado antes
            # de nos.
            entry.reverted = True
            self._save_journal()
            return ReliefResult(ACTION_RESTORE, NOTHING, pid=entry.pid, name=entry.name)
        info = actuator.inspect(entry.pid)
        if info is None or info["create_time"] != entry.create_time:
            # O processo morreu (ou o pid foi reciclado): nao ha a quem
            # devolver, e registrar isso como falha acusaria o alivio de um
            # crime que nao aconteceu.
            entry.reverted = True
            self._save_journal()
            return ReliefResult(ACTION_RESTORE, SKIP_GONE, pid=entry.pid, name=entry.name)
        reason = actuator.set_level(entry.pid, entry.from_raw)[0]
        entry.reverted = reason in (OK, NOTHING, SKIP_GONE)
        self._save_journal()
        return ReliefResult(
            ACTION_RESTORE,
            reason,
            pid=entry.pid,
            name=entry.name,
            from_level=actuator.level_name(entry.to_raw),
            to_level=actuator.level_name(entry.from_raw),
        )

    # -- o proprio daemon ---------------------------------------------

    def _track_self(self, suspect: bool, *, ref: str = "") -> ReliefResult:
        """Sob suspeita, o vigia nao pode ser a vitima (spec 4).

        O boost e do processo do daemon, vive enquanto ele vive, e nao conta
        no teto de intervencoes: contar contra si mesmo faria o degrau 1
        desligar justo na hora em que ele e necessario.
        """
        if suspect and self._self_entry is None:
            return self._boost_self(ref=ref)
        if not suspect and self._self_entry is not None:
            return self._restore_self()
        return ReliefResult(ACTION_BOOST_SELF, NOTHING, pid=self.self_pid)

    def _boost_self(self, *, ref: str = "") -> ReliefResult:
        actuator = self.actuator
        high = actuator.priority_class("HIGH_PRIORITY_CLASS")
        info = actuator.inspect(self.self_pid)
        if high is None or info is None:
            # POSIX sem HIGH_PRIORITY_CLASS: nao ha boost, e nao ha fracasso.
            return ReliefResult(ACTION_BOOST_SELF, NOTHING, pid=self.self_pid)
        reason, before, after = actuator.set_level(self.self_pid, high)
        if reason != OK:
            return ReliefResult(ACTION_BOOST_SELF, reason, pid=self.self_pid)
        self._self_entry = JournalEntry(
            pid=self.self_pid,
            name="sentinel",
            create_time=info["create_time"],
            at=_iso(self._now()),
            action=ACTION_BOOST_SELF,
            from_raw=before,
            to_raw=after,
        )
        # Deliberadamente fora do journal: o boost do daemon morre com ele,
        # entao nao ha o que devolver pra quem vem depois -- e um registro
        # eterno de "devolver pro pid X" apontando pro proprio daemon seria
        # lixo esperando o dia em que um pid estranho herdar esse numero.
        return ReliefResult(
            ACTION_BOOST_SELF, OK, pid=self.self_pid, name="sentinel",
            from_level=actuator.level_name(before),
            to_level=actuator.level_name(after), ref=ref,
        )

    def _restore_self(self) -> ReliefResult:
        entry, self._self_entry = self._self_entry, None
        if entry is None:
            return ReliefResult(ACTION_RESTORE_SELF, NOTHING, pid=self.self_pid)
        result = self._restore(entry)
        result.action = ACTION_RESTORE_SELF
        return result

    # -- vida do daemon ------------------------------------------------

    def recover(self) -> list:
        """Devolve o que um daemon morto deixou aplicado.

        Roda uma vez, no inicio do loop. Sem isso, um terminate() no meio de
        um episodio deixa o app do usuario rebaixado ate ele fechar, e nada em
        lugar nenhum diz por que.
        """
        out: list = []
        for entry in self.pending():
            result = self._restore(entry)
            if result.reason != SKIP_GONE:
                result.ref = "recuperacao"
                out.append(result)
        return out

    def shut_down(self) -> list:
        """Ao encerrar, nada fica para tras."""
        out: list = []
        for entry in self.pending():
            out.append(self._restore(entry))
        if self._self_entry is not None:
            out.append(self._restore_self())
        self._decided = 0
        return out

    # -- o caminho digitado -------------------------------------------

    def apply_manual(self, pid: int) -> ReliefResult:
        """Rebaixar porque alguem pediu, nao porque o indice decidiu.

        Sem guardas de autonomia -- o teto de intervencoes e o cooldown
        existem pra conter uma decisao que ninguem revisa, e aqui a revisao
        foi voce mesmo digitar o comando. As recusas de seguranca continuam:
        servico do Windows e o proprio Sentinel nao sao alvo nem por pedido
        explicito, porque o pedido nao vem com o motivo que tornaria aquilo
        uma boa ideia.

        Nao entra no journal: quem manda no journal e o daemon vivo, e dois
        processos escrevendo o mesmo arquivo fazem um dos dois perder
        historico. A prova do que foi feito fica no `events.jsonl`, e o
        `--restore` le de la.
        """
        return self._hand_apply(pid, ACTION_LOWER)

    def restore_manual(self, pid: int, raw) -> ReliefResult:
        if raw is None:
            # Devolver exige saber o que estava la antes. Chutar 'normal'
            # subiria a prioridade de algo que ja estava rebaixado antes de o
            # Sentinel existir -- e `set_level(pid, None)` e justamente o
            # rebaixamento, nao a reversao.
            return ReliefResult(
                ACTION_RESTORE, SKIP_NO_PREVIOUS, pid=pid, ref="manual"
            )
        return self._hand_apply(pid, ACTION_RESTORE, raw=raw)

    def _hand_apply(self, pid: int, action: str, raw=None) -> ReliefResult:
        actuator = self.actuator
        if not actuator.available:
            return ReliefResult(action, SKIP_NO_ACTUATOR, pid=pid, ref="manual")
        info = actuator.inspect(pid)
        if info is None:
            return ReliefResult(action, SKIP_GONE, pid=pid, ref="manual")
        name = str(info["name"])
        if is_protected(name) or is_self(name):
            return ReliefResult(
                action, SKIP_PROTECTED, pid=pid, name=name,
                from_level=actuator.level_name(info["raw"]), ref="manual",
            )
        if raw is None and action == ACTION_LOWER:
            reason, before, after = actuator.lower(pid)
        else:
            reason, before, after = actuator.set_level(pid, raw)
        return ReliefResult(
            action,
            reason,
            pid=pid,
            name=name,
            from_level=actuator.level_name(before),
            to_level=actuator.level_name(after),
            from_raw=before,
            to_raw=after,
            ref="manual",
        )
