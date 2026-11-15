"""Averaging tests with stub Home Assistant modules.

Run: python3 -I tests/test_averager.py custom_components
"""
import sys, types, asyncio
from datetime import datetime, timedelta, timezone
UTC = timezone.utc
NOW = [datetime(2026, 11, 15, 16, 7, tzinfo=UTC)]
def mod(name, **kw):
    m = types.ModuleType(name); m.__dict__.update(kw); sys.modules[name] = m; return m
class Dummy:
    def __init__(self, *a, **k): pass
    def __getattr__(self, n): return Dummy()
dt_util = types.SimpleNamespace(
    utcnow=lambda: NOW[0], as_utc=lambda d: d.astimezone(UTC), as_local=lambda d: d,
    parse_datetime=lambda s: datetime.fromisoformat(s))
STORE = {}
class Store:
    def __init__(self, hass, v, key): self.key = key
    async def async_load(self): return STORE.get(self.key)
    async def async_save(self, d): STORE[self.key] = d
for n in ["homeassistant","homeassistant.components","homeassistant.helpers","homeassistant.util"]: mod(n)
mod("homeassistant.components.sensor", SensorDeviceClass=Dummy(), SensorEntity=object, SensorStateClass=Dummy())
mod("homeassistant.config_entries", ConfigEntry=object)
mod("homeassistant.const", UnitOfPower=Dummy())
mod("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
mod("homeassistant.helpers.event", async_track_state_change_event=None, async_track_time_change=None)
mod("homeassistant.helpers.storage", Store=Store)
sys.modules["homeassistant.util"].dt = dt_util
sys.path.insert(0, sys.argv[1])
import importlib
pkg = types.ModuleType("e15"); pkg.__path__ = [sys.argv[1] + "/elektro_15min_average"]; sys.modules["e15"] = pkg
s = importlib.import_module("e15.sensor")

t0 = datetime(2026, 11, 15, 16, 0, tzinfo=UTC)
a = s.IntervalAverager(None, "x")
a.add_sample(500, t0)
a.add_sample(2500, t0 + timedelta(minutes=5))
live = a.current_averages(until=t0 + timedelta(minutes=10))
assert round(live.time_weighted) == 1500, live           # (500*5 + 2500*5)/10
fin = a.finalize_until(t0 + timedelta(minutes=15))
assert round(fin.averages.time_weighted) == 1833, fin.averages   # (500*5+2500*10)/15
assert fin.averages.arithmetic == 1500
# Next interval carries the last value from the boundary.
a.add_sample(1000, t0 + timedelta(minutes=20))
assert round(a.current_averages(until=t0+timedelta(minutes=25)).time_weighted) == 1750  # (2500*5+1000*5)/10
# until is capped at the interval end
assert round(a.current_averages(until=t0+timedelta(hours=2)).time_weighted) == round((2500*300+1000*600)/900)

# Restore: a finished interval is dropped.
asyncio.run(a.async_save())
NOW[0] = t0 + timedelta(hours=3)
b = s.IntervalAverager(None, "x")
assert asyncio.run(b.async_restore()) is False and b.interval_start is None
# Restore inside the same interval: data kept, downtime not weighted.
NOW[0] = t0 + timedelta(minutes=26)
c = s.IntervalAverager(None, "x")
assert asyncio.run(c.async_restore()) is True
assert c.last_sample_ts is None and c.restart_detected
c.add_sample(200, t0 + timedelta(minutes=28))   # 25→28 downtime must not count
fin = c.finalize_until(t0 + timedelta(minutes=30))
exp = (2500*300 + 200*120) / 420   # only measured time counts
assert round(fin.averages.time_weighted) == round(exp), (fin.averages, exp)
print("all tests passed")
