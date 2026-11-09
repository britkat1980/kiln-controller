'''heat-work: the equivalent orton cone reached by a firing, from its
temperature over time.

a cone bends as its glassy body softens, which speeds up exponentially
with temperature, so it responds to time at temperature, not just the
peak. each cone n gets an arrhenius model:

    H_n = integral of exp(-E_n / (R T)) dt      (T in kelvin, t in seconds)

and bends when H_n reaches its threshold. E_n and the threshold were
fitted, for each cone, to orton's self-supporting cone chart (2016) at
15, 60 and 150 degC/h; the fitted models reproduce that chart to within
about 3 degC from cone 019 to cone 10 (worse below 019). see
Test/test_heatwork.py, which repeats the check.

it is a model: witness cones have the final say, and its answer can only
be as good as the thermocouple's reading near the top of the firing.
'''
import math

R = 8.314  # J / (mol K)

# (cone, activation energy E in J/mol, ln of the heat-work threshold)
CONE_MODELS = [
    ('022', 247655, -26.6025),
    ('021', 333217, -37.6794),
    ('020', 360631, -40.1579),
    ('019', 427506, -47.0773),
    ('018', 368665, -37.7394),
    ('017', 319057, -30.5867),
    ('016', 369187, -35.1726),
    ('015', 296575, -26.0412),
    ('014', 251879, -20.4108),
    ('013', 417811, -37.9524),
    ('012', 611217, -57.6772),
    ('011', 663395, -62.4448),
    ('010', 1085107, -104.3583),
    ('09', 1166189, -111.0922),
    ('08', 808291, -73.1889),
    ('07', 1175585, -106.6377),
    ('06', 947572, -82.8203),
    ('05', 1379094, -120.5109),
    ('04', 1082097, -90.6246),
    ('03', 1043864, -85.3816),
    ('02', 800769, -62.9087),
    ('01', 799185, -61.9402),
    ('1', 812492, -62.2512),
    ('2', 711375, -53.2115),
    ('3', 661625, -48.6463),
    ('4', 916220, -69.6316),
    ('5', 824342, -60.7586),
    ('6', 699414, -48.9823),
    ('7', 731291, -50.9631),
    ('8', 701249, -48.0903),
    ('9', 762572, -52.5829),
    ('10', 822159, -56.2435),
]

# orton self-supporting cone chart, degC at 15, 60 and 150 degC/h, which
# the models above were fitted to (kept for the tests and for reference)
ORTON_SELF_SUPPORTING = {
    '022': (586, 590, 630), '021': (600, 617, 643), '020': (626, 638, 666),
    '019': (656, 678, 695), '018': (686, 715, 734), '017': (705, 738, 763),
    '016': (742, 772, 796), '015': (750, 791, 818), '014': (757, 807, 838),
    '013': (807, 837, 861), '012': (843, 861, 882), '011': (857, 875, 894),
    '010': (891, 903, 915), '09': (907, 920, 930), '08': (922, 942, 956),
    '07': (962, 976, 987), '06': (981, 998, 1013), '05': (1021, 1031, 1044),
    '04': (1046, 1063, 1077), '03': (1071, 1086, 1104), '02': (1078, 1102, 1122),
    '01': (1093, 1119, 1138), '1': (1109, 1137, 1154), '2': (1112, 1142, 1164),
    '3': (1115, 1152, 1170), '4': (1141, 1162, 1183), '5': (1159, 1186, 1207),
    '6': (1185, 1222, 1243), '7': (1201, 1239, 1257), '8': (1211, 1249, 1271),
    '9': (1224, 1260, 1280), '10': (1251, 1285, 1305),
}

# below this a minute adds nothing measurable to any cone, so skip the maths
MIN_TEMP_C = 400.0


def _log_add(a, b):
    '''ln(e^a + e^b) without overflow; None is ln(0)'''
    if a is None:
        return b
    if b is None:
        return a
    hi, lo = (a, b) if a >= b else (b, a)
    return hi + math.log1p(math.exp(lo - hi))


