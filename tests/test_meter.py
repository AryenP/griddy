"""powermetrics parsing. The block below is the field layout `make probe` prints on this Mac;
numbers are a test fixture, not a measurement."""
from meter.powermetrics import parse_sample, reading_from

BLOCK = """*** Sampled system activity (Thu Oct 23 21:50:01 2026 -0700) (1003.12ms elapsed) ***

**** Processor usage ****

CPU Power: 1234 mW
GPU Power: 56 mW
ANE Power: 0 mW
Combined Power (CPU + GPU + ANE): 1290 mW

**** GPU usage ****

GPU HW active frequency: 444 MHz
GPU Power: 56 mW
"""


def test_parse_fields():
    f = parse_sample(BLOCK)
    assert f == {"cpu": 1.234, "gpu": 0.056, "ane": 0.0, "combined": 1.29}


def test_reading_prefers_combined_and_lists_fields():
    r = reading_from(parse_sample(BLOCK), t=1.0)
    assert r.combined_w == 1.29 and r.cpu_w == 1.234 and r.fields == ["ane", "combined", "cpu", "gpu"]


def test_reading_sums_when_no_combined_line():
    r = reading_from({"cpu": 2.0, "gpu": 1.0})
    assert r.combined_w == 3.0 and r.ane_w is None


def test_meter_splits_on_headers_only():
    """macOS 15 repeats GPU Power after Combined; a trailing line must not become its own reading."""
    from meter.powermetrics import PowerMeter
    m = PowerMeter()
    got = []
    m.subscribers.append(got.append)
    for block in (BLOCK, BLOCK):
        m._emit(block)
    m._emit("GPU Power: 56 mW\n")          # orphan line: ignored
    assert [r.combined_w for r in got] == [1.29, 1.29]


def test_only_one_run_measures_power_at_a_time(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("fcntl")          # the lock is POSIX-only; Windows can still run the rest of the suite
    import meter.powermetrics as pm
    monkeypatch.setattr(pm, "LOCK", tmp_path / ".meter.lock")
    a, b = pm.PowerMeter(), pm.PowerMeter()
    a._acquire()
    with pytest.raises(pm.MeterBusy, match="another run is measuring power"):
        b._acquire()
    a._release()
    b._acquire()                          # free again once the first run releases it
    b._release()
