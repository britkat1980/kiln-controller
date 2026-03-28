import paho.mqtt.client as mqtt
import sys
import logging
import config
import requests
import json

logging.basicConfig(level=config.log_level, format=config.log_format)
logger = logging.getLogger("kiln-controller")

def isfloat(num):
    try:
        float(num)
        return True
    except ValueError:
        return False

def on_message(client, userdata, message):
    payload={}
    logger.critical("MQTT Message Recieved: "+str(message.topic)+"= "+str(message.payload.decode("utf-8")))
    writecommand={}
    url="http://localhost:8081/api"
    contenttype= "application/json"
    headers = {'Content-type': 'application/json', 'Accept': 'text/plain'}
    
    try:
        command=str(message.topic).split("/")[-1]
        logger.critical("MQTT topic is: "+command)
        if command=="Pause_Program":
            logger.info("Pause command called")
            payload= {"cmd":"pause"}
        elif command=="Stop_Program":
            logger.info("stop command called")
            payload= {"cmd":"stop"}
        elif command=="Resume_Program":
            logger.info("Resume command called")
            payload= {"cmd":"resume"}
        elif command=="Restart_Congtroller":
            logger.info("Restart command called")
            payload= {"cmd":"restart"}    
        elif command== "profiles":
            profile=message.payload.decode("utf-8")
            logger.info("Profile Start command called: "+profile)
            payload= {"cmd": "run", "profile": profile }
        if not payload == "":
            r = requests.post(url, data=json.dumps(payload), headers=headers)
        

    except:
        e = sys.exc_info()
        logger.error("MQTT.OnMessage Exception: "+str(e))
        return
    
    #Do something with the result??

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code==0:
        client.connected_flag=True #set flag
        logger.debug("connected OK Returned code="+str(reason_code))
        #Subscribe to the control topic for this inverter - relies on serial_number being present
        client.subscribe(config.mqtt_kiln_name+"/control/#")
        logger.debug("Subscribing to "+config.mqtt_kiln_name+"/control/#")
    else:
        logger.error("Bad connection Returned code= "+str(reason_code))

if config.mqtt_port=='':
    MQTT_Port=1883
else:
    MQTT_Port=int(config.mqtt_port)
MQTT_Address=config.mqtt_host
if config.mqtt_host=='':
    MQTTCredentials=False
else:
    MQTTCredentials=True
    MQTT_Username=config.mqtt_user
    MQTT_Password=config.mqtt_pass
if config.mqtt_kiln_name=='':
    MQTT_Topic='GivEnergy'
else:
    MQTT_Topic=config.mqtt_kiln_name

logger.critical("Connecting to MQTT broker for Kiln control- "+str(config.mqtt_host))
#loop till serial number has been found
count=0          # 09-July-2023  set start point

client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "GivEnergy_GivTCP_EVC_Control")
mqtt.Client.connected_flag=False        			#create flag in class
if MQTTCredentials:
    client.username_pw_set(MQTT_Username,MQTT_Password)
client.on_connect=on_connect     			        #bind call back function
client.on_message=on_message                        #bind call back function
#client.loop_start()

logger.debug ("Connecting to broker(sub): "+ MQTT_Address)
client.connect(MQTT_Address,port=MQTT_Port)
client.loop_forever()

