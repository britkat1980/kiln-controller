# Modbus thermocouple modules

Instead of a MAX31855/MAX31856 breakout board, the controller can read the
temperature from an industrial thermocouple input module over Modbus RTU
(RS-485). The module does the thermocouple conversion and cold junction
compensation itself. Modules like the Seneca Z-4TC have been reported
stable to 1260°C where MAX31856 boards struggled above 900°C
(see upstream PR #245).

The heater relay is still driven from a GPIO pin as usual.

## Wiring

Raspberry Pi USB → USB RS-485 adapter → module A/B terminals (and GND if
the module has it). The adapter usually appears as `/dev/ttyUSB0`.
Check with `ls /dev/ttyUSB*` after plugging it in.

## Configure the module

Using the manufacturer's tool or DIP switches, set:

- the thermocouple type (K, N, S, ...)
- the reading in **degrees C**
- the slave address, baud rate and parity
- 50 Hz mains rejection, if the module has the option (UK/EU)

## Configure the controller

In `config.py`:

```python
modbus = 1                     # takes priority over max31855 / max31856
modbus_port_name = "/dev/ttyUSB0"
modbus_slave_address = 1
modbus_baudrate = 38400
modbus_parity = "N"
modbus_stopbits = 1
modbus_registernumber = 12     # 0-based address: a manual's "40013" is 12
modbus_functioncode = 3        # 3 holding registers, 4 input registers
modbus_format = "int"          # or "float" for 32-bit float readings
modbus_decimal = 1             # int: register holds tenths of a degree
modbus_signed = True
modbus_fault_values = []       # raw values some modules use to flag an open thermocouple
modbus_status_register = 11    # or None: a register whose bits flag faults
modbus_status_open_bits = [12] # set -> "not connected"
modbus_status_error_bits = [8] # set -> "unknown"
```

Find the register, function code, format and fault reporting in the
module's manual. Modules flag an open thermocouple either with a special
reading (`modbus_fault_values`) or with bits in a status register
(`modbus_status_*`). Without one of these set, an open thermocouple
would not be detected.

### Seneca Z-4TC

The defaults above are for a Z-4TC with the thermocouple on input 1
(register map from user manual MI00258):

| Address (`modbus_registernumber`) | Manual | Contents |
|---|---|---|
| 11 | 40012 | status: bits 12–15 input 1–4 burn-out, bits 8–11 input 1–4 acquisition error |
| 12–15 | 40013–40016 | input 1–4, signed, °C × 10 (`modbus_decimal = 1`) |
| 26, 28, 30, 32 | 40027–40034 | input 1–4, 32-bit float °C (`modbus_format = "float"`, firmware 667+) |

For another input, change `modbus_registernumber` and both status bit
lists, e.g. input 2 is register 13, open bit 13 and error bit 9.

- Function code 3 only.
- Set the thermocouple type with Seneca's Easy-SETUP software or over
  Modbus (registers 40004–40007).
- Burn-out detection is on by default.
- The RS-485 baud rate, parity and address come from the module's DIP
  switches or Easy-SETUP. Make `config.py` match them.

## Test

```bash
source venv/bin/activate
./test-thermocouple.py
```

This uses the same code as the controller and prints a reading every
second. Warm the thermocouple and check the reading rises.

## Errors

| Problem | Reported as | Ignore with |
|---|---|---|
| no reply, bad CRC, serial port error | `unknown` | `ignore_tc_unknown_error` |
| reading equals one of `modbus_fault_values` | `not connected` | `ignore_tc_lost_connection` |

Failed reads count towards the thermocouple error rate like any other
board, so a module that stops answering trips the too-many-errors
shutoff (unless `ignore_tc_too_many_errors` is set) and the thermocouple
alerts.

`tc_compensation` and `thermocouple_offset` still apply to the
module's readings.
