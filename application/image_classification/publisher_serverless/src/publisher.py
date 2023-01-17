"""\
This is a publisher, sending local images over MQTT to a subscriber for further processing.
"""

import time
import os
import paho.mqtt.client as mqtt

MQTT_LOCAL_IP = os.environ["MQTT_LOCAL_IP"]
MQTT_REMOTE_IP = os.environ["MQTT_REMOTE_IP"]
MQTT_LOGS = os.environ["MQTT_LOGS"]
FREQUENCY = int(os.environ["FREQUENCY"])
MQTT_TOPIC_PUB = "image-classification-pub"
MQTT_TOPIC_SUB = "image-classification-sub"

# Set how many imgs to send, and how often
DURATION = 300
SEC_PER_FRAME = float(1 / FREQUENCY)
MAX_IMGS = FREQUENCY * DURATION


def on_message(_client, _userdata, msg):
    """Execute when receiving a message on a topic you are subscribed to

    Args:
        _client (_type_): _description_
        _userdata (_type_): _description_
        msg (str): Received message
    """
    t_now = time.time_ns()

    t_old_bytes = msg.payload[-25:]
    t_old = int(t_old_bytes.decode("utf-8"))

    print("Latency (ns): %i" % (t_now - t_old))
    global RECEIVED
    RECEIVED += 1


def send():
    """Loop over local images, and send them one by one to a remote MQTT broker"""
    # Loop over the dataset of 60 images
    files = []
    for file in os.listdir("images"):
        if file.endswith(".JPEG"):
            files.append(file)

    print("Start connecting to the remote MQTT broker")
    print("Broker ip: " + str(MQTT_REMOTE_IP))
    print("Topic: " + str(MQTT_TOPIC_SUB))

    remote_client = mqtt.Client()
    remote_client.on_publish = on_publish

    remote_client.connect(MQTT_REMOTE_IP, port=1883, keepalive=120)
    print("Connected with the broker")

    # Send all frames over MQTT, one by one
    for i in range(MAX_IMGS):
        start_time = time.time_ns()
        with open("images/" + files[i % len(files)], "rb") as f:
            byte_arr = bytearray(f.read())
            f.close()

        # Prepend 0's to the time to get a fixed length string
        t = time.time_ns()
        t = (20 - len(str(t))) * "0" + str(t)
        byte_arr.extend(t.encode("utf-8"))

        # Append local IP address so edge or cloud knows who to send a reply to
        ip_bytes = (15 - len(MQTT_LOCAL_IP)) * "-" + MQTT_LOCAL_IP
        byte_arr.extend(ip_bytes.encode("utf-8"))

        print("Sending data (bytes): %i" % (len(byte_arr)))
        _ = remote_client.publish(MQTT_TOPIC_SUB, byte_arr, qos=0)

        # Try to keep a frame rate of X
        sec_frame = time.time_ns() - start_time
        print("Preparation and preprocessing (ns): %i" % (sec_frame))
        sec_frame = float(sec_frame) / 10**9

        if sec_frame < SEC_PER_FRAME:
            # Wait until next frame should happen
            frame = 0.1 * (SEC_PER_FRAME - sec_frame)
            while sec_frame < SEC_PER_FRAME:
                time.sleep(frame)
                sec_frame = float(time.time_ns() - start_time) / 10**9
        else:
            print("Can't keep up with %f seconds per frame: Took %f" % (SEC_PER_FRAME, sec_frame))

    # Make sure the finish message arrives
    remote_client.loop_start()
    remote_client.publish(MQTT_TOPIC_SUB, "1", qos=2)
    remote_client.loop_stop()

    remote_client.disconnect()
    print("Finished, sent %i images" % (MAX_IMGS))


if __name__ == "__main__":
    send()

    print("Wait for all images to be received back")
    while RECEIVED != MAX_IMGS:
        print("Waiting progress: %i / %i" % (RECEIVED, MAX_IMGS))
        time.sleep(10)

    print("All %i images have been received back" % (MAX_IMGS))
