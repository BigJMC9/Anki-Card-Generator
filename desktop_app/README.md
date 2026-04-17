# Anki Card Generator Desktop

Nuxt UI frontend + Tauri desktop shell + Python sidecar backend.

## What Is Included

- Collection/deck management
- Dictionary search + bulk add to deck/global pool
- Manual card builder with verb/adjective form generation
- Global pool management + import/export between global/deck cards
- Deck card review (bulk schema update, single-card edit, media replacement)
- Revision mode with card flip
- Game modes:
  - Verb sort (Ichidan vs Godan)
  - Adjective sort (い vs な)
  - て-form builder
- Scoring with streak + speed bonuses + per-round summary
- OCR scan flow, CSV import, Anki `.apkg` export
- Inflection-aware search on stored cards (dictionary/masu/te/past/negative forms)

## Prerequisites

- Node.js `20+`
- Rust toolchain (`rustc`, `cargo`)
- Python `3.14` (same runtime used in this workspace)

## Install

From `desktop_app`:

```bash
npm install
```

## Build Sidecar Binary

```bash
npm run sidecar:build
```

Output binary:

`src-tauri/binaries/anki-sidecar-<rust-target-triple>.exe`

## Run Desktop App (Dev)

```bash
npm run tauri:dev
```

This builds the sidecar first, then starts Nuxt + Tauri.

## Build Installers/Bundles

```bash
npm run tauri:build
```

Generates Tauri bundles in:

`src-tauri/target/release/bundle`

## Technical Notes

- Tauri calls `sidecar_call` (Rust command), which invokes the Python sidecar with an action name and JSON payload file.
- The sidecar venv is created with `--system-site-packages` to reuse the existing local Japanese dictionary stack in this environment.
- The frontend requires Tauri runtime for all sidecar-backed actions. If you run plain Nuxt web dev, backend actions are disabled.
