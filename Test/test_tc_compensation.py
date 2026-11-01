import pytest

import config
from lib.temp import compensate, corrected_temp


def test_offset_used_when_compensation_off(monkeypatch):
    monkeypatch.setattr(config, 'tc_compensation', False, raising=False)
    monkeypatch.setattr(config, 'temp_scale', 'c')
    monkeypatch.setattr(config, 'thermocouple_offset', -4)
    assert corrected_temp(100) == 96


def test_offset_is_display_scale_delta(monkeypatch):
    monkeypatch.setattr(config, 'tc_compensation', False, raising=False)
    monkeypatch.setattr(config, 'temp_scale', 'f')
    monkeypatch.setattr(config, 'thermocouple_offset', 9)
    assert corrected_temp(100) == pytest.approx(105)


def test_missing_setting_means_off(monkeypatch):
    monkeypatch.delattr(config, 'tc_compensation', raising=False)
    monkeypatch.setattr(config, 'temp_scale', 'c')
    monkeypatch.setattr(config, 'thermocouple_offset', 0)
    assert corrected_temp(500) == 500


def test_compensation_ignores_offset(monkeypatch):
    monkeypatch.setattr(config, 'tc_compensation', True, raising=False)
    monkeypatch.setattr(config, 'thermocouple_offset', 50)
    monkeypatch.setattr(config, 'tc_compensation_curve',
                        [(None, (0, 2))], raising=False)
    assert corrected_temp(100) == 200


def test_compensate_picks_segment():
    curve = [(10, (0, 1)), (20, (100,)), (None, (0, 0, 1))]
    assert compensate(5, curve) == 5
    assert compensate(10, curve) == 10      # bound is inclusive
    assert compensate(15, curve) == 100
    assert compensate(30, curve) == 900


def test_default_curve_is_continuous():
    '''the shipped curve must not jump at its breakpoints, or the PID
    sees a sudden temperature step mid-firing'''
    curve = config.tc_compensation_curve
    for (upper, coeffs), (_, next_coeffs) in zip(curve, curve[1:]):
        below = compensate(upper, [(None, coeffs)])
        above = compensate(upper, [(None, next_coeffs)])
        assert above == pytest.approx(below, abs=0.5), upper


def test_default_curve_is_increasing():
    curve = config.tc_compensation_curve
    readings = [compensate(t, curve) for t in range(0, 1400, 5)]
    assert all(b > a for a, b in zip(readings, readings[1:]))
