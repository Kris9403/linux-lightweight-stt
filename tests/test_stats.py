import logging

from stt.stats import Timings


def test_empty_summary():
    t = Timings()
    assert len(t) == 0
    assert "no transcriptions" in t.summary()


def test_summary_reports_count_mean_and_extremes():
    t = Timings()
    for s in (0.1, 0.2, 0.3):        # 100, 200, 300 ms
        t.add(s)
    out = t.summary()
    assert out.startswith("3 transcriptions")
    assert "mean 200 ms" in out
    assert "min 100" in out and "max 300" in out


def test_p95_picks_a_high_sample():
    t = Timings()
    for i in range(100):
        t.add(i / 1000)             # 0..99 ms
    assert "p95 95" in t.summary()


def test_log_summary_emits_one_info_line(caplog):
    t = Timings()
    t.add(0.05)
    with caplog.at_level(logging.INFO, logger="stt"):
        t.log_summary()
    assert "latency:" in caplog.text
    assert "1 transcriptions" in caplog.text
