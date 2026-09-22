from __future__ import annotations

import datetime
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sentinel import kb, settings


# ---------------------------------------------------------------------------
# O que e este modulo
# ---------------------------------------------------------------------------
# `.sentinel/kb.db` e a memoria de longo prazo do Sentinel: o que ele sabe
# sobre esta maquina e, sobretudo, o que JA RESOLVEU antes contra esta
# anomalia. `kb.py` e o catalogo curado (vem com o programa); a base e o
# que o uso escreve por cima.
#
# A ordem de busca e o pedido do usuario, e ela e deliberada:
#
#   1. fingerprint exato   — "desta anomalia, com este processo, ja sei"
#   2. metrica + causa     — "muda o app, mas o culpado e o mesmo modulo"
#   3. metrica generica    — o catalogo curado de `kb.py`
#   4. modelo local        — so quando a base nao sabe; e o resultado VIRA
#                            entrada na base (aprender, nao repetir)
#
# Meta mensuravel: com uso, a camada 4 quase nunca roda. Isso e tambem o que
# mantem o Sentinel util sem rede e sem IA paga: a resposta boa fica local.
#
# Tudo aqui e `sqlite3` da stdlib. Nenhum dado sai da maquina; a unica
# escrita externa do Sentinel continua sendo o modelo local, sob chamada do
# usuario.

# Camadas, na ordem em que `lookup` as tenta.
LAYER_FINGERPRINT = 1
LAYER_CAUSE = 2
LAYER_METRIC = 3
LAYER_MODEL = 4

# Nome da camada em texto, pra `--explain-source` e pro campo `source` da
# resolucao. A camada 4 e o motor (hoje `claude`, depois Ollama); as tres
# primeiras sao a base local.
LAYER_NAME = {
    LAYER_FINGERPRINT: "kb:fingerprint",
    LAYER_CAUSE: "kb:causa",
    LAYER_METRIC: "kb:metrica",
    LAYER_MODEL: "modelo",
}

# Origem declarada de cada linha de `option`: o curado que ships com o
# programa vs. o que a base aprendeu de uma resposta de modelo.
ORIGIN_CURATED = "curado"
ORIGIN_LEARNED = "aprendido"

_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(text: str, *, max_len: int = 28) -> str:
    base = _NON_SLUG.sub("-", (text or "").lower()).strip("-")
    return base[:max_len].rstrip("-") or "opcao"


def _option_key(metric: str, title: str) -> str:
    """Id estavel pra uma opcao.

    O `sha1` curto entra como sufixo de seguranca: duas opcoes com títulos
    que reduzem ao mesmo slug (comum em PT-BR, onde acento e pontuacao
    somem) nao podem colidir e apagar uma a outra na base.
    """
    digest = hashlib.sha1((title or "").encode("utf-8")).hexdigest()[:8]
    return f"{metric}:{_slug(title)}-{digest}"


def cause_of(event: dict) -> str:
    """A assinatura de causa: o que produz o sintoma, nao o sintoma.

    Uma anomalia de limiar aponta pro processo mais caro; um incidente ja
    veio com o culpado nomeado pelo proprio Windows. A causa do `app_failure`
    e o modulo que falhou (mesma DLL derruba apps diferentes), e a do
    `orphan_tree` e o pai que morreu. Normalizado em minusculas porque nome
    de processo chega com caixa variavel.
    """
    metric = event.get("metric", "")
    detail = event.get("detail") or {}

    if metric == kb.METRIC_APP_FAILURE:
        module = str(detail.get("module") or "").strip()
        if module:
            return module.lower()
        code = str(detail.get("exception_code") or "").strip()
        app = str(detail.get("app") or "").strip()
        return (code and f"{app.lower()}:{code.lower()}") or app.lower()

    if metric == kb.METRIC_ORPHAN_TREE:
        return str(detail.get("parent", {}).get("name") or "").strip().lower()

    top = event.get("top_processes") or []
    if top:
        return str(top[0].get("name") or "").strip().lower()
    return ""


def _fingerprint(event: dict) -> str:
    return str(event.get("fingerprint") or "").strip()


