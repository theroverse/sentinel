# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Delegated (user chose "como os irmãos", code-first): vanilla HTML/CSS/JS,
no framework, no build step. Reasoning: the surface is hosted inside a
WebView2 control embedded in a native PowerShell/.NET borderless form
(`gui/SentinelHost.ps1`, compiled to a single `Sentinel.exe` via ps2exe)
— same architecture as `vector/gui/` (`VectorHost.ps1` + `gui/vector/`)
and `genesis/gui/` (`WizardHost.ps1` + `gui/wizard/`). There is no server
and no bundler; the deliverable is a portable folder of plain files next
to the exe. Python 3.10+ remains a runtime dependency because the real
engine (`src/sentinel/`, which needs `psutil`) is the source of truth;
the GUI is a thin client over it.

Confirmed delivery order (user decision): **mock first** — the GUI ships
with `gui/sentinel/mock.js` reproducing the exact real data shapes so the
owner can approve look and flow, then the WebView2 bridge is wired to the
real CLI in a later phase.

## Users

Single user (the machine's owner) on their own Windows 11 PC. Two
moments of use: (1) glancing at the console to see whether the machine is
behaving, and (2) reacting to a recorded anomaly — reading a short
fix-it tutorial, trying it, and telling the Sentinel whether it worked.
The CLI/daemon is the always-on part; the GUI is the human-facing window
onto it.

## Product Purpose

Sentinel is the vigilance satellite of the Theroverse ecosystem: it
watches CPU/RAM/disk/network in background, records sustained anomalies
locally, and turns each one into a guided mini-tutorial with up to 3
candidate fixes, validated interactively. This surface gives that
loop a live console — gauges, an anomaly inspector, the fix cycle, and
safe process termination — so the owner can see and act without reading
a terminal.

## Positioning

Not a commercial product. The meaningful difference is against the
project's own current state (a text-only Python CLI + JSONL log): the
same detect → tutorial → validate → next-alternative ritual gets a real
usage surface without adding a backend, telemetry, or hosted component.
Against generic "system monitors", the difference is the second half:
Sentinel does not just graph, it proposes fixes and asks whether they
worked. Everything runs 100% local; the only network egress is an
explicit `claude -p` call the user triggers.

## Operating Context

- Runs on the owner's own Windows 11 PC. Reads and writes only the
  `.sentinel/` territory (`events.jsonl`, `daemon.log`, `daemon.pid`,
  `config.json`) under the chosen root.
- The real work (sampling, detection, tutorial generation, kill safety)
  is performed by `src/sentinel/*.py` via the CLI. The GUI never
  reimplements detection, thresholds, or process protection.
- The daemon may or may not be running when the console opens; the
  console has to show that state honestly rather than assume it.
- Interface language is Portuguese (pt-BR), matching the CLI strings.
- Must keep working as a single portable artifact: `Sentinel.exe` plus
  sibling `src/` and `gui/` folders — no Node/npm to build.

## Capabilities and Constraints

- WebView2 Runtime ships with Windows 11; if missing, the shell must
  explain plainly instead of crashing silently.
- Screens (dashboard-first, not a wizard): PAINEL (live gauges + spark +
  HUD), ANOMALIAS (event list + inspector), TUTORIAL (fix cycle),
  PROCESSOS (suspects + safe kill), CONFIG (thresholds + source), LOG.
- Safety rules are product truth and stay in Python: protected system
  processes and the Sentinel/Python itself are never killable; a service
  is only ever suggested as `net stop <nome>`; killing needs explicit
  human confirmation; a non-interactive session never kills anything.
  The GUI's confirm modal is UX on top of that, never a replacement.
- Interactive-only CLI paths (`fix`, `kill`) cannot run from a WebView
  (no tty). Wiring the bridge therefore requires machine-mode JSON
  endpoints — `metrics --json`, `status --json`, `events --json`,
  `fix --plan/--resolve --json`, `kill --yes --json` — tracked as
  "Fase 0" in the spec. Decided, not yet built.
- Undecided: whether the GUI gains tray/persistent presence. Not in
  scope for v1.

## Brand Commitments

- Ecosystem rule: no two tools share a primary color. Occupied primaries
  — Thero orange `#f4652c`, Zeus lime `#a3e635`, Athena rose-red
  `#eb445b`, Vector magenta `#EC4899`, Genesis/Nexo cyan→violet
  `#22d3ee`/`#8b5cf6`.
- Sentinel primary is a **deep true red** `#B3121B` chosen by the user
  (they explicitly rejected `#FF3B30` as "not red, orange/yellow" and
  confirmed `#B3121B`). Red must read as vigilance/security and must not
  be confused with Athena's pink-leaning `#eb445b`.
- Field is **neutral graphite**, deliberately unhued: Vector's near-black
  is magenta-tinted, Genesis's is navy-tinted. Sentinel's is neither.
- Name for the palette: "Vermelho Vigia & Grafite".
- No image generation for the mark: the glyph is an authored inline SVG.

## Evidence on Hand

- `src/sentinel/*.py` is the working, tested source of truth: 60 pytest
  passing, plus a verified live run against a real Windows machine
  (sampling, daemon lifecycle, dedupe, kb fallback, protected-PID
  refusal all observed).
- Exact data shapes the mock must mirror: `Sample` (`sensor.py`),
  `Finding` (`detector.py`), and the JSONL records
  `kind: anomaly` / `kind: resolution` (`events.py`, schema version 1).
- `vector/gui/` (`VectorHost.ps1`, `app.js`, `style.css`, `mock.js`,
  `assets/*.svg`, `scripts/make-exe-icon.ps1`) and `genesis/gui/` are the
  architectural reference for the WebView2 shell, the postMessage
  protocol and the ps2exe build — port the pattern, not the styling.
- `guia-do-mochileiro.md` (repo root) is the ecosystem lore; Sentinel is
  the "Vigilância" satellite and is canonically described as a
  non-aggressive eye that only shows what it observed.

## Product Principles

1. Thin client: the console presents and asks, the Python engine
   detects, decides and protects. No duplicated rules.
2. Vigilance, not accusation: an anomaly is "this sustained pattern
   appeared", never "an app is doing something wrong".
3. The fix cycle is the product: propose ≤3, let the human validate,
   advance on failure. The GUI must make that loop the default path,
   not a hidden feature.
4. One red, and it is the alarm: identity color and critical color are
   the same family — the console literally turns red when something is
   wrong. Never color alone: icon + label always accompany severity.
5. Single portable offline artifact: no telemetry, no hosted assets,
   graceful degradation to the offline knowledge base when Claude is
   absent.

## Accessibility & Inclusion

Red is the sole hue with semantic weight in this product, so color-blind
users (protanopia/deuteranopia) would otherwise lose severity
information: every severity state carries a glyph and a text label in
addition to color. Body text ≥ 4.5:1 on the graphite field; color is
used at ≥ 3:1 only for large marks and UI component boundaries. Full
keyboard operability of the fix cycle and the confirm modal, visible
focus, and reduced-motion respect.
