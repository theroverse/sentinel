# Design

<!-- impeccable:design-schema 1 -->

## World

Dark vigilance console: a neutral graphite near-black field carrying one
signature red (vermelho vigia → brasa), monospace telemetry labels,
hairline-bordered instrument panels. Mode: **Operate** — the visitor is
reading the state of their own machine and working an anomaly through a
fix loop, not being persuaded. The red is spent once per screen (active
nav indicator, critical severity, primary action, the sweep highlight),
never as ambient decoration.

The world's governing metaphor is an **instrument, not a dashboard
toy**: the console reads like surveillance/monitoring hardware —
numeric-first, restrained, unhued metal — so that when something IS
wrong, red is the only thing that moves, and it means it. That is why
identity color and alarm color are deliberately the same hue: a Sentinel
that is calm is nearly monochrome, a Sentinel that has found something
is red. Color never lies and never decorates.

Runs inside a WebView2 control hosted by a native, borderless Windows
form (`gui/SentinelHost.ps1`) — Chromium rendering, but no browser
chrome, so the page owns its own custom titlebar and window controls.
Same shell pattern as Vector and Genesis, re-skinned in Sentinel red on
graphite. Unlike those two, the surface is a live console rather than a
linear wizard, because the daemon runs in background and the human's
visit is a check-in, not a one-time task.

## Palette

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0B0C0E` | Base field — **neutral graphite, unhued** (Vector's is magenta-tinted, Genesis's navy) |
| `--bg-elevated` | `#14161A` | Panels/cards |
| `--bg-elevated-2` | `#1C1F24` | Hover/active surface |
| `--bg-inset` | `#070809` | Inputs, gauge wells, log panel |
| `--border` / `--border-strong` | `rgba(228,231,238,.10 / .22)` | Hairlines |
| `--text` | `#F4F5F7` | Primary text |
| `--text-dim` | `#B4BAC6` | Secondary (≥ 4.5:1 on `--bg`/`--bg-elevated`) |
| `--text-faint` | `#767D89` | Tertiary/meta only (mono ids, counters) — tuned to clear 4.5:1 rather than the sibling's `#5b6688` |
| `--primary` | `#B3121B` | Brand fill: active badge, primary button (with white text — 6.9:1) |
| `--primary-lit` | `#E11D29` | The same red *lit* for use on the dark field: nav bar, critical mark, focus ring (≥ 3:1 as a UI component) |
| `--primary-deep` | `#7E0C12` | Base of the embers gradient, pressed state |
| `--teal` | `#2DD9B9` | Success / resolved |
| `--amber` | `#FBBF5B` | Warning severity |
| `--danger` | `#B3121B` / `#E11D29` | Critical + destructive (= brand family, see Color strategy) |
| `--glow` | `rgba(179,18,27,.40)` | Focus / active halo only, never ambient |

One hue family, two luminances by **role**, not two reds: `#B3121B` is a
fill (reads best with white on top), `#E11D29` is the mark/graphic
version that survives being placed *on* the graphite field. Introducing a
separate "alert" red would have made critical and brand indistinguishable
and would have added a fourth warm hue to a field that must stay cold and
neutral.

Distinctness from siblings: Athena's `#eb445b` is hue ≈ 350 (pink-leaning,
lighter). Sentinel's `#B3121B` is hue ≈ 357, deeper and more saturated,
and — decisively — sits on a *neutral* field instead of a tinted one, so
the pair never reads as the same brand at a glance.

