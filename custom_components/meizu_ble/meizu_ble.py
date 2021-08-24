import paho.mqtt.client as mqtt
import json, time, hashlib, threading, random
from shaonianzhentan import load_yaml
from meizu import MZBtIr

def md5(text):
    data = hashlib.md5(text.encode('utf-8')).hexdigest()
    return data[8:-8]

# 读取配置
config = load_yaml('meizu_ble.yaml')
config_mqtt = config['mqtt']
client_id = "meizu_ble"
HOST = config_mqtt['host']
PORT = int(config_mqtt['port'])
USERNAME = config_mqtt['user']
PASSWORD = config_mqtt['password']
SCAN_INTERVAL = 40
# 读取红外码
config_ir = load_yaml('ir.yaml')

# 自动配置
def auto_config(domain, data, mac):
    param = {
        "device":{
            "name": "魅族智能遥控器",
            "identifiers": [ mac ],
            "model": "MeizuBLE",
            "sw_version": "1.0",
            "manufacturer":"shaonianzhentan"
        },
    }
    param.update(data)
    client.publish(f"homeassistant/{domain}/{data['unique_id']}/config", payload=json.dumps(param), qos=0)

# 自动发送信息
def auto_publish():
    for config_meizu in config['meizu']:
        mac = config_meizu['mac']
        # 获取设备信息
        # print(mac)
        try:
            ble = MZBtIr(mac)
            ble.update()
            temperature = ble.temperature()
            humidity = ble.humidity()
            battery = ble.battery()
            client.publish(f"meizu_ble/{mac}/temperature", payload=temperature, qos=0)
            client.publish(f"meizu_ble/{mac}/humidity", payload=humidity, qos=0)
            client.publish(f"meizu_ble/{mac}/battery", payload=battery, qos=0)
            time.sleep(2)
        except Exception as ex:
            print(f"{mac}：出现异常")
            print(ex)

    global timer
    timer = threading.Timer(SCAN_INTERVAL, auto_publish)
    timer.start()

def on_connect(client, userdata, flags, rc):
    print("Connected with result code "+str(rc))
    options = []
    for key in config_ir:
        for ir_key in config_ir[key]:
            options.append(f"{key}_{ir_key}")

    # 读取配置
    for config_meizu in config['meizu']:
        name = config_meizu['name']
        mac = config_meizu['mac']

        select_unique_id = md5(f"{mac}红外遥控")
        command_topic = f"meizu_ble/{select_unique_id}/{mac}"
        client.subscribe(command_topic)
        # 自动配置红外遥控
        auto_config("select", {
            "unique_id": select_unique_id,
            "name": f"{name}红外遥控",            
            "command_topic": command_topic,
            "options": options
        }, mac)
        # 自动配置温湿度传感器
        auto_config("sensor", {
            "unique_id": md5(f"{mac}温度"),
            "name": f"{name}温度",            
            "state_topic": f"meizu_ble/{mac}/temperature",
            "unit_of_measurement": "°C",
            "device_class": "temperature",
        }, mac)
        auto_config("sensor", {
            "unique_id": md5(f"{mac}湿度"),
            "name": f"{name}湿度",
            "state_topic": f"meizu_ble/{mac}/humidity",
            "unit_of_measurement": "%",
            "device_class": "humidity"
        }, mac)
        auto_config("sensor", {
            "unique_id": md5(f"{mac}电量"),
            "name": f"{name}电量",
            "state_topic": f"meizu_ble/{mac}/battery",
            "unit_of_measurement": "%",
            "device_class": "battery"
        }, mac)

    # 定时执行获取设备信息
    timer = threading.Timer(10, auto_publish)
    timer.start()

def on_message(client, userdata, msg):
    payload = str(msg.payload.decode('utf-8'))
    print("主题:" + msg.topic + " 消息:" + payload)
    arr = msg.topic.split('/')
    mac = arr[len(arr)-1]
    arr = payload.split('_', 1)
    if len(arr) == 2:
        device = arr[0]
        command = arr[1]
        print(mac, device, command)
        if device in config_ir:
            if command in config_ir[device]:
                print('发送红外命令')

def on_subscribe(client, userdata, mid, granted_qos):
    print("On Subscribed: qos = %d" % granted_qos)

def on_disconnect(client, userdata, rc):
    if rc != 0:
        print("Unexpected disconnection %s" % rc)
        global timer
        timer.cancel()

client = mqtt.Client(client_id)
client.username_pw_set(USERNAME, PASSWORD)
client.on_connect = on_connect
client.on_message = on_message
client.on_subscribe = on_subscribe
client.on_disconnect = on_disconnect
client.connect(HOST, PORT, 60)
client.loop_forever()