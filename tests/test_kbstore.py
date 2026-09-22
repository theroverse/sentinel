from __future__ import annotations

import re

from sentinel import kb, kbstore, settings
from sentinel.detector import METRIC_CPU, METRIC_RAM
from sentinel.events import OUTCOME_FIXED, OUTCOME_NOT_FIXED
from sentinel.incidents import METRIC_APP_FAILURE, METRIC_ORPHAN_TREE


_TOKEN_RE = re.compile(r"\{[a-z_]+\}")


# ---------------------------------------------------------------------------
# Eventos de teste: um de limiar (tem value/top_processes) e um de incidente
# (schema 2, so label/detail). As camadas da base precisam funcionar nos
# dois, porque a assinatura de causa vem de lugares diferentes.
# ---------------------------------------------------------------------------


def _finding(metric=METRIC_RAM, severity="critical", name="chrome", pid=4321,
             rss=3276.0):
    return {
        "id": f"evt-{metric}-{severity}-{name}",
        "schema": 2,
        "kind": "anomaly",
        "metric": metric,
        "severity": severity,
        "value": 96.0,
        "threshold": 93.0,
        "window": {"samples": 5, "span_s": 10.0},
        "top_processes": [{"pid": pid, "name": name, "cpu": 1.0, "rss_mb": rss}],
        "status": "open",
        "fingerprint": f"{metric}:{severity}:{name}",
        "occurrences": 1,
    }


def _crash(app="editor.exe", module="render.dll", name="editor.exe"):
    return {
        "id": "evt-crash",
        "schema": 2,
        "kind": "anomaly",
        "metric": METRIC_APP_FAILURE,
        "severity": "warning",
        "label": f"{app} parou de funcionar (excecao 0xc0000005 em {module})",
        "detail": {
            "kind": "crash",
            "app": app,
            "module": module,
            "exception_code": "0xc0000005",
            "pid": 4242,
        },
        "status": "open",
        "fingerprint": f"app_failure:warning:{app}",
        "occurrences": 1,
    }


def _orphan(name="setup"):
    return {
        "id": "evt-orphan",
        "schema": 2,
        "kind": "anomaly",
        "metric": METRIC_ORPHAN_TREE,
        "severity": "warning",
        "label": f"{name} (pid 1) saiu deixando 2 processo(s) vivo(s) na arvore",
        "detail": {
            "parent": {"pid": 1, "name": name},
            "orphans": [{"pid": 2, "ppid": 1, "name": "installer", "depth": 1}],
            "orphan_count": 1,
            "tree": [{"pid": 2, "ppid": 1, "name": "installer", "depth": 1}],
            "tree_size": 2,
        },
        "status": "open",
        "fingerprint": f"orphan_tree:warning:{name}",
        "occurrences": 1,
    }


def _event_for(metric):
    """Um evento representativo de cada metrica: o minimo pra a camada
    generica responder e os tokens terem de onde vir."""
    if metric == METRIC_APP_FAILURE:
        return _crash()
    if metric == METRIC_ORPHAN_TREE:
        return _orphan()
    return _finding(metric=metric)


def _learned(title="Fecha as abas presas do chrome"):
    # Assim como a camada 4 devolve: opcao sem `key`, quem grava e a base.
    return [{"title": title, "steps": ["passo concreto", "outro passo"]}]


# ---------------------------------------------------------------------------
# Abertura / seed
# ---------------------------------------------------------------------------


def test_open_creates_the_file(tmp_path):
    db = kbstore.open_store(tmp_path / "kb.db")
    db.close()
    assert (tmp_path / "kb.db").is_file()


