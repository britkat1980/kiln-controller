#!/usr/bin/env python

import time
import os
import sys
import logging
import json
import datetime
import bottle
import gevent
import geventwebsocket
#from bottle import post, get
from gevent.pywsgi import WSGIServer
from geventwebsocket.handler import WebSocketHandler
from geventwebsocket import WebSocketError
import paho.mqtt.client as mqtt

# try/except removed here on purpose so folks can see why things break
import config

class EType:
    def __init__(self,dT,sC,name,iP:False,iC):
        self.devType = dT
        self.sensorClass=sC
        self.friendly_name=name
        self.isPID=iP
        self.icon=iC

class Entity_Type():
    entity_type={
        "cost":EType("sensor","money","",False,"mdi:currency-gbp"),
        "runtime":EType("sensor","string","Program Running Time",False,"mdi:timer-outline"),
        "endtime":EType("sensor","string","Program End Time",False,"mdi:timer-outline"),
        "progress":EType("sensor","string","Progress",False,"mdi:timer-outline"),
        "temperature":EType("sensor","temperature","",False,"mdi:thermometer"),
        "target":EType("sensor","temperature","",False,"mdi:thermometer-check"),
        "state":EType("sensor","string","",False,"mdi:progress-clock"),
        "heat":EType("binary_sensor","","",False,"mdi:fire"),
        "heat_rate":EType("sensor","number","",False,"mdi:fire-circle"),
        "totaltime":EType("sensor","string","Program Duration",False,"mdi:timer-outline"),
        "catching_up":EType("binary_sensor","","",False,"mdi:run-fast"),
        "name":EType("sensor","string","",False,""),
        "profiles":EType("select","","",False,""),
        "Restart_Program":EType("button","","",False,""),
        "Pause_Program":EType("button","","",False,""),
        "Stop_Program":EType("button","","",False,""),
#PIDSTATS
        "time":EType("sensor","timestamp","PID Time",True,"mdi:clock-outline"),
        "timedelta":EType("sensor","number","PID Time Delta",True,"mdi:timer-sand"),
        "setpoint":EType("sensor","number","PID Setpoint",True,"mdi:thermometer-check"),
        "ispoint":EType("sensor","number","",True,"mdi:thermometer"),
        "err":EType("sensor","number","",True,"mdi:alert-circle-outline"),
        "errDelta":EType("sensor","number","",True,"mdi:delta"),
        "p":EType("sensor","number","",True,"mdi:alpha-p-circle-outline"),
        "i":EType("sensor","number","",True,"mdi:alpha-i-circle-outline"),
        "d":EType("sensor","number","",True,"mdi:alpha-d-circle-outline"),
        "kp":EType("sensor","number","",True,"mdi:alpha-p-box-outline"),
        "ki":EType("sensor","number","",True,"mdi:alpha-i-box-outline"),
        "kd":EType("sensor","number","",True,"mdi:alpha-d-box-outline"),
        "pid":EType("sensor","number","Power Output",True,""),
        "out":EType("sensor","number","Power Output",True,"mdi:chart-bell-curve")
    }


logging.basicConfig(level=config.log_level, format=config.log_format)
log = logging.getLogger("kiln-controller")
log.info("Starting kiln controller")

script_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, script_dir + '/lib/')
profile_path = config.kiln_profiles_directory

from lib.oven import SimulatedOven, RealOven, Profile
from lib.ovenWatcher import OvenWatcher

app = bottle.Bottle()

if config.simulate == True:
    log.info("this is a simulation")
    oven = SimulatedOven()
else:
    log.info("this is a real kiln")
    oven = RealOven()
ovenWatcher = OvenWatcher(oven)
# this ovenwatcher is used in the oven class for restarts
oven.set_ovenwatcher(ovenWatcher)

import subprocess

def ha_discovery(entities):
    
    return True

def restart_kiln_controller():
    subprocess.run(
        ["sudo", "service", "kiln-controller", "restart"],
        check=True
    )

@app.route('/')
def index():
    return bottle.redirect('/picoreflow/index.html')

@app.route('/state')
def state():
    return bottle.redirect('/picoreflow/state.html')

