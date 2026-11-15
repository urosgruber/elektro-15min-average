# Elektro 15-Minute Average Power

A Home Assistant integration that calculates the 15-minute average power of a
power sensor. It uses fixed quarter hours (:00–:15, :15–:30, :30–:45,
:45–:00), as the electricity meter does. The network tariff in Slovenia uses
this value, and Moj Elektro shows it one day late. This integration shows it
in real time.

## Sensors

Each power sensor that you add gets one device with three sensors:

| Sensor | What it shows |
|---|---|
| **15-minute average** | The average of the current quarter hour so far. |
| **Projected 15-minute average** | The value that the current quarter hour ends at if the power stays as it is now. Use it to see where the value climbs to, and to react before the quarter hour ends. |
| **Last 15-minute average** | The result of the last finished quarter hour. It keeps its value after a restart. |

The first two sensors update on each change of the source and every 10
seconds. The last sensor updates at :00, :15, :30 and :45.

## Tariff blocks, agreed power and monthly peaks

The Slovenian network tariff has five time blocks. Block 1 is the most
expensive. The integration adds these entities:

| Entity | What it shows |
|---|---|
| **Tariff block** | The block now (1 to 5). The attributes show the source of the block, the season and whether today is a working day. |
| **Agreed power exceeded** | On when the projected 15-minute average is above the agreed power of the current block. It is off when the block has no agreed power. The attribute `headroom` shows the margin in W. |
| **Monthly peak block 1–5** | The highest finished quarter hour of the month in each block, with its time (`peak_start`). It resets on the 1st and keeps its value after a restart. It is unknown until the block has a finished quarter hour in the month (block 1 does not occur from March to October). |

The projected and the last sensor also show `block` and `agreed_power`. The
last sensor shows `exceeded`.

**How the block is found:**

1. If you set a **tariff block entity** (for example a select with `b1`…`b5`
   or a sensor with `1`…`5`), its state is used.
2. Otherwise the integration calculates the block from the season (high
   season: November to February), the type of day and the hour. It uses the
   table of the Energy Agency that is valid up to 2026, and from
   1 January 2027 the new table (act of 29 September 2025, Annex 2).

**Working days:** a block calculation needs to know if today is a working
day. Set **Holiday calendar or workday sensor** to the calendar of Home
Assistant's Holiday integration (a day with an event is a holiday) or to the
binary sensor of the Workday integration (on = working day). Home Assistant
keeps these up to date. Without it, the integration uses a built-in list of
Slovenian public holidays.

**Agreed power:** enter it per block in kW in **Configure**. You find it on
the network bill or in Moj Elektro. A higher block may not have a lower
agreed power than a lower block.

An automation example that warns before the quarter hour ends:

```yaml
triggers:
  - trigger: state
    entity_id: binary_sensor.grid_agreed_power_exceeded
    to: "on"
actions:
  - action: notify.mobile_app_phone
    data:
      message: >
        The 15-minute power will go over the agreed power
        ({{ state_attr('binary_sensor.grid_agreed_power_exceeded', 'agreed_power') }} W).
```

## How it calculates

The meter divides the energy of the quarter hour by 15 minutes. The
integration does the same from the power samples: each value holds until the
next sample (a time-weighted average).

An average of the samples (an arithmetic mean) gives a wrong result. A source
sends more samples while the load changes, so these periods get too much
weight. On a real install, the phase energy meters gave 1793 W for one
quarter hour. The time-weighted average gave 1793 W. The arithmetic mean gave
1598 W. The last sensor shows the arithmetic mean only as the attribute
`arithmetic_average`, for comparison.

**Projected value:** the energy measured so far, plus the latest power for the
rest of the quarter hour, divided by 15 minutes. At the end of the quarter
hour, it equals the average.

**Grid import only:** a grid sensor with solar is negative during export. The
meter's import register does not count export. Turn on **Count only grid
import**, and negative values count as 0 W.

**Restarts:** the integration saves its state. After a restart, it continues
the current quarter hour. It does not count the time while Home Assistant was
down. The attribute `restart_detected` is then true, and `coverage` shows the
measured share of the quarter hour. If the saved quarter hour already ended,
the integration starts with the next one.

## Installation (HACS)

1. In HACS, add `https://github.com/urosgruber/elektro-15min-average` as a
   custom repository of the type **Integration**.
2. Install **Elektro 15-Minute Average Power**.
3. Restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and select
   **Elektro 15-Minute Average Power**.

Home Assistant 2026.2 or newer is necessary.

## Configuration

| Field | Description |
|---|---|
| Power sensor | A sensor in W or kW. For the grid, use the power at the meter. |
| Name | Optional. The default is the name of the power sensor. |
| Count only grid import | Negative values count as 0 W. Use it for a net grid sensor with solar. |

**Configure** (after setup) also has the agreed power per block, the holiday
calendar or workday sensor, and the tariff block entity.

## Attributes

**15-minute average:** `interval_start`, `interval_end`, `coverage`,
`sample_count`, `min_value`, `max_value`, `last_value`, `restart_detected`,
`source_entity`, `import_only`. The recorder does not store the attributes
that change with each sample.

**Projected 15-minute average:** `interval_end`.

**Last 15-minute average:** `interval_start`, `interval_end`, `coverage`,
`sample_count`, `min_value`, `max_value`, `arithmetic_average`,
`restart_detected`.

## Dashboard examples

A gauge of the projected value:

```yaml
type: gauge
entity: sensor.grid_projected_15_minute_average
min: 0
max: 11000
severity:
  green: 0
  yellow: 6000
  red: 9000
```

A bar chart of the finished quarter hours:

```yaml
type: statistics-graph
entities:
  - sensor.grid_last_15_minute_average
stat_types:
  - max
period: 5minute
chart_type: bar
```

## Upgrade from version 0.x

Version 1.0 migrates the entries on start:

- The average is always time-weighted. The options **Average method**,
  **Create finalized-only sensor** and **Entity picture** are removed.
- Each entry gets all three sensors. The entity IDs of the existing sensors
  stay the same. The new sensor is the projected value.
- The integration shows its own brand icon.

## Development

```bash
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest -q -W error
```

`bash scripts/podman-run.sh` starts a local Home Assistant in Podman with the
integration mounted.

## Icon

The integration ships its own icon in
`custom_components/elektro_15min_average/brand/`. It is an original drawing.
Run `uv run --with pillow python scripts/make_icon.py` to draw it again.

## Release checklist

1. Update the version in `manifest.json` and `pyproject.toml`.
2. Run the tests and ruff.
3. Tag the commit (for example `v1.0.0`) and create a GitHub release.

## Logging

```yaml
logger:
  logs:
    custom_components.elektro_15min_average: debug
```
