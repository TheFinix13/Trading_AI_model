"""Tests for the online performance memory (lightweight learning)."""
from agent.journal.performance_memory import (
    PerformanceMemory,
    SignatureStats,
    make_signature,
)


def test_make_signature_is_stable_and_descriptive():
    sig = make_signature("FVGRetest", "long", "London", True, "reaction")
    assert sig == "FVGRetest|long|london|htfAlign|reaction"
    assert make_signature("x", "short", "", None, "anticipation").endswith("|htfNA|anticipation")
    assert "htfMiss" in make_signature("x", "long", "ny", False, "reaction")


def test_stats_expectancy_and_winrate():
    st = SignatureStats()
    for r in (2.0, -1.0, 2.0, -1.0):
        st.record(r)
    assert st.n == 4
    assert st.wins == 2 and st.losses == 2
    assert abs(st.win_rate - 0.5) < 1e-9
    assert abs(st.expectancy_r - 0.5) < 1e-9


def test_adjustment_zero_below_min_samples():
    pm = PerformanceMemory(min_samples=4, autosave=False)
    pm.record("s", 2.0)
    pm.record("s", 2.0)
    assert pm.conviction_adjustment("s") == 0.0  # only 2 < 4 samples


def test_positive_expectancy_raises_conviction():
    pm = PerformanceMemory(min_samples=4, max_adjustment=0.20, autosave=False)
    for _ in range(10):
        pm.record("win", 1.0)
    adj = pm.conviction_adjustment("win")
    assert adj > 0.0
    assert adj <= 0.20


def test_negative_expectancy_lowers_conviction():
    pm = PerformanceMemory(min_samples=4, max_adjustment=0.20, autosave=False)
    for _ in range(10):
        pm.record("lose", -1.0)
    assert pm.conviction_adjustment("lose") < 0.0


def test_adjustment_is_bounded():
    pm = PerformanceMemory(min_samples=4, max_adjustment=0.20, autosave=False)
    for _ in range(50):
        pm.record("huge", 5.0)  # huge expectancy, many samples
    assert pm.conviction_adjustment("huge") <= 0.20


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "perf.json"
    pm = PerformanceMemory(path, autosave=True)
    pm.record("a", 2.0)
    pm.record("a", -1.0)
    pm.record("b", 1.5)

    reloaded = PerformanceMemory(path, autosave=False)
    assert len(reloaded) == 2
    assert reloaded.get("a").n == 2
    assert abs(reloaded.get("a").sum_r - 1.0) < 1e-9


def test_summary_rows_sorted_by_expectancy():
    pm = PerformanceMemory(min_samples=1, autosave=False)
    pm.record("bad", -1.0)
    pm.record("good", 2.0)
    rows = pm.summary_rows()
    assert rows[0]["signature"] == "good"
    assert rows[-1]["signature"] == "bad"
