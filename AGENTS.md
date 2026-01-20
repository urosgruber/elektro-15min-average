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
- The sensor computes fixed 15-minute interval averages aligned to wall-clock
  quarter-hour boundaries (00, 15, 30, 45).
- Source sensor is configurable; unit is watts (W).
- Two averaging methods are supported: arithmetic and time-weighted.
- The current interval value updates on source changes; the interval result is
  discrete once the boundary passes.
- Restarts should restore partial interval state and mark the interval as
  potentially inaccurate if a restart happened.

## File-Level Expectations
- `custom_components/elektro_15min_average/sensor.py`: keep averaging logic,
  boundary scheduling, and persistence here. Favor clear, testable helpers.
- `custom_components/elektro_15min_average/config_flow.py`: add new options
  via options flow, keep the config entry stable (no breaking fields).
- `custom_components/elektro_15min_average/const.py`: store new constants here.
- `custom_components/elektro_15min_average/manifest.json`: bump version on any
  user-visible change; keep documentation/issue URLs pointing to the repo.
- `custom_components/elektro_15min_average/strings.json` and
  `custom_components/elektro_15min_average/translations/en.json`: update UI
  text and option labels whenever new config fields are added.
- `README.md`: update behavior, attributes, config, and release checklist.

## Data Integrity & Backwards Compatibility
- Do not rename `unique_id` formats or entity_id patterns; add new attributes
  instead of renaming existing ones.
- When introducing new settings, supply sensible defaults and migrate old
  config entries if needed.
- Avoid changing attribute meanings without documenting in `README.md`.

## UI & Attributes
- Keep attributes useful for diagnostics: interval start/end, min/max, samples,
  method, and restart markers. If adding new attributes, document them.
- If adding new sensors, ensure they are optional and do not clutter by default.

## Quality Bar
- Prefer readable, well-structured code with small helpers and minimal state.
- Add concise comments only around non-obvious logic (interval math, weighting).
- If introducing new behavior, add a manual test checklist to `README.md`.

## Release Steps (Maintain)
- Update version in `manifest.json`.
- Update `README.md` release checklist and any new config or attributes.
- Ensure HACS metadata in `hacs.json` remains valid.
