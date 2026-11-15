# Elektro 15-Minute Average Power

Custom Home Assistant integration that creates a sensor with a fixed 15-minute average of a power entity. Intervals are aligned to local time boundaries (00, 15, 30, 45).

## Features

- Configurable source power sensor
- Fixed 15-minute intervals aligned to quarter hours
- Two average methods:
  - Time-weighted (default): integrates values over time between samples. This is energy / time, which is what the electricity meter measures.
  - Arithmetic: mean of samples
- Optional import-only mode: negative values (export) count as 0 W
- Attributes for min, max, last value, sample count, and interval boundaries
- Restart detection flag to show potential partial intervals

## Installation (HACS)

1. Add `https://github.com/urosgruber/elektro-15min-average` as a custom repository in HACS (Integration).
2. Install the integration.
3. Restart Home Assistant.
4. Add the integration via Settings -> Devices & Services.

## Configuration

During setup you can choose:

- Source power entity (W)
- Optional name
- Average method (time-weighted or arithmetic)
- Import only: count negative values as 0 W. Use it when the source is a net grid power sensor that goes negative during export (solar).
- Optional finalized-only sensor (updates only at 15-minute boundaries)
- Optional entity picture URL (defaults to the bundled icon)

## Attributes

- `average_method`
- `arithmetic_average`
- `time_weighted_average`
- `interval_start`
- `interval_end`
- `sample_count`
- `min_value`
- `max_value`
- `last_value`
- `source_entity`
- `import_only`
- `restart_detected`
- `restart_at`

## Arithmetic vs time-weighted

Time-weighted treats the last value as holding until the next update and averages over time. The result equals the energy in the interval divided by 15 minutes, which is how the meter (and Moj Elektro) computes the 15-minute power.

Arithmetic uses the mean of received samples. A source that reports more often while the load changes gets more weight in those periods, so the result can be wrong by 10 % or more. Example from a real install: the energy meters gave 1793 W, time-weighted 1793 W, arithmetic 1598 W.

## Notes

- The integration updates the sensor on each source change and on each 15-minute boundary.
- The optional finalized-only sensor only updates at the boundary for discrete history points.
- Averages are rounded to whole watts.
- If Home Assistant restarts mid-interval, `restart_detected` is set to true for that interval. The time while Home Assistant was down is not counted. If the stored interval already ended, it is dropped.
- The live sensor's time-weighted value includes the time since the last source update.
- By default, the integration serves a bundled icon at `/api/elektro_15min_average/static/icon.png`.
- To use a local PNG, place it in `/config/www/` and reference it as `/local/<filename>.png` in the options.

## Logging

To enable debug logging for this integration, add:

```yaml
logger:
  default: info
  logs:
    custom_components.elektro_15min_average: debug
```

## Local development (Podman)

1. Run `bash scripts/podman-run.sh`.
2. Open `http://localhost:8123` and complete onboarding.
3. Add the integration via Settings -> Devices & Services.

Notes:

- The script creates a local `ha-config/` folder (gitignored).
- Code changes are picked up via integration reload or container restart.

## Release checklist

- Update the version in `custom_components/elektro_15min_average/manifest.json`.
- Tag the commit (e.g., `v0.1.0`) and create a GitHub release.
- Update `README.md` if any usage details changed.

## Lovelace

For a bar-style view, try a statistics graph with 15-minute periods (example):

```yaml
type: statistics-graph
entities:
  - sensor.your_15min_average
stat_types:
  - mean
period: 15minute
```

If you prefer a live running value and attributes, a simple entities card works well:

```yaml
type: entities
entities:
  - entity: sensor.your_15min_average
    name: 15-minute average
```

## Tests

Run `python3 -I tests/test_averager.py custom_components`. It uses stub Home Assistant modules.

## Manual test checklist

- Create the integration, pick a power sensor, and verify the new sensor updates on each source change.
- At a quarter-hour boundary, confirm the interval flips and `interval_start`/`interval_end` move to the next window.
- Compare arithmetic vs time-weighted by forcing irregular updates (e.g., rapid changes followed by a pause).
- Restart Home Assistant mid-interval and confirm `restart_detected` becomes true and the interval continues.
- Enable the finalized-only sensor and verify it only updates at quarter-hour boundaries.
- Confirm the bundled icon shows in the entity list, then set a custom entity picture URL and verify it overrides.
