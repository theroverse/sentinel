/* Sentinel GUI — console de vigilância (fase 1: dados de exemplo).
   Mesma casca do vector/gui e genesis/gui (titlebar + sidebar + conteudo,
   dual-mode WebView2/preview). Nada aqui toca o sistema: as acoes que
   exigiriam o motor mostram o gesto e dizem "demonstração". Fase 2 liga o
   bridge nos endpoints JSON do CLI (spec, fase 0) sem mudar nenhuma forma
   de dado — mock.js espelha sensor.Sample, detector.Finding e as linhas de
   .sentinel/events.jsonl (schema 1). */

const M = SENTINEL_MOCK;

/* icones desenhados (SVG inline, traco 1.6-1.8, grade 24, currentColor) — um
   so sistema, sem unicode/emoji fazendo papel de icone. */
const ICON = {
  gauge: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 15a8 8 0 0 1 16 0"/><path d="M12 15l4-4"/><path d="M4 19h16"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4 3 19h18z"/><path d="M12 9v4.5"/><path d="M12 16.4h.01"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><path d="M12 7.9h.01"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4 3 19h18z"/><path d="M12 9v4.5"/><path d="M12 16.4h.01"/></svg>',
  crit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M8.6 8.6l6.8 6.8"/><path d="M15.4 8.6l-6.8 6.8"/></svg>',
  book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 5.5A1.5 1.5 0 0 1 6.5 4H11v16H6.5A1.5 1.5 0 0 1 5 18.5z"/><path d="M19 5.5A1.5 1.5 0 0 0 17.5 4H13v16h4.5A1.5 1.5 0 0 0 19 18.5z"/></svg>',
  list: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M9 6h11M9 12h11M9 18h11"/><path d="M4.5 6h.01M4.5 12h.01M4.5 18h.01"/></svg>',
  terminal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M7 10l2.5 2L7 14"/><path d="M12.5 14H17"/></svg>',
  sliders: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M5 7h14M5 12h14M5 17h14"/><circle cx="10" cy="7" r="2.1" fill="var(--bg-elevated)"/><circle cx="15" cy="17" r="2.1" fill="var(--bg-elevated)"/></svg>',
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="5.5" y="10.5" width="13" height="9" rx="2"/><path d="M8.8 10.5V8a3.2 3.2 0 0 1 6.4 0v2.5"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  power: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M12 4v8"/><path d="M7.2 6.6a7 7 0 1 0 9.6 0"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12a7 7 0 1 1-2.4-5.3"/><path d="M19 4.5V7h-2.5"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4l7 2.5v6c0 4-3 6.8-7 8-4-1.2-7-4-7-8v-6z"/><path d="M9 12l2.2 2.2L15.5 10"/></svg>',
  open: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 5h5v5"/><path d="M19 5l-8 8"/><path d="M18 13.5V19H5V6h5.5"/></svg>',
};

const METRICS = {
  cpu: { label: "CPU", word: "CPU", fmt: "pct" },
  ram: { label: "RAM", word: "memória", fmt: "pct" },
  disk: { label: "DISCO", word: "disco", fmt: "pct" },
  io: { label: "I/O", word: "uso do disco", fmt: "pct" },
  network: { label: "REDE", word: "rede", fmt: "mbit" },
};

const SEV = {
  info: { word: "info", cls: "sev-info", icon: "info" },
  warning: { word: "ATENÇÃO", cls: "sev-warning", icon: "warn" },
  critical: { word: "CRÍTICO", cls: "sev-critical", icon: "crit" },
};

const STATUS_WORD = { open: "aberta", addressing: "em correção", resolved: "resolvida", dismissed: "descartada" };

// outcome de uma linha `resolution` do events.jsonl (tutor.py)
const OUTCOME_WORD = { fixed: "resolveu", not_fixed: "não resolveu", dismissed: "descartada" };

const NAV = [
  {
    title: "Vigilância",
    items: [
      { id: "painel", label: "Visão geral", icon: "gauge" },
      { id: "anomalias", label: "Anomalias", icon: "alert", count: "open" },
      { id: "tutorial", label: "Tutorial de correção", icon: "book" },
    ],
  },
  {
    title: "Sistema",
    items: [
      { id: "processos", label: "Processos", icon: "list" },
      { id: "log", label: "Log do daemon", icon: "terminal" },
    ],
  },
  { title: "Config", items: [{ id: "ajustes", label: "Limites e privacidade", icon: "sliders" }] },
];

// espelha settings.PROTECTED_PROCESS_NAMES (processctl.is_protected), nome a
// nome: qualquer divergencia aqui faria a GUI trancar um alvo que o Python
// mataria, ou o contrario.
const PROTECTED_NAMES = [
  "system", "system idle process", "registry", "smss", "csrss", "wininit",
  "services", "lsass", "svchost", "winlogon", "dwm",
];

const state = {
  view: "painel",
  events: M.events.map(function (e) { return Object.assign({}, e); }),
  resolutions: M.resolutions.slice(),
  log: M.log.slice(),
  sel: "evt-20260922-101244-9a31",
  filter: "open",
  sevFilter: "all",
  procSort: "cpu",
  engineAvailable: false,
  pending: null,   // { html, kind } — proximo render coloca no slot da vista
  tutor: null,    // { eventId, index, tried:[{i,outcome}], status }
  kill: null,     // modal aberto: { pid }
  killed: [],
  newId: null,
};

/* ---------------- util ---------------- */

const $ = function (sel) { return document.querySelector(sel); };

