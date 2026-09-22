from __future__ import annotations

import datetime
import json
import os
import tempfile
import uuid
from pathlib import Path

from sentinel import settings
from sentinel.detector import Finding
from sentinel.sensor import Sample


# Status de uma anomalia ao longo do ciclo de vida.
STATUS_OPEN = "open"
STATUS_ADDRESSING = "addressing"
STATUS_RESOLVED = "resolved"
STATUS_DISMISSED = "dismissed"

# Desfechos de uma resolucao (linha anexada pelo tutor).
OUTCOME_FIXED = "fixed"
OUTCOME_NOT_FIXED = "not_fixed"
OUTCOME_DISMISSED = "dismissed"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def new_id(prefix: str, dt: datetime.datetime) -> str:
    """Id legivel e ordenavel por tempo: prefixo-AAAAMMDD-HHMMSS-<hex4>.

    Ordenavel importa porque `events --limit` mostra os mais recentes; o
    sufixo aleatorio evita colicao quando duas anomalias caem no mesmo
    segundo.
    """
    stamp = dt.astimezone(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:4]}"


class EventStore:
    """Log JSONL append-only em `.sentinel/events.jsonl`.

    Cada linha e um objeto JSON independente (facil de grep, nao-corrupto
    se uma escrita cair no meio). Duas variantes: `kind: anomaly` e
    `kind: resolution` (esta ultima aponta `ref` pra uma anomalia).

    Dedupe: `record_finding` nao re-emite uma anomalia cujo `fingerprint`
    ja esta `open` dentro de DEDUPE_WINDOW_S — incrementa `occurrences` e
    atualiza `value`/`ts`. Isso exige reescrever a linha antiga, entao o
    append-only vira "rewrite do arquivo" nesse caminho especifico; o
    resto e so append. Arquivo local pequeno, o custo e irrelevante.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    # -- leitura -------------------------------------------------------

    def all(self) -> list[dict]:
        if not self.path.is_file():
            return []

        events: list[dict] = []
        # `utf-8-sig`: o historico e editavel a Mao (tirar uma linha, limpar o
        # arquivo), e Notepad/`Set-Content` poem BOM no comeco. Sem isto a
        # primeira linha vira JSON ilegitimo e a anomalia mais antiga sumiria.
        with self.path.open("r", encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    # Linha corrompida (ex.: escrita interrompida): ignora
                    # so ela, nao derruba a leitura do resto do historico.
                    continue
                if isinstance(obj, dict):
                    events.append(obj)
        return events

    def find(self, event_id: str) -> dict | None:
        for event in self.all():
            if event.get("id") == event_id:
                return event
        return None

    def anomalies(self) -> list[dict]:
        return [e for e in self.all() if e.get("kind") == "anomaly"]

    def open_anomalies(self) -> list[dict]:
        return [
            e
            for e in self.anomalies()
            if e.get("status", STATUS_OPEN) == STATUS_OPEN
        ]

    def latest_open(self) -> dict | None:
        opens = self.open_anomalies()
        if not opens:
            return None
        return max(opens, key=lambda e: e.get("ts", ""))

    def resolutions_for(self, event_id: str) -> list[dict]:
        return [
            e
            for e in self.all()
            if e.get("kind") == "resolution" and e.get("ref") == event_id
        ]

    def interventions(self) -> list[dict]:
        return [e for e in self.all() if e.get("kind") == "intervention"]

    # -- escrita -------------------------------------------------------

    def _append_line(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n" explicito: sem isso o Windows traduce \n pra \r\n e
        # um parser rigido de JSONL pode estranhar. Compativel com 3.8+.
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_all(self, records: list[dict]) -> None:
        """Reescrita atomica (tmp + replace) pro caminho de dedupe/update,
        onde nao da pra so acrescentar ao fim."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".events.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                for rec in records:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def record_finding(self, finding: Finding, sample: Sample) -> dict:
        """Persiste um `Finding`, colapsando duplicatas por fingerprint.

        Retorna o registro de anomalia resultante (novo OU o existente
        atualizado) — quem chama (daemon) so quer saber o id/status.
        """
        now = sample.ts if sample.ts else _utcnow()
        events = self.all()

        prior = self._recent_matching_open(events, finding.fingerprint, now)
        if prior is not None:
            prior["value"] = round(finding.value, 2)
            prior["ts_last"] = _iso(now)
            prior["occurrences"] = int(prior.get("occurrences", 1)) + 1
            self._write_all(events)
            return prior

        record = self.build_anomaly_record(finding, now)
        events.append(record)
        self._write_all(events)
        return record

    def record_incident(self, incident, now: datetime.datetime | None = None) -> dict:
        """Persiste um `Incident` (arvore orfa, falha de app) no mesmo
        historico das finding de limiar.

        Mesma regra de dedupe por fingerprint, porque o incidente é o evento
        repetido: um app que cai quatro vezes em dois minutos é UMA anomalia
        com `occurrences: 4` — a contagem é justamente o que distingue
        "hoje quebrou" de "está em loop de queda", e duas linhas separadas
        jogariam esse sinal fora.
        """
        moment = now or _utcnow()
        events = self.all()

        prior = self._recent_matching_open(events, incident.fingerprint, moment)
        if prior is not None:
            prior["detail"] = incident.detail
            prior["label"] = incident.label
            prior["ts_last"] = _iso(moment)
            prior["occurrences"] = int(prior.get("occurrences", 1)) + 1
            self._write_all(events)
            return prior

        record = self.build_incident_record(incident, moment)
        events.append(record)
        self._write_all(events)
        return record

    def record_intervention(self, result, now: datetime.datetime | None = None) -> dict:
        """Persiste uma decisao do alivio (`relief.ReliefResult`) como linha
        `kind: intervention`.

        Sem dedupe, de proposito: a segunda intervencao no mesmo app nao e a
        primeira repetida — e um fato novo, com consequencia nova. E o
        historico que da pra confiar no degrau 3 e exatamente a lista sem
        buracos do que foi feito. O que limita a frequencia sao as guardas do
        `relief`, nao o armazenamento.
        """
        moment = now or _utcnow()
        record = self.build_intervention_record(result, moment)
        self._append_line(record)
        return record

    def build_anomaly_record(self, finding: Finding, now: datetime.datetime) -> dict:
        return {
            "schema": settings.EVENT_SCHEMA_VERSION,
            "id": new_id("evt", now),
            "ts": _iso(now),
            "kind": "anomaly",
            "metric": finding.metric,
            "severity": finding.severity,
            "value": round(finding.value, 2),
            "threshold": round(finding.threshold, 2),
            "window": {
                "samples": finding.samples,
                "span_s": round(finding.span_s, 1),
            },
            "top_processes": [p.to_dict() for p in finding.top_processes],
            "status": STATUS_OPEN,
            "fingerprint": finding.fingerprint,
            "occurrences": 1,
        }

    def build_incident_record(self, incident, now: datetime.datetime) -> dict:
        """Formato schema 2 de anomalia sem limiar.

        `value`/`threshold`/`top_processes` não existem aqui: o que faz
        sentido num `orphan_tree` é o mapa da árvore, e num `app_failure` é
        o módulo culpado e o código de exceção. Em vez de encher a linha de
        zeros pra caber no molde antigo, o registro carrega `label` (uma
        linha, pra log/CLI) e `detail` (o que a UI e o tutorial citam).
        """
        return {
            "schema": settings.EVENT_SCHEMA_VERSION,
            "id": new_id("evt", now),
            "ts": _iso(now),
            "kind": "anomaly",
            "metric": incident.metric,
            "severity": incident.severity,
            "label": incident.label,
            "detail": incident.detail,
            "status": STATUS_OPEN,
            "fingerprint": incident.fingerprint,
            "occurrences": 1,
        }

    def build_intervention_record(self, result, now: datetime.datetime) -> dict:
        """A linha de uma intervencao do alivio.

        `kind` diferente de `anomaly` de proposito: uma intervencao nao e um
        problema, e a resposta a um, e misturar as duas coisas no mesmo filtro
        faria `events --metric relief_applied` contar como anomalia o que o
        proprio Sentinel fez. `ref` aponta pra anomalia que abriu o episodio,
        quando existia uma.
        """
        return {
            "schema": settings.EVENT_SCHEMA_VERSION,
            "id": new_id("int", now),
            "ts": _iso(now),
            "kind": "intervention",
            "metric": result.action,
            "action": result.action,
            "reason": result.reason,
            "shadow": result.shadow,
            "applied": result.applied,
            "ref": result.ref,
            "label": result.label(),
            "detail": result.to_detail(),
        }

    def _recent_matching_open(
        self, events: list[dict], fingerprint: str, now: datetime.datetime
    ) -> dict | None:
        cutoff = now - datetime.timedelta(seconds=settings.DEDUPE_WINDOW_S)
        match: dict | None = None
        for event in events:
            if event.get("kind") != "anomaly":
                continue
            if event.get("fingerprint") != fingerprint:
                continue
            if event.get("status", STATUS_OPEN) not in (
                STATUS_OPEN,
                STATUS_ADDRESSING,
            ):
                continue
            ts = _parse_iso(event.get("ts_last") or event.get("ts", ""))
            if ts is not None and ts >= cutoff:
                match = event
        return match

    def set_status(self, event_id: str, status: str) -> bool:
        events = self.all()
        changed = False
        for event in events:
            if event.get("id") == event_id and event.get("kind") == "anomaly":
                event["status"] = status
                event["ts_updated"] = _iso(_utcnow())
                changed = True
                break
        if changed:
            self._write_all(events)
        return changed

    def append_resolution(
        self,
        *,
        ref: str,
        outcome: str,
        option_index: int | None,
        source: str,
        note: str = "",
        set_status_to: str = STATUS_RESOLVED,
    ) -> dict:
        """Anexa uma linha `resolution` e move a anomalia `ref` pro status
        final dado (resolved por padrao; dismissed quando o usuario pula).

        As duas coisas (linha nova + status da anomalia) vao juntas numa
        reescrita pra ficarem consistentes entre si.
        """
        now = _utcnow()
        record = {
            "schema": settings.EVENT_SCHEMA_VERSION,
            "id": new_id("res", now),
            "ts": _iso(now),
            "kind": "resolution",
            "ref": ref,
            "outcome": outcome,
            "option_index": option_index,
            "source": source,
            "note": note,
        }

        events = self.all()
        for event in events:
            if event.get("id") == ref and event.get("kind") == "anomaly":
                event["status"] = set_status_to
                event["ts_updated"] = _iso(now)
                break
        events.append(record)
        self._write_all(events)
        return record

    def prune(self, *, older_than_days: int) -> int:
        """Descarta linhas (anomalia e resolucao) mais antigas que N dias.
        Retorna quantas foram removidas. Resolucoes sao comparadas pelo
        proprio ts (nao pelo da anomalia referenciada)."""
        events = self.all()
        cutoff = _utcnow() - datetime.timedelta(days=older_than_days)
        kept: list[dict] = []
        dropped = 0
        for event in events:
            ts = _parse_iso(event.get("ts", ""))
            if ts is not None and ts < cutoff:
                dropped += 1
            else:
                kept.append(event)
        if dropped:
            self._write_all(kept)
        return dropped