Color strategy: **Committed** — the dark field carries the whole surface.
Justified because the world is pinned evidence (Genesis/Vector console
pattern already shipped in this ecosystem + the "o dono do computador é
você" privacy stance), not an invented aesthetic.

Non-negotiable: severity is **never** color-only. Every severity state
pairs its hue with a glyph and a pt-BR word (`info` / `ATENÇÃO` /
`CRÍTICO`), because red is this product's only semantic hue.

## Type

- Display/headings: `Segoe UI Variable Display` → `Segoe UI Semibold` →
  `Segoe UI` (Windows 11's native display face; ships with the OS).
- Body: `Segoe UI Variable Text` → `Segoe UI`.
- Technical (metric numerals, paths, PIDs, fingerprints, log, timestamps):
  `Cascadia Code` → `Cascadia Mono` → `Consolas`.

Numeric telemetry uses `font-variant-numeric: tabular-nums` so gauge
values do not jitter width as they update. No web fonts, no downloads —
portable offline artifact.

## Components

- **Titlebar** (`.titlebar`): custom chrome, draggable; red radar-eye
  glyph + `SENTINEL.EXE` mono wordmark; a `VIVO`/`PARADO` state pill
  (teal dot / red dot, plus the word — color never alone); min/close.
- **HUD strip** (`.hud`): daemon state, last heartbeat (mono, relative +
  absolute), uptime, open-anomaly count. This is the honest "is the
  satellite actually up there" line; it never assumes the daemon is
  running.
- **Gauges** (`.gauge`): CPU · RAM · DISCO · REDE as a dense instrument
  row — big tabular mono percentage, hairline arc/bar with a visible
  threshold tick, severity tint on the value only. Deliberately *not*
  four equal marketing cards; it is a measurement strip.
- **Sparkline** (`.spark`): 60-second window per metric, hairline mono
  trace with the anomaly moment marked, so a spike is readable as time,
  not just as a number.
- **Anomaly inspector** (`.ev-list` / `.ev-detail`): two-pane. Left is a
  dense list (severity glyph + metric + value + relative time),
  filterable by open/severity. Right is the selected record: value vs
  threshold, sustained window, `top_processes` as a compact mono table
  (pid, name, cpu, RSS), `fingerprint`, `occurrences`, and actions
  `[Corrigir]` `[Encerrar processo]` `[Descartar]`.
- **Tutorial panel** (`.tutor`): drives the `tutor.py` state machine.
  Renders one option at a time — title, numbered steps, source badge
  (`IA` or `base local`) — then the validation row: `Funcionou?`
  → `[sim]` / `[não, próxima]` / `[pular tudo]`. Exhausted and resolved
  states are shown, not silently closed. When the run is non-interactive
  the panel degrades to "list the options, no loop" exactly like the CLI.
- **Confirm modal** (`.modal`): the destructive path. Names the exact
  process and PID, shows the descendant tree it would take with it, and
  requires an explicit click on the red action (Escape/overlay = cancel).
  Mirrors Vector/Genesis "navigation itself is the guard"; the real
  protection stays in Python.
- **Process list** (`.proc-row`): suspects with protected/own-Sentinel
  rows visibly non-actionable (lock glyph + `protegido` label) rather
  than hidden — hiding them would imply they were killable.
- **Log panel** (`.log-panel`): mono feed of the real `daemon.log` lines,
  in the format `daemon.py` writes them — a `tick cpu=… ram=… disk=… io=…
  net_down_bps=… net_up_bps=…` every 2 s and one `ANOMALIA <metric> <sev>
  value=… thr=… status=… id=…` when the detector fires. Resolutions are
  not in this file (they live in `events.jsonl`), so the log never shows
  them. `ANOMALIA` lines take `--primary-lit`; ticks stay `--text-dim`.
- **Sidebar nav** (`.side-*`): three groups — Vigilância (Visão geral,
  Anomalias, Tutorial de correção), Sistema (Processos, Log do daemon),
  Config (Limites e privacidade). The open-anomaly count sits on
  *Anomalias* and turns amber while any open event is critical; the
  current item takes an elevated fill and a `--primary-lit` left rule.
  Never a numbered stepper.

## Motion

Two authored moments, both feedback-only: a single **radar sweep** across
the titlebar glyph when a new anomaly is recorded (~600ms, once, never
looping), and the gauge value cross-fading to its severity tint on
threshold crossing (~140ms exponential ease-out). The 60s spark updates
step-wise, not animated, because a smooth tween would misrepresent
sampled data as continuous. No entrance animations, no scroll reveals.
`prefers-reduced-motion: reduce` disables the sweep and the cross-fade
outright.

## Provenance

Glyph is an authored inline SVG (a radar/scan eye in Sentinel red,
`gui/sentinel/assets/sentinel-mark.svg`); the `.ico` is generated from it
by `scripts/make-exe-icon.ps1`, same approach as Genesis/Vector. No
external imagery, no stock, no AI-generated stand-ins for product truth.
Mock telemetry in `gui/sentinel/mock.js` mirrors the real `Sample`,
`Finding` and `events.jsonl` (schema 1) shapes exactly, so the phase-2
bridge is a data-source swap, not a re-render.

## Finish

Phase 1 (mock console) shipped and inspected in a Chromium viewport at
1151 px — the same engine family WebView2 uses — on 2026-09-22.

Verified by execution:
- `node --check` on `gui/sentinel/app.js` and `gui/sentinel/mock.js`.
- PowerShell parser on `gui/SentinelHost.ps1` (no AST errors).
- `impeccable detect sentinel/gui/sentinel` → 0 findings. The first pass
  flagged the 10.5 px titlebar phase label; the whole micro-label tier
  (`.src`, `.kv dt`, `.badge`, `.panel-title`, `.chip`, `.gauge-name`,
  `.side-group-title`, `.hud-k`, `.tbl th`, `.lock-flag`, `.ev-meta`) was
  raised to the 11 px floor and the narrow-width override that lowered the
  statusbar back to 10.5 px was removed.
- The 60 pytest of the CLI still pass (nothing in `src/` changed).
- Rendered and read: Visão geral (HUD, 4 gauges, sparklines, latest
  anomalies, live log), Anomalias (ABERTAS/TODAS, severity chips, detail
  `kv`, process table with locked rows, RESOLUÇÕES block), Tutorial
  (opção 1 → 2 → 3, JÁ TENTADAS struck, exhausted, resolved), Processos +
  the kill confirm modal, Log do daemon, Limites e privacidade.
- Mock data was re-checked against the engine, and three fictions were
  corrected: `daemon.log` has no `heartbeat`/`daemon iniciado`/`resolucao`
  lines (only `tick` and `ANOMALIA`, with `thr=` not `threshold=`); a
  resolution's `source` is one of `kb:fingerprint`|`kb:causa`|`kb:metrica`|
  `modelo`, never `user`; an exhausted tutor
  cycle closes the event as `dismissed` with `outcome=not_fixed`, it does
  not leave it in `addressing`. `isProtectedName()` now mirrors
  `processctl.is_protected` name-for-name (the invented
  `Memory Compression` entry is gone, `system idle process` and `registry`
  are in).

Not verified — needs a run on the target machine, so nothing here claims
it:
- Real hosting: `SentinelHost.ps1` window, titlebar drag, min/close,
  elevation prompt, crash trap, `.ico`, and every bridge message
  (`host-ready` is the only one the page can receive today, and the engine
  handler still throws "fase 2").
- The `max-width: 1080px` breakpoint (2-column meters, 190 px sidebar) is
  written but was not pixel-inspected; the browser harness had no viewport
  control.
- Payload extraction and the `.exe` build (Fase 3).
