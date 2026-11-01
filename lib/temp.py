import config

########################################################################
# temperature unit conversions
#
# The server works internally in celsius. config.py settings that are
# temperatures (or temperature deltas) are written in the display scale
# (config.temp_scale). Convert at the boundaries:
#
#   to_c / delta_to_c        : display scale -> internal celsius
#   to_display / delta_to_display : internal celsius -> display scale
########################################################################

def c_to_f(value):
    return (value * 9 / 5) + 32


def f_to_c(value):
    return (5 / 9) * (value - 32)


def to_display(temp):
    '''convert an absolute celsius temperature to the display scale.'''
    if config.temp_scale.lower() == "f":
        return c_to_f(temp)
    return temp


def to_c(temp):
    '''convert an absolute display-scale temperature to celsius.'''
    if config.temp_scale.lower() == "f":
        return f_to_c(temp)
    return temp


def delta_to_display(delta):
    '''convert a celsius temperature difference to the display scale.'''
    if config.temp_scale.lower() == "f":
        return delta * (9 / 5)
    return delta


def delta_to_c(delta):
    '''convert a display-scale temperature difference to celsius.'''
    if config.temp_scale.lower() == "f":
        return delta * (5 / 9)
    return delta


def display_profile_data(data):
    '''convert a list of (time, celsius) points to the display scale.'''
    return [(t, to_display(temp)) for (t, temp) in data]


def display_pidstats(pidstats):
    '''convert pid stats (celsius internally) to the display scale.'''
    out = dict(pidstats)
    for key in ('setpoint', 'ispoint'):
        if key in out:
            out[key] = to_display(out[key])
    for key in ('err', 'errDelta', 'p', 'i', 'd'):
        if key in out:
            out[key] = delta_to_display(out[key])
    return out


########################################################################
# thermocouple correction
#
# every raw thermocouple reading (celsius, straight off the board) goes
# through corrected_temp() before the controller uses it. by default
# that just adds thermocouple_offset. with tc_compensation enabled the
# reading is mapped through the piecewise polynomial in
# tc_compensation_curve instead (and the offset is not applied).
########################################################################

def _poly(coeffs, x):
    return sum(c * (x ** n) for n, c in enumerate(coeffs))


def compensate(raw, curve):
    '''map a raw celsius reading through a piecewise polynomial curve:
    a list of (upper_bound, coeffs) where coeffs are in ascending
    powers of the raw reading. the last segment's bound is None.'''
    for upper, coeffs in curve:
        if upper is None or raw <= upper:
            return _poly(coeffs, raw)
    return _poly(curve[-1][1], raw)


def corrected_temp(raw):
    '''raw thermocouple celsius -> corrected celsius'''
    if getattr(config, 'tc_compensation', False):
        return compensate(raw, config.tc_compensation_curve)
    return raw + delta_to_c(config.thermocouple_offset)
