/* Dados de exemplo — espelham exatamente as shapes do motor Python:
   Sample/top_processes (src/sentinel/sensor.py), Finding (detector.py), e as
   linhas de .sentinel/events.jsonl schema 1 (src/sentinel/events.py), mais as
   opcoes de kb.options_for(). Fase 1 e visual: nada aqui toca o sistema.
   Fase 2: o SentinelHost.ps1 substitui SENTINEL_MOCK pelas respostas dos
   endpoints JSON do CLI (fase 0 da spec) sem mudar nenhuma forma de dado. */

/* LCG deterministico: a linha do tempo precisa ser a mesma a cada abertura
   para aprovar visual, nao um ruido novo por recarga. */
function rand(seed) {
  let s = seed >>> 0;
  return function () {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function trace(seed, n, base, spread, spikeAt, spikeAmp) {
  const rnd = rand(seed);
  const out = [];
  for (let i = 0; i < n; i++) {
    let v = base + (rnd() - 0.5) * spread;
    if (spikeAt >= 0) {
      const d = Math.abs(i - spikeAt);
      if (d < 9) v += spikeAmp * (1 - d / 9);
    }
    out.push(Math.max(0, Math.round(v * 10) / 10));
  }
  return out;
}

const NOW = "2026-09-22T10:42:07+00:00";

const SENTINEL_MOCK = {
  demo: true,

  // settings.DaemonStatus
  daemon: {
    running: true,
    pid: 18420,
    last_heartbeat: NOW,
    started_ts: "2026-09-22T07:58:12+00:00",
    interval_s: 2.0,
  },

  // sensor.Sample.to_dict()
  sample: {
    ts: NOW,
    cpu_percent: 38.4,
    ram_percent: 76.1,
    disk_percent: 88.2,
    disk_path: "C:\\",
    io_busy_percent: 11.7,
    net_recv_bps: 412000,
    net_sent_bps: 68400,
    top_cpu: [
      { pid: 36884, name: "Qoder IDE.exe", cpu: 61.2, rss_mb: 1184.5 },
      { pid: 12044, name: "chrome.exe", cpu: 18.7, rss_mb: 2412.0 },
      { pid: 8120, name: "MsMpEng.exe", cpu: 7.4, rss_mb: 148.2 },
      { pid: 4192, name: "dwm.exe", cpu: 3.1, rss_mb: 212.6 },
    ],
    top_mem: [
      { pid: 12044, name: "chrome.exe", cpu: 18.7, rss_mb: 2412.0 },
      { pid: 36884, name: "Qoder IDE.exe", cpu: 61.2, rss_mb: 1184.5 },
      { pid: 2260, name: "svchost.exe", cpu: 0.4, rss_mb: 611.3 },
      { pid: 9464, name: "Explorer.EXE", cpu: 0.9, rss_mb: 388.7 },
    ],
  },

  // settings.* — o que a GUI mostra como referenca do medidor
  thresholds: {
    cpu: { warning: 85.0, critical: 95.0, sustained: 5 },
    ram: { warning: 80.0, critical: 93.0, sustained: 5 },
    disk: { warning: 85.0, critical: 95.0, sustained: 1 },
    io: { warning: 70.0, critical: 90.0, sustained: 8 },
    network: { warning_ratio: 0.8, sustained: 3 },
  },

  // janelas de amostras (SAMPLE_WINDOW) por metrica; ponto marcando o spike
  series: {
    cpu: { points: trace(7, 60, 34, 18, 41, 58), spike: 41, unit: "%" },
    ram: { points: trace(19, 60, 72, 6, -1, 0), unit: "%" },
    disk: { points: trace(23, 60, 87.4, 1.2, -1, 0), unit: "%" },
    io: { points: trace(31, 60, 22, 26, 12, 62), spike: 12, unit: "%" },
    net: { points: trace(37, 60, 3.4, 2.2, 47, 3.6), spike: 47, unit: "Mbit" },
  },

  // events.jsonl, kind:"anomaly" — campos exatos de EventStore.record_finding
  events: [
    {
      schema: 1,
      id: "evt-20260922-103911-4f21",
      ts: "2026-09-22T10:39:11+00:00",
      kind: "anomaly",
      metric: "disk",
      severity: "warning",
      value: 88.2,
      threshold: 85.0,
      window: { samples: 1, span_s: 2.0 },
      top_processes: [
        { pid: 12044, name: "chrome.exe", cpu: 18.7, rss_mb: 2412.0 },
        { pid: 36884, name: "Qoder IDE.exe", cpu: 61.2, rss_mb: 1184.5 },
      ],
      status: "open",
      fingerprint: "disk:warning:chrome.exe",
      occurrences: 1,
      ts_last: "2026-09-22T10:39:11+00:00",
    },
    {
      schema: 1,
      id: "evt-20260922-101244-9a31",
      ts: "2026-09-22T09:04:38+00:00",
      kind: "anomaly",
      metric: "cpu",
      severity: "critical",
      value: 96.4,
      threshold: 95.0,
      window: { samples: 7, span_s: 14.0 },
      top_processes: [
        { pid: 36884, name: "Qoder IDE.exe", cpu: 92.8, rss_mb: 1204.1 },
        { pid: 8120, name: "MsMpEng.exe", cpu: 41.3, rss_mb: 152.7 },
        { pid: 4192, name: "dwm.exe", cpu: 4.0, rss_mb: 212.6 },
      ],
      status: "addressing",
      fingerprint: "cpu:critical:Qoder IDE.exe",
      occurrences: 19,
      ts_last: "2026-09-22T10:12:44+00:00",
    },
    {
      schema: 1,
      id: "evt-20260922-084102-1c77",
      ts: "2026-09-22T08:41:02+00:00",
      kind: "anomaly",
      metric: "ram",
      severity: "warning",
      value: 82.7,
      threshold: 80.0,
      window: { samples: 5, span_s: 10.0 },
      top_processes: [
        { pid: 12044, name: "chrome.exe", cpu: 6.2, rss_mb: 5216.4 },
        { pid: 2260, name: "svchost.exe", cpu: 0.3, rss_mb: 611.3 },
      ],
      status: "resolved",
      fingerprint: "ram:warning:chrome.exe",
      occurrences: 4,
      ts_last: "2026-09-22T09:22:18+00:00",
    },
    {
      schema: 1,
      id: "evt-20260922-080511-6b0d",
      ts: "2026-09-22T08:05:11+00:00",
      kind: "anomaly",
      metric: "network",
      severity: "info",
      value: 742000,
      threshold: 593600,
      window: { samples: 3, span_s: 6.0 },
      top_processes: [
        { pid: 12044, name: "chrome.exe", cpu: 4.1, rss_mb: 2380.2 },
        { pid: 17288, name: "OneDrive.exe", cpu: 1.2, rss_mb: 96.4 },
      ],
      status: "dismissed",
      fingerprint: "network:info:chrome.exe",
      occurrences: 2,
      ts_last: "2026-09-22T08:11:02+00:00",
    },
  ],

  // events.jsonl, kind:"resolution" — campos exatos de append_resolution
  resolutions: [
    {
      schema: 1,
      id: "res-20260922-092231-0e58",
      ts: "2026-09-22T09:22:31+00:00",
      kind: "resolution",
      ref: "evt-20260922-084102-1c77",
      outcome: "fixed",
      option_index: 1,
      source: "kb",
      note: "",
    },
    {
      schema: 1,
      id: "res-20260922-081140-7a12",
      ts: "2026-09-22T08:11:40+00:00",
      kind: "resolution",
      ref: "evt-20260922-080511-6b0d",
      outcome: "dismissed",
      option_index: 0,
      source: "kb",
      note: "usuario pulou/descartou",
    },
  ],

  // kb.options_for(metric) — texto verbatim da base local, sem inventar
  kb: {
    cpu: [
      {
        title: "Fechar o processo que esta puxando a CPU",
        steps: [
          "Abra o Gerenciador de Tarefas (Ctrl+Shift+Esc).",
          "Ordene pela coluna 'Processos' (CPU) e identifique o topo.",
          "Se for um app seu (navegador com abas presas, build esquecido rodando), encerre-o.",
          "Voce tambem pode usar 'sentinel kill <PID>' com o PID listado no evento — o Sentinel confirma antes e nunca mata processo do sistema.",
        ],
        action: { type: "kill_top_process" },
      },
      {
        title: "Investigar processo que nao deveria estar rodando",
        steps: [
          "Veja se algo indexando/antivirus/scanner esta em spike.",
          "Adie a varredura pro periodo ocioso (Configuracoes do programa > agendamento).",
          "Confira se nao e malware disfarcado: nome estranho ou CPU alto constante pede uma checagem.",
        ],
      },
      {
        title: "Reduzir carga de inicializacao",
        steps: [
          "Gerenciador de Tarefas > aba 'Inicializar'.",
          "Desabilite itens que voce nao usa todo boot.",
          "Reinicie e observe se o pico de CPU no inicio diminui.",
        ],
      },
    ],
    ram: [
      {
        title: "Liberar memoria do processo que mais ocupa",
        steps: [
          "No evento, olhe 'top_processes' por RSS (memoria).",
          "Feche janelas/abas sobressalentes do navegador.",
          "'sentinel kill <PID>' encerra um app travado que nao libera RAM (confirma antes; nunca alvo de sistema).",
        ],
        action: { type: "kill_top_process" },
      },
      {
        title: "Verificar vazamento (memoria sobe e nunca cai)",
        steps: [
          "Reabra o suspeito do zero e observe o RSS por alguns minutos.",
          "Se crescer sem teto, e provavel leak: reinicie o app e procure atualizacao dele.",
          "Rode 'sentinel events' pra ver se a anomalia de RAM reaparece pro mesmo processo (fingerprint igual).",
        ],
      },
      {
        title: "Reduzir aplicativos residentes",
        steps: [
          "Feche o que nao esta em uso agora (launcher de jogos, suites de criacao pesadas).",
          "Considere diminuir programas em bandeja/inicializacao.",
        ],
      },
    ],
    disk: [
      {
        title: "Liberar espaco em disco",
        steps: [
          "Configuracoes > Sistema > Armazenamento: veja o que ocupa.",
          "Rode Limpeza de Disco (cleanmgr) e esvazie a Lixeira.",
          "'sentinel kill' nao resolve disco cheio — aqui e apagar arquivo, nao processo.",
        ],
        action: { type: "open_settings", target: "storage" },
      },
      {
        title: "Mover/arquivar dados grandes",
        steps: [
          "Identifique pastas de midia/downloads no volume cheio.",
          "Mova pra outro disco ou armazenamento externo.",
          "Reavalie com 'sentinel status' depois.",
        ],
      },
      {
        title: "Reduzir ponto de restauracao / shadow copies",
        steps: [
          "Painel de Controle > Sistema > Protecao do Sistema.",
          "Diminua o uso maximo de Restauracao do Sistema.",
          "Configuracoes > Sistema > Sobre > Armazenamento > arquivos temporarios do Windows.",
        ],
      },
    ],
    io: [
      {
        title: "Descobrir quem esta martelando o disco",
        steps: [
          "Gerenciador de Tarefas > coluna 'Disco'.",
          "Indexador, Windows Update ou antivirus em spike sao causas comuns e temporarias.",
          "Se persistir num app seu, encerre com 'sentinel kill <PID>' (confirma antes).",
        ],
        action: { type: "kill_top_process" },
      },
      {
        title: "Pausar tarefas de leitura/escrita pesada",
        steps: [
          "Adie sync de nuvem (OneDrive/Dropbox) no horario de uso.",
          "Pause downloads grandes.",
          "Rode varreduras de antivirus fora do horario de trabalho.",
        ],
      },
      {
        title: "Checar saude do disco (se gargalo for fisico)",
        steps: [
          "IO alto COM pouca transferencia pode indicar disco morrendo.",
          "Rode uma checagem de saude do volume e faca backup do que importa.",
          "Em SSD, veja espaco livre (<10% derruba escrita).",
        ],
      },
    ],
    network: [
      {
        title: "Identificar quem esta usando a banda",
        steps: [
          "Gerenciador de Tarefas > aba 'Desempenho' > Rede, ou Resource Monitor (resmon) > Rede.",
          "Update, sync de nuvem e streaming sao os suspeitos de sempre.",
        ],
        action: { type: "open_settings", target: "taskmgr" },
      },
      {
        title: "Agendar uploads/downloads pesados",
        steps: [
          "Limite de banda em cliente de sync/update, se houver.",
          "Rode backup grande de madrugada.",
        ],
      },
      {
        title: "So confirmar que e esperado",
        steps: [
          "Pico de rede nao e, sozinho, um defeito — e contexto.",
          "Se coincide com download/updates legitimos, ignore.",
          "Se nao ha app seu ativo e a banda continua alta, vale uma checagem de seguranca.",
        ],
      },
    ],
  },

  // sensor.top_processes() alargado, com os protegidos visiveis de proposito:
  // a lista mostra o que NAO se pode encerrar em vez de esconder.
  processes: [
    { pid: 36884, name: "Qoder IDE.exe", cpu: 61.2, rss_mb: 1184.5, protected: false, self: false, children: 3 },
    { pid: 12044, name: "chrome.exe", cpu: 18.7, rss_mb: 2412.0, protected: false, self: false, children: 11 },
    { pid: 8120, name: "MsMpEng.exe", cpu: 7.4, rss_mb: 148.2, protected: false, self: false, children: 0 },
    { pid: 17288, name: "OneDrive.exe", cpu: 2.1, rss_mb: 96.4, protected: false, self: false, children: 0 },
    { pid: 9464, name: "Explorer.EXE", cpu: 0.9, rss_mb: 388.7, protected: false, self: false, children: 6 },
    { pid: 2260, name: "svchost.exe", cpu: 0.4, rss_mb: 611.3, protected: true, self: false, children: 0 },
    { pid: 1120, name: "lsass.exe", cpu: 0.2, rss_mb: 22.1, protected: true, self: false, children: 0 },
    { pid: 968, name: "services.exe", cpu: 0.1, rss_mb: 9.8, protected: true, self: false, children: 0 },
    { pid: 18420, name: "python.exe (sentinel daemon)", cpu: 0.3, rss_mb: 38.4, protected: false, self: true, children: 0 },
    { pid: 4, name: "System", cpu: 0.0, rss_mb: 152.0, protected: true, self: false, children: 128 },
  ],

  // linhas do daemon.log, na ordem e no formato exatos que daemon.py escreve
  // (_heartbeat: "tick cpu=... swap=<%> swap_rate=<pag/s>", com stall=1 quando
  // o indice de estagnacao esta em episodio; _persist: "ANOMALIA <metric>
  // <sev> value= <v> thr=<t> status=<s> id=<id>"; _persist_incident: "ANOMALIA
  // <metric> <sev> occ=N status=<s> id=<id> :: <label>"; _log_stall_clear:
  // "ESTAGNACAO CESSOU dur=.. ticks=.. sinais=.."). Resolucoes nao passam por
  // aqui: vao para events.jsonl.
  log: [
    { ts: "2026-09-22T10:42:07+00:00", text: "tick cpu=38.4 ram=76.1 disk=88.2 io=11.7 swap=6.6 swap_rate=0 net_down_bps=412000 net_up_bps=68400" },
    { ts: "2026-09-22T10:42:05+00:00", text: "tick cpu=41.2 ram=76.0 disk=88.2 io=9.4 swap=6.6 swap_rate=118 net_down_bps=388000 net_up_bps=61200" },
    { ts: "2026-09-22T10:42:03+00:00", text: "tick cpu=37.8 ram=75.9 disk=88.2 io=8.1 swap=6.5 swap_rate=0 net_down_bps=126000 net_up_bps=40400" },
    { ts: "2026-09-22T10:39:11+00:00", text: "ANOMALIA disk warning value=88.2 thr=85.0 status=open id=evt-20260922-103911-4f21" },
    { ts: "2026-09-22T10:12:58+00:00", text: "ESTAGNACAO CESSOU dur=27.0s ticks=54 sinais=starved, thrashing" },
    { ts: "2026-09-22T10:12:44+00:00", text: "ANOMALIA cpu critical value=96.4 thr=95.0 status=open id=evt-20260922-101244-9a31" },
    { ts: "2026-09-22T10:12:31+00:00", text: "ANOMALIA stall critical occ=1 status=open id=evt-20260922-101231-7bd0 :: estagnacao: code.exe em critico (cpu) com o proprio daemon nao foi escalado no tempo pedido, paginacao em ritmo de gargalo" },
    { ts: "2026-09-22T08:41:02+00:00", text: "ANOMALIA ram warning value=82.7 thr=80.0 status=open id=evt-20260922-084102-1c77" },
  ],

  // a anomalia que "chega" pouco depois da abertura, so para demonstrar o
  // unico momento de movimento da casa (varredura de radar). O ts fica 2 s
  // depois do heartbeat: senao a linha do log nasceria no futuro da amostra.
  arriving: {
    schema: 1,
    id: "evt-20260922-104209-c205",
    ts: "2026-09-22T10:42:09+00:00",
    kind: "anomaly",
    metric: "io",
    severity: "warning",
    value: 78.9,
    threshold: 70.0,
    window: { samples: 8, span_s: 16.0 },
    top_processes: [
      { pid: 8120, name: "MsMpEng.exe", cpu: 44.8, rss_mb: 152.9 },
      { pid: 17288, name: "OneDrive.exe", cpu: 3.2, rss_mb: 96.4 },
    ],
    status: "open",
    fingerprint: "io:warning:MsMpEng.exe",
    occurrences: 1,
    ts_last: "2026-09-22T10:42:09+00:00",
  },
};
