'''heat-work model (lib/heatwork.py): the fitted cone models must reproduce
orton's self-supporting chart, and the oven must accumulate heat-work the
way a cone experiences the firing.'''
import types

import pytest

import config
import heatwork
from heatwork import CONE_MODELS, HeatWork, cone_label, equivalent_cone

INDEX = {cone: i for i, (cone, _, _) in enumerate(CONE_MODELS)}


def ramp(end, rate, start=20.0, hold=0, step=20.0):
    '''(t, temp) samples for a constant ramp from start to end at rate
    degC/h, then an optional hold in seconds'''
    t, temp, out = 0.0, start, []
    while temp < end:
        out.append((t, temp))
        t += step
        temp += rate * step / 3600.0
    out.append((t, end))
    for _ in range(int(hold / step)):
        t += step
        out.append((t, end))
    return out


@pytest.mark.parametrize('cone', ['010', '06', '04', '1', '5', '6', '7', '10'])
@pytest.mark.parametrize('rate_i,rate', [(0, 15), (1, 60), (2, 150)])
def test_chart_temperature_reaches_that_cone(cone, rate_i, rate):
    '''a steady ramp to orton's temperature for a cone lands on that cone.
    the fit is within about 3 degC, and neighbouring high cones can be
    only 10 degC apart, so allow a third of a cone'''
    temp = heatwork.ORTON_SELF_SUPPORTING[cone][rate_i]
    index, _ = equivalent_cone(ramp(temp, rate))
    assert index == pytest.approx(INDEX[cone], abs=0.35)


def test_hold_adds_heat_work():
    plain, _ = equivalent_cone(ramp(1222, 60))
    held, label = equivalent_cone(ramp(1222, 60, hold=900))
    assert held > plain + 0.4
    assert label.startswith('6.')


def test_fast_finish_falls_short():
    '''the same peak reached fast is less heat-work: 150C/h to 1222C does
    not make cone 6'''
    index, _ = equivalent_cone(ramp(1222, 150))
    assert index < INDEX['6']


def test_cold_firing_has_no_cone():
    assert equivalent_cone(ramp(500, 60)) == (None, None)
    assert HeatWork().equivalent() == (None, None)


def test_long_gaps_are_capped():
    '''a gap in the record (controller restart) is not hours at temperature'''
    gap = [(0, 1200.0), (6 * 3600, 1200.0)]
    capped = HeatWork()
    capped.add(1200.0, 600.0)
    assert equivalent_cone(gap) == capped.equivalent()


def test_labels():
    assert cone_label(INDEX['5'], 0.43) == '5.4'
    assert cone_label(INDEX['6'], 0.0) == '6.0'
    assert cone_label(INDEX['04'], 0.3) == '04+30%'
    assert cone_label(INDEX['04'], 0.0) == '04'


def test_restore_round_trip():
    work = HeatWork()
    for _, temp in ramp(1200, 100):
        work.add(temp, 20.0)
    copy = HeatWork()
    assert copy.restore(work.to_list())
    assert copy.equivalent() == work.equivalent()
    assert not copy.restore('nonsense')
    assert not copy.restore([1.0, 2.0])
    assert copy.equivalent() == work.equivalent()


########################################################################
# oven integration
########################################################################

class Sensor:
    def __init__(self, temp, stale=0.0):
        self.temp = temp
        self.stale = stale
        self.status = types.SimpleNamespace(over_error_limit=lambda: False)

    def temperature(self):
        return self.temp

    def seconds_since_valid_reading(self):
        return self.stale


@pytest.fixture
def oven(monkeypatch):
    import lib.oven as oven_module
    clock = types.SimpleNamespace(now=1000.0)
    monkeypatch.setattr(oven_module.time, 'time', lambda: clock.now)
    monkeypatch.setattr(config, 'automatic_restarts', False)
    o = oven_module.Oven()
    o.board = types.SimpleNamespace(temp_sensor=Sensor(1200.0))
    o.clock = clock
    return o


