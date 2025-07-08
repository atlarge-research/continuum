"""\
This is a subscriber, receiving images through MQTT and
processing them using image classification from TFLite.
"""

import os
import time
import multiprocessing
import paho.mqtt.client as mqtt
import torch

# pylint: disable-next=import-error
from transformers import MarianMTModel, MarianTokenizer

MQTT_LOGS = os.environ["MQTT_LOGS"]
CPU_THREADS = int(os.environ["CPU_THREADS"])
ENDPOINT_CONNECTED = int(os.environ["ENDPOINT_CONNECTED"])
MQTT_TOPIC_PUB = "text-translation-pub"
MQTT_LOCAL_IP = os.environ["MQTT_LOCAL_IP"]
MQTT_TOPIC_SUB = "text-translation-sub"

work_queue = multiprocessing.Queue()
endpoints_connected = multiprocessing.Value("i", ENDPOINT_CONNECTED)
texts_processed = multiprocessing.Value("i", 0)


def on_connect(client, _userdata, _flags, rc):
    """Execute when connecting to MQTT broker

    Args:
        client (object): Client object
        _userdata (_type_): _description_
        _flags (_type_): _description_
        rc (str): Result code
    """
    print("Connected with result code " + str(rc) + "\n", end="")
    client.subscribe(MQTT_TOPIC_SUB)


def on_subscribe(_mqttc, _obj, _mid, _granted_qos):
    """Execute when subscribing to a topic on a MQTT broker

    Args:
        _mqttc (_type_): _description_
        _obj (_type_): _description_
        _mid (_type_): _description_
        _granted_qos (_type_): _description_
    """
    print("Subscribed to topic\n", end="")


def on_log(_client, _userdata, level, buff):
    """Execute MQTT log on every MQTT event

    Args:
        _client (_type_): _description_
        _userdata (_type_): _description_
        level (str): Log level (error, warning, info, etc)
        buff (str): Log message
    """
    print("[ %s ] %s\n" % (str(level), buff), end="")


def on_message(_client, _userdata, msg):
    """Execute when receiving a message on a topic you are subscribed to

    Args:
        _client (_type_): _description_
        _userdata (_type_): _description_
        msg (str): Received message
    """
    work_queue.put([time.time_ns(), msg.payload])


def on_publish(_mqttc, _obj, _mid):
    """Execute when publishing / sending data

    Args:
        _mqttc (_type_): _description_
        _obj (_type_): _description_
        _mid (_type_): _description_
    """
    print("Published data")


def connect_remote_client(current, ip):
    """Connect to a remote MQTT broker

    Args:
        current (obj): Multiprocessing current process object
        ip (str): IP address to connect to

    Returns:
        obj: MQTT client object, broker you connected to
    """
    # Save IPs from connected endpoints
    print("[%s] Connect to remote broker on endpoint %s" % (current.name, ip))
    remote_client = mqtt.Client()
    remote_client.on_publish = on_publish

    remote_client.connect(ip, port=1883, keepalive=120)
    print("[%s] Connected with the remote broker" % (current.name))

    return remote_client


def do_tflite(queue):
    """A Multiprocessing thread
    Receive text from a queue, and perform text translation on it

    Args:
        queue (obj): Multiprocessing queue with work
    """
    current = multiprocessing.current_process()
    print("[%s] Start thread\n" % (current.name), end="")

    # Load the model
    interpreter = MarianMTModel.from_pretrained("./model")
    tokenizer = MarianTokenizer.from_pretrained("./tokenizer")
    print("[%s] Model loaded\n" % (current.name), end="")
    # Set the model to evaluation mode
    interpreter.eval()
    print("[%s] Model set to evaluation mode\n" % (current.name), end="")
    # Set the model to use CPU
    if torch.cuda.is_available():
        interpreter.to("cpu")
        print("[%s] Model set to use CPU\n" % (current.name), end="")
    else:
        print("[%s] No GPU available, using CPU\n" % (current.name), end="")

    print("[%s] Preparations finished\n" % (current.name), end="")

    remote_clients = {}

    while True:
        print("[%s] Get item\n" % (current.name), end="")
        item = queue.get(block=True)

        start_time = time.time_ns()
        t_now = item[0]
        data = item[1]

        # Stop if a specific message is sent
        try:
            if data.decode() == "1":
                with endpoints_connected.get_lock():
                    endpoints_connected.value -= 1
                    counter = endpoints_connected.value

                print(
                    "[%s] A client disconnected, %i clients left\n" % (current.name, counter),
                    end="",
                )
                continue
        except (AttributeError, UnicodeDecodeError):
            print("[%s] Read text and apply ML\n" % (current.name), end="")

        print("[%s] Read text and apply ML\n" % (current.name), end="")

        # Read the text, do ML on it
        with texts_processed.get_lock():
            texts_processed.value += 1

        # Get sender IP, needed to reply back
        ip_bytes = data[-15:]
        ip = ip_bytes.decode("utf-8")
        while ip[0] == "-":
            ip = ip[1:]

        # Get timestamp to calculate latency. We prepended 0's to the time to make it a fixed length
        t_bytes = data[-35:-15]
        t_old = int(t_bytes.decode("utf-8"))

        print("[%s] Received time is" % (current.name, t_old), end="")
        print("[%s] Latency (ns): %s\n" % (current.name, str(t_now - t_old)), end="")

        # Get data to process
        text = data[:-35].decode("utf-8")
        translated = interpreter.generate(**tokenizer([text], return_tensors="pt", padding=True))
        result = [tokenizer.decode(t, skip_special_tokens=True) for t in translated][0]

        print("[%s] Translated text: %s\n" % (current.name, result), end="")
        # Prepare the result to send back
        result_bytes = result.encode("utf-8")
        
        sec_frame = time.time_ns() - start_time
        print("[%s] Processing (ns): %i\n" % (current.name, sec_frame), end="")

        # Send result back (currently only timestamp,
        # but adding real feedback is trivial and has no impact)
        print("[%s] Send result to source: %s" % (current.name, ip))
        if ip not in remote_clients:
            remote_clients[ip] = connect_remote_client(current, ip)

        _ = remote_clients[ip].publish(MQTT_TOPIC_PUB, result_bytes + t_bytes, qos=0)


def main():
    """Create multiprocessing elements and start generator / processor functions."""
    print("Start connecting to the local MQTT broker")
    print("Broker ip: " + str(MQTT_LOCAL_IP))
    print("Topic: " + str(MQTT_TOPIC_SUB))

    with multiprocessing.Pool(CPU_THREADS, do_tflite, (work_queue,)):
        local_client = mqtt.Client()
        local_client.on_connect = on_connect
        local_client.on_message = on_message
        local_client.on_subscribe = on_subscribe

        if MQTT_LOGS == "True":
            local_client.on_log = on_log

        local_client.connect(MQTT_LOCAL_IP, port=1883, keepalive=300)
        local_client.loop_start()

        while True:
            time.sleep(1)
            with endpoints_connected.get_lock():
                if endpoints_connected.value == 0 and work_queue.empty():
                    # Wait for any processing still happening to finish
                    time.sleep(10)
                    break

        local_client.loop_stop()

        work_queue.close()
        work_queue.join_thread()

    with texts_processed.get_lock():
        print("Finished, processed texts: %i" % texts_processed.value)


if __name__ == "__main__":
    main()
