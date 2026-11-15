# Codex Agent Guidance

This repo is a Home Assistant custom integration (HACS-ready) named
`elektro-15min-average`, domain `elektro_15min_average`. Use this document to
keep future iterations consistent, safe, and aligned with HA standards.

## Architecture & Standards
- Follow Home Assistant custom integration best practices from
  https://developers.home-assistant.io/ and HACS requirements from
  https://www.hacs.xyz/.
- Keep all async I/O in async functions; avoid blocking calls in the event loop.
- Domain name, config flow identifiers, and storage keys must remain stable to
  prevent breaking existing installs.
- Prefer modern HA APIs: config flow + options flow, `Store` for persistence,
  and `async_track_state_change_event` / `async_track_time_interval`.

## Core Behavior (Do Not Regress)
- Fixed 15-minute intervals aligned to local quarter hours (00, 15, 30, 45).
- The average is time-weighted (energy / time), as the meter measures it. Do
  not bring back the arithmetic mean as the state; it is wrong for sources
  that report at an uneven rate. It stays only as an attribute.
- Per entry: current average, projected value, last interval, tariff block,
  agreed-power warning, monthly peak per block.
  The current and projected values update on source changes and every 10 s.
  None of them may show `unknown` while the source has a value.
- `import_only` counts negative source values as 0 W (grid export).
- Tariff blocks: `tariff.py` holds the Energy Agency tables (up to 2026 and
  from 2027). A block entity overrides the calculation; a holiday calendar or
  a workday sensor overrides the built-in holiday list. The block of an
  interval is the block seen up to 60 s before its end.
- Agreed power per block (kW, non-decreasing from block 1 to 5) drives the
  binary sensor on the projected value. Monthly peaks per block are stored.
- Restarts restore the current interval, do not count the downtime, and drop
  a stored interval that already ended. The last interval is stored too.

## File-Level Expectations
- `averager.py`: the interval arithmetic, no Home Assistant state. Test it in
  `tests/test_averager.py`.
- `tracker.py`: source subscription, boundary and tick timers, storage.
- `entity.py`, `sensor.py`, `binary_sensor.py`: the entities; they only read
  from the tracker.
- `tariff.py`: blocks, seasons, holidays. Test it in `tests/test_tariff.py`.
- `config_flow.py`, `__init__.py` (setup and config entry migration),
  `diagnostics.py`, `strings.json` and `translations/` (en, sl).
- `brand/` holds the icon; `scripts/make_icon.py` draws it.
- Run `uv run ruff check .`, `uv run ruff format --check .` and
  `uv run pytest -q -W error` before each commit.

## Data Integrity & Backwards Compatibility
- Do not rename `unique_id` formats or entity_id patterns; add new attributes
  instead of renaming existing ones.
- When introducing new settings, supply sensible defaults and migrate old
  config entries if needed.
- Avoid changing attribute meanings without documenting in `README.md`.

## UI & Attributes
- Keep attributes useful for diagnostics: interval start/end, min/max, samples,
  method, and restart markers. If adding new attributes, document them.

## Quality Bar
- Prefer readable, well-structured code with small helpers and minimal state.
- Add concise comments only around non-obvious logic (interval math, weighting).
- If introducing new behavior, add a manual test checklist to `README.md`.

## Release Steps (Maintain)
- Update version in `manifest.json`.
- Update `README.md` release checklist and any new config or attributes.
- Ensure HACS metadata in `hacs.json` remains valid.
