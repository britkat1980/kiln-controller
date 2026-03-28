import requests
import logging
import config
import sys

logging.basicConfig(level=config.log_level, format=config.log_format)
logger = logging.getLogger("kiln-controller")
message=""
payload={}
logger.debug("MQTT Message Recieved: "+str(message.topic)+"= "+str(message.payload.decode("utf-8")))
writecommand={}
url="http://localhost:8081/api"
contenttype= "application/json"
try:
    command=str(message.topic).split("/")[-1]
    logger.critical("MQTT topic is: "+command)
    if command=="Pause_Program":
        logger.info("Pause command called")
        payload= '{"cmd":"pause"}'
    elif command=="Stop_Program":
        logger.info("stop command called")
        payload= '{"cmd":"stop"}'
    elif command=="Resart_Program":
        logger.info("Restart command called")
        payload= '{"cmd":"resume"}'
    elif command== "profiles":
        profile=message.payload.decode("utf-8")
        logger.info("Profile Start command called: "+profile)
        payload= '{"cmd": "run", "profile": "{{ '  + profile +' }}"}'
    
    response = requests.post(url, json=payload)

except:
    e = sys.exc_info()
    logger.error("MQTT.OnMessage Exception: "+str(e))