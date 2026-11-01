import sys
import types

import pytest

import config
import lib.oven as oven
from lib.oven import Modbus, Modbus_Error


class NoResponseError(OSError):
    '''stands in for minimalmodbus.NoResponseError (an OSError subclass)'''


class FakeInstrument:
    instances = []

    def __init__(self, port, slave):
        self.port = port
        self.slave = slave
        self.serial = types.SimpleNamespace(baudrate=None, parity=None,
                                            stopbits=None, timeout=None)
        self.register_value = 0
        self.status_value = 0
        self.float_value = 0.0
        self.error = None
        self.calls = []
        FakeInstrument.instances.append(self)

    def read_register(self, register, decimals, functioncode=3, signed=False):
        if register == getattr(config, 'modbus_status_register', None):
            self.calls.append(('status', register, functioncode))
            if self.error:
                raise self.error
            return self.status_value
        self.calls.append(('register', register, decimals, functioncode, signed))
        if self.error:
            raise self.error
        return self.register_value

    def read_float(self, register, functioncode=3, number_of_registers=2, byteorder=0):
        self.calls.append(('float', register, functioncode, byteorder))
        if self.error:
            raise self.error
        return self.float_value


@pytest.fixture
def modbus(monkeypatch):
    FakeInstrument.instances = []
    monkeypatch.setitem(sys.modules, 'minimalmodbus',
                        types.SimpleNamespace(Instrument=FakeInstrument))

    def no_spi(*a, **k):
        raise AssertionError("modbus sensor must not touch spi")

    monkeypatch.setattr(oven, 'digitalio', types.SimpleNamespace(DigitalInOut=no_spi))
    monkeypatch.setattr(oven, 'bitbangio', types.SimpleNamespace(SPI=no_spi))
    settings = dict(modbus=1, modbus_port_name='/dev/ttyUSB0',
                    modbus_slave_address=3, modbus_baudrate=38400,
                    modbus_registernumber=12, modbus_decimal=1,
                    modbus_functioncode=3, modbus_signed=True,
                    modbus_format='int', modbus_byteorder=0,
                    modbus_parity='N', modbus_stopbits=1, modbus_timeout=0.5,
                    modbus_fault_values=[32767, -32768],
                    modbus_status_register=None, modbus_status_open_bits=[],
                    modbus_status_error_bits=[],
                    sensor_time_wait=2, temperature_average_samples=5,
                    ignore_tc_unknown_error=False, ignore_tc_lost_connection=False)
    for key, value in settings.items():
        monkeypatch.setattr(config, key, value, raising=False)

    def make():
        sensor = Modbus()
        return sensor, FakeInstrument.instances[-1]
    return make


def test_serial_settings(modbus):
    sensor, inst = modbus()
    assert (inst.port, inst.slave) == ('/dev/ttyUSB0', 3)
    assert inst.serial.baudrate == 38400
    assert inst.serial.parity == 'N'
    assert inst.serial.stopbits == 1
    assert inst.serial.timeout == 0.5
    assert not hasattr(sensor, 'spi')


def test_int_register_scaled_by_decimals(modbus):
    sensor, inst = modbus()
    inst.register_value = 12345
    assert sensor.raw_temp() == pytest.approx(1234.5)
    assert inst.calls[-1] == ('register', 12, 0, 3, True)


def test_input_registers_and_no_decimals(modbus, monkeypatch):
    monkeypatch.setattr(config, 'modbus_functioncode', 4)
    monkeypatch.setattr(config, 'modbus_decimal', 0)
    sensor, inst = modbus()
    inst.register_value = 1222
    assert sensor.raw_temp() == 1222
    assert inst.calls[-1][3] == 4


def test_float_format(modbus, monkeypatch):
    monkeypatch.setattr(config, 'modbus_format', 'float')
    monkeypatch.setattr(config, 'modbus_byteorder', 1)
    sensor, inst = modbus()
    inst.float_value = 1031.25
    assert sensor.raw_temp() == 1031.25
    assert inst.calls[-1] == ('float', 12, 3, 1)


def test_fault_value_is_not_connected(modbus):
    sensor, inst = modbus()
    inst.register_value = 32767
    with pytest.raises(Modbus_Error) as exc:
        sensor.raw_temp()
    assert exc.value.message == 'not connected'
    assert '32767' in exc.value.orig_message


def test_comms_error_is_unknown(modbus):
    sensor, inst = modbus()
    inst.error = NoResponseError("No communication with the instrument (no answer)")
    with pytest.raises(Modbus_Error) as exc:
        sensor.raw_temp()
    assert exc.value.message == 'unknown'
    assert 'no answer' in exc.value.orig_message


