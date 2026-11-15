# Roadmap

## Next: agreed power and monthly peaks (agreed 2026-11-15)

1. **Agreed-power warning.** An option for the agreed power (dogovorjena
   obračunska moč) per tariff block, or an entity that gives the current
   block. A binary sensor turns on when the projected value goes over the
   agreed power of the current block, so an automation can warn before the
   quarter hour ends.
2. **Monthly peak per block.** Sensors with the highest finished quarter hour
   of the month, per tariff block when a block entity is set, with the time
   of the peak. They reset on the 1st of the month and survive a restart.

Open question: which entity gives the current tariff block on each install
(home has `sensor.main_daily_energy_new_b1`…`b5`, so a block source exists).
