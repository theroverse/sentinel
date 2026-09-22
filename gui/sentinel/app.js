/* Sentinel GUI — console de vigilância (fase 2: motor ligado).
   Mesma casca do vector/gui e genesis/gui (titlebar + sidebar + conteudo,
   dual-mode WebView2/preview). Duas fontes de dado, uma só pagina:

   - sem ponte (preview no browser, ou Python ausente no PATH): `mock.js`,
     com exatamente as formas do motor, e a barra de titulo dizendo isso;
   - com ponte: `sentinel metrics --json` responde pelo `M` inteiro
     (`applyEngine`), e as ações viram `fix --plan` / `fix --resolve` /
     `kill --yes` / `start|stop` no mesmo CLI.

   Regra que nada aqui fura: limiar, severidade, lista de proteção e recusa
   sao do Python (`src/sentinel/api.py`). A pagina mostra e pergunta; nunca
   decide. */

let M = SENTINEL_MOCK;

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
  pause: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M9.5 5.5v13M14.5 5.5v13"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 5.5l10 6.5L8 18.5z"/></svg>',
};

const METRICS = {
  cpu: { label: "CPU", word: "CPU", fmt: "pct" },
  ram: { label: "RAM", word: "memória", fmt: "pct" },
  disk: { label: "DISCO", word: "disco", fmt: "pct" },
  io: { label: "I/O", word: "uso do disco", fmt: "pct" },
  network: { label: "REDE", word: "rede", fmt: "mbit" },
  /* Incidentes (schema 2) nao tem limiar: o que a ficha mostra e o que
     houve, nao "0,0 vs 0,0". `incident: true` e o que o renderizador usa
     para trocar as linhas — ver `renderDetail`. */
  stall: { label: "TRAVAMENTO", word: "travamento", fmt: "none", incident: true },
  app_failure: { label: "FALHA DE APP", word: "falha de app", fmt: "none", incident: true },
  orphan_tree: { label: "ÁRVORE ÓRFÃ", word: "árvore órfã", fmt: "none", incident: true },
};

// metrica sem entrada no vocabulario ainda nao e tela em branco: o nome cru
// do motor e melhor que um "undefined", e continua sendo a verdade.
function metricOf(metric) {
  return METRICS[metric] || { label: String(metric || "?").toUpperCase(), word: String(metric || "?"), fmt: "none" };
}

function isIncident(e) {
  const mm = metricOf(e && e.metric);
  return !!mm.incident || (e && e.value == null && e.threshold == null);
}

/* Uma linha que se lê sozinha: o `label` que o motor já escreveu pra esse
   caso (incidente) ou "CPU crítica 97,0%" (limiar). Nunca "0 vs 0". */
function headline(e) {
  if (!e) return "";
  if (isIncident(e)) return e.label || metricOf(e.metric).word;
  const mm = metricOf(e.metric);
  const v = e.metric === "network" ? mbits(e.value) : e.value;
  return mm.word + " " + sevOf(e).word.toLowerCase() + " · " + fmtValue(mm.fmt, v);
}

const SEV = {
  info: { word: "info", cls: "sev-info", icon: "info" },
  warning: { word: "ATENÇÃO", cls: "sev-warning", icon: "warn" },
  critical: { word: "CRÍTICO", cls: "sev-critical", icon: "crit" },
};

const STATUS_WORD = { open: "aberta", addressing: "em correção", resolved: "resolvida", dismissed: "descartada" };

// outcome de uma linha `resolution` do events.jsonl (tutor.py)
const OUTCOME_WORD = { fixed: "resolveu", not_fixed: "não resolveu", dismissed: "descartada" };

/* A `fonte` que o `fix --plan` devolve (kbstore.LAYER_NAME) diz de onde veio o
   conselho, e isso é informação útil: base local responde na hora e já foi
   validada nesta máquina; `modelo` é inferência do motor local, e o tutorial
   avisa em vez de fingir que é conhecimento curado. */
const FONTES = {
  "kb:fingerprint": { word: "base local · mesma anomalia", cls: "is-local", icon: "shield" },
  "kb:causa": { word: "base local · mesma causa", cls: "is-local", icon: "shield" },
  "kb:metrica": { word: "base local · catálogo da métrica", cls: "is-local", icon: "shield" },
  "modelo": { word: "motor local · inferência", cls: "is-ia", icon: "terminal" },
};

function fonteOf(fonte) {
  return FONTES[fonte] || { word: fonte || "base local", cls: "is-local", icon: "shield" };
}

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
  plan: null,     // resposta do `fix --plan`: { options, fonte, camada, event_id }
  kill: null,     // modal aberto: { pid }
  busy: null,     // comando em voo: "kill" | "daemon" | "refresh" | ...
  error: null,    // ultima falha do motor, pra dizer em vez de fingir
  focus: null,    // seletor do elemento focado: o re-render nao pode roubar o teclado
  dataRoot: "",   // onde mora o .sentinel/ desta instancia (disse o host)
  dataRootFrom: "",
  hasData: false, // a primeira resposta do motor chegou? (antes dela nao ha numero a pintar)
  killed: [],
  newId: null,
};

/* ---------------- util ---------------- */

const $ = function (sel) { return document.querySelector(sel); };

/* O territorio que o motor respondeu (`M.territory`) e a autoridade sobre onde
 * o arquivo esta; `state.dataRoot` e o que o host disse antes da primeira
 * resposta, e a raiz dele nao tem `.sentinel` colado. Reconstruir o caminho a
 * partir da raiz era como o log mostrava `C:\x\.sentinel\.sentinel\daemon.log`
 * sempre que host e CLI divergissem sobre a pasta. */
function territoryOf() {
  if (M && M.territory) return String(M.territory);
  return state.dataRoot ? state.dataRoot + "\\.sentinel" : "";
}

/* Um PID sem nome e real (o Windows recusa o nome de um processo que acabou de
 * morrer no meio da varredura). Celula em branco faria a pessoa achar que a
 * tabela quebrou, e "Encerrar ?" no modal e pior que dizer o que se sabe. */
function nameOf(p) { return p.name || "(sem nome)"; }

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
  if (!iso) return "—";
  const dt = new Date(iso);
  if (isNaN(dt.getTime())) return "—";
  const p = function (n) { return (n < 10 ? "0" : "") + n; };
  return p(dt.getHours()) + ":" + p(dt.getMinutes()) + ":" + p(dt.getSeconds());
}

function uptime(fromIso) {
  const t = Date.parse(fromIso);
  if (!fromIso || isNaN(t)) return "—";
  const s = Math.max(0, Math.round((nowMs() - t) / 1000));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return (h > 0 ? h + " h " : "") + m + " min";
}

function num(v, dec) {
  const d = dec === undefined ? 1 : dec;
  return Number(v).toFixed(d).replace(".", ",");
}

