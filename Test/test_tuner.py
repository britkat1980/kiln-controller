import types

from lib.tuner import Tuner


class StubOven:
    def __init__(self, state='IDLE'):
        self.state = state
        self.output = types.SimpleNamespace(cool=lambda secs: None)
        self.heat = 0


def make_tuner(oven_state='IDLE'):
    oven = StubOven(oven_state)
    return Tuner(oven), oven


def stub_tuning_steps(tuner, monkeypatch, calls):
    '''replace the blocking/hardware parts so start() runs instantly'''
    monkeypatch.setattr(tuner, '_record', lambda target: calls.append('record'))

    def fake_calculate():
        calls.append('calc')
        tuner.pid_values = {'kp': 1.0, 'ki': 1.0, 'kd': 1.0}

    monkeypatch.setattr(tuner, '_calculate', fake_calculate)
    monkeypatch.setattr(tuner, '_apply_pid', lambda: calls.append('apply'))


def test_start_runs_full_sequence(monkeypatch):
    tuner, oven = make_tuner()
    calls = []
    stub_tuning_steps(tuner, monkeypatch, calls)

    tuner.start(100.0)

    assert tuner.state == Tuner.DONE
    assert oven.state == 'IDLE'
    assert calls == ['record', 'calc', 'apply']


def test_start_allowed_again_after_done(monkeypatch):
    '''the tuner must be re-runnable without a process restart; it used to
    lock up after its first run because DONE was treated as "running"'''
    tuner, oven = make_tuner()
    calls = []
    stub_tuning_steps(tuner, monkeypatch, calls)

    tuner.start(100.0)
    assert tuner.state == Tuner.DONE

    tuner.start(150.0)
    assert tuner.state == Tuner.DONE
    assert calls == ['record', 'calc', 'apply'] * 2


def test_start_allowed_again_after_error(monkeypatch):
    '''a failed tuning run must not block future attempts'''
    tuner, oven = make_tuner()
    calls = []
    stub_tuning_steps(tuner, monkeypatch, calls)

    def boom():
        raise ValueError('no usable data')

    monkeypatch.setattr(tuner, '_record', lambda target: calls.append('record'))
    monkeypatch.setattr(tuner, '_calculate', boom)

    tuner.start(100.0)
    assert tuner.state == Tuner.ERROR

    stub_tuning_steps(tuner, monkeypatch, calls)
    tuner.start(100.0)
    assert tuner.state == Tuner.DONE


def test_stop_during_record_returns_to_idle(monkeypatch):
    '''stopping mid-tune used to leave the state stuck at HEATING forever'''
    tuner, oven = make_tuner()
    started = []

    def fake_record(target):
        started.append(1)
        tuner.stop()    # user hits stop while the heating loop is running

    monkeypatch.setattr(tuner, '_record', fake_record)

    tuner.start(100.0)  # record exits early on _stop_requested

    assert started == [1]
    assert tuner.state == Tuner.IDLE
    assert oven.state == 'IDLE'


def test_start_rejected_when_oven_busy():
    tuner, oven = make_tuner(oven_state='RUNNING')

    tuner.start(100.0)

    assert tuner.state == Tuner.ERROR
    assert 'busy' in tuner.error
    assert oven.state == 'RUNNING'


def _real_config_module(tmp_path, monkeypatch, local_text=None):
    '''a real module from a tmp config.py ending in config.py's own
    config_local.py loader, swapped in for lib.tuner's config'''
    import importlib.util
    import os
    import sys
    import uuid
    import lib.tuner as tuner_module
    root = os.path.join(os.path.dirname(__file__), '..')
    with open(os.path.join(root, 'config.py'), encoding='utf-8') as f:
        loader = f.read().split('# local settings - keep this last.')[1]
    path = tmp_path / 'config.py'
    path.write_text('import os\npid_kp = 4.112\npid_ki = 32.972\npid_kd = 139.384\n' + loader)
    if local_text is not None:
        (tmp_path / 'config_local.py').write_text(local_text, encoding='utf-8')
    name = 'tuner_cfg_%s' % uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)

    class Finder:
        '''lets importlib.reload find the tmp module again'''
        @staticmethod
        def find_spec(fullname, path=None, target=None):
            return spec if fullname == name else None

    monkeypatch.setattr(sys, 'meta_path', [Finder] + sys.meta_path)
    monkeypatch.setattr(tuner_module, 'config', module)
    return module, path


def test_apply_pid_adds_values_to_config_local(tmp_path, monkeypatch):
    module, path = _real_config_module(tmp_path, monkeypatch,
                                       local_text='simulate = False\n')
    before = path.read_text()
    tuner, _ = make_tuner()
    tuner.pid_values = {'kp': 7.5, 'ki': 18.8, 'kd': 270.7}
    tuner._apply_pid()
    local = (tmp_path / 'config_local.py').read_text(encoding='utf-8')
    assert local == 'simulate = False\npid_kp = 7.5\npid_ki = 18.8\npid_kd = 270.7\n'
    assert path.read_text() == before  # defaults untouched
    assert (module.pid_kp, module.pid_ki, module.pid_kd) == (7.5, 18.8, 270.7)


def test_apply_pid_replaces_values_in_config_local(tmp_path, monkeypatch):
    module, path = _real_config_module(
        tmp_path, monkeypatch,
        local_text='pid_kp = 1.0\npid_ki = 2.0\npid_kd = 3.0\nsimulate = False\n')
    tuner, _ = make_tuner()
    tuner.pid_values = {'kp': 7.5, 'ki': 18.8, 'kd': 270.7}
    tuner._apply_pid()
    local = (tmp_path / 'config_local.py').read_text(encoding='utf-8')
    assert local == 'pid_kp = 7.5\npid_ki = 18.8\npid_kd = 270.7\nsimulate = False\n'
    assert module.pid_kd == 270.7


def test_apply_pid_writes_config_py_without_local(tmp_path, monkeypatch):
    module, path = _real_config_module(tmp_path, monkeypatch)
    tuner, _ = make_tuner()
    tuner.pid_values = {'kp': 7.5, 'ki': 18.8, 'kd': 270.7}
    tuner._apply_pid()
    assert 'pid_kp = 7.5\npid_ki = 18.8\npid_kd = 270.7\n' in path.read_text()
    assert module.pid_ki == 18.8