@app.get('/api/stats')
def handle_api():
    stats={}
    st={}
    log.info("/api/stats command received")
    profiles=json.loads(get_profiles())
    stats["Profiles"]=[item["name"] for item in profiles if "name" in item]
    if hasattr(oven,'pid'):
        st["cost"]=oven.cost
        st["catching_up"]=oven.catching_up
        st["heat_rate"]=oven.heat_rate
        st["State"]=oven.state
        st["runtime"]=oven.runtime
        if len(oven.pid.pidstats)>0:
            st["start_time"]=oven.start_time.isoformat()
            st["pidstats"]=oven.pid.pidstats
            st["Profile"]=oven.profile.name
        stats["Stats"]=st
    return json.dumps(stats)

@app.post('/api')
def handle_api():
    log.info("/api is alive. Message recieved: "+str(bottle.request.json)


    # run a kiln schedule
    if bottle.request.json['cmd'] == 'run':
        wanted = bottle.request.json['profile']
        log.info('api requested run of profile = %s' % wanted)

        # start at a specific minute in the schedule
        # for restarting and skipping over early parts of a schedule
        startat = 0;      
        if 'startat' in bottle.request.json:
            startat = bottle.request.json['startat']

        #Shut off seek if start time has been set
        allow_seek = True
        if startat > 0:
            allow_seek = False

        # get the wanted profile/kiln schedule
        profile = find_profile(wanted)
        if profile is None:
            return { "success" : False, "error" : "profile %s not found" % wanted }

        # FIXME juggling of json should happen in the Profile class
        profile_json = json.dumps(profile)
        profile = Profile(profile_json)
        oven.run_profile(profile, startat=startat, allow_seek=allow_seek)
        ovenWatcher.record(profile)
        # publish start_time
        

    if bottle.request.json['cmd'] == 'pause':
        log.info("api pause command received")
        oven.state = 'PAUSED'

    if bottle.request.json['cmd'] == 'resume':
        log.info("api resume command received")
        oven.state = 'RUNNING'

    if bottle.request.json['cmd'] == 'stop':
        log.info("api stop command received")
        oven.abort_run()

    if bottle.request.json['cmd'] == 'restart':
        log.info("api service restart command received")
        restart_kiln_controller()

    if bottle.request.json['cmd'] == 'memo':
        log.info("api memo command received")
        memo = bottle.request.json['memo']
        log.info("memo=%s" % (memo))

    # get stats during a run
    if bottle.request.json['cmd'] == 'stats':
        log.info("api stats command received")
        if hasattr(oven,'pid'):
            if hasattr(oven.pid,'pidstats'):
                return json.dumps(oven.pid.pidstats)

    return { "success" : True }

def find_profile(wanted):
    '''
    given a wanted profile name, find it and return the parsed
    json profile object or None.
    '''
    #load all profiles from disk
    profiles = get_profiles()
    json_profiles = json.loads(profiles)

    # find the wanted profile
    for profile in json_profiles:
        if profile['name'] == wanted:
            return profile
    return None

@app.route('/picoreflow/:filename#.*#')
def send_static(filename):
    log.debug("serving %s" % filename)
    return bottle.static_file(filename, root=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])), "public"))


def get_websocket_from_request():
    env = bottle.request.environ
    wsock = env.get('wsgi.websocket')
    if not wsock:
        abort(400, 'Expected WebSocket request.')
    return wsock


@app.route('/control')
def handle_control():
    wsock = get_websocket_from_request()
    log.info("websocket (control) opened")
    while True:
        try:
            message = wsock.receive()
            if message:
                log.info("Received (control): %s" % message)
                msgdict = json.loads(message)
                if msgdict.get("cmd") == "RUN":
                    log.info("RUN command received")
                    profile_obj = msgdict.get('profile')
                    if profile_obj:
                        profile_json = json.dumps(profile_obj)
                        profile = Profile(profile_json)
                    oven.run_profile(profile)
                    ovenWatcher.record(profile)
                elif msgdict.get("cmd") == "SIMULATE":
                    log.info("SIMULATE command received")
                elif msgdict.get("cmd") == "STOP":
                    log.info("Stop command received")
                    oven.abort_run()
            time.sleep(1)
        except WebSocketError as e:
            log.error(e)
            break
    log.info("websocket (control) closed")