def tick(o, seconds):
    o.clock.now += seconds
    o.update_heat_work()


def test_oven_accumulates_while_hot(oven):
    oven.update_heat_work()       # first call only starts the clock
    for _ in range(60):
        tick(oven, 30)
    index, label = oven.heat_work.equivalent()
    assert index is not None
    state = oven.get_state()
    assert state['cone'] == label
    assert state['cone_index'] == round(index, 2)


def test_oven_skips_stale_readings(oven):
    oven.board.temp_sensor.stale = 45
    oven.update_heat_work()
    for _ in range(60):
        tick(oven, 30)
    assert oven.heat_work.equivalent() == (None, None)


def test_oven_caps_long_gaps(oven):
    oven.update_heat_work()
    tick(oven, 3600)
    one_minute = HeatWork()
    one_minute.add(1200.0, 60.0)
    assert oven.heat_work.to_list() == one_minute.to_list()


def test_new_run_starts_from_zero(oven, monkeypatch):
    oven.update_heat_work()
    tick(oven, 600)
    assert oven.heat_work.equivalent()[0] is not None
    profile = types.SimpleNamespace(name='p', get_duration=lambda: 3600,
                                    data=[[0, 20], [3600, 1000]])
    monkeypatch.setattr(oven, 'save_automatic_restart_state', lambda *a, **k: None)
    oven.run_profile(profile, allow_seek=False)
    assert oven.heat_work.equivalent() == (None, None)


########################################################################
# home assistant and recorded firings
########################################################################

def test_home_assistant_publishes_cone(monkeypatch):
    import homeassistant
    monkeypatch.setattr(config, 'mqtt_kiln_name', 'K', raising=False)
    ha = homeassistant.HomeAssistant(lambda *a: (True, None), lambda: [],
                                     client=types.SimpleNamespace(publish=lambda *a, **k: None))
    msgs = dict(ha.state_messages({'state': 'IDLE', 'cone': '5.4',
                                   'cone_index': INDEX['5'] + 0.43}))
    assert msgs['cone'] == '5.4'
    assert msgs['cone_number'] == pytest.approx(5.43)
    msgs = dict(ha.state_messages({'state': 'IDLE', 'cone': None, 'cone_index': None}))
    assert msgs['cone'] == 'None' and msgs['cone_number'] == 'None'
    # cone 01 is 0, cone 02 is -1
    msgs = dict(ha.state_messages({'state': 'IDLE', 'cone': '02', 'cone_index': INDEX['02']}))
    assert msgs['cone_number'] == -1


def test_recorded_firing_cone_in_fahrenheit():
    '''the firing db stores display-scale temperatures'''
    samples = [{'t': t, 'temp': temp * 9 / 5 + 32} for t, temp in ramp(1222, 60)]
    samples.append({'t': 'bad', 'temp': None})
    result = heatwork.recorded_firing_cone(samples, 'f')
    expected, label = equivalent_cone(ramp(1222, 60))
    assert result['cone'] == label
    assert result['cone_index'] == pytest.approx(expected, abs=0.01)
    celsius = [{'t': t, 'temp': temp} for t, temp in ramp(1222, 60)]
    assert heatwork.recorded_firing_cone(celsius, 'c')['cone'] == label


def test_heat_work_errors_never_reach_the_control_loop(oven, monkeypatch):
    '''the cone figure is display only: a fault in it must not stop the
    oven loop from controlling the kiln'''
    def broken(*a, **k):
        raise RuntimeError('boom')
    monkeypatch.setattr(oven.heat_work, 'add', broken)
    oven.update_heat_work()
    tick(oven, 30)  # must not raise


def test_heat_work_without_a_board():
    import lib.oven as oven_module
    bare = oven_module.Oven()
    bare.update_heat_work()
    bare.update_heat_work()  # must not raise
