# Home Assistant

The controller can appear in Home Assistant as a single device using
[MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery).
No YAML is needed on the Home Assistant side, just the MQTT integration
pointed at the same broker.

## Setup

In `config.py`:

```python
mqtt_enable = True
mqtt_host = "192.168.1.10"
mqtt_port = 1883
mqtt_user = "mqtt"
mqtt_pass = "secret"
mqtt_kiln_name = "My_Kiln"      # no spaces or slashes, it is part of every topic
mqtt_ha_discovery = True
mqtt_ha_interval = 15           # seconds between state publishes
mqtt_ha_prefix = "homeassistant"
mqtt_ha_currency = "GBP"        # ISO 4217 code for the cost sensor
```

Restart the controller. The device appears under the MQTT integration,
named after `mqtt_kiln_name`.

`mqtt_enable` also turns on the upstream JSON state stream on `mqtt_topic`
(default `kiln/sensor`). Both can run side by side.

## Entities

| Entity | Topic |
|---|---|
| temperature, temperature raw, target, heat rate, cost | `<kiln>/<key>` |
| state, profile, name | `<kiln>/state`, `<kiln>/profile`, `<kiln>/name` |
| heat, catching up (binary sensors, `1`/`0`) | `<kiln>/heat`, `<kiln>/catching_up` |
| running time, duration (`H:MM:SS`) | `<kiln>/runtime`, `<kiln>/totaltime` |
| end time (`HH:MM:SS`, `-` when idle), progress (%) | `<kiln>/endtime`, `<kiln>/progress` |
| schedule (running profile, `None` when idle; attributes below) | `<kiln>/schedule`, `<kiln>/schedule/attributes` |
| PID stats | `<kiln>/pidstats/<key>` |
| availability (`online` / `offline`, last will) | `<kiln>/status` |

State is published every `mqtt_ha_interval` seconds, and straight away when
the oven state or running profile changes. Everything is retained so
Home Assistant has values immediately after it restarts. Discovery is
re-sent when Home Assistant announces itself on `<prefix>/status`, and when
the list of profiles changes.

## Firing graph

The schedule sensor's attributes hold the running profile as wall-clock
points, so a dashboard can draw the whole schedule ahead of time, like the
controller's own graph:

```json
{"start": 1767268800000, "end": 1767308400000,
 "points": [[1767268800000, 20.0], [1767272400000, 600.0], ...]}
```

Times are epoch milliseconds and temperatures are in the display scale.
The schedule is laid from the run's start (now minus running time), so it
moves right when the kiln is catching up or paused, as it does in the
controller. When nothing is running, `points` is empty.

This card plots actual temperature against the schedule, with the time axis
fitted to the firing. It needs
[apexcharts-card](https://github.com/RomRider/apexcharts-card) and
[config-template-card](https://github.com/iantrich/config-template-card)
from HACS. Change `kittec_cb40` to your `mqtt_kiln_name`.

```yaml
type: custom:config-template-card
entities:
  - sensor.kittec_cb40_schedule
  - sensor.kittec_cb40_temperature
variables:
  START: states['sensor.kittec_cb40_schedule'].attributes.start
  END: states['sensor.kittec_cb40_schedule'].attributes.end
card:
  type: custom:apexcharts-card
  header:
    show: true
    title: Firing
    show_states: true
  # while firing: the whole schedule plus 15 minutes either side.
  # otherwise: the last 12 hours
  graph_span: "${START ? Math.ceil((END - START) / 60000) + 30 + 'min' : '12h'}"
  span:
    end: minute
    offset: "${START ? '+' + Math.max(1, Math.round((END - Date.now()) / 60000) + 15) + 'min' : '+1min'}"
  now:
    show: true
  yaxis:
    - min: 0
      decimals: 0
  series:
    - entity: sensor.kittec_cb40_temperature
      name: Actual
      stroke_width: 2
      # stop at now rather than flatlining to the end of the schedule
      extend_to: now
    - entity: sensor.kittec_cb40_schedule
      name: Schedule
      curve: straight
      stroke_width: 2
      show:
        in_header: false
      data_generator: |
        return entity.attributes.points || [];
```

## Controls

| Entity | Command topic | Does |
|---|---|---|
| profiles (select) | `<kiln>/control/profiles` | starts the chosen profile if the kiln is idle; `None` does nothing |
| Pause Program | `<kiln>/control/Pause_Program` | pause a running firing |
| Resume Program | `<kiln>/control/Resume_Program` | resume a paused firing |
| Stop Program | `<kiln>/control/Stop_Program` | stop the firing |
| Restart Controller | `<kiln>/control/Restart_Controller` | restart the controller process (refused mid-firing if `automatic_restarts` is off) |

Retained messages on control topics are ignored, so a stale command left on
the broker can never start a firing when the controller reconnects.

The same actions are available over HTTP: `POST /api` with
`{"cmd": "run", "profile": "<name>"}`, `{"cmd": "pause"}`, `{"cmd": "resume"}`,
`{"cmd": "stop"}` or `{"cmd": "restart"}`.

## Thermocouple compensation

`thermocouple_offset` adds a fixed correction. Some thermocouple / board
combinations drift more the hotter they get. With `tc_compensation = True`
every raw reading (in °C, straight off the board) is mapped through a
piecewise polynomial instead, and the offset is not applied:

```python
tc_compensation = True
tc_compensation_curve = [
    (409.5, (0, 1)),                          # raw <= 409.5: unchanged
    (None,  (12.193, 0.893126, 0.000188281)), # above: 12.193 + 0.893126*raw + 0.000188281*raw^2
]
```

Each entry is `(upper_bound, coefficients)` with coefficients in ascending
powers of the raw reading. The last segment's bound is `None`.

### Fitting a curve

Record pairs of (raw reading, reference meter reading) across the firing
range. Fit a quadratic by least squares to the points where the readings
diverge, and use the plain reading (`(0, 1)`) below the point where the
fit crosses it, so the two segments meet with no step. The default above
came from 12 readings from 122 to 1031°C and matches every one to within 1.8°C:

| raw | 122 | 173 | 295 | 564 | 604 | 650 | 700 | 750 | 820 | 888 | 900 | 950 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| meter | 122 | 173 | 295 | 576 | 619 | 673 | 731 | 788 | 870 | 952 | 970 | 1031 |

Avoid high-order polynomials and steep top segments. Anything above your
highest reference reading is extrapolation, and a curve that steepens
there will over-read and end firings early. Check the top end with
witness cones.

The corrected value is used everywhere: PID control, the emergency
shutoffs, alerts, seek-start, the auto-tuner and the display.
`temperature_raw` in the state broadcast (and the Home Assistant
`Temperature Raw` sensor) shows the uncorrected reading so you can check
the curve against a reference meter.

**Keep segments continuous.** At each `upper_bound` the two neighbouring
segments must give (nearly) the same value. Otherwise the reading jumps as
the kiln passes through that point, and the PID reacts to the jump.