def _type_key_fingerprint(fp: str) -> str:
    return f"fp:{fp}"


def _type_key_cause(metric: str, cause: str) -> str:
    return f"causa:{metric}+{cause}"


def _type_key_metric(metric: str) -> str:
    return f"metrica:{metric}"


@dataclass(frozen=True)
class Candidate:
    """Um par (tipo de anomalia, opcao) lido da base, antes do ranking."""

    type_key: str
    layer: int
    option: dict


class KbStore:
    """Acesso a `.sentinel/kb.db`.

    Injetavel: `tutor` recebe a store (ou None). Sem store — ex.: psutil
    ausente e o `.sentinel/` ainda nem criado — o ciclo segue usando `kb.py`
    em memoria, exatamente como hoje. A base acelera e memoriza, nunca e
    obrigatoria pra responder.
    """

    def __init__(self, conn: sqlite3.Connection, *, path: Path | None = None):
        self.conn = conn
        self.path = path

    # -- ciclo de vida ----------------------------------------------------
    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "KbStore":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    # -- leitura ----------------------------------------------------------
    def lookup(self, event: dict) -> tuple[list[dict], int]:
        """Devolve (opcoes, camada) na primeira camada que ainda tem o que
        dizer.

        "Ainda tem" e a metade importante: uma camada cujas opcoes foram
        TODAS recusadas contra este fingerprint esta esgotada, e insistir
        nela seria o Sentinel dando o mesmo conselho que ja nao funcionou.
        Ahi ele desce uma camada, e no fim pergunta ao modelo — cuja
        resposta volta pra ca (`learn`). E assim que a meta do design se
        cumpre sozinha: com uso, a camada 4 quase nao roda.

        Camada 4 nao esta aqui: ela e o que roda quando isto devolve
        `([], 0)`. As opcoes saem ordenadas por merecimento — o que resolveu
        antes nesta mesma anomalia vai pro topo.
        """
        for candidate in self.candidates(event):
            if self._exhausted(event, candidate):
                continue
            ranked = self._ranked(event, candidate)
            if ranked:
                # `bind` aqui, e nao no seed: a base guarda o texto curado
                # com os tokens, e cada leitura preenche com o numero deste
                # evento. Salvar a frase ja resolvida seria a mesma
                # resposta servir pra maquinas diferentes.
                return [kb.bind(option, event) for option in ranked], candidate.layer
        return [], 0

    def _exhausted(self, event: dict, candidate: Candidate) -> bool:
        """Toda opcao desta camada ja foi tentada e nenhuma resolveu?

        So conta recusa DESTE fingerprint: o fato de o conselho nao ter
        funcionado contra o chrome nao o desqualifica contra o blender.
        """
        fp = _fingerprint(event)
        if not fp:
            return False
        counts = self._outcome_counts(
            [option["key"] for option in candidate.option], fp
        )
        if not counts:
            return False
        for tally in counts.values():
            if tally["fixed"]:
                return False
            if not (tally["fixed"] or tally["not_fixed"]):
                return False  # ainda ha opcao que ninguem tentou
        return True

    def candidates(self, event: dict) -> list[Candidate]:
        """Os pares (tipo, opcoes) que a base conhece pra este evento, na
        ordem de especificidade."""
        metric = event.get("metric", "")
        fp = _fingerprint(event)
        cause = cause_of(event)
        out: list[Candidate] = []
        for type_key, layer in self._type_keys(metric, fp, cause):
            rows = self._options_of(type_key)
            if rows:
                out.append(Candidate(type_key=type_key, layer=layer, option=rows))
        return out

    def _type_keys(self, metric: str, fp: str, cause: str) -> list[tuple[str, int]]:
        keys = []
        if fp:
            keys.append((_type_key_fingerprint(fp), LAYER_FINGERPRINT))
        if metric and cause:
            keys.append((_type_key_cause(metric, cause), LAYER_CAUSE))
        if metric:
            keys.append((_type_key_metric(metric), LAYER_METRIC))
        return keys

    def _options_of(self, type_key: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT o.key, o.title, o.why, o.steps, o.proof, o.risk, o.reversible,"
            " o.action, o.origin, t.ordinal"
            " FROM option AS o"
            " JOIN type_option AS t ON t.option_key = o.key"
            " WHERE t.type_key = ?"
            " ORDER BY t.ordinal",
            (type_key,),
        ).fetchall()
        return [self._to_option(row) for row in rows]

    @staticmethod
    def _to_option(row) -> dict:
        option = {
            "key": row[0],
            "title": row[1],
            "why": row[2],
            "steps": json.loads(row[3] or "[]"),
            "proof": row[4],
            "risk": row[5],
            "reversible": bool(row[6]),
        }
        action = row[7]
        if action:
            option["action"] = json.loads(action)
        option["origin"] = row[8]
        return option

    def _ranked(self, event: dict, candidate: Candidate) -> list[dict]:
        """Ordena por historico DESTE fingerprint, mantendo a ordem curada
        como empate.

        Contar so dentro do fingerprint e o ponto: uma vitoria contra o
        chrome nao deve embaralhar a resposta sobre o blender, que nunca foi
        tentado. Sem contagem, a ordem e a do catalogo — que e a ordem em
        que a opcao foi escrita, da mais provavel pra menos.
        """
        fp = _fingerprint(event)
        counts = self._outcome_counts([o["key"] for o in candidate.option], fp)
        ranked: list[dict] = []
        for index, option in enumerate(candidate.option):
            tally = counts.get(option["key"], {"fixed": 0, "not_fixed": 0})
            item = dict(option)
            item["fixed_for_this_fingerprint"] = tally["fixed"]
            item["not_fixed_for_this_fingerprint"] = tally["not_fixed"]
            ranked.append((index, tally["fixed"], tally["not_fixed"], item))
        ranked.sort(key=lambda row: (-row[1], row[2], row[0]))
        return [row[3] for row in ranked]

    def _outcome_counts(self, option_keys: list[str], fp: str) -> dict:
        if not option_keys or not fp:
            return {}
        marks = ",".join("?" for _ in option_keys)
        rows = self.conn.execute(
            f"SELECT option_key, outcome, COUNT(*) FROM outcome"
            f" WHERE fingerprint = ? AND option_key IN ({marks})"
            " GROUP BY option_key, outcome",
            [fp, *option_keys],
        ).fetchall()
        counts: dict[str, dict[str, int]] = {
            key: {"fixed": 0, "not_fixed": 0} for key in option_keys
        }
        for key, outcome, total in rows:
            if outcome == "fixed":
                counts[key]["fixed"] = total
            elif outcome in ("not_fixed", "dismissed"):
                counts[key]["not_fixed"] = total
        return counts

    def explain(self, event: dict) -> dict:
        """O relatorio do `fix --explain-source`: de onde veio a sugestao e
        o que pesou no ranking."""
        options, layer = self.lookup(event)
        info = {
            "camada": self._layer_note(event, layer),
            "layer": layer,
            "metrica": event.get("metric", ""),
            "causa": cause_of(event),
            "fingerprint": _fingerprint(event),
            "respostas": len(options),
            "ranked_by": {
                option["key"]: {
                    "fixed": option.get("fixed_for_this_fingerprint", 0),
                    "not_fixed": option.get("not_fixed_for_this_fingerprint", 0),
                    "origem": option.get("origin", ""),
                }
                for option in options
            },
        }
        return info

    def _layer_note(self, event: dict, layer: int) -> str:
        """Nomeia a camada, e diz POR QUE ela foi a escolhida quando a base
        tinha mais de uma."""
        if layer:
            return LAYER_NAME[layer]
        if self.candidates(event):
            return (
                "nenhuma (a base sabia, mas voce ja recusou tudo que ela "
                "sabia contra este fingerprint)"
            )
        return "nenhuma (a base ainda nao conhece esta anomalia)"

    def count_options(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM option").fetchone()[0])

    def all_options(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT key, title, why, steps, proof, risk, reversible, origin"
            " FROM option ORDER BY key"
        ).fetchall()
        out = []
        for row in rows:
            item = self._to_option([row[0], row[1], row[2], row[3], row[4], row[5],
                                    row[6], None, row[7]])
            out.append(item)
        return out

    # -- escrita ----------------------------------------------------------
    def learn(self, event: dict, options: list[dict], *, source: str = "") -> int:
        """Registra na base a resposta que a camada 4 acabou de dar.

        Escreve nos dois niveis que fazem sentido depois: o fingerprint
        exato (se repetir, a base responde sem modelo) e a causa (se for o
        mesmo modulo derrubando outro app, o aprendizado aproveita). Idempotente
        por design: a mesma opcao regravada nao duplica linha.
        """
        metric = event.get("metric", "")
        if not metric or not options:
            return 0
        fp = _fingerprint(event)
        cause = cause_of(event)
        now = _iso_now()
        written = 0
        keys: list[tuple[str, int]] = []
        if fp:
            keys.append((_type_key_fingerprint(fp), LAYER_FINGERPRINT))
        if cause:
            keys.append((_type_key_cause(metric, cause), LAYER_CAUSE))
        for type_key, layer in keys:
            self.conn.execute(
                "INSERT OR IGNORE INTO anomaly_type"
                " (key, layer, metric, cause, fingerprint, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (type_key, layer, metric, cause, fp if layer == LAYER_FINGERPRINT else "",
                 now),
            )
        for index, option in enumerate(options[: settings.MAX_FIX_OPTIONS]):
            key = _option_key(metric, str(option.get("title", "")))
            self._upsert_option(key, option, now, ORIGIN_LEARNED)
            for type_key, _layer in keys:
                self.conn.execute(
                    "INSERT OR REPLACE INTO type_option (type_key, option_key, ordinal)"
                    " VALUES (?,?,?)",
                    (type_key, key, index),
                )
            written += 1
        self.conn.commit()
        return written

    def _upsert_option(self, key: str, option: dict, now: str, origin: str) -> None:
        action = option.get("action")
        self.conn.execute(
            "INSERT OR IGNORE INTO option"
            " (key, title, why, steps, proof, risk, reversible, action, origin,"
            " created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                key,
                str(option.get("title", "")),
                str(option.get("why", "")),
                json.dumps(_steps_of(option), ensure_ascii=False),
                str(option.get("proof", "")),
                str(option.get("risk", "")),
                1 if option.get("reversible", True) else 0,
                json.dumps(action, ensure_ascii=False) if isinstance(action, dict) else "",
                origin,
                now,
            ),
        )

    def record(
        self,
        event: dict,
        option: dict,
        *,
        outcome: str,
        source: str = "",
    ) -> bool:
        """Anexa um desfecho a uma opcao. Sem `key` nao ha o que ligar."""
        key = option.get("key")
        if not key:
            return False
        self.conn.execute(
            "INSERT INTO outcome (option_key, fingerprint, outcome, source, ts)"
            " VALUES (?,?,?,?,?)",
            (key, _fingerprint(event), outcome, source, _iso_now()),
        )
        self.conn.commit()
        return True

    def touch_anomaly(self, event: dict) -> None:
        """Marca que este fingerprint ja foi visto, com a contagem acumulada.

        A tabela `anomaly_type` e tambien o inventario do que acontece nesta
        maquina: `sentinel kb --stats` le daqui pra dizer onde o Sentinel
        ainda nao tem resposta.
        """
        fp = _fingerprint(event)
        if not fp:
            return
        now = _iso_now()
        row = self.conn.execute(
            "SELECT occurrences FROM anomaly_type WHERE key = ?",
            (_type_key_fingerprint(fp),),
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO anomaly_type (key, layer, metric, cause, fingerprint,"
                " created_at, last_seen, occurrences) VALUES (?,?,?,?,?,?,?,1)",
                (_type_key_fingerprint(fp), LAYER_FINGERPRINT, event.get("metric", ""),
                 cause_of(event), fp, now, now),
            )
        else:
            self.conn.execute(
                "UPDATE anomaly_type SET occurrences = occurrences + 1, last_seen = ?"
                " WHERE key = ?",
                (now, _type_key_fingerprint(fp)),
            )
        self.conn.commit()

    def stats(self) -> dict:
        totals = {
            "tipos": int(self.conn.execute(
                "SELECT COUNT(*) FROM anomaly_type").fetchone()[0]),
            "opcoes": self.count_options(),
            "desfechos": int(self.conn.execute(
                "SELECT COUNT(*) FROM outcome").fetchone()[0]),
            "aprendidas": int(self.conn.execute(
                "SELECT COUNT(*) FROM option WHERE origin = ?",
                (ORIGIN_LEARNED,)).fetchone()[0]),
        }
        rows = self.conn.execute(
            "SELECT outcome, COUNT(*) FROM outcome GROUP BY outcome").fetchall()
        totals["por_desfecho"] = {name: total for name, total in rows}
        return totals


def _steps_of(option: dict) -> list[str]:
    steps = option.get("steps")
    if steps is None:
        steps = option.get("do")
    if not isinstance(steps, list):
        return []
    return [str(step) for step in steps if str(step).strip()]


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS anomaly_type (
        key         TEXT PRIMARY KEY,
        layer       INTEGER NOT NULL,
        metric      TEXT NOT NULL DEFAULT '',
        cause       TEXT NOT NULL DEFAULT '',
        fingerprint TEXT NOT NULL DEFAULT '',
        created_at  TEXT NOT NULL,
        last_seen   TEXT NOT NULL DEFAULT '',
        occurrences INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS option (
        key        TEXT PRIMARY KEY,
        title      TEXT NOT NULL,
        why        TEXT NOT NULL DEFAULT '',
        steps      TEXT NOT NULL DEFAULT '[]',
        proof      TEXT NOT NULL DEFAULT '',
        risk       TEXT NOT NULL DEFAULT '',
        reversible INTEGER NOT NULL DEFAULT 1,
        action     TEXT NOT NULL DEFAULT '',
        origin     TEXT NOT NULL DEFAULT 'curado',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS type_option (
        type_key   TEXT NOT NULL,
        option_key TEXT NOT NULL,
        ordinal    INTEGER NOT NULL,
        PRIMARY KEY (type_key, option_key)
    );
    CREATE TABLE IF NOT EXISTS outcome (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        option_key  TEXT NOT NULL,
        fingerprint TEXT NOT NULL DEFAULT '',
        outcome     TEXT NOT NULL,
        source      TEXT NOT NULL DEFAULT '',
        ts          TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_outcome_fp ON outcome (fingerprint, option_key);
    """,
)


def seed(store: KbStore) -> int:
    """Copia o catalogo curado (`kb.py`) pra camada 3 da base.

    `INSERT OR IGNORE`: editar o texto curado nao reescreve por cima do que
    o usuario ja avaliou — a linha velha continua com seus desfechos. Sem
    isso, cada update do Sentinel jogaria fora o ranking aprendido.
    """
    now = _iso_now()
    written = 0
    for metric in kb.known_metrics():
        type_key = _type_key_metric(metric)
        store.conn.execute(
            "INSERT OR IGNORE INTO anomaly_type (key, layer, metric, cause,"
            " fingerprint, created_at) VALUES (?,?,?,?,?,?)",
            (type_key, LAYER_METRIC, metric, "", "", now),
        )
        for index, option in enumerate(kb.options_for(metric)):
            key = _option_key(metric, str(option.get("title", "")))
            store._upsert_option(key, option, now, ORIGIN_CURATED)
            store.conn.execute(
                "INSERT OR IGNORE INTO type_option (type_key, option_key, ordinal)"
                " VALUES (?,?,?)",
                (type_key, key, index),
            )
            written += 1
    store.conn.commit()
    return written


def open_store(path: Path | str, *, seeded: bool = True) -> KbStore:
    """Abre (criando se preciso) a `.sentinel/kb.db` de uma raiz."""
    target = Path(path)
    if str(target) not in (":memory:", ""):
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.execute(f"PRAGMA user_version = {settings.KB_SCHEMA_VERSION}")
    for script in _SCHEMA:
        conn.executescript(script)
    conn.commit()
    store = KbStore(conn, path=target if str(target) != ":memory:" else None)
    if seeded:
        seed(store)
    return store