def test_malformed_reply_is_unknown(modbus):
    sensor, inst = modbus()
    inst.error = ValueError("bad checksum")
    with pytest.raises(Modbus_Error) as exc:
        sensor.raw_temp()
    assert exc.value.message == 'unknown'


def test_errors_counted_by_tracker(modbus):
    sensor, inst = modbus()
    inst.error = NoResponseError("no answer")
    assert sensor.get_temperature() is None
    assert sensor.status.error_percent() > 0
    inst.error = None
    inst.register_value = 250
    assert sensor.get_temperature() == 25.0


def test_ignore_unknown_applies_to_comms_errors(modbus, monkeypatch):
    monkeypatch.setattr(config, 'ignore_tc_unknown_error', True)
    sensor, inst = modbus()
    inst.error = NoResponseError("no answer")
    assert sensor.get_temperature() is None
    assert sensor.status.error_percent() == 0


def test_old_pr_config_without_new_keys(modbus, monkeypatch):
    '''configs written for upstream PR #245 only have the original keys'''
    for key in ('modbus_functioncode', 'modbus_signed', 'modbus_format',
                'modbus_byteorder', 'modbus_parity', 'modbus_stopbits',
                'modbus_timeout', 'modbus_fault_values',
                'modbus_status_register', 'modbus_status_open_bits',
                'modbus_status_error_bits'):
        monkeypatch.delattr(config, key, raising=False)
    sensor, inst = modbus()
    inst.register_value = 9876
    assert sensor.raw_temp() == pytest.approx(987.6)


def test_board_prefers_modbus(modbus, monkeypatch):
    monkeypatch.setattr(config, 'max31855', 1)
    monkeypatch.setitem(sys.modules, 'board', types.SimpleNamespace(board_id='TEST'))
    started = []
    monkeypatch.setattr(oven.Modbus, 'start', lambda self: started.append(self))
    board = oven.RealBoard()
    assert isinstance(board.temp_sensor, Modbus)
    assert started == [board.temp_sensor]


def test_board_without_modbus_setting(monkeypatch):
    monkeypatch.delattr(config, 'modbus', raising=False)
    monkeypatch.setattr(config, 'max31855', 1)
    picked = []
    monkeypatch.setattr(oven, 'Max31855', lambda: picked.append('max31855') or 'sensor')
    assert oven.RealBoard.choose_tempsensor(object()) == 'sensor'
    assert picked == ['max31855']


@pytest.fixture
def z4tc(modbus, monkeypatch):
    '''Seneca Z-4TC, thermocouple on input 1'''
    monkeypatch.setattr(config, 'modbus_status_register', 11)
    monkeypatch.setattr(config, 'modbus_status_open_bits', [12])
    monkeypatch.setattr(config, 'modbus_status_error_bits', [8])
    return modbus


def test_status_checked_before_temperature(z4tc):
    sensor, inst = z4tc()
    inst.register_value = 220
    assert sensor.raw_temp() == pytest.approx(22.0)
    assert [c[0] for c in inst.calls] == ['status', 'register']
    assert inst.calls[0] == ('status', 11, 3)


def test_status_burnout_is_not_connected(z4tc):
    sensor, inst = z4tc()
    inst.status_value = 1 << 12
    with pytest.raises(Modbus_Error) as exc:
        sensor.raw_temp()
    assert exc.value.message == 'not connected'
    assert 'bit 12' in exc.value.orig_message


def test_status_acquisition_error_is_unknown(z4tc):
    sensor, inst = z4tc()
    inst.status_value = 1 << 8
    with pytest.raises(Modbus_Error) as exc:
        sensor.raw_temp()
    assert exc.value.message == 'unknown'


def test_other_inputs_status_bits_ignored(z4tc):
    '''a burn-out on input 2-4 must not stop a kiln wired to input 1'''
    sensor, inst = z4tc()
    inst.status_value = (1 << 13) | (1 << 14) | (1 << 15) | (1 << 9)
    inst.register_value = 12220
    assert sensor.raw_temp() == pytest.approx(1222.0)


def test_status_read_failure_is_comms_error(z4tc):
    sensor, inst = z4tc()
    inst.error = NoResponseError("no answer")
    with pytest.raises(Modbus_Error) as exc:
        sensor.raw_temp()
    assert exc.value.message == 'unknown'


def test_no_status_read_when_disabled(modbus):
    sensor, inst = modbus()
    inst.register_value = 100
    sensor.raw_temp()
    assert [c[0] for c in inst.calls] == ['register']