function fmtValue(kind, v) {
  // `none` e a forma dos incidentes e de qualquer grandeza que nao e
  // percentual: um "0,0%" inventado ali seria a pagina falando numero que o
  // motor nunca mediu.
  if (kind === "none" || v === null || v === undefined) return "—";
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

/* Um aviso vive alguns segundos, nao ate o proximo repaint: toda acao que
 * responde (kill, daemon, desfecho) chama `refresh()` logo depois de `notice()`,
 * e o render dessa resposta apagava a frase que dizia se a acao deu certo. A
 * pessoa clicava "Encerrar agora" e a janela ficava muda exatamente sobre o
 * resultado. */
const NOTICE_MS = 12000;

function notice(html, kind) {
  state.pending = { html: html, kind: kind || "info", until: Date.now() + NOTICE_MS };
}

function slotHtml(fallback) {
  if (state.pending && state.pending.until > Date.now()) {
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
  const d = M.daemon || {};
  // Com o motor ligado o que vale é o pidfile lido pelo Python; o `killed` só
  // existe para a demonstração poder parar um daemon de mentira.
  if (state.engineAvailable) return !!d.running;
  return !!(d.running && state.killed.indexOf(d.pid) < 0);
}

function daemonPaused() {
  return !!(M.daemon && M.daemon.paused);
}

function renderTitlebar() {
  const live = daemonLive();
  const paused = live && daemonPaused();
  const pill = $("#daemon-pill");
  pill.className = "state-pill " + (paused ? "is-paused" : live ? "is-live" : "is-dead");
  pill.innerHTML = '<span class="led" aria-hidden="true"></span>' +
    (paused ? "PAUSADA" : live ? "VIVO" : "PARADO");
  // O estado tem de se explicar parado sobre ele: "PAUSADA" sem causa vira
  // enigma, e quem abre a janela depois de um `pause` não viu o comando.
  pill.title = paused
    ? "Daemon vivo, mas sem registrar anomalias novas — o botão “Vigília” da Visão geral retoma."
    : live
      ? "Daemon amostrando e gravando em .sentinel/events.jsonl."
      : "Sem daemon: nada é medido sozinho. A janela ainda lê o que já está em disco.";
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
  if (awaitingFirstData()) {
    $("#statusbar-left").innerHTML = "<b>conectando ao motor</b>" +
      '<span class="sep">·</span>' + esc(state.dataRoot || ".");
    $("#statusbar-right").innerHTML = "100% local, sem telemetria";
    return;
  }
  const s = M.sample || {};
  const live = daemonLive();
  $("#statusbar-left").innerHTML =
    "<b>" + (state.error ? "motor sem resposta" : live ? (daemonPaused() ? "vigília pausada" : "vigilando") : "daemon parado") + "</b>" +
    '<span class="sep">·</span>amostra ' + esc(clock(s.ts)) +
    '<span class="sep">·</span>pid ' + (live && M.daemon ? (M.daemon.pid || "—") : "—") +
    '<span class="sep">·</span>' + (function () {
      const n = openEvents().length;
      return n + (n === 1 ? " anomalia aberta" : " anomalias abertas");
    })();
  $("#statusbar-right").innerHTML = "100% local, sem telemetria" +
    '<span class="sep">·</span>Sentinel v' + esc(M.version || "0.1.0");
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
  // As duas listas do topo podem vir vazias (daemon sem psutil, primeira
  // amostra ainda sem ranking): um [0].name aqui derrubaria a pagina inteira.
  const lead = function (list, fallback) {
    return list && list.length ? list[0].name : fallback;
  };
  // Quatro medidores, como o DESIGN manda: I/O e a ocupacao do volume vivem
  // no rodape do DISCO (e um gargalo do mesmo instrumento), nao viram um
  // quinto medidor que deixaria buraco na grade.
  return [
    { key: "cpu", name: "CPU", kind: "pct", value: s.cpu_percent, max: 100, thr: t.cpu, series: "cpu", lead: lead(s.top_cpu, "sem leitura de processo") },
    { key: "ram", name: "RAM", kind: "pct", value: s.ram_percent, max: 100, thr: t.ram, series: "ram", lead: lead(s.top_mem, "sem leitura de processo") },
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
  const s = M.series[seriesKey] || { points: [] };
  const pts = s.points || [], n = pts.length;
  // Um ponto nao e tendencia: desenhar linha entre "nada" e a primeira
  // amostra faria historico do que ainda nao existe.
  if (n < 2) {
    return '<svg class="spark is-empty" viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">' +
      '<line class="spark-line" x1="0" y1="29" x2="100" y2="29" /></svg>';
  }
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
  const mm = metricOf(e.metric);
  const incident = isIncident(e);
  // Um incidente nao tem "valor contra limiar" nem processo do topo: o que
  // cabe na linha e a frase que o motor escreveu (label) e a contagem.
  const v = incident ? "—" : fmtValue(mm.fmt, e.metric === "network" ? mbits(e.value) : e.value);
  const who = incident
    ? (e.label || mm.word)
    : (e.top_processes.length ? nameOf(e.top_processes[0]) : "sem alvo");
  return '<button class="ev-row' + (e.id === state.sel ? " is-sel" : "") +
    (e.id === state.newId ? " is-new" : "") + '" data-ev="' + esc(e.id) + '">' +
    '<span class="sev ' + s.cls + '">' + ICON[s.icon] + "</span>" +
    "<span><span class=\"ev-metric\">" + esc(incident ? mm.word : mm.label) + "</span>" +
    '<span class="ev-meta">' + esc(who) +
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
        '<td><span class="pname">' + esc(nameOf(p)) + "</span>" +
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
    ICON.power + "Encerrar " + esc(nameOf(top)) + "…</button>";
}

/* A "assinatura" de um incidente: o que o distingue de outro da mesma
   especie. crash → codigo da excecao e modulo; orphan_tree → o pai que morreu
   e quantos ficaram; stall → os sinais que dispararam. Vem do `detail`
   gravado pelo motor, nunca de conta feita aqui. */
function signature(e) {
  const d = e.detail || {};
  if (e.metric === "app_failure") {
    const bits = [];
    if (d.exception_code) bits.push("exceção " + d.exception_code);
    if (d.module) bits.push("em " + d.module);
    if (!bits.length && d.kind === "hang") bits.push("parou de responder (Windows o fechou)");
    if (d.report_id) bits.push("report " + d.report_id);
    return { app: d.app, pid: d.pid, text: bits.join(" · ") || "sem código de exceção no evento" };
  }
  if (e.metric === "orphan_tree") {
    const parent = d.parent || {};
    return {
      text: (parent.name || "?") + " (pid " + parent.pid + ") saiu deixando " +
        (d.tree_size || 0) + " processo(s)",
      count: d.orphan_count,
    };
  }
  if (e.metric === "stall") {
    const sig = (d.signals || []).join(" + ") || "sinais não nomeados";
    const m = d.measured || {};
    return { text: sig + " · paginção " + num(m.swap_percent || 0, 1) + "% · I/O " + num(m.io_busy_percent || 0, 1) + "%" };
  }
  return { text: e.label || "—" };
}

function orphanTreeTable(tree) {
  return '<table class="tbl"><thead><tr><th>PID</th><th>PPID</th><th>Processo</th>' +
    '<th class="r">Profundidade</th></tr></thead><tbody>' +
    tree.map(function (row) {
      return '<tr><td class="pid">' + row.pid + "</td><td class=\"pid\">" + row.ppid + "</td>" +
        '<td><span class="pname">' + "· ".repeat(row.depth) + esc(row.name) + "</span></td>" +
        '<td class="meas r">' + row.depth + "</td></tr>";
    }).join("") + "</tbody></table>";
}

function renderDetail(e) {
  if (!e) {
    return '<div class="empty">' + ICON.alert +
      '<div class="empty-t">Selecione uma anomalia</div>' +
      "Aqui aparecem valor contra limiar, janela sustentada e os processos do topo.</div>";
  }
  const mm = metricOf(e.metric);
  const incident = isIncident(e);
  const isNet = e.metric === "network";
  const val = fmtValue(mm.fmt, isNet ? mbits(e.value) : e.value);
  const thr = fmtValue(mm.fmt, isNet ? mbits(e.threshold) : e.threshold);
  const s = sevOf(e);
  const procs = (e.top_processes || []).map(function (p) { return Object.assign({}, p); });
  const tree = (e.detail && e.detail.tree) || [];
  const res = state.resolutions.filter(function (r) { return r.ref === e.id; });
  const settled = e.status === "resolved" || e.status === "dismissed";
  const sig = incident ? signature(e) : null;
  // Um incidente nao tem processo mais caro na amostra: oferecer "Encerrar"
  // para um PID que nao esta ali seria a pagina mentindo.
  const canKill = !incident && !isNet && procs.length > 0;
  const actions = settled
    ? '<span class="src">nada a fazer — anomalia ' +
      esc(e.status === "resolved" ? "resolvida" : "descartada") + "</span>"
    : '<button class="btn btn-primary" data-tutor="' + esc(e.id) + '">' + ICON.book + "Corrigir</button>" +
      (isNet
        ? '<span class="src">rede: nenhuma ação automática — é contexto, não defeito</span>'
        : canKill ? killButton(e) : '<span class="src">sem alvo para encerrar nesta evidência</span>') +
      '<button class="btn btn-ghost" data-dismiss="' + esc(e.id) + '">Descartar</button>';

  return '<div class="panel"><div class="panel-head"><span class="panel-title">' + esc(e.id) + "</span>" +
    '<span class="badge">' + esc(STATUS_WORD[e.status]) + "</span></div>" +
    '<div class="panel-body">' +
    '<dl class="kv">' +
    (incident
      ? '<dt>O que houve</dt><dd>' + esc(e.label || mm.word) + "</dd>" +
        '<dt>Espécie</dt><dd>' + esc(mm.word) + ' <span class="src">metric=' + esc(e.metric) + "</span></dd>" +
        '<dt>Assinatura</dt><dd>' + esc(sig.text) +
        (sig.app ? ' <span class="src">app=' + esc(sig.app) + (sig.pid ? " pid=" + sig.pid : "") + "</span>" : "") + "</dd>"
      : '<dt>Métrica</dt><dd>' + esc(mm.word) + ' <span class="src">metric=' + esc(e.metric) + "</span></dd>" +
        '<dt>Valor</dt><dd><span class="num">' + esc(val) + '</span> <span class="src">vs limiar ' + esc(thr) + "</span></dd>" +
        "<dt>Sustentada</dt><dd><span class=\"num\">" + e.window.samples + " amostras em " +
        num(e.window.span_s, 1) + " s</span> <span class=\"src\">· " +
        num(e.window.span_s / e.window.samples, 1) + " s por amostra</span></dd>") +
    '<dt>Severidade</dt><dd><span class="sev-word ' + s.cls + '">' + ICON[s.icon] + esc(s.word) + "</span></dd>" +
    "<dt>Repetições</dt><dd><span class=\"num\">" + e.occurrences + "</span>" +
    ' <span class="src">· última ' + esc(relTime(e.ts_last)) + "</span></dd>" +
    "<dt>Fingerprint</dt><dd class=\"mono\">" + esc(e.fingerprint) + "</dd>" +
    "<dt>Aberto em</dt><dd class=\"mono\">" + esc(clock(e.ts)) + " · " + esc(relTime(e.ts)) + "</dd>" +
    "</dl>" +
    (tree.length
      ? '<div class="panel-title" style="margin:18px 0 8px">ÁRVORE QUE FICOU</div>' +
        orphanTreeTable(tree) +
        '<p class="src" style="margin-top:6px">pid/ppid/nome como o motor gravou — sem consumo inventado.</p>'
      : "") +
    (procs.length
      ? '<div class="panel-title" style="margin:18px 0 8px">TOPO DA AMOSTRA</div>' +
        renderProcTable(procs, canKill && !settled)
      : "") +
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

/* `optionsFor(metric)` e o catalogo do painel (M.kb). O tutorial nao usa
   catalogo: com motor ligado ele mostra a resposta do `fix --plan`, que ja
   saiu da base local com o ranking desta maquina. */
function optionsFor(metric) { return M.kb[metric] || []; }

function currentOptions() {
  if (state.engineAvailable) return state.plan ? (state.plan.options || []) : [];
  const e = eventById(state.tutor ? state.tutor.eventId : null);
  return optionsFor(e ? e.metric : "");
}

function startTutor(eventId) {
  const e = eventById(eventId);
  if (!e) return;
  // Nada de mutear status local: `addressing` é o tutor.run_cycle do terminal
  // que escreve, e a tela que inventa "em correção" sem o disco dizer é a
  // mesma tela que depois desmente o próprio número no primeiro refresh.
  state.tutor = { eventId: eventId, index: 0, tried: [], status: "asking", fonte: "", camada: 0 };
  state.plan = null;
  state.sel = eventId;
  go("tutorial");
  if (!state.engineAvailable) return;

  state.busy = "plan";
  render();
  engineCall("fix-plan", { id: eventId }, function (r) {
    state.busy = null;
    if (!r.ok) {
      state.error = r.error;
      notice("<b>O motor não respondeu o tutorial:</b> " + esc(r.error), "bad");
      render();
      return;
    }
    state.plan = r.result;
    state.tutor.fonte = r.result.fonte;
    state.tutor.camada = r.result.camada;
    if (!(r.result.options || []).length) {
      notice("A base local não tem opção para esta anomalia ainda. O catálogo " +
        "cresce com o seu feedback nas próximas rodadas — nada aqui foi inventado.", "warn");
    }
    render();
  });
}

/* 'Sim' / 'próxima' / 'pular' viram o mesmo portão do terminal:
   `fix <id> --resolve <desfecho>`. Duas coisas que o bridge não pode
   improvisar:

   - a `key` da opção volta do `--plan` em vez de repropor: com o motor local
     ligado a fila poderia mudar, e o "não funcionou" seria gravado contra um
     conselho que ninguém viu;
   - `--option` é 1-based na linha de comando e 0-based no events.jsonl
     (`cli.py` faz o -1). Mandamos o número que o usuário vê.

   `not_fixed` com opção é o meio do caminho (desfecho na base, anomalia
   continua); `not_fixed` sem opção é a fila esgotada, e aí o motor fecha. */
function onFix(kind) {
  const t = state.tutor;
  if (!t) return;
  // Um desfecho por vez: dois cliques rápidos gravariam duas resoluções contra
  // o mesmo evento, e a segunda anularia a primeira no ranking da base.
  if (state.busy) return;
  const e = eventById(t.eventId);
  if (!e) { state.tutor = null; go("anomalias"); return; }
  const opts = currentOptions();

  if (state.engineAvailable) { engineFix(kind, e, t, opts); return; }

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
      '<span class="inline-code">events.jsonl</span> — quem grava é o motor.', "warn");
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

function engineFix(kind, e, t, opts) {
  const last = t.index >= opts.length - 1;
  const opt = opts[t.index] || null;
  const call = {
    id: e.id,
    key: opt && opt.key ? opt.key : "",
    source: t.fonte || "base local",
  };
  if (kind === "yes") {
    call.outcome = "fixed";
    call.option = t.index + 1;
    call.note = "usuario validou a opcao";
  } else if (kind === "skip") {
    call.outcome = "dismissed";
    call.option = t.index + 1;
    call.note = "usuario pulou/descartou";
  } else {
    call.outcome = "not_fixed";
    call.note = "opcao tentada sem resultado";
    if (last) delete call.option;  // fila esgotada: e o que fecha o episodio
  }

  state.busy = kind;
  render();
  engineCall("fix-resolve", call, function (r) {
    state.busy = null;
    if (!r.ok) {
      notice("<b>O motor recusou o desfecho:</b> " + esc(r.error), "bad");
      render();
      return;
    }
    const res = r.result;
    if (res.ok === false) {
      notice("<b>O motor recusou o desfecho:</b> " + esc(res.error), "bad");
      render();
      return;
    }
    e.status = res.status;
    if (kind === "yes") {
      t.tried.push({ i: t.index, outcome: "fixed" });
      t.status = "resolved";
    } else if (kind === "skip") {
      state.tutor = null;
    } else {
      t.tried.push({ i: t.index, outcome: "not_fixed" });
      if (!last) t.index += 1;
    }
    notice(aprenderMensagem(res, kind), res.tally ? "ok" : "info");
    // A tela segue o disco, nao o contrario: o proximo `metrics` traz a linha
    // `resolution` que o Python acabou de escrever.
    refresh();
    if (kind === "skip") go("anomalias"); else render();
  });
}

/* O que o ciclo aprendeu, dito com as palavras do motor — `tally` so e true
   quando a opcao tinha `key` e foi contada na base local. */
function aprenderMensagem(res, kind) {
  const fim = {
    fixed: "Resolução gravada em " + '<span class="inline-code">events.jsonl</span>',
    dismissed: "Anomalia descartada — o evento continua no histórico pelo fingerprint",
    not_fixed: res.option_index == null
      ? "Fila esgotada: o motor fechou o episódio como descartado"
      : "Contado como não-resolveu; a próxima opção da fila sobe se já funcionou aqui",
  }[kind === "yes" ? "fixed" : kind === "skip" ? "dismissed" : "not_fixed"];
  const base = res.tally
    ? " · <b>aprendido</b>: este desfecho pesa no ranking da próxima rodada desta anomalia"
    : " · sem <span class=\"inline-code\">key</span> na opção, nada foi contado na base";
  return "<b>" + esc(fim) + "</b>" + base;
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

/* Uma linha de justificativa do tutorial: o kicker em mono miúdo e o texto em
   corpo. `render_option()` do terminal imprime as mesmas três perguntas nesta
   ordem — o que fazer, por que mexe no problema, como saber que funcionou, o
   que doi — porque é a ordem em que uma decisão se toma. */
function whyLine(k, text, cls) {
  return '<div class="tutor-line' + (cls || "") + '"><div class="tutor-k">' + esc(k) + "</div>" +
    '<p class="tutor-t">' + esc(text) + "</p></div>";
}

function optionActions(opt, e) {
  const a = opt.action || null;
  if (!a) return "";
  if (a.type === "kill_top_process") {
    return '<div class="btn-row" style="margin-top:6px">' + killButton(e) + "</div>";
  }
  if (a.type === "open_settings") {
    return '<div class="btn-row" style="margin-top:6px"><button class="btn btn-ghost" data-open="' +
      esc(a.target) + '">' + ICON.open + "Onde abrir isto</button></div>";
  }
  // tipo que a pagina nao conhece (o motor local pode nomear outro): os passos
  // acima ja dizem o que fazer, e inventar botao seria a GUI falando de si.
  return '<p class="src" style="margin-top:6px">ação sugerida: ' + esc(a.type) +
    (a.target ? " · " + esc(a.target) : "") + " — o passo a passo acima é o que vale.</p>";
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
  if (!e) {
    // A tela segue o disco: se o evento saiu da fila (resolvido por outra
    // janela, ou um `prune`), insistir nele seria tutorial de anomalia falsa.
    state.tutor = null;
    state.plan = null;
    go("anomalias");
    return;
  }
  const opts = currentOptions();
  const mm = metricOf(e.metric);
  const src = fonteOf(state.engineAvailable ? (t.fonte || "") : "kb:metrica");
  const loading = state.engineAvailable && (state.busy === "plan" || !state.plan);
  const empty = !loading && !opts.length;
  const exhausted = !loading && !empty && t.index >= opts.length;
  const opt = exhausted || loading || empty ? null : opts[t.index];
  let body;

  if (t.status === "resolved") {
    body = '<div class="notice is-ok">' + ICON.check +
      "<div><b>Resolvido.</b> Resolução gravada contra " +
      '<span class="inline-code">' + esc(e.id) + "</span> usando a opção " +
      (t.tried.length ? t.tried[t.tried.length - 1].i + 1 : opts.length) +
      ", fonte <b>" + esc(src.word) + "</b>." +
      (state.engineAvailable
        ? ' <span class="src">linha <span class="inline-code">resolution</span> escrita em <span class="inline-code">events.jsonl</span></span>'
        : ' <span class="src">demonstração: nada foi escrito em .sentinel/</span>') +
      "</div></div>" +
      '<div class="btn-row" style="margin-top:16px"><button class="btn btn-ghost" data-goto="anomalias">Voltar às anomalias</button></div>';
  } else if (loading) {
    body = '<div class="busy"><span class="busy-dot"></span>Consultando a base local — ' +
      esc(e.id) + "…</div>" +
      '<p class="src" style="margin-top:8px">As camadas 1-3 (esta máquina já viu essa anomalia?) respondem ' +
      "antes de qualquer inferência; o motor local só é chamado se elas não souberem.</p>";
  } else if (empty) {
    body = '<div class="empty">' + ICON.book + '<div class="empty-t">A base local não tem opção para isto</div>' +
      "Nada foi inventado para preencher o vazio. O catálogo cresce com o seu feedback e com o " +
      (state.engineAvailable ? "motor local" : "motor local (que esta demonstração não chama)") +
      " — e a anomalia continua no histórico pelo <span class=\"inline-code\">fingerprint</span>.</div>" +
      '<div class="btn-row" style="margin-top:14px"><button class="btn btn-ghost" data-goto="anomalias">Voltar às anomalias</button></div>';
  } else if (exhausted) {
    body = '<div class="notice is-warn">' + ICON.warn +
      "<div><b>Fim da fila.</b> As " + opts.length + " opções da base local para " +
      esc(mm.word) + " não resolveram. O motor grava uma resolução " +
      '<span class="inline-code">not_fixed</span> e fecha o evento como ' +
      '<span class="inline-code">dismissed</span> — a anomalia continua no histórico pelo ' +
      '<span class="inline-code">fingerprint</span>, e na próxima vez o ' +
      '<span class="inline-code">motor local</span> pode acrescentar opções novas.</div></div>' +
      '<div class="btn-row" style="margin-top:16px"><button class="btn btn-ghost" data-retry="1">Repetir do início</button>' +
      '<button class="btn btn-ghost" data-goto="anomalias">Voltar às anomalias</button></div>';
  } else {
    body = '<div class="tutor-head"><span class="tutor-count">OPÇÃO ' + (t.index + 1) + " DE " + opts.length + "</span>" +
      '<span class="badge ' + src.cls + '">' + ICON[src.icon] + esc(src.word) + "</span>" +
      (state.engineAvailable ? "" : '<span class="badge">demonstração: catálogo de mock.js</span>') +
      (opt.reversible === false ? '<span class="badge is-ia">' + ICON.warn + "sem volta</span>" : "") +
      "</div>" +
      '<h2 class="tutor-title">' + esc(opt.title) + "</h2>" +
      (opt.why ? whyLine("por que isto resolve", opt.why) : "") +
      '<ol class="steps">' + (opt.steps || []).map(function (s) { return "<li>" + esc(s) + "</li>"; }).join("") + "</ol>" +
      (opt.proof ? whyLine("como você sabe que funcionou", opt.proof) : "") +
      (opt.risk ? whyLine("risco · " + (opt.reversible === false ? "sem volta" : "reversível"), opt.risk, " is-risk") : "") +
      optionActions(opt, e);
  }

  const ask = (t.status === "resolved" || exhausted || loading || empty) ? "" :
    (state.busy && state.busy !== "plan"
      ? '<div class="ask"><span class="src">gravando o desfecho no motor…</span></div>'
      : '<div class="ask"><span class="ask-q">Funcionou?</span>' +
        '<button class="btn btn-primary" data-fix="yes">' + ICON.check + "Sim, resolveu</button>" +
        '<button class="btn" data-fix="next">Não, próxima</button>' +
        '<button class="btn btn-ghost" data-fix="skip">Pular tudo</button></div>');

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
    '<p class="view-sub">' + esc(headline(e)) + " · " + esc(sevOf(e).word) + " · evento " + esc(e.id) +
    (territoryOf() ? '<span class="src"> · território ' + esc(territoryOf()) + "</span>" : "") +
    "</p></div>" +
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
  const busy = !!state.busy;
  host.innerHTML = '<div class="view">' +
    '<div class="view-head"><div><h1 class="view-title">Visão geral</h1>' +
    '<p class="view-sub">O daemon amostra a cada ' + num((M.daemon && M.daemon.interval_s) || 2, 1) +
    " s e grava anomalia em " +
    '<span class="inline-code">.sentinel/events.jsonl</span>. Isto é o que ele viu.</p></div>' +
    '<div class="view-tools">' +
    (state.engineAvailable && daemonLive()
      ? '<button class="btn btn-sm btn-ghost" data-pause="1"' + (busy ? " disabled" : "") + ">" +
        (daemonPaused() ? ICON.play + "Retomar vigilância" : ICON.pause + "Pausar vigilância") + "</button>"
      : "") +
    '<button class="btn btn-sm btn-ghost" data-daemon="1"' + (busy ? " disabled" : "") + ">" + ICON.power +
    (daemonLive() ? "Parar daemon" : "Iniciar daemon") + "</button>" +
    '<button class="btn btn-sm btn-ghost" data-refresh="1">' + ICON.refresh + "Atualizar</button>" +
    "</div></div>" +
    slotHtml(M.demo ? '<div class="notice is-warn">' + ICON.warn + "<div>" + DEMO_BANNER + "</div></div>" : "") +
    (state.error ? '<div class="notice is-bad">' + ICON.crit + "<div><b>Última falha do motor:</b> " +
      esc(state.error) + "</div></div>" : "") +
    '<div class="hud">' +
    hudCell("DAEMON", daemonLive()
      ? (daemonPaused()
        ? '<span class="hud-v is-paused">pausada</span>'
        : '<span class="hud-v is-live">vivo</span>')
      : '<span class="hud-v is-dead">parado</span>',
      "pid " + ((M.daemon && M.daemon.pid) || "—")) +
    hudCell("AMOSTRA", '<span class="hud-v">' + esc(clock(s.ts)) +
      ' <span class="unit">· ' + esc(relTime(s.ts)) + "</span></span>",
      daemonLive()
        ? "batimento do daemon " + esc(clock(M.daemon.last_heartbeat))
        : "medida por esta janela; o daemon está parado") +
    hudCell("VIGÍLIA", '<span class="hud-v">' + esc(uptime(M.daemon.started_ts)) + "</span>",
      M.daemon.started_ts ? "desde " + esc(clock(M.daemon.started_ts)) : "o daemon não subiu nesta sessão") +
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
    '<div class="panel-body" style="padding:4px 6px 8px">' + renderProcTable((s.top_cpu || []).slice(0, 4), false) + "</div>" +
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
  const terr = territoryOf();
  host.innerHTML = '<div class="view"><div class="view-head"><div>' +
    '<h1 class="view-title">Log do daemon</h1>' +
    '<p class="view-sub">Fio de <span class="inline-code">.sentinel/daemon.log</span>: um <span class="inline-code">tick</span> a cada 2 s, uma linha <span class="inline-code">ANOMALIA</span> quando o detector dispara e uma <span class="inline-code">ALIVIO</span> por decisão do degrau 1.</p></div>' +
    '<div class="view-tools"><button class="btn btn-sm btn-ghost" data-refresh="1">' + ICON.refresh + "Recarregar</button></div></div>" +
    slotHtml("") +
    '<div class="panel"><div class="panel-head"><span class="panel-title">' + state.log.length + " LINHAS · O RABO DO ARQUIVO</span>" +
    '<span class="src">' + esc(terr ? terr + "\\daemon.log" : "gui/sentinel/mock.js") + "</span></div>" +
    '<div class="panel-body" style="padding:10px 6px 10px 12px">' +
    (state.log.length ? '<div class="log-panel" style="border:none;background:transparent;max-height:none;padding:0">' +
      logLines(200) + "</div>"
      : '<div class="empty">' + ICON.terminal + '<div class="empty-t">O arquivo ainda não existe</div>' +
        "Nenhum daemon gravou batimento neste território. Inicie um no botão acima e volte aqui.</div>") +
    "</div></div>" +
    '<p class="view-sub" style="margin-top:12px">O motor lê as últimas linhas e não rotaciona o arquivo por ' +
    "conta própria: quando ele pesar, apague <span class=\"inline-code\">daemon.log</span> — o daemon recria na " +
    "amostra seguinte, e o histórico que importa está em <span class=\"inline-code\">events.jsonl</span>.</p></div>";
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
    ICON.terminal + '<div>A única saída de rede é a pergunta a um <span class="inline-code">motor local</span> (loopback) que gera opções novas — disparado por você numa correção, nunca pelo daemon.</div>',
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
    '<span class="inline-code">' +
    esc(territoryOf() ? territoryOf() + "\\" : "<pasta do Sentinel>\\.sentinel\\") +
    "</span> (events.jsonl, daemon.log, config.json, kb.db). " +
    (state.engineAvailable && state.dataRootFrom
      ? "Esta janela vigia o território escolhido por: " + esc(state.dataRootFrom) + ". "
      : "") +
    "Apagar é seguro: o daemon recria.</p></div>";
}

/* ---------------- modal de confirmação ---------------- */

/* O alvo do modal, procurado onde ele foi clicado: a tabela de processos (que
   o motor já devolve com `children`, `protected` e `self`) e, se não estiver
   lá, o topo da anomalia que abriu o tutorial. Nada de nome inventado: sem
   leitura, o que se mostra é o PID cru. */
function killTarget(pid) {
  const lists = [M.processes || []];
  state.events.forEach(function (e) { lists.push(e.top_processes || []); });
  for (let i = 0; i < lists.length; i++) {
    for (let j = 0; j < lists[i].length; j++) {
      if (lists[i][j].pid === pid) return lists[i][j];
    }
  }
  return { pid: pid, name: "processo " + pid, cpu: 0, rss_mb: 0, children: 0 };
}

function renderModal() {
  const root = $("#modal-root");
  if (!state.kill) { root.innerHTML = ""; return; }
  const p = killTarget(state.kill.pid);
  const n = p.children || 0;
  const blocked = procFlags(p);
  root.innerHTML =
    '<div class="overlay" data-close="1"><div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">' +
    '<div class="modal-head"><h2 class="modal-title" id="modal-title">Encerrar ' + esc(nameOf(p)) + "?</h2></div>" +
    '<div class="modal-body"><dl class="kv">' +
    '<dt>PID</dt><dd><span class="num">' + p.pid + "</span></dd>" +
    '<dt>CPU / RSS</dt><dd><span class="num">' + num(p.cpu, 1) + "% · " + esc(rss(p.rss_mb)) + "</span></dd>" +
    "<dt>Dependentes</dt><dd>" + (n
      ? '<span class="num">' + n + (n === 1 ? " processo filho" : " processos filhos") + "</span>" +
        ' <span class="src">contados pelo motor; os nomes dele não estão nesta leitura</span>'
      : "nenhum filho vivo nesta amostra") + "</dd>" +
    "</dl>" +
    '<div class="tree">' + esc(nameOf(p)) + " (" + p.pid + ")" +
    (n ? "\n└─ " + n + (n === 1 ? " filho direto, que fica órfão" : " filhos diretos, que ficam órfãos") : "") +
    "</div>" +
    '<p style="margin-top:12px">Isto encerra o processo e não desfaz nada dele que já esteja em disco. ' +
    "Salve o que estiver aberto.</p>" +
    (n ? '<p class="src" style="margin-top:8px">Se você quer a árvore inteira, marque “inclusive os filhos” — ' +
      "o motor encerra cada um deles, e não só este PID.</p>" : "") +
    (blocked.protected || blocked.self
      ? '<p class="notice is-bad" style="margin-top:12px">' + ICON.crit + "<div><b>" +
        (blocked.self ? "Este é o próprio Sentinel" : "Processo protegido do Windows") +
        ".</b> O Python recusa antes de tocar, e a página não tem como contornar isso.</div></p>"
      : "") +
    '<p class="src" style="margin-top:8px">com o motor ligado, o Python revalida este PID contra a lista de proteção ' +
    "antes de tocar em qualquer coisa — e um serviço do Windows nunca morre por PID.</p>" +
    '</div><div class="modal-foot">' +
    (n ? '<label class="check"><input type="checkbox" id="kill-tree"' +
      (state.kill.tree ? " checked" : "") + ">Inclusive os " + n + " filhos</label>" : "") +
    '<button class="btn btn-ghost" data-close="1">Cancelar</button>' +
    '<button class="btn btn-primary" data-kill-go="' + p.pid + '"' +
    (blocked.protected || blocked.self ? " disabled" : "") + ">Encerrar agora</button>" +
    "</div></div></div>";
  const chk = root.querySelector("#kill-tree");
  if (chk) {
    chk.addEventListener("change", function () {
      state.kill.tree = chk.checked;
    });
  }
  const btn = root.querySelector("[data-kill-go]");
  if (btn && !btn.disabled) btn.focus();
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

/* Re-render perde o foco, e quem navega pelo teclado nas anomalias perceberia
   isso a cada 5 s. A marca é o atributo de ação do próprio botão: sobrevive ao
   innerHTML novo porque o elemento com a mesma chave continua existindo. */
const FOCUS_ATTRS = ["data-ev", "data-view", "data-goto", "data-back", "data-filter",
  "data-sev", "data-sort", "data-tutor", "data-fix", "data-retry", "data-open",
  "data-daemon", "data-pause", "data-refresh", "data-dismiss", "data-kill",
  "data-kill-go", "data-close"];

function focusMark() {
  const el = document.activeElement;
  if (!el || !el.hasAttribute) return null;
  for (let i = 0; i < FOCUS_ATTRS.length; i++) {
    const a = FOCUS_ATTRS[i];
    if (el.hasAttribute(a)) {
      const v = String(el.getAttribute(a)).replace(/"/g, "");
      if (v) return "[" + a + '="' + v + '"]';
    }
  }
  return null;
}

/* Antes da primeira resposta do motor não há o que pintar: mostrar o mock por
   meio segundo sob o rótulo "motor real" seria a janela mentindo uma vez por
   abertura. */
function awaitingFirstData() {
  return state.engineAvailable && !state.hasData;
}

function render() {
  const mark = focusMark();
  renderTitlebar();
  renderSidebar();
  renderStatusbar();
  const host = $("#content");
  host.innerHTML = "";
  if (awaitingFirstData()) viewLendo(host);
  else (VIEWS[state.view] || viewPainel)(host);
  renderModal();
  if (mark) {
    const el = document.querySelector(mark);
    if (el && el.focus) el.focus({ preventScroll: true });
  }
}

function viewLendo(host) {
  host.innerHTML = '<div class="view"><div class="view-head"><div>' +
    '<h1 class="view-title">Sentinel</h1>' +
    '<p class="view-sub">Lendo o território ' +
    '<span class="inline-code">' + esc(state.dataRoot || ".") + "</span></p></div></div>" +
    slotHtml("") +
    '<div class="panel"><div class="panel-body"><div class="busy"><span class="busy-dot"></span>' +
    "Primeira medição do motor — uma amostra honesta custa ~0,6 s, porque o psutil só " +
    "devolve uso real na segunda leitura.</div></div></div></div>";
}

function go(view) {
  state.view = view;
  // Trocar de secao e uma decisao nova da pessoa: o aviso anterior deixou de
  // ser sobre o que esta na tela.
  state.pending = null;
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
  if (d.retry) {
    state.tutor.index = 0;
    state.tutor.status = "asking";
    render();
    return true;
  }
  if (d.open) {
    // Abrir painel de configuração do Windows não é comando do motor: a página
    // mostra o caminho em vez de fingir que clicou por você.
    notice("O Sentinel não abre janelas do Windows por você. Abra " +
      "<b>" + esc(d.open === "storage"
        ? "Configurações → Sistema → Armazenamento"
        : "Gerenciador de Tarefas (Ctrl+Shift+Esc)") + "</b> e siga o passo acima.", "info");
    render();
    return true;
  }
  if (d.daemon) { engineDaemon(daemonLive() ? "stop" : "start"); return true; }
  if (d.pause) { engineDaemon(daemonPaused() ? "resume" : "pause"); return true; }
  if (d.refresh) {
    if (!state.engineAvailable) {
      demo("a amostra nova viria de <span class=\"inline-code\">sentinel metrics --json</span>.");
      render();
      return true;
    }
    sweepMark();
    refresh();
    return true;
  }
  if (d.dismiss) { engineDismiss(d.dismiss); return true; }
  if (d.kill) {
    const pid = parseInt(d.kill, 10);
    if (!isNaN(pid)) { state.kill = { pid: pid, tree: false }; render(); return true; }
    return false;
  }
  if (d.killGo) { engineKill(parseInt(d.killGo, 10)); return true; }
  if (d.close) { state.kill = null; render(); return true; }
  return false;
}

/* Os três caminhos que tocam o sistema passam todos pelo mesmo portão: um
   `engine-call`, a resposta do Python dita o texto, e o `refresh()` no fim faz
   a tela acompanhar o disco — nunca o contrário. */
function engineDaemon(action) {
  if (!state.engineAvailable) {
    if (action === "stop") state.killed.push(M.daemon.pid);
    else if (action === "start") state.killed = [];
    demo(action === "stop" ? "o daemon simulado parou; o de verdade é <span class=\"inline-code\">sentinel stop</span>."
      : action === "start" ? "o daemon simulado voltou; o de verdade é <span class=\"inline-code\">sentinel start</span>."
        : action === "pause" ? "a pausa de verdade escreve <span class=\"inline-code\">.sentinel/paused</span>, que o daemon lê a cada amostra."
          : "a retomada de verdade apaga <span class=\"inline-code\">.sentinel/paused</span>.");
    render();
    return;
  }
  if (state.busy) return;
  state.busy = "daemon:" + action;
  render();
  engineCall("daemon", { action: action }, function (r) {
    state.busy = null;
    if (!r.ok) { bridgeFail("o daemon não respondeu", r.error); return; }
    const res = r.result || {};
    if (res.ok === false) {
      notice("<b>O motor recusou:</b> " + esc(res.error || "sem motivo"), "bad");
      render();
      return;
    }
    notice(daemonMensagem(action, res), "ok");
    refresh();
  });
}

function daemonMensagem(action, res) {
  if (action === "start") {
    return res.started
      ? "<b>Daemon iniciado</b> (pid " + esc(res.pid) + "), gravando em " +
        '<span class="inline-code">' + esc(res.log || ".sentinel/daemon.log") + "</span>."
      : "Já havia um daemon vivo" + (res.warning ? " — " + esc(res.warning) : "") + ".";
  }
  if (action === "stop") {
    return res.stopped
      ? "<b>Daemon encerrado</b> (pid " + esc(res.pid) + "). Nada novo é medido até iniciar outro."
      : "Não havia daemon vivo para parar.";
  }
  if (action === "pause") {
    return "<b>Vigília pausada.</b> O daemon continua amostrando, mas não registra anomalia " +
      "nem age sozinho — nada é apagado do que já está em disco.";
  }
  return "<b>Vigília retomada.</b> O daemon volta a classificar e a gravar anomalias.";
}

function engineDismiss(id) {
  const e = eventById(id);
  if (!e) return;
  if (!state.engineAvailable) {
    e.status = "dismissed";
    recordResolution(e, "dismissed", null, "usuario pulou/descartou");
    demo("a linha <span class=\"inline-code\">outcome=dismissed</span> sairia de " +
      "<span class=\"inline-code\">sentinel fix &lt;id&gt; --resolve dismissed</span>; aqui só mudou a tela.");
    render();
    return;
  }
  if (state.busy) return;
  state.busy = "dismiss";
  render();
  engineCall("fix-resolve", {
    id: id, outcome: "dismissed", note: "descartada pela interface",
  }, function (r) {
    state.busy = null;
    if (!r.ok) { bridgeFail("a descartada não foi gravada", r.error); return; }
    const res = r.result || {};
    if (res.ok === false) {
      notice("<b>O motor recusou:</b> " + esc(res.error || "sem motivo"), "bad");
      render();
      return;
    }
    if (state.tutor && state.tutor.eventId === id) { state.tutor = null; state.plan = null; }
    notice("<b>Anomalia descartada.</b> O evento continua no histórico pelo " +
      '<span class="inline-code">fingerprint</span>, e o desfecho pesa no ranking da base local.', "ok");
    refresh();
  });
}

function engineKill(pid) {
  const tree = !!(state.kill && state.kill.tree);
  state.kill = null;
  if (!state.engineAvailable) {
    demo("encerrar um processo de verdade passa pelo guard do Python " +
      "(lista de proteção, sessão interativa, confirmação explícita).");
    render();
    return;
  }
  if (state.busy || isNaN(pid)) { render(); return; }
  state.busy = "kill";
  engineCall("kill", { pid: pid, tree: tree }, function (r) {
    state.busy = null;
    if (!r.ok) { bridgeFail("o pedido de encerramento falhou", r.error); return; }
    notice(killMensagem(r.result || {}), (r.result && r.result.ok) ? "ok" : "bad");
    refresh();
  });
  render();
}

/* A recusa é o caso mais importante desta resposta: é ela que prova que a
   guarda é do Python e não uma cortesia da página. */
function killMensagem(res) {
  if (res.refused) {
    return "<b>O motor recusou:</b> " + esc(res.refused) +
      " — a lista de proteção vale antes de qualquer confirmação da interface.";
  }
  const killed = (res.killed || []).join(", ");
  if (res.ok) {
    return "<b>Encerrado:</b> PID " + esc(killed || res.pid) + (res.tree ? " com a árvore de filhos" : "") + ".";
  }
  return "<b>Parcial:</b> encerrados " + esc(killed || "nenhum") + "; falharam " +
    esc((res.failed || []).join(", ") || "ninguém") +
    " (permissão negada, ou o processo já tinha morrido).";
}

const SEL = "[data-view],[data-ev],[data-goto],[data-back],[data-filter],[data-sev],[data-sort]," +
  "[data-tutor],[data-fix],[data-retry],[data-open],[data-daemon],[data-pause],[data-refresh]," +
  "[data-dismiss],[data-kill],[data-kill-go],[data-close]";

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

/* Uma chamada de motor = um pedido numerado + um callback na mesa.
 *
 * O host devolve o JSON do Python dentro de `result` SEM re-serializar (é a
 * regra que impede o ConvertTo-Json do PowerShell 5.1 de transformar array em
 * {"value":[…],"Count":N}), e o `request_id` volta igual para o callback
 * encontrar o dono. `engineFix`/`startTutor` já falam esta língua; daqui só
 * depende que o host ecoe o id.
 */
const bridge = { seq: 0, pending: {}, timeout_ms: 25000 };

function engineCall(cmd, args, cb) {
  const rid = "r" + (++bridge.seq);
  const payload = Object.assign({ cmd: cmd, request_id: rid }, args || {});
  if (!sendToHost("engine-call", payload)) {
    // Preview no browser: não há host. A resposta de erro é a mesma forma de
    // uma recusa real, então nenhuma chamada precisa de caminho especial.
    setTimeout(function () { cb({ ok: false, cmd: cmd, error: "sem ponte com o host (janela aberta em preview)" }); }, 0);
    return;
  }
  bridge.pending[rid] = cb;
  // Rede de segurança: o host já tem timeout próprio (15 s). Este cobre o host
  // morto no meio do pedido, que sem ele deixaria a tela em "gravando…" para
  // sempre.
  setTimeout(function () {
    if (!bridge.pending[rid]) return;
    delete bridge.pending[rid];
    cb({ ok: false, cmd: cmd, error: "o host não respondeu ao pedido " + cmd });
  }, bridge.timeout_ms);
}

function bridgeFail(what, err) {
  state.busy = null;
  state.error = String(err || "sem detalhes");
  notice("<b>" + esc(what) + ":</b> " + esc(state.error), "bad");
  render();
}

/* A resposta do `metrics --json` tem exatamente as formas do mock.js, então
 * trocar de fonte de dado é trocar o `M` inteiro e re-derivar o que a página
 * guarda por cópia (eventos, resoluções, log) — sem perder seleção nem filtro.
 */
function applyEngine(d) {
  M = d;
  state.hasData = true;
  state.events = (d.events || []).map(function (e) { return Object.assign({}, e); });
  state.resolutions = (d.resolutions || []).slice();
  state.log = (d.log || []).slice();
  if (!eventById(state.sel)) state.sel = state.events.length ? state.events[0].id : null;

  // O tutorial acompanha o disco: se a anomalia saiu da fila enquanto a janela
  // estava aberta (resolveu em outro lugar, ou um `prune`), o ciclo sai dela em
  // vez de tutoriar evento que já não está aberto.
  const t = state.tutor;
  if (t && t.status !== "resolved") {
    const e = eventById(t.eventId);
    if (!e || e.status === "dismissed") { state.tutor = null; state.plan = null; }
    else if (e.status === "resolved") t.status = "resolved";
  }
}

/* `metrics` é a única chamada periódica: ela já traz amostra, série, eventos,
 * resoluções, processos e log. Um `status`+`events`+`log` separados custariam
 * três processos Python por atualização para desenhar a mesma tela. */
function refresh(cb) {
  if (!state.engineAvailable) { if (cb) cb(); return; }
  engineCall("metrics", { history: 90, limit: 80, log: 200 }, function (r) {
    if (!r.ok) {
      state.error = String(r.error);
    } else if (r.result && r.result.ok === false) {
      // rc 0 com ok:false é o "sem sensor" do CLI: é dado, não falha da ponte.
      state.error = String(r.result.error);
    } else {
      state.error = null;
      applyEngine(r.result);
    }
    if (cb) cb(); else render();
  });
}

/* 5 s ≈ duas voltas do daemon (2 s por amostra). Mais que isso a janela vira
 * outra aba; menos, e o custo de importar o interpretador Python por
 * atualização pesa mais que o que se olha. */
function startPolling() {
  setInterval(function () {
    if (!state.engineAvailable || !isHosted()) return;
    // Uma chamada por vez, e nunca debaixo do modal de confirmação: trocar os
    // números do alvo enquanto a pessoa lê "Encerrar agora?" é a pior
    // interação possível nesta tela.
    if (state.kill || Object.keys(bridge.pending).length) return;
    if (document.hidden) return;
    refresh();
  }, 5000);
}

function onBridgeMessage(event) {
  const msg = event && event.data;
  if (!msg || !msg.type) return;
  const p = msg.payload || {};

  if (msg.type === "engine-reply") {
    const cb = bridge.pending[p.request_id];
    if (cb) { delete bridge.pending[p.request_id]; cb(p); }
    return;
  }
  if (msg.type === "bridge-error") {
    bridgeFail("a ponte falhou", p.error);
    return;
  }
  if (msg.type === "host-ready") {
    state.engineAvailable = !!p.engineAvailable;
    state.dataRoot = p.data_root || "";
    state.dataRootFrom = p.data_root_from || "";
    if (!state.engineAvailable) {
      // Sem Python no PATH a janela NÃO quebra nem finge: continua em mock.js
      // e diz o motivo na barra de título.
      notice("<b>A janela abriu sem motor:</b> " +
        esc(p.notice || "o host não encontrou o CLI.") +
        " Os números abaixo são de <span class=\"inline-code\">mock.js</span>.", "warn");
      render();
      return;
    }
    render();      // a casca já mostra "lendo o território…"
    refresh();     // e a primeira resposta real substitui o que estava na tela
    return;
  }
  // Tipos que esta página não conhece são ignorados: a interface continua com
  // a última resposta válida em vez de quebrar por uma mensagem nova do host.
}

/* A anomalia que "chega" pouco depois da abertura é puro teatro de vitrine: só
 * faz sentido enquanto a tela mostra dado de exemplo. */
function demoArrival() {
  if (state.engineAvailable || !M.arriving) return;
  setTimeout(function () {
    if (state.engineAvailable || state.hasData) return;
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

function boot() {
  if (isHosted() && window.chrome.webview.addEventListener) {
    window.chrome.webview.addEventListener("message", onBridgeMessage);
    sendToHost("ready", null);
    startPolling();
  }
  render();
  demoArrival();
}

boot();