def test_metric_layer_answers_every_known_metric(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        for metric in kb.known_metrics():
            options, layer = db.lookup(_finding(metric=metric, name="app"))
            assert options, f"{metric} sem resposta na base"
            assert layer == kbstore.LAYER_METRIC


def test_seed_is_idempotent_across_reopen(tmp_path):
    path = tmp_path / "kb.db"
    with kbstore.open_store(path) as db:
        first = db.count_options()
    with kbstore.open_store(path) as db:
        again = db.count_options()
    assert first == again


def test_paths_expose_the_db(tmp_path):
    paths = settings.paths_for(tmp_path)
    assert paths.kb_db.name == "kb.db"
    assert paths.kb_db.parent == paths.output_dir


# ---------------------------------------------------------------------------
# Formato assertivo: o conteudo da base nao e adjetivo
# ---------------------------------------------------------------------------


def test_seeded_options_carry_the_assertive_fields(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        options, _layer = db.lookup(_finding())
    for opt in options:
        assert opt["why"].strip()
        assert opt["proof"].strip()
        assert opt["risk"].strip()
        assert isinstance(opt["reversible"], bool)
        assert opt["steps"]
        assert opt["key"]


def test_read_fills_the_tokens_with_this_events_numbers(tmp_path):
    """A base guarda o texto com tokens; a leitura devolve a frase com o
    numero medido. Guardar a frase ja resolvida serviria chrome pra quem
    estava com o blender aberto."""
    with kbstore.open_store(tmp_path / "kb.db") as db:
        chrome, _layer = db.lookup(_finding(name="chrome", pid=4321, rss=3276.0))
        blender, _layer = db.lookup(_finding(name="blender", pid=99, rss=812.0))
    assert "chrome" in chrome[0]["title"] and "4321" in " ".join(chrome[0]["steps"])
    assert "blender" in blender[0]["title"]
    assert "{" not in chrome[0]["title"] + " ".join(chrome[0]["steps"])


def test_no_metric_leaves_a_bare_token_behind(tmp_path):
    """Se o catalogo tem um token que o evento nao sabe preencher, o
    tutorial mostra `{module}` pro usuario — e isso e buraco, nao estilo."""
    with kbstore.open_store(tmp_path / "kb.db") as db:
        for metric in kb.known_metrics():
            options, layer = db.lookup(_event_for(metric))
            assert options and layer, f"{metric} sem resposta"
            for option in options:
                text = " ".join([option["title"], option["why"], option["proof"],
                                 option["risk"], *option["steps"]])
                left = _TOKEN_RE.findall(text)
                assert not left, f"{metric}/{option['key']} deixou {left}"


def test_banned_hedging_never_appears(tmp_path):
    proibidas = ("geralmente", "pode ser que", "recomendamos", "tente ")
    with kbstore.open_store(tmp_path / "kb.db") as db:
        rows = db.all_options()
    for row in rows:
        text = " ".join(
            [row["title"], row["why"], row["proof"], row["risk"], *row["steps"]]
        ).lower()
        for word in proibidas:
            assert word not in text, f"{row['key']} escribe '{word}'"


# ---------------------------------------------------------------------------
# Ordem de busca: fingerprint > causa > metrica
# ---------------------------------------------------------------------------


def test_fingerprint_layer_beats_the_generic_one(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        event = _finding()
        db.learn(event, _learned(), source=kbstore.LAYER_MODEL)
        options, layer = db.lookup(event)
    assert layer == kbstore.LAYER_FINGERPRINT
    assert options[0]["title"] == "Fecha as abas presas do chrome"


def test_cause_layer_serves_a_different_fingerprint(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        db.learn(_finding(severity="critical"), _learned(), source=kbstore.LAYER_MODEL)
        # Mesmo processo (chrome), outro fingerprint: critical -> warning.
        options, layer = db.lookup(_finding(severity="warning"))
    assert layer == kbstore.LAYER_CAUSE
    assert options[0]["title"] == "Fecha as abas presas do chrome"


def test_incident_cause_is_the_module_not_the_process(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        db.learn(_crash(), _learned("Atualiza o driver do modulo render.dll"),
                 source=kbstore.LAYER_MODEL)
        # Outro app, mesma culpa (mesmo modulo): a causa vale mais que o app.
        options, layer = db.lookup(_crash(app="jogo.exe"))
    assert layer == kbstore.LAYER_CAUSE
    assert options and layer != kbstore.LAYER_METRIC


def test_learn_is_idempotent(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        event = _finding()
        db.learn(event, _learned(), source=kbstore.LAYER_MODEL)
        after_first = db.count_options()
        db.learn(event, _learned(), source=kbstore.LAYER_MODEL)
        assert db.count_options() == after_first


def test_unknown_metric_still_has_no_answer(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        options, layer = db.lookup(_finding(metric="gpu"))
    assert options == []
    assert layer == 0, "0 = nenhuma camada respondeu; e a camada 4 que roda"


# ---------------------------------------------------------------------------
# Ranking: o que resolveu AQUI sobe
# ---------------------------------------------------------------------------


def test_option_that_fixed_before_comes_first(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        event = _finding()
        before, _layer = db.lookup(event)
        last = before[-1]
        db.record(event, last, outcome=OUTCOME_FIXED, source=kbstore.LAYER_METRIC)
        after, _layer = db.lookup(event)
    assert after[0]["key"] == last["key"]
    assert [o["key"] for o in after] == [last["key"]] + [
        o["key"] for o in before if o["key"] != last["key"]
    ]


def test_option_that_failed_sinks_below_one_that_worked(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        event = _finding()
        first, second = db.lookup(event)[0][:2]
        db.record(event, first, outcome=OUTCOME_NOT_FIXED, source=kbstore.LAYER_METRIC)
        db.record(event, second, outcome=OUTCOME_FIXED, source=kbstore.LAYER_METRIC)
        order = [o["key"] for o in db.lookup(event)[0]]
    assert order.index(second["key"]) < order.index(first["key"])


def test_ranking_is_scoped_to_the_fingerprint(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        chrome = _finding(name="chrome")
        blender = _finding(name="blender")
        seeded = db.lookup(chrome)[0]
        last = seeded[-1]
        db.record(chrome, last, outcome=OUTCOME_FIXED, source=kbstore.LAYER_METRIC)
        chrome_order = [o["key"] for o in db.lookup(chrome)[0]]
        blender_order = [o["key"] for o in db.lookup(blender)[0]]
    # A vitoria contra o chrome sobe aquela opcao SO para o chrome; o
    # blender, que nunca tentou nada, recebe a ordem curada de sempre.
    assert chrome_order[0] == last["key"]
    assert blender_order == [o["key"] for o in seeded]


# ---------------------------------------------------------------------------
# Camada esgotada: insistir num conselho ja recusado e o que o usuario
# chamou de "site de suporte"
# ---------------------------------------------------------------------------


def test_a_layer_the_user_refused_entirely_stops_answering(tmp_path):
    event = _finding()
    with kbstore.open_store(tmp_path / "kb.db") as db:
        curated, layer = db.lookup(event)
        assert layer == kbstore.LAYER_METRIC
        for option in curated[:-1]:
            db.record(event, option, outcome=OUTCOME_NOT_FIXED,
                      source=kbstore.LAYER_METRIC)
        # Falta uma opcao que ninguem tentou: a camada ainda tem o que dizer.
        assert db.lookup(event)[1] == kbstore.LAYER_METRIC
        db.record(event, curated[-1], outcome=OUTCOME_NOT_FIXED,
                  source=kbstore.LAYER_METRIC)
        options, layer = db.lookup(event)
    assert options == [] and layer == 0, "esgotou: a bola vai pro modelo"


def test_refusing_chrome_does_not_silence_the_answer_for_blender(tmp_path):
    chrome = _finding(name="chrome")
    blender = _finding(name="blender")
    with kbstore.open_store(tmp_path / "kb.db") as db:
        for option in db.lookup(chrome)[0]:
            db.record(chrome, option, outcome=OUTCOME_NOT_FIXED,
                      source=kbstore.LAYER_METRIC)
        options, layer = db.lookup(blender)
    assert options and layer == kbstore.LAYER_METRIC


def test_explain_says_why_no_layer_answered(tmp_path):
    event = _finding(metric="gpu")
    with kbstore.open_store(tmp_path / "kb.db") as db:
        info = db.explain(event)
    assert info["layer"] == 0
    assert "nao conhece" in info["camada"]


def test_record_without_key_is_a_noop(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        assert db.record(_finding(), {"title": "solta"}, outcome=OUTCOME_FIXED,
                         source=kbstore.LAYER_METRIC) is False


# ---------------------------------------------------------------------------
# --explain-source
# ---------------------------------------------------------------------------


def test_explain_reports_layer_and_counts(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        event = _finding()
        first = db.lookup(event)[0][0]
        db.record(event, first, outcome=OUTCOME_FIXED, source=kbstore.LAYER_METRIC)
        info = db.explain(event)
    assert info["layer"] == kbstore.LAYER_METRIC
    assert info["ranked_by"][first["key"]]["fixed"] == 1
    assert "camada" in info


# ---------------------------------------------------------------------------
# A base cresce com o uso: o desfecho de uma opcao aprendida tambem conta
# ---------------------------------------------------------------------------


def test_learned_option_can_be_ranked_and_recorded(tmp_path):
    with kbstore.open_store(tmp_path / "kb.db") as db:
        event = _finding(metric=METRIC_CPU, name="ffmpeg")
        db.learn(event, _learned("Reduz o numero de workers do ffmpeg"),
                 source=kbstore.LAYER_MODEL)
        options, _layer = db.lookup(event)
        db.record(event, options[0], outcome=OUTCOME_FIXED,
                  source=kbstore.LAYER_FINGERPRINT)
        again, layer = db.lookup(event)
    assert layer == kbstore.LAYER_FINGERPRINT
    assert again[0]["fixed_for_this_fingerprint"] == 1


def test_orphan_incident_seeds_from_kb(tmp_path):
    event = {
        "id": "evt-orphan",
        "schema": 2,
        "kind": "anomaly",
        "metric": METRIC_ORPHAN_TREE,
        "severity": "warning",
        "label": "setup (pid 1) saiu deixando 2 processo(s) vivo(s) na arvore",
        "detail": {"parent": {"pid": 1, "name": "setup"}, "tree": [], "tree_size": 2},
        "fingerprint": "orphan_tree:warning:setup",
        "occurrences": 1,
    }
    with kbstore.open_store(tmp_path / "kb.db") as db:
        options, layer = db.lookup(event)
    assert options and layer == kbstore.LAYER_METRIC
    assert kbstore.cause_of(event) == "setup"
