#!/usr/bin/env python
import config
from digitalio import DigitalInOut
import time
import datetime
import adafruit_bitbangio as bitbangio

try:
    import board
except NotImplementedError:
    print("not running a recognized blinka board, exiting...")
    import sys
    sys.exit()

########################################################################
#
# To test your thermocouple...
#
# Edit config.py and set the following in that file to match your
# hardware setup: SPI_SCLK, SPI_MOSI, SPI_MISO, SPI_CS
#
# then run this script...
# 
# ./test-thermocouple.py
#
# It will output a temperature in degrees every second. Touch your
# thermocouple to heat it up and make sure the value changes. Accuracy
# of my thermocouple is .25C.
########################################################################

if getattr(config, 'modbus', 0):
    # use the controller's own modbus sensor so this tests the same code path
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib'))
    from oven import Modbus
    print("\nboard: %s" % (board.board_id))
    print("thermocouple: modbus %s slave %s register %s" % (
        config.modbus_port_name, config.modbus_slave_address,
        config.modbus_registernumber))
    read_temp = Modbus().raw_temp
else:
    spi = None
    if(hasattr(config,'spi_sclk') and
       hasattr(config,'spi_mosi') and
       hasattr(config,'spi_miso')):
        spi = bitbangio.SPI(config.spi_sclk, config.spi_mosi, config.spi_miso)
        print("Software SPI selected for reading thermocouple")
        print("SPI configured as:\n")
        print("    config.spi_sclk = %s BCM pin" % (config.spi_sclk))
        print("    config.spi_mosi = %s BCM pin" % (config.spi_mosi))
        print("    config.spi_miso = %s BCM pin" % (config.spi_miso))
        print("    config.spi_cs   = %s BCM pin\n" % (config.spi_cs))
    else:
        spi = board.SPI();
        print("Hardware SPI selected for reading thermocouple")

    cs = DigitalInOut(config.spi_cs)
    cs.switch_to_output(value=True)
    sensor = None

    print("\nboard: %s" % (board.board_id))
    if(config.max31855):
        import adafruit_max31855
        print("thermocouple: adafruit max31855")
        sensor = adafruit_max31855.MAX31855(spi, cs)
    if(config.max31856):
        import adafruit_max31856
        print("thermocouple: adafruit max31856")
        sensor = adafruit_max31856.MAX31856(spi, cs)
    read_temp = lambda: sensor.temperature

print("Degrees displayed in %s\n" % (config.temp_scale))

temp = 0
while(True):
    time.sleep(1)
    try:
        temp = read_temp()
        scale = "C"
        if config.temp_scale == "f":
            temp = temp * (9/5) + 32 
            scale ="F"
        print("%s %0.2f%s" %(datetime.datetime.now(),temp,scale))
    except Exception as error:
        print("error: " , error)
