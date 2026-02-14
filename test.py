def fluke_from_max(t):
    """
    Piecewise calibration optimised for MAX31855 above 564°C.
    Continuous at 750°C.
    """
    if t <= 750:
        # Segment 1: 564–750°C
        return 1.085 * t - 20.7
    else:
        # Segment 2: 750–1000°C (continuity-adjusted)
        return 1.155 * t - 71.5

print (fluke_from_max(950))