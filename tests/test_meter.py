import numpy as np

from stt.meter import bar, rms


def test_rms_of_a_constant_frame():
    assert rms(np.full(1000, 0.1, dtype=np.float32)) == 0.1


def test_rms_of_silence_and_empty():
    assert rms(np.zeros(1000, dtype=np.float32)) == 0.0
    assert rms(np.zeros(0, dtype=np.float32)) == 0.0


def test_rms_accepts_a_2d_block():
    assert abs(rms(np.full((500, 1), 0.2, dtype=np.float32)) - 0.2) < 1e-6


def test_bar_empty_at_zero_and_full_at_scale():
    assert bar(0.0, width=10, full_scale=0.3) == "-" * 10
    assert bar(0.3, width=10, full_scale=0.3) == "#" * 10


def test_bar_is_half_at_half_scale():
    assert bar(0.15, width=10, full_scale=0.3) == "#" * 5 + "-" * 5


def test_bar_clamps_above_full_scale():
    assert bar(9.0, width=10, full_scale=0.3) == "#" * 10