class HeatWork(object):
    '''accumulates heat-work for every cone. values are kept as logs, as
    the raw integrals span hundreds of orders of magnitude.'''

    def __init__(self):
        self.reset()

    def reset(self):
        self.ln_work = [None] * len(CONE_MODELS)

    def add(self, temp_c, seconds):
        '''seconds spent at temp_c (celsius)'''
        if temp_c is None or seconds <= 0 or temp_c < MIN_TEMP_C:
            return
        kelvin = temp_c + 273.15
        ln_dt = math.log(seconds)
        for i, (_, energy, _) in enumerate(CONE_MODELS):
            self.ln_work[i] = _log_add(self.ln_work[i], ln_dt - energy / (R * kelvin))

    def progress(self):
        '''[(cone, ln of work / threshold)], 0 meaning just bent'''
        return [(cone, None if w is None else w - ln_thr)
                for (cone, _, ln_thr), w in zip(CONE_MODELS, self.ln_work)]

    def equivalent(self):
        '''the cone reached, as (index into CONE_MODELS + fraction toward
        the next cone, label) or (None, None) below cone 022. e.g. cone 5
        and 40% of the way to cone 6 gives (26.4, "5.4").'''
        prog = self.progress()
        reached = None
        for i, (_, p) in enumerate(prog):
            if p is not None and p >= 0:
                reached = i
        if reached is None:
            return None, None
        fraction = 0.0
        if reached + 1 < len(prog):
            here, nxt = prog[reached][1], prog[reached + 1][1]
            if nxt is not None and here > nxt:
                # where ln(progress) would cross zero between the two
                fraction = min(max(here / (here - nxt), 0.0), 0.99)
        return reached + fraction, cone_label(reached, fraction)

    def to_list(self):
        return list(self.ln_work)

    def restore(self, values):
        '''from to_list(), e.g. after an automatic restart. bad input
        leaves the heat-work as it is.'''
        if not isinstance(values, list) or len(values) != len(CONE_MODELS):
            return False
        try:
            self.ln_work = [None if v is None else float(v) for v in values]
        except (TypeError, ValueError):
            return False
        return True


def cone_label(index, fraction=0.0):
    '''"5.4" for 40% of the way from cone 5 to 6; "04+30%" for the cones
    whose names start with 0, where a decimal would read as another cone'''
    cone = CONE_MODELS[index][0]
    tenths = int(fraction * 10)
    if cone.startswith('0'):
        return cone if tenths == 0 else '%s+%d0%%' % (cone, tenths)
    return '%s.%d' % (cone, tenths)


def recorded_firing_cone(samples, temp_scale='c'):
    '''equivalent cone of a firing from the firing db: samples are dicts
    with "t" (epoch seconds) and "temp" in the display scale. the db
    records only while the firing runs, so the cool-down is not
    included. returns {"cone": label, "cone_index": index}.'''
    points = []
    for s in samples:
        try:
            temp = float(s["temp"])
            points.append((float(s["t"]),
                           (temp - 32) * 5 / 9 if temp_scale == 'f' else temp))
        except (KeyError, TypeError, ValueError):
            continue
    index, label = equivalent_cone(points)
    return {"cone": label,
            "cone_index": None if index is None else round(index, 2)}


def equivalent_cone(samples):
    '''heat-work of a recorded firing: samples are (epoch seconds, temp
    in celsius), in time order. each step counts at its mean temperature.
    returns HeatWork.equivalent().'''
    work = HeatWork()
    prev = None
    for t, temp in samples:
        if temp is None:
            continue
        if prev is not None and t > prev[0]:
            # gaps over 10 minutes are missing data, not time at temperature
            work.add((temp + prev[1]) / 2.0, min(t - prev[0], 600.0))
        prev = (t, temp)
    return work.equivalent()
