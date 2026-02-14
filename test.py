def fluke_from_max(t):
    """
    Three-region calibration for MAX31855 → Fluke.

    - 0–300°C:   identity (matches your low-temp data)
    - 300–750°C: high-temp segment 1 (already fitted)
    - >750°C:    high-temp segment 2 (continuity-adjusted)

    High-temp behaviour (>564°C) is unchanged from your tuned model.
    """

    if t <= 300:
        # Low range: your data is effectively y = x
        return t

    elif t <= 750:
        # Mid/high range segment 1 (includes 564–750°C region you tuned)
        return 1.085 * t - 20.7

    else:
        # High range segment 2, continuity-adjusted at 750°C
        return 1.155 * t - 71.5


print (fluke_from_max(820))