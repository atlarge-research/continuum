"""\
This is a publisher, sending local images over HTTP to a subscriber for further processing.
"""

import time
import os
import requests

FREQUENCY = int(os.environ["FREQUENCY"])

# Set how many imgs to send, and how often
DURATION = 300
SEC_PER_FRAME = float(1 / FREQUENCY)
MAX_IMGS = FREQUENCY * DURATION


def send():
    """Loop over local images, and send them one by one to a remote MQTT broker"""
    # Loop over the dataset of 60 images
    files = []
    for file in os.listdir("images"):
        if file.endswith(".JPEG"):
            files.append(file)

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

        print("Sending data (bytes): %i" % (len(byte_arr)))
        t_before_send = time.time_ns()
        response = requests.post("%s:8080/function/subscriber_serverless", data=byte_arr)

        t_old = int(response.decode("utf-8"))
        t_respone = time.time_ns()
        print("Latency (ns): %i" % (t_respone - t_old))

        # Try to keep a frame rate of X
        sec_frame = t_before_send - start_time
        print("Preparation and preprocessing (ns): %i" % (sec_frame))

        sec_frame = float(t_respone - t_old) / 10**9

        if sec_frame < SEC_PER_FRAME:
            # Wait until next frame should happen
            frame = 0.1 * (SEC_PER_FRAME - sec_frame)
            while sec_frame < SEC_PER_FRAME:
                time.sleep(frame)
                sec_frame = float(time.time_ns() - start_time) / 10**9
        else:
            print("Can't keep up with %f seconds per frame: Took %f" % (SEC_PER_FRAME, sec_frame))

    print("Finished, sent %i images" % (MAX_IMGS))


if __name__ == "__main__":
    send()