@app.route('/storage')
def handle_storage():
    wsock = get_websocket_from_request()
    log.info("websocket (storage) opened")
    while True:
        try:
            message = wsock.receive()
            if not message:
                break
            log.debug("websocket (storage) received: %s" % message)

            try:
                msgdict = json.loads(message)
            except:
                msgdict = {}

            if message == "GET":
                log.info("GET command received")
                wsock.send(get_profiles())
            elif msgdict.get("cmd") == "DELETE":
                log.info("DELETE command received")
                profile_obj = msgdict.get('profile')
                if delete_profile(profile_obj):
                  msgdict["resp"] = "OK"
                wsock.send(json.dumps(msgdict))
                #wsock.send(get_profiles())
            elif msgdict.get("cmd") == "PUT":
                log.info("PUT command received")
                profile_obj = msgdict.get('profile')
                #force = msgdict.get('force', False)
                force = True
                if profile_obj:
                    #del msgdict["cmd"]
                    if save_profile(profile_obj, force):
                        msgdict["resp"] = "OK"
                    else:
                        msgdict["resp"] = "FAIL"
                    log.debug("websocket (storage) sent: %s" % message)

                    wsock.send(json.dumps(msgdict))
                    wsock.send(get_profiles())
            time.sleep(1) 
        except WebSocketError:
            break
    log.info("websocket (storage) closed")


@app.route('/config')
def handle_config():
    wsock = get_websocket_from_request()
    log.info("websocket (config) opened")
    while True:
        try:
            message = wsock.receive()
            wsock.send(get_config())
        except WebSocketError:
            break
        time.sleep(1)
    log.info("websocket (config) closed")


@app.route('/status')
def handle_status():
    wsock = get_websocket_from_request()
    ovenWatcher.add_observer(wsock)
    log.info("websocket (status) opened")
    while True:
        try:
            message = wsock.receive()
            wsock.send("Your message was: %r" % message)
        except WebSocketError:
            break
        time.sleep(1)
    log.info("websocket (status) closed")


def get_profiles():
    try:
        profile_files = os.listdir(profile_path)
    except:
        profile_files = []
    profiles = []
    for filename in profile_files:
        with open(os.path.join(profile_path, filename), 'r') as f:
            profiles.append(json.load(f))
    profiles = normalize_temp_units(profiles)
    return json.dumps(sorted(profiles, key=lambda x: x["name"]))


def save_profile(profile, force=False):
    profile=add_temp_units(profile)
    profile_json = json.dumps(profile)
    filename = profile['name']+".json"
    filepath = os.path.join(profile_path, filename)
    if not force and os.path.exists(filepath):
        log.error("Could not write, %s already exists" % filepath)
        return False
    with open(filepath, 'w+') as f:
        f.write(profile_json)
        f.close()
    log.info("Wrote %s" % filepath)
    #always publish new profile data to MQTT
    profile_mqtt()
    return True

def add_temp_units(profile):
    """
    always store the temperature in degrees c
    this way folks can share profiles
    """
    if "temp_units" in profile:
        return profile
    profile['temp_units']="c"
    if config.temp_scale=="c":
        return profile
    if config.temp_scale=="f":
        profile=convert_to_c(profile)
        return profile

def convert_to_c(profile):
    newdata=[]
    for (secs,temp) in profile["data"]:
        temp = (5/9)*(temp-32)
        newdata.append((secs,temp))
    profile["data"]=newdata
    return profile

def convert_to_f(profile):
    newdata=[]
    for (secs,temp) in profile["data"]:
        temp = ((9/5)*temp)+32
        newdata.append((secs,temp))
    profile["data"]=newdata
    return profile

def normalize_temp_units(profiles):
    normalized = []
    for profile in profiles:
        if "temp_units" in profile:
            if config.temp_scale == "f" and profile["temp_units"] == "c": 
                profile = convert_to_f(profile)
                profile["temp_units"] = "f"
        normalized.append(profile)
    return normalized

def delete_profile(profile):
    profile_json = json.dumps(profile)
    filename = profile['name']+".json"
    filepath = os.path.join(profile_path, filename)
    os.remove(filepath)
    log.info("Deleted %s" % filepath)
    return True

def get_config():
    return json.dumps({"temp_scale": config.temp_scale,
        "time_scale_slope": config.time_scale_slope,
        "time_scale_profile": config.time_scale_profile,
        "kwh_rate": config.kwh_rate,
        "currency_type": config.currency_type})    

