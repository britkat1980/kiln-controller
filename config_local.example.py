# your own settings. copy this file to config_local.py and change what you
# need: config.py holds every default (and documents each one), and
# config_local.py is read after it, so only list settings that differ.
# config_local.py is not tracked by git, so updates never overwrite it.
#
# it is plain python run inside config.py, so it can use anything config.py
# has already imported or defined, such as board for gpio pins.

#listening_port = 8081
#simulate = False
#temp_scale = "c"

# cost
#kwh_rate = 0.25
#kw_elements = 3.0
#currency_type = "£"

# wiring - only if yours differs from config.py
#try:
#    import board
#    spi_sclk = board.D17
#    spi_miso = board.D27
#    spi_cs = board.D22
#    gpio_heat = board.D23
#except (NotImplementedError, AttributeError):
#    pass

# pid, from kiln-tuner.py
#pid_kp = 4.112
#pid_ki = 32.972
#pid_kd = 139.384

# with temp_scale = "c", give temperature limits in celsius too
#emergency_shutoff_temp = 1300

# mqtt / home assistant
#mqtt_enable = True
#mqtt_host = "192.168.1.10"
#mqtt_user = "mqtt"
#mqtt_pass = "secret"
#mqtt_kiln_name = "my-kiln"
#mqtt_ha_discovery = True
