# Roadmap

## Done in 1.1.1

- The forecast attributes are empty when a tariff block entity sets the block.
  The 48-hour walk uses real hours across the DST change.

## Done in 1.1.0

- Tariff block attributes `next_change`, `next_block` and `next_cheap_start`.

## Done in 1.0.0

- Agreed-power warning per tariff block (binary sensor on the projected value).
- Monthly peak per tariff block, with the time of the peak.
- Tariff block: calculated (tables up to 2026 and from 2027), or from an
  entity. Working days from a holiday calendar or a workday sensor, with a
  built-in list as the fallback.

## Ideas

- A cost estimate of the excess power (presežna moč) when the rules for its
  price are clear.