def profile_mqtt():
    # Only do this if MQTT is enabled in config
    if config.mqtt_enabled:
        disco_messages={}
        entities=Entity_Type().entity_type
        for item in entities:
            tempObj={}
            if entities[item].isPID:
                tempObj['stat_t']=str(config.mqtt_kiln_name+"/pidstats/"+item).replace(" ","_")
            else:
                tempObj['stat_t']=str(config.mqtt_kiln_name+"/"+item).replace(" ","_")
            tempObj['avty_t'] = config.mqtt_kiln_name+"/status"
            tempObj["pl_avail"]= "online"
            tempObj["pl_not_avail"]= "offline"
            tempObj['device']={}
            if entities[item].friendly_name=="":
                tempObj["name"]=item.replace("_"," ") #Just final bit past the last "/"
                tempObj['unique_id']=config.mqtt_kiln_name+"_"+item
                tempObj['default_entity_id']=entities[item].devType+"."+config.mqtt_kiln_name+"_"+item
            else:
                tempObj["name"]=entities[item].friendly_name
                tempObj['unique_id']=config.mqtt_kiln_name+"_"+str(entities[item].friendly_name).replace(" ","_")
                tempObj['default_entity_id']=entities[item].devType+"."+config.mqtt_kiln_name+"_"+str(entities[item].friendly_name).replace(" ","_")
            tempObj['device']['model']=config.mqtt_kiln_name
            tempObj['device']['manufacturer']=config.mqtt_kiln_name
            tempObj['device']['identifiers']=config.mqtt_kiln_name
            tempObj['device']['name']=config.mqtt_kiln_name
            if not entities[item].icon=="":
                tempObj["icon"]=entities[item].icon

# Add sensor specific details
            if entities[item].devType=="select":
                tempObj['stat_t']=config.mqtt_kiln_name+"/profile"
                json_profiles = json.loads(get_profiles())
                profile_list=[]
                for profile in json_profiles:
                    profile_list.append(profile['name'])
                tempObj["options"]=profile_list
                tempObj["command_topic"]=config.mqtt_kiln_name+"/control/"+item
            elif entities[item].devType=="sensor":
                if entities[item].sensorClass=="temperature":
                    tempObj['unit_of_meas']="°C"
                    tempObj['device_class']="Temperature"
                    tempObj['state_class']="measurement"
                if entities[item].sensorClass=="money":
                    tempObj['unit_of_meas']="{GBP}"
                    if "state_class" in tempObj:
                        del tempObj['state_class']
                    tempObj['device_class']="Monetary"
                if entities[item].sensorClass=="timestamp":
                    tempObj['device_class']="timestamp"
            elif entities[item].devType=="button":
                tempObj["command_topic"]=config.mqtt_kiln_name+"/control/"+item
            elif entities[item].devType=="binary_sensor":
                tempObj["payload_on"]="1"
                tempObj["payload_off"]="0"

            disco_messages[item]=[entities[item].devType, tempObj]
        #publish messages
        try:
            client = mqtt.Client()
            client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "kiln_controller")
            client.username_pw_set(config.mqtt_user, config.mqtt_pass)
            client.connect(config.mqtt_host, config.mqtt_port)
            client.publish("Kittec_CB40/status","online",retain=True)
            for item in disco_messages:
                if disco_messages[item][0]=="sensor":
                    pubtopic="homeassistant/sensor/kiln_controller"+"/"+item+"/config"
                elif disco_messages[item][0]=="select":
                    pubtopic="homeassistant/select/kiln_controller"+"/"+item+"/config"
                elif disco_messages[item][0]=="button":
                    pubtopic="homeassistant/button/kiln_controller"+"/"+item+"/config"
                elif disco_messages[item][0]=="binary_sensor":
                    pubtopic="homeassistant/binary_sensor/kiln_controller"+"/"+item+"/config"
                client.publish(pubtopic, json.dumps(disco_messages[item][1]),retain=True)
            client.disconnect()
        except:
            log.error("MQTT publish failed. Check config.")

def main():
    profile_mqtt()
    # Run mqtt client
    mqtt_client=subprocess.Popen(["python3","/home/pi/kiln-controller/mqtt_client.py"])
    ip = "0.0.0.0"
    port = config.listening_port
    log.info("listening on %s:%d" % (ip, port))

    server = WSGIServer((ip, port), app,
                        handler_class=WebSocketHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