function esc(s) {
  return String(s === undefined || s === null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isHosted() { return !!(window.chrome && window.chrome.webview); }

function sendToHost(type, payload) {
  if (!isHosted()) return false;
  // JSON.stringify obrigatorio: o host le com TryGetWebMessageAsString(),
  // que devolve null para objeto cru (mesma regra provada no Vector/Genesis).
  window.chrome.webview.postMessage(JSON.stringify({ type: type, payload: payload }));
  return true;
}

/* Em modo mock o "agora" e o ts da ultima amostra, para que as idades
   relativas aprovadas visualmente sejam sempre as mesmas; com o motor
   ligado, passa a ser o relogio real. */
function nowMs() {
  return state.engineAvailable ? Date.now() : Date.parse(M.sample.ts);
}

function relTime(iso) {
  const t = Date.parse(iso);
  if (isNaN(t)) return "—";
  const s = Math.max(0, Math.round((nowMs() - t) / 1000));
  if (s < 45) return "agora";
  if (s < 5400) return "há " + Math.round(s / 60) + " min";
  if (s < 86400) return "há " + (s / 3600).toFixed(1).replace(".", ",") + " h";
  const d = Math.round(s / 86400);
  return d === 1 ? "ontem" : "há " + d + " d";
}

function clock(iso) {
  const dt = new Date(iso);
  if (isNaN(dt.getTime())) return "—";
  const p = function (n) { return (n < 10 ? "0" : "") + n; };
  return p(dt.getHours()) + ":" + p(dt.getMinutes()) + ":" + p(dt.getSeconds());
}

function uptime(fromIso) {
  const s = Math.max(0, Math.round((nowMs() - Date.parse(fromIso)) / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return (h > 0 ? h + " h " : "") + m + " min";
}

function num(v, dec) {
  const d = dec === undefined ? 1 : dec;
  return Number(v).toFixed(d).replace(".", ",");
}

function fmtValue(kind, v) {
  if (kind === "mbit") return num(v, 1) + " Mbit/s";
  return num(v, 1) + "%";
}

function mbits(bps) { return (bps * 8) / 1e6; }

function rss(mb) { return mb >= 1024 ? num(mb / 1024, 2) + " GB" : num(mb, 0) + " MB"; }

function eventById(id) {
  for (let i = 0; i < state.events.length; i++) if (state.events[i].id === id) return state.events[i];
  return null;
}

function openEvents() {
  return state.events.filter(function (e) { return e.status === "open" || e.status === "addressing"; });
}

function criticalCount() {
  return openEvents().filter(function (e) { return e.severity === "critical"; }).length;
}

function sevOf(e) { return SEV[e.severity] || SEV.info; }

function metricSev(metric) {
  let worst = null;
  const rank = { info: 1, warning: 2, critical: 3 };
  openEvents().forEach(function (e) {
    if (e.metric !== metric) return;
    if (!worst || rank[e.severity] > rank[worst]) worst = e.severity;
  });
  return worst;
}

function isProtectedName(name) {
  // processctl.is_protected: tira o caminho, compara em minusculas, e aceita
  // a base com ou sem .exe.
  const low = String(name || "").toLowerCase();
  const base = low.split(/[\\/]/).pop().replace(/\.exe$/, "");
  return PROTECTED_NAMES.indexOf(base) !== -1;
}

function notice(html, kind) {
  state.pending = { html: html, kind: kind || "info" };
}

function slotHtml(fallback) {
  if (state.pending) {
    const n = state.pending;
    return '<div id="notice-slot"><div class="notice is-' + n.kind + '">' +
      ICON[n.kind === "bad" ? "crit" : n.kind === "warn" ? "warn" : "info"] +
      "<div>" + n.html + "</div></div></div>";
  }
  state.pending = null;
  return '<div id="notice-slot">' + (fallback || "") + "</div>";
}

const DEMO_BANNER = "<b>Modo demonstração.</b> Os números vêm de " +
  '<span class="inline-code">gui/sentinel/mock.js</span>, com exatamente as formas do motor. ' +
  "Nenhum processo, arquivo ou registro foi tocado.";

/* ---------------- casca ---------------- */

function daemonLive() {
  return !!(M.daemon.running && state.killed.indexOf(M.daemon.pid) < 0);
}

function renderTitlebar() {
  const live = daemonLive();
  const pill = $("#daemon-pill");
  pill.className = "state-pill " + (live ? "is-live" : "is-dead");
  pill.innerHTML = '<span class="led" aria-hidden="true"></span>' + (live ? "VIVO" : "PARADO");
  $("#titlebar-phase").textContent = state.engineAvailable
    ? "motor real — .sentinel/"
    : "dados de exemplo — demonstração";
}

function renderSidebar() {
  const open = openEvents().length;
  const hot = criticalCount();
  $("#sidebar").innerHTML = NAV.map(function (g) {
    return '<div class="side-group"><div class="side-group-title">' + esc(g.title) + "</div>" +
      g.items.map(function (it) {
        const cur = state.view === it.id ? " is-current" : "";
        const hotc = it.count === "open" && hot ? " has-hot" : "";
        const cnt = it.count === "open" && open ? '<span class="side-count">' + open + "</span>" : "";
        return '<button class="side-item' + cur + hotc + '" data-view="' + it.id + '">' +
          ICON[it.icon] + "<span>" + esc(it.label) + "</span>" + cnt + "</button>";
      }).join("") + "</div>";
  }).join("");
}

function renderStatusbar() {
  const s = M.sample;
  $("#statusbar-left").innerHTML =
    "<b>" + (daemonLive() ? "vigilando" : "daemon parado") + "</b>" +
    '<span class="sep">·</span>amostra ' + esc(clock(s.ts)) +
    '<span class="sep">·</span>pid ' + (daemonLive() ? M.daemon.pid : "—") +
    '<span class="sep">·</span>' + (function () {
      const n = openEvents().length;
      return n + (n === 1 ? " anomalia aberta" : " anomalias abertas");
    })();
  $("#statusbar-right").innerHTML = "100% local, sem telemetria" +
    '<span class="sep">·</span>Sentinel v0.1.0';
}

function sweepMark() {
  const mark = $("#titlebar-mark");
  mark.classList.remove("sweep");
  void mark.offsetWidth;
  mark.classList.add("sweep");
}

/* ---------------- medidores ---------------- */

function gaugeDefs() {
  const s = M.sample, t = M.thresholds;
  // Quatro medidores, como o DESIGN manda: I/O e a ocupacao do volume vivem
  // no rodape do DISCO (e um gargalo do mesmo instrumento), nao viram um
  // quinto medidor que deixaria buraco na grade.
  return [
    { key: "cpu", name: "CPU", kind: "pct", value: s.cpu_percent, max: 100, thr: t.cpu, series: "cpu", lead: s.top_cpu[0].name },
    { key: "ram", name: "RAM", kind: "pct", value: s.ram_percent, max: 100, thr: t.ram, series: "ram", lead: s.top_mem[0].name },
    {
      key: "disk", name: "DISCO", kind: "pct", value: s.disk_percent, max: 100, thr: t.disk, series: "disk",
      lead: s.disk_path + " cheio · I/O " + num(s.io_busy_percent, 1) + "%",
      sev: worstSev(sevFromValue(s.disk_percent, t.disk), metricSev("io")),
    },
    {
      key: "network", name: "REDE", kind: "mbit", value: mbits(s.net_recv_bps), max: 12,
      thr: { warning: null, critical: null }, series: "net", lead: "recebendo agora",
      sev: metricSev("network"),
    },
  ].map(function (g) {
    if (g.sev === undefined) g.sev = sevFromValue(g.value, g.thr);
    return g;
  });
}

function sevFromValue(v, thr) {
  if (thr.warning == null) return null;
  if (v >= thr.critical) return "critical";
  if (v >= thr.warning) return "warning";
  return null;
}

function worstSev(a, b) {
  const rank = { info: 1, warning: 2, critical: 3 };
  if (!a) return b || null;
  if (!b) return a;
  return rank[a] >= rank[b] ? a : b;
}

function gaugeSeverity(g) { return g.sev; }

/* Sparkline: traco de 60 amostras com o momento da anomalia marcado e a linha
   de limiar. Step-wise de proposito — interpolar faria dado amostrado parecer
   continuo. */
function spark(seriesKey, thrWarn, max) {
  const s = M.series[seriesKey];
  const pts = s.points, n = pts.length;
  const top = Math.max(Math.max.apply(null, pts), max * 0.5, thrWarn == null ? 0 : thrWarn) * 1.15;
  const step = 100 / (n - 1);
  const line = pts.map(function (v, i) {
    return (i * step).toFixed(2) + "," + (30 - (v / top) * 30).toFixed(2);
  }).join(" ");
  let extra = "";
  if (thrWarn != null) {
    const y = (30 - (thrWarn / top) * 30).toFixed(2);
    extra += '<line class="spark-warn" x1="0" y1="' + y + '" x2="100" y2="' + y + '"/>';
  }
  if (s.spike != null) {
    const x = (s.spike * step).toFixed(2);
    extra += '<line class="spark-mark" x1="' + x + '" y1="0" x2="' + x + '" y2="30"/>';
  }
  return '<svg class="spark" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">' +
    '<polyline class="spark-line" points="' + line + '" />' + extra + "</svg>";
}

function renderGauges() {
  return '<div class="meters" role="group" aria-label="Medidores do sistema">' +
    gaugeDefs().map(function (g) {
      const sev = gaugeSeverity(g);
      const cls = sev === "critical" ? " is-critical" : sev === "warning" ? " is-warning" : "";
      const pctw = Math.min(100, (g.value / g.max) * 100);
      const ticks =
        (g.thr.warning == null ? "" :
          '<span class="gauge-tick" style="left:' + (g.thr.warning / g.max) * 100 + '%"></span>') +
        (g.thr.critical == null ? "" :
          '<span class="gauge-tick is-crit" style="left:' + (g.thr.critical / g.max) * 100 + '%"></span>');
      const thrTxt = g.thr.warning == null
        ? "limiar relativo"
        : "atenção " + num(g.thr.warning, 0) + "% · crítico " + num(g.thr.critical, 0) + "%";
      return '<div class="gauge' + cls + '">' +
        '<div class="gauge-top"><span class="gauge-name">' + esc(g.name) + "</span>" +
        '<span class="gauge-sev' + (sev ? " " + SEV[sev].cls : "") + '">' +
        (sev ? ICON[SEV[sev].icon] + esc(SEV[sev].word) : "<span>na faixa</span>") +
        "</span></div>" +
        '<div class="gauge-val"><span class="n">' + num(g.value, 1) + "</span>" +
        '<span class="u">' + (g.kind === "mbit" ? "Mbit/s" : "%") + "</span></div>" +
        '<div class="gauge-bar"><span class="gauge-fill" style="width:' + pctw.toFixed(1) + '%"></span>' + ticks + "</div>" +
        spark(g.series, g.thr.warning, g.max) +
        '<div class="gauge-foot"><span class="lead">' + esc(g.lead) + "</span><span>" + thrTxt + "</span></div>" +
        "</div>";
    }).join("") + "</div>";
}

/* ---------------- listas ---------------- */

function visibleEvents() {
  return state.events.filter(function (e) {
    if (state.filter === "open" && !(e.status === "open" || e.status === "addressing")) return false;
    if (state.sevFilter !== "all" && e.severity !== state.sevFilter) return false;
    return true;
  });
}

function renderEvRow(e) {
  const s = sevOf(e);
  const mm = METRICS[e.metric];
  const v = fmtValue(mm.fmt, e.metric === "network" ? mbits(e.value) : e.value);
  return '<button class="ev-row' + (e.id === state.sel ? " is-sel" : "") +
    (e.id === state.newId ? " is-new" : "") + '" data-ev="' + esc(e.id) + '">' +
    '<span class="sev ' + s.cls + '">' + ICON[s.icon] + "</span>" +
    "<span><span class=\"ev-metric\">" + esc(mm.label) + "</span>" +
    '<span class="ev-meta">' + esc(e.top_processes.length ? e.top_processes[0].name : "sem alvo") +
    " · " + esc(relTime(e.ts_last)) + " · " + esc(STATUS_WORD[e.status]) + "</span></span>" +
    '<span class="ev-val">' + esc(v) +
    (e.occurrences > 1 ? '<span class="ev-meta">×' + e.occurrences + "</span>" : "") +
    "</span></button>";
}

function renderEvList() {
  const evs = visibleEvents();
  if (!evs.length) {
    return '<div class="empty">' + ICON.check +
      '<div class="empty-t">Nada na fila</div>' +
      (state.filter === "open"
        ? "Nenhuma anomalia aberta. O daemon continua vigiando."
        : "Nenhuma anomalia com esse filtro.") + "</div>";
  }
  return '<div class="ev-list">' + evs.map(renderEvRow).join("") + "</div>";
}

function procFlags(p) {
  // So acrescenta trava em relacao ao motor (nome na lista, marca `self`);
  // nunca tira, porque o guard real e do Python.
  return {
    protected: !!p.protected || isProtectedName(p.name),
    self: !!p.self || /sentinel/i.test(p.name),
  };
}

function renderProcTable(procs, killable) {
  return '<table class="tbl"><thead><tr><th>PID</th><th>Processo</th>' +
    '<th class="r">CPU</th><th class="r">RSS</th>' + (killable ? '<th class="r">Ação</th>' : "") +
    "</tr></thead><tbody>" +
    procs.map(function (p) {
      const f = procFlags(p);
      const blocked = f.protected || f.self;
      return "<tr" + (blocked ? ' class="is-blocked"' : "") + ">" +
        '<td class="pid">' + p.pid + "</td>" +
        '<td><span class="pname">' + esc(p.name) + "</span>" +
        (blocked ? ' <span class="lock-flag">' + ICON.lock + (f.self ? "sentinel" : "protegido") + "</span>" : "") +
        "</td>" +
        '<td class="meas r">' + num(p.cpu, 1) + "%</td>" +
        '<td class="meas r">' + esc(rss(p.rss_mb)) + "</td>" +
        (killable
          ? '<td class="r">' + (blocked
            ? '<span class="src">—</span>'
            : '<button class="btn btn-sm btn-ghost" data-kill="' + p.pid + '">Encerrar…</button>') + "</td>"
          : "") +
        "</tr>";
    }).join("") + "</tbody></table>";
}

function killButton(e, cls) {
  const top = (e.top_processes || [])[0];
  if (!top) return '<span class="src">sem alvo matável nesta amostra</span>';
  const f = procFlags(top);
  if (f.protected || f.self) {
    return '<span class="src">alvo do topo é protegido — encerre pelo Gerenciador de Tarefas</span>';
  }
  return '<button class="btn ' + (cls || "btn-danger") + '" data-kill="' + top.pid + '">' +
    ICON.power + "Encerrar " + esc(top.name) + "…</button>";
}

function renderDetail(e) {
  if (!e) {
    return '<div class="empty">' + ICON.alert +
      '<div class="empty-t">Selecione uma anomalia</div>' +
      "Aqui aparecem valor contra limiar, janela sustentada e os processos do topo.</div>";
  }
  const mm = METRICS[e.metric];
  const isNet = e.metric === "network";
  const val = fmtValue(mm.fmt, isNet ? mbits(e.value) : e.value);
  const thr = fmtValue(mm.fmt, isNet ? mbits(e.threshold) : e.threshold);
  const s = sevOf(e);
  const procs = e.top_processes.map(function (p) { return Object.assign({}, p); });
  const res = state.resolutions.filter(function (r) { return r.ref === e.id; });
  const settled = e.status === "resolved" || e.status === "dismissed";
  const actions = settled
    ? '<span class="src">nada a fazer — anomalia ' +
      esc(e.status === "resolved" ? "resolvida" : "descartada") + "</span>"
    : '<button class="btn btn-primary" data-tutor="' + esc(e.id) + '">' + ICON.book + "Corrigir</button>" +
      (isNet ? '<span class="src">rede: nenhuma ação automática — é contexto, não defeito</span>' : killButton(e)) +
      '<button class="btn btn-ghost" data-dismiss="' + esc(e.id) + '">Descartar</button>';

  return '<div class="panel"><div class="panel-head"><span class="panel-title">' + esc(e.id) + "</span>" +
    '<span class="badge">' + esc(STATUS_WORD[e.status]) + "</span></div>" +
    '<div class="panel-body">' +
    '<dl class="kv">' +
    '<dt>Métrica</dt><dd>' + esc(mm.word) + ' <span class="src">metric=' + esc(e.metric) + "</span></dd>" +
    '<dt>Valor</dt><dd><span class="num">' + esc(val) + '</span> <span class="src">vs limiar ' + esc(thr) + "</span></dd>" +
    '<dt>Severidade</dt><dd><span class="sev-word ' + s.cls + '">' + ICON[s.icon] + esc(s.word) + "</span></dd>" +
    "<dt>Sustentada</dt><dd><span class=\"num\">" + e.window.samples + " amostras em " +
    num(e.window.span_s, 1) + " s</span> <span class=\"src\">· " +
    num(e.window.span_s / e.window.samples, 1) + " s por amostra</span></dd>" +
    "<dt>Repetições</dt><dd><span class=\"num\">" + e.occurrences + "</span>" +
    ' <span class="src">· última ' + esc(relTime(e.ts_last)) + "</span></dd>" +
    "<dt>Fingerprint</dt><dd class=\"mono\">" + esc(e.fingerprint) + "</dd>" +
    "<dt>Aberto em</dt><dd class=\"mono\">" + esc(clock(e.ts)) + " · " + esc(relTime(e.ts)) + "</dd>" +
    "</dl>" +
    '<div class="panel-title" style="margin:18px 0 8px">TOPO DA AMOSTRA</div>' +
    renderProcTable(procs, !isNet && !settled) +
    (res.length
      ? '<div class="panel-title" style="margin:18px 0 8px">RESOLUÇÕES</div><div class="tried" style="border-top:none;padding-top:0">' +
        res.map(function (r) {
          const fixedRow = r.outcome === "fixed";
          const opt = r.option_index == null ? "todas as opções" : "opção " + (r.option_index + 1);
          return '<div class="tried-row">' + (fixedRow ? ICON.check : ICON.x) + "<span>" + opt +
            " · " + esc(OUTCOME_WORD[r.outcome] || r.outcome) + " · fonte " + esc(r.source) +
            (r.note ? " — " + esc(r.note) : "") + " · " + esc(relTime(r.ts)) + "</span></div>";
        }).join("") + "</div>"
      : "") +
    '<div class="detail-actions">' + actions + "</div>" +
    "</div></div>";
}

/* ---------------- tutorial (espelha tutor.py) ---------------- */

function optionsFor(metric) { return M.kb[metric] || []; }

function startTutor(eventId) {
  const e = eventById(eventId);
  if (!e) return;
  // tutor.run_cycle abre o ciclo marcando o evento como "addressing".
  if (e.status === "open") e.status = "addressing";
  state.tutor = { eventId: eventId, index: 0, tried: [], status: "asking" };
  state.sel = eventId;
  go("tutorial");
}

// Desfecho do ciclo de validacao. O motor grava UMA linha `resolution` no
// fim (fixed / dismissed / not_fixed com option_index null), nunca uma por
// opcao tentada - "next" so avanca o indice.
function onFix(kind) {
  const t = state.tutor;
  if (!t) return;
  const e = eventById(t.eventId);
  if (!e) { state.tutor = null; go("anomalias"); return; }
  const opts = optionsFor(e.metric);

  if (kind === "yes") {
    t.tried.push({ i: t.index, outcome: "fixed" });
    recordResolution(e, "fixed", t.index, "usuario validou solucao");
    e.status = "resolved";
    t.status = "resolved";
    render();
    return;
  }
  if (kind === "skip") {
    recordResolution(e, "dismissed", t.index, "usuario pulou/descartou");
    e.status = "dismissed";
    state.tutor = null;
    notice("<b>Demonstração:</b> a linha de resolução não foi escrita em " +
      '<span class="inline-code">events.jsonl</span> — quem grava é o motor (fase 2 da spec).', "warn");
    go("anomalias");
    return;
  }
  t.tried.push({ i: t.index, outcome: "not_fixed" });
  t.index += 1;
  if (t.index >= opts.length) {
    recordResolution(e, "not_fixed", null, "todas as opcoes esgotadas sem sucesso");
    e.status = "dismissed";
  }
  render();
}

function recordResolution(e, outcome, optionIndex, note) {
  state.resolutions.unshift({
    schema: 1,
    id: "res-demo-" + (state.resolutions.length + 1),
    ts: new Date().toISOString(),
    kind: "resolution",
    ref: e.id,
    outcome: outcome,
    option_index: optionIndex,
    source: "kb",
    note: note,
  });
}

function renderTutor(host) {
  const t = state.tutor;
  if (!t) {
    const cands = openEvents();
    host.innerHTML = '<div class="view"><div class="view-head"><div>' +
      '<h1 class="view-title">Tutorial de correção</h1>' +
      '<p class="view-sub">O ciclo é do motor: até 3 opções, você valida cada uma, e o que falhou é descartado.</p></div></div>' +
      (cands.length
        ? '<div class="panel"><div class="panel-head"><span class="panel-title">ABERTAS — ESCOLHA UMA</span></div>' +
          '<div class="ev-list">' + cands.map(renderEvRow).join("") + "</div></div>"
        : '<div class="empty">' + ICON.check + '<div class="empty-t">Nenhuma anomalia em correção</div>' +
          "Quando o daemon achar algo, o tutorial abre daqui.</div>") +
      "</div>";
    return;
  }
  const e = eventById(t.eventId);
  const opts = optionsFor(e.metric);
  const exhausted = t.index >= opts.length;
  const opt = exhausted ? null : opts[t.index];
  let body;

  if (t.status === "resolved") {
    body = '<div class="notice is-ok">' + ICON.check +
      "<div><b>Resolvido.</b> Resolução gravada contra " +
      '<span class="inline-code">' + esc(e.id) + "</span> usando a opção " +
      (t.tried.length ? t.tried[t.tried.length - 1].i + 1 : opts.length) +
      ", fonte <b>base local</b>." +
      (M.demo ? ' <span class="src">demonstração: nada foi escrito em .sentinel/</span>' : "") +
      "</div></div>" +
      '<div class="btn-row" style="margin-top:16px"><button class="btn btn-ghost" data-goto="anomalias">Voltar às anomalias</button></div>';
  } else if (exhausted) {
    body = '<div class="notice is-warn">' + ICON.warn +
      "<div><b>Fim da fila.</b> As " + opts.length + " opções da base local para " +
      esc(METRICS[e.metric].word) + " não resolveram. O motor grava uma resolução " +
      '<span class="inline-code">not_fixed</span> e fecha o evento como ' +
      '<span class="inline-code">dismissed</span> — a anomalia continua no histórico pelo ' +
      '<span class="inline-code">fingerprint</span>, e na próxima vez o ' +
      '<span class="inline-code">claude -p</span> pode acrescentar opções novas.</div></div>' +
      '<div class="btn-row" style="margin-top:16px"><button class="btn btn-ghost" data-retry="1">Repetir do início</button>' +
      '<button class="btn btn-ghost" data-goto="anomalias">Voltar às anomalias</button></div>';
  } else {
    body = '<div class="tutor-head"><span class="tutor-count">OPÇÃO ' + (t.index + 1) + " DE " + opts.length + "</span>" +
      '<span class="badge is-local">' + ICON.shield + "base local</span>" +
      (state.engineAvailable ? "" : '<span class="badge">IA indisponível nesta demonstração</span>') +
      "</div>" +
      '<h2 class="tutor-title">' + esc(opt.title) + "</h2>" +
      '<ol class="steps">' + opt.steps.map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") + "</ol>" +
      (opt.action && opt.action.type === "kill_top_process"
        ? '<div class="btn-row" style="margin-top:6px">' + killButton(e) + "</div>"
        : "") +
      (opt.action && opt.action.type === "open_settings"
        ? '<div class="btn-row" style="margin-top:6px"><button class="btn btn-ghost" data-open="' +
          esc(opt.action.target) + '">' + ICON.open + "Abrir " +
          (opt.action.target === "storage" ? "Armazenamento" : "Gerenciador de Tarefas") + "</button></div>"
        : "");
  }

  const ask = (t.status === "resolved" || exhausted) ? "" :
    '<div class="ask"><span class="ask-q">Funcionou?</span>' +
    '<button class="btn btn-primary" data-fix="yes">' + ICON.check + "Sim, resolveu</button>" +
    '<button class="btn" data-fix="next">Não, próxima</button>' +
    '<button class="btn btn-ghost" data-fix="skip">Pular tudo</button></div>';

  const tried = t.tried.length
    ? '<div class="tried"><div class="panel-title" style="margin-bottom:8px">JÁ TENTADAS</div>' +
      t.tried.map(function (r) {
        return '<div class="tried-row' + (r.outcome === "not_fixed" ? " is-dud" : "") + '">' +
          (r.outcome === "not_fixed" ? ICON.x : ICON.check) +
          '<span class="t">' + esc(opts[r.i] ? opts[r.i].title : "opção " + (r.i + 1)) + "</span>" +
          '<span class="src">· ' +
          esc(r.outcome === "not_fixed" ? "não resolveu" : "resolvido") + "</span></div>";
      }).join("") + "</div>"
    : "";

  host.innerHTML = '<div class="view"><div class="view-head"><div>' +
    '<h1 class="view-title">Tutorial de correção</h1>' +
    '<p class="view-sub">' + esc(METRICS[e.metric].word) + " · " + esc(sevOf(e).word) + " · " +
    esc(fmtValue(METRICS[e.metric].fmt, e.metric === "network" ? mbits(e.value) : e.value)) +
    " · evento " + esc(e.id) + "</p></div>" +
    '<div class="view-tools"><button class="btn btn-sm btn-ghost" data-back="' + esc(e.id) +
    '">Ver evidência</button></div></div>' +
    slotHtml("") +
    '<div class="panel"><div class="panel-body">' + body + ask + tried + "</div></div></div>";
}

/* ---------------- vistas ---------------- */

function hudCell(k, v, sub) {
  return '<div class="hud-cell"><div class="hud-k">' + esc(k) + "</div>" + v +
    '<div class="hud-k" style="letter-spacing:.05em;margin-top:1px">' + esc(sub) + "</div></div>";
}

function logLines(n) {
  return state.log.slice(0, n).map(function (l) {
    return '<div class="log-line' + (/ANOMALIA/.test(l.text) ? " is-anom" : "") + '"><span class="log-ts">' +
      esc(clock(l.ts)) + "</span>" +
      '<span class="log-text">' + esc(l.text) + "</span></div>";
  }).join("");
}

function viewPainel(host) {
  const s = M.sample;
  host.innerHTML = '<div class="view">' +
    '<div class="view-head"><div><h1 class="view-title">Visão geral</h1>' +
    '<p class="view-sub">O daemon amostra a cada 2 s e grava anomalia em ' +
    '<span class="inline-code">.sentinel/events.jsonl</span>. Isto é o que ele viu.</p></div>' +
    '<div class="view-tools">' +
    '<button class="btn btn-sm btn-ghost" data-daemon="1">' + ICON.power +
    (daemonLive() ? "Parar daemon" : "Iniciar daemon") + "</button>" +
    '<button class="btn btn-sm btn-ghost" data-refresh="1">' + ICON.refresh + "Atualizar</button>" +
    "</div></div>" +
    slotHtml(M.demo ? '<div class="notice is-warn">' + ICON.warn + "<div>" + DEMO_BANNER + "</div></div>" : "") +
    '<div class="hud">' +
    hudCell("DAEMON", daemonLive() ? '<span class="hud-v is-live">vivo</span>' : '<span class="hud-v is-dead">parado</span>',
      "pid " + M.daemon.pid) +
    hudCell("ÚLTIMA AMOSTRA", '<span class="hud-v">' + esc(clock(s.ts)) +
      ' <span class="unit">· ' + esc(relTime(s.ts)) + "</span></span>", "intervalo 2,0 s") +
    hudCell("VIGÍLIA", '<span class="hud-v">' + esc(uptime(M.daemon.started_ts)) + "</span>",
      "desde " + esc(clock(M.daemon.started_ts))) +
    hudCell("ABERTAS", '<span class="hud-v">' + openEvents().length +
      (criticalCount() ? ' <span class="unit">· ' + criticalCount() +
        (criticalCount() === 1 ? " crítica" : " críticas") + "</span>" : "") + "</span>",
      "anomalias na fila") +
    hudCell("RESOLUÇÕES", '<span class="hud-v">' + state.resolutions.length + "</span>", "feedback gravado") +
    "</div>" +
    renderGauges() +
    '<div class="split" style="margin-top:14px">' +
    '<div class="panel"><div class="panel-head"><span class="panel-title">ÚLTIMAS ANOMALIAS</span>' +
    '<button class="btn btn-sm btn-ghost" data-goto="anomalias">Abrir</button></div>' +
    '<div class="ev-list">' + state.events.slice(0, 4).map(renderEvRow).join("") + "</div>" +
    '<div class="panel-head" style="border-top:1px solid var(--border)"><span class="panel-title">TOPO AGORA (CPU)</span></div>' +
    '<div class="panel-body" style="padding:4px 6px 8px">' + renderProcTable(s.top_cpu.slice(0, 4), false) + "</div>" +
    "</div>" +
    '<div class="panel"><div class="panel-head"><span class="panel-title">REGISTRO VIVO</span>' +
    '<button class="btn btn-sm btn-ghost" data-goto="log">Tudo</button></div>' +
    '<div class="panel-body" style="padding:8px 4px 8px 10px">' +
    '<div class="log-panel" style="border:none;background:transparent;max-height:none;padding:0">' +
    logLines(6) + "</div></div></div>" +
    "</div></div>";
}

function viewAnomalias(host) {
  const sevs = [
    { id: "all", label: "todas as severidades" },
    { id: "critical", label: "só críticas" },
    { id: "warning", label: "só atenção" },
    { id: "info", label: "só info" },
  ];
  host.innerHTML = '<div class="view"><div class="view-head"><div>' +
    '<h1 class="view-title">Anomalias</h1>' +
    '<p class="view-sub">Cada linha é um registro de <span class="inline-code">events.jsonl</span>; ' +
    "ao lado, a evidência que o motor usou para classificá-la.</p></div>" +
    '<div class="view-tools">' +
    '<button class="chip' + (state.filter === "open" ? " is-on" : "") + '" data-filter="open">ABERTAS</button>' +
    '<button class="chip' + (state.filter === "all" ? " is-on" : "") + '" data-filter="all">TODAS</button>' +
    "</div></div>" +
    slotHtml("") +
    '<div class="split"><div class="panel">' +
    '<div class="panel-head"><span class="panel-title">' + visibleEvents().length + " DE " + state.events.length + "</span></div>" +
    '<div class="panel-body" style="padding:10px 14px"><div class="filters">' +
    sevs.map(function (x) {
      return '<button class="chip' + (state.sevFilter === x.id ? " is-on" : "") + '" data-sev="' + x.id + '">' + x.label + "</button>";
    }).join("") + "</div></div>" +
    renderEvList() + "</div>" +
    "<div>" + renderDetail(eventById(state.sel)) + "</div>" +
    "</div></div>";
}

function viewProcessos(host) {
  const procs = M.processes.slice().sort(function (a, b) {
    return state.procSort === "mem" ? b.rss_mb - a.rss_mb : b.cpu - a.cpu;
  });
  host.innerHTML = '<div class="view"><div class="view-head"><div>' +
    '<h1 class="view-title">Processos</h1>' +
    '<p class="view-sub">Suspeitos da última amostra. O que o motor protege aparece trancado em vez de escondido — ' +
    "esconder deixaria parecer que dava para encerrar.</p></div>" +
    '<div class="view-tools">' +
    '<button class="chip' + (state.procSort === "cpu" ? " is-on" : "") + '" data-sort="cpu">POR CPU</button>' +
    '<button class="chip' + (state.procSort === "mem" ? " is-on" : "") + '" data-sort="mem">POR MEMÓRIA</button>' +
    "</div></div>" +
    slotHtml("") +
    '<div class="panel"><div class="panel-body" style="padding:4px 6px 10px">' +
    renderProcTable(procs, true) + "</div></div>" +
    '<p class="view-sub" style="margin-top:14px">Serviço do Windows nunca morre por PID: o motor sugere ' +
    '<span class="inline-code">net stop "&lt;nome&gt;"</span> e a decisão continua sua.</p></div>';
}

function viewLog(host) {
  host.innerHTML = '<div class="view"><div class="view-head"><div>' +
    '<h1 class="view-title">Log do daemon</h1>' +
    '<p class="view-sub">Fio de <span class="inline-code">.sentinel/daemon.log</span>: um <span class="inline-code">tick</span> a cada 2 s e uma linha <span class="inline-code">ANOMALIA</span> quando o detector dispara.</p></div>' +
    '<div class="view-tools"><button class="btn btn-sm btn-ghost" data-refresh="1">' + ICON.refresh + "Recarregar</button></div></div>" +
    slotHtml("") +
    '<div class="panel"><div class="panel-body" style="padding:10px 6px 10px 12px">' +
    '<div class="log-panel" style="border:none;background:transparent;max-height:none;padding:0">' +
    logLines(60) + "</div></div></div>" +
    '<p class="view-sub" style="margin-top:12px">' + state.log.length + " linhas nesta janela · rotação por tamanho no motor</p></div>";
}

function viewAjustes(host) {
  const t = M.thresholds;
  const rows = [
    ["cpu", "CPU", num(t.cpu.warning, 0) + "%", num(t.cpu.critical, 0) + "%", t.cpu.sustained + " amostras"],
    ["ram", "RAM", num(t.ram.warning, 0) + "%", num(t.ram.critical, 0) + "%", t.ram.sustained + " amostras · crítico imediato"],
    ["disk", "DISCO", num(t.disk.warning, 0) + "%", num(t.disk.critical, 0) + "%", t.disk.sustained + " amostra · imediato"],
    ["io", "I/O", num(t.io.warning, 0) + "%", num(t.io.critical, 0) + "%", t.io.sustained + " amostras"],
    ["network", "REDE", "0,8× da mediana", "—", t.network.sustained + " amostras · sempre info"],
  ];
  const rules = [
    ICON.shield + "<div>Roda 100% local: sem servidor, sem telemetria, sem asset hospedado, sem fonte web. Nada sai da máquina porque você pediu.</div>",
    ICON.terminal + '<div>A única saída de rede é o <span class="inline-code">claude -p</span> que gera opções novas — disparado por você numa correção, nunca pelo daemon.</div>',
    ICON.lock + "<div>Processo protegido do Windows e o próprio Sentinel nunca são encerrados: o Python recusa antes de a GUI perguntar.</div>",
    ICON.info + '<div>Anomalia de rede é contexto, não defeito: entra como <span class="inline-code">info</span> e não oferece ação automática.</div>',
    ICON.warn + "<div>Severidade nunca é só cor: cada estado tem glifo e palavra em português, porque vermelho é o único matiz semântico desta casa.</div>",
  ];
  host.innerHTML = '<div class="view"><div class="view-head"><div>' +
    '<h1 class="view-title">Limites e privacidade</h1>' +
    '<p class="view-sub">Valores vindos de <span class="inline-code">src/sentinel/settings.py</span>, com override opcional em ' +
    '<span class="inline-code">.sentinel/config.json</span>. A GUI não reinterpreta regra nenhuma.</p></div></div>' +
    slotHtml("") +
    '<div class="panel"><div class="panel-head"><span class="panel-title">LIMIARES</span>' +
    '<span class="src">fonte: padrão do código</span></div>' +
    '<div class="panel-body" style="padding:4px 6px 10px"><table class="tbl thr-tbl"><thead><tr>' +
    "<th>Métrica</th><th>Atenção</th><th>Crítico</th><th>Sustentação</th></tr></thead><tbody>" +
    rows.map(function (r) {
      return "<tr><td>" + esc(r[1]) + '</td><td class="meas">' + esc(r[2]) + '</td><td class="meas">' +
        esc(r[3]) + '</td><td class="meas">' + esc(r[4]) + "</td></tr>";
    }).join("") + "</tbody></table></div></div>" +
    '<div class="panel" style="margin-top:14px"><div class="panel-head"><span class="panel-title">REGRAS DURAS</span></div>' +
    '<div class="panel-body privacy">' +
    rules.map(function (row) { return "<div>" + row + "</div>"; }).join("") +
    "</div></div>" +
    '<p class="view-sub" style="margin-top:14px">Tudo que fica em disco está em ' +
    '<span class="inline-code">&lt;pasta do Sentinel&gt;\\.sentinel\\</span> ' +
    "(events.jsonl, daemon.log, config.json). Apagar é seguro: o daemon recria.</p></div>";
}

/* ---------------- modal de confirmação ---------------- */

function killTarget(pid) {
  for (let i = 0; i < M.processes.length; i++) if (M.processes[i].pid === pid) return M.processes[i];
  return { pid: pid, name: "processo " + pid, cpu: 0, rss_mb: 0, children: 0 };
}

function renderModal() {
  const root = $("#modal-root");
  if (!state.kill) { root.innerHTML = ""; return; }
  const p = killTarget(state.kill.pid);
  const tree = p.children
    ? p.name + " (" + p.pid + ")\n├─ " + (p.pid + 1) + " · filho worker\n└─ " + (p.pid + 2) + " · filho worker"
    : p.name + " (" + p.pid + ")";
  root.innerHTML =
    '<div class="overlay" data-close="1"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">' +
    '<div class="modal-head"><h2 class="modal-title" id="modal-title">Encerrar ' + esc(p.name) + "?</h2></div>" +
    '<div class="modal-body"><dl class="kv">' +
    '<dt>PID</dt><dd><span class="num">' + p.pid + "</span></dd>" +
    '<dt>CPU / RSS</dt><dd><span class="num">' + num(p.cpu, 1) + "% · " + esc(rss(p.rss_mb)) + "</span></dd>" +
    "<dt>Dependentes</dt><dd>" + (function () {
      const n = p.children || 0;
      return n + (n === 1 ? " processo filho" : " processos filhos");
    })() + "</dd>" +
    "</dl>" +
    '<div class="tree">' + esc(tree) + "</div>" +
    '<p style="margin-top:12px">Isto encerra o processo e não desfaz nada dele que já esteja em disco. ' +
    "Salve o que estiver aberto.</p>" +
    '<p class="src" style="margin-top:8px">com o motor ligado, o Python revalida este PID contra a lista de proteção antes de tocar em qualquer coisa.</p>' +
    '</div><div class="modal-foot">' +
    '<button class="btn btn-ghost" data-close="1">Cancelar</button>' +
    '<button class="btn btn-primary" data-kill-go="' + p.pid + '">Encerrar agora</button>' +
    "</div></div></div>";
  const btn = root.querySelector("[data-kill-go]");
  if (btn) btn.focus();
}

/* ---------------- render ---------------- */

const VIEWS = {
  painel: viewPainel,
  anomalias: viewAnomalias,
  tutorial: renderTutor,
  processos: viewProcessos,
  log: viewLog,
  ajustes: viewAjustes,
};

function render() {
  renderTitlebar();
  renderSidebar();
  renderStatusbar();
  const host = $("#content");
  host.innerHTML = "";
  (VIEWS[state.view] || viewPainel)(host);
  renderModal();
  state.pending = null;
}

function go(view) {
  state.view = view;
  render();
  $("#content").scrollTop = 0;
}

/* ---------------- interacao ---------------- */

function demo(text) {
  notice("<b>Demonstração:</b> " + text + " só acontece com a ponte ligada ao CLI " +
    "(fase 2 da spec). A regra de segurança continua no Python, não nesta página.", "warn");
}

function handleActivate(el) {
  if (!el) return false;
  const d = el.dataset;

  if (d.view) { go(d.view); return true; }
  if (d.goto) { go(d.goto); return true; }
  if (d.back) { state.sel = d.back; go("anomalias"); return true; }
  if (d.ev) {
    state.sel = d.ev;
    if (state.view !== "anomalias") state.view = "anomalias";
    render();
    return true;
  }
  if (d.filter) { state.filter = d.filter; render(); return true; }
  if (d.sev) { state.sevFilter = d.sev; render(); return true; }
  if (d.sort) { state.procSort = d.sort; render(); return true; }
  if (d.tutor) { startTutor(d.tutor); return true; }
  if (d.fix) { onFix(d.fix); return true; }
  if (d.retry) { state.tutor.index = 0; state.tutor.status = "asking"; render(); return true; }
  if (d.open) {
    demo("abrir " + (d.open === "storage" ? "Configurações de Armazenamento" : "o Gerenciador de Tarefas"));
    render();
    return true;
  }
  if (d.daemon) {
    if (daemonLive()) {
      state.killed.push(M.daemon.pid);
      demo("o daemon simulado parou; o de verdade é <span class=\"inline-code\">sentinel stop</span>.");
    } else {
      state.killed = [];
      demo("o daemon simulado voltou; o de verdade é <span class=\"inline-code\">sentinel start</span>.");
    }
    render();
    return true;
  }
  if (d.refresh) {
    demo("a amostra nova viria de <span class=\"inline-code\">sentinel metrics --json</span>.");
    render();
    return true;
  }
  if (d.dismiss) {
    const e = eventById(d.dismiss);
    if (e) {
      e.status = "dismissed";
      recordResolution(e, "dismissed", 0, "usuario pulou/descartou");
    }
    demo("a linha <span class=\"inline-code\">outcome=dismissed</span> sairia de " +
      "<span class=\"inline-code\">sentinel fix &lt;id&gt; --dismiss</span>; aqui só mudou a tela.");
    render();
    return true;
  }
  if (d.kill) {
    const pid = parseInt(d.kill, 10);
    if (!isNaN(pid)) { state.kill = { pid: pid }; render(); return true; }
    return false;
  }
  if (d.killGo) {
    state.kill = null;
    demo("encerrar um processo de verdade passa pelo guard do Python.");
    render();
    return true;
  }
  if (d.close) { state.kill = null; render(); return true; }
  return false;
}

const SEL = "[data-view],[data-ev],[data-goto],[data-back],[data-filter],[data-sev],[data-sort]," +
  "[data-tutor],[data-fix],[data-retry],[data-open],[data-daemon],[data-refresh],[data-dismiss]," +
  "[data-kill],[data-kill-go],[data-close]";

document.addEventListener("click", function (ev) {
  const el = ev.target.closest ? ev.target.closest(SEL) : null;
  if (!el) return;
  if (handleActivate(el)) {
    if (state.kill) return;
    const focus = el.getAttribute("data-ev");
    if (focus) { const row = document.querySelector('.ev-row[data-ev="' + focus + '"]'); if (row) row.focus(); }
  }
});

document.addEventListener("keydown", function (ev) {
  if (ev.key === "Escape" && state.kill) { state.kill = null; render(); return; }
  if (state.view !== "anomalias" || (ev.key !== "ArrowDown" && ev.key !== "ArrowUp")) return;
  const list = visibleEvents().map(function (e) { return e.id; });
  if (!list.length) return;
  let i = list.indexOf(state.sel);
  i = ev.key === "ArrowDown" ? Math.min(list.length - 1, i + 1) : Math.max(0, i < 0 ? 0 : i - 1);
  if (i < 0) i = 0;
  state.sel = list[i];
  ev.preventDefault();
  render();
  const row = document.querySelector('.ev-row[data-ev="' + state.sel + '"]');
  if (row) row.focus();
});

$("#titlebar").addEventListener("mousedown", function (ev) {
  if (ev.target.closest && (ev.target.closest(".titlebar-actions") || ev.target.closest("button"))) return;
  sendToHost("window-drag", null);
});
$("#btn-min").addEventListener("click", function () { sendToHost("window-minimize", null); });
$("#btn-close").addEventListener("click", function () { sendToHost("window-close", { confirm: daemonLive() }); });

/* ---------------- bridge + boot ---------------- */

function onBridgeMessage(event) {
  const msg = event && event.data;
  if (!msg || !msg.type) return;
  const p = msg.payload || {};
  if (msg.type === "host-ready") {
    state.engineAvailable = !!p.engineAvailable;
    renderTitlebar();
    // fase 2: 'metrics', 'events-list', 'tutor-options', 'kill-result' e
    // 'daemon-state' substituem mock.js — as mesmas formas, fonte real.
  }
  // tipos desconhecidos sao ignorados com seguranca: a interface segue em mock.
}

function boot() {
  if (isHosted() && window.chrome.webview.addEventListener) {
    window.chrome.webview.addEventListener("message", onBridgeMessage);
    sendToHost("ready", null);
  }
  render();
  // o unico momento de movimento da casa: uma anomalia chega enquanto voce
  // olha, e o olho de radar varre uma vez.
  setTimeout(function () {
    if (state.events.some(function (e) { return e.id === M.arriving.id; })) return;
    state.events.unshift(Object.assign({}, M.arriving));
    state.log.unshift({
      ts: M.arriving.ts,
      text: "ANOMALIA io warning value=78.9 thr=70.0 status=open id=" + M.arriving.id,
    });
    state.newId = M.arriving.id;
    render();
    sweepMark();
    setTimeout(function () { state.newId = null; }, 1000);
  }, 2600);
}

boot();
