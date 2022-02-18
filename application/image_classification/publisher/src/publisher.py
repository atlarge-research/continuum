'''\
This is a publisher, sending local images over MQTT to a subscriber for further processing.
'''

import paho.mqtt.client as mqtt
import time
import os

MQTT_SERVER = os.environ['MQTT_SERVER_IP']
FREQUENCY = int(os.environ['FREQUENCY'])
MQTT_TOPIC = 'kubeedge-image-classification'

# Set how many imgs to send, and how often
DURATION = 300
SEC_PER_FRAME = float(1 / FREQUENCY)
MAX_IMGS = FREQUENCY * DURATION

def on_publish(mqttc, obj, mid):
    print('Published data')


def main():
    # Loop over the dataset of 60 images
    files = []
    for file in os.listdir('images'):
        if file.endswith('.JPEG'):
            files.append(file)

    print('Start connecting to the MQTT broker')
    print('Broker ip: ' + str(MQTT_SERVER))
    print('Topic: ' + str(MQTT_TOPIC))

    client = mqtt.Client()
    client.on_publish = on_publish

    client.connect(MQTT_SERVER, port=1883, keepalive=120)
    print('Connected with the broker')

    # Send all frames over MQTT, one by one
    for i in range(MAX_IMGS):
        start_time = time.time_ns()
        file = open('images/' + files[i % len(files)], 'rb')
        byte_arr = bytearray(file.read())

        # Prepend 0's to the time to get a fixed length string
        t = time.time_ns()
        t = (25 - len(str(t))) * '0' + str(t)
        byte_arr.extend(t.encode('utf-8'))
        print('Sending data (bytes): %i' % (len(byte_arr)))

        _ = client.publish(MQTT_TOPIC, byte_arr, qos=0)

        # Try to keep a frame rate of X
        sec_frame = time.time_ns() - start_time
        print('Preparation and preprocessing (ns): %i' % (sec_frame))
        sec_frame = float(sec_frame) / 10**9

        if sec_frame < SEC_PER_FRAME:
            # Wait until next frame should happen
            frame = 0.1 * (SEC_PER_FRAME - sec_frame)
            while sec_frame < SEC_PER_FRAME:
                time.sleep(frame)
                sec_frame = float(time.time_ns() - start_time) / 10**9
        else:
            print('Can\'t keep up with %f seconds per frame: Took %f' % (SEC_PER_FRAME, sec_frame))

    # Make sure the finish message arrives
    client.loop_start()
    client.publish(MQTT_TOPIC, '1', qos=2)
    client.loop_stop()

    client.disconnect()
    print('Finished, sent %i images' % (MAX_IMGS))


if __name__ == '__main__':
    main()
