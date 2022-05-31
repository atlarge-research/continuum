"""\
This is a subscriber, receiving images through MQTT and processing them using image classification from TFLite.
"""

import paho.mqtt.client as mqtt

import PIL.Image as Image
import io

import tflite_runtime.interpreter as tflite
import numpy as np
import os
import time
import multiprocessing

MQTT_SERVER = os.environ["MQTT_SERVER_IP"]
MQTT_LOGS = os.environ["MQTT_LOGS"]
CPU_THREADS = int(os.environ["CPU_THREADS"])
ENDPOINT_CONNECTED = int(os.environ["ENDPOINT_CONNECTED"])
MQTT_TOPIC = "kubeedge-image-classification"

work_queue = multiprocessing.Queue()
endpoints_connected = multiprocessing.Value("i", ENDPOINT_CONNECTED)
images_processed = multiprocessing.Value("i", 0)


def on_connect(client, userdata, flags, rc):
    print("Connected with result code " + str(rc) + "\n", end="")
    client.subscribe(MQTT_TOPIC)


def on_subscribe(mqttc, obj, mid, granted_qos):
    print("Subscribed to topic\n", end="")


def on_log(client, userdata, level, buff):
    print("[ %s ] %s\n" % (str(level), buff), end="")


def on_message(client, userdata, msg):
    work_queue.put([time.time_ns(), msg.payload])


def do_tflite(queue):
    """A Multiprocessing thread
    Receive images from a queue, and perform image classification on it

    Args:
        data (bytestream): Raw received data
    """
    current = multiprocessing.current_process()
    print("[%s] Start thread\n" % (current.name), end="")

    # Load the labels
    with open("labels.txt", "r") as f:
        labels = [line.strip() for line in f.readlines()]

    # Load the model
    interpreter = tflite.Interpreter(model_path="model.tflite", num_threads=1)
    interpreter.allocate_tensors()

    # Get model input details and resize image
    input_details = interpreter.get_input_details()
    floating_model = input_details[0]["dtype"] == np.float32

    iw = input_details[0]["shape"][2]
    ih = input_details[0]["shape"][1]

    print("[%s] Preparations finished\n" % (current.name), end="")

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
                    "[%s] A client disconnected, %i clients left\n"
                    % (current.name, counter),
                    end="",
                )
                continue
        except:
            print("[%s] Read image and apply ML\n" % (current.name), end="")

        # Read the image, do ML on it
        with images_processed.get_lock():
            images_processed.value += 1

        # Get timestamp to calculate latency. We prepended 0's to the time to make it a fixed length
        t_bytes = data[-25:]
        t_old = int(t_bytes.decode("utf-8"))
        print("[%s] Latency (ns): %s\n" % (current.name, str(t_now - t_old)), end="")

        # Get data to process
        data = data[: -len(str(t_now))]
        image = Image.open(io.BytesIO(data))
        image = image.resize((iw, ih)).convert(mode="RGB")

        input_data = np.expand_dims(image, axis=0)

        if floating_model:
            input_data = (np.float32(input_data) - 127.5) / 127.5

        interpreter.set_tensor(input_details[0]["index"], input_data)

        interpreter.invoke()

        output_details = interpreter.get_output_details()
        output_data = interpreter.get_tensor(output_details[0]["index"])
        results = np.squeeze(output_data)

        top_k = results.argsort()[-5:][::-1]
        for i in top_k:
            if floating_model:
                print("\t{:08.6f} - {}\n".format(float(results[i]), labels[i]), end="")
            else:
                print(
                    "\t{:08.6f} - {}\n".format(float(results[i] / 255.0), labels[i]),
                    end="",
                )

        sec_frame = time.time_ns() - start_time
        print("[%s] Processing (ns): %i\n" % (current.name, sec_frame), end="")


def main():
    print("Start connecting to the MQTT broker")
    print("Broker ip: " + str(MQTT_SERVER))
    print("Topic: " + str(MQTT_TOPIC))

    pool = multiprocessing.Pool(CPU_THREADS, do_tflite, (work_queue,))

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_subscribe = on_subscribe

    if MQTT_LOGS == "True":
        client.on_log = on_log

    client.connect(MQTT_SERVER, port=1883, keepalive=300)
    client.loop_start()

    while True:
        time.sleep(1)
        with endpoints_connected.get_lock():
            if endpoints_connected.value == 0 and work_queue.empty():
                # Wait for any processing still happening to finish
                time.sleep(10)
                break

    client.loop_stop()

    work_queue.close()
    work_queue.join_thread()

    pool.close()
    pool.terminate()

    with images_processed.get_lock():
        print("Finished, processed images: %i" % images_processed.value)


if __name__ == "__main__":
    main()
