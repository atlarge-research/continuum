"""\
This is a publisher, sending local images over HTTP to a subscriber for further processing.
"""

import time
import os
import sys
import base64
import json
import requests

FREQUENCY = int(os.environ["FREQUENCY"])
CLOUD_CONTROLLER_IP = os.environ["CLOUD_CONTROLLER_IP"]

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
            im_bytes = f.read()

        im_b64 = base64.b64encode(im_bytes).decode("utf-8")

        # Prepend 0's to the time to get a fixed length string
        t = time.time_ns()
        t_str = str(t)

        # In JSON
        headers = {"Content-type": "application/json", "Accept": "text/plain"}
        payload = json.dumps({"image": im_b64, "time": t_str})

        print("Sending data (bytes): %i" % (len(payload)))
        t_before_send = time.time_ns()
        response = requests.post(
            "http://%s:8080/function/image" % (CLOUD_CONTROLLER_IP),
            data=payload,
            headers=headers,
            timeout=100000,
        )

        # pylint: disable=broad-except
        try:
            response = response.text
            return_line = response.split("\n")[-2]
            return_dict_str = return_line.replace("'", '"')
            return_dict = json.loads(return_dict_str)
            t_old = int(return_dict["time"])
        except Exception:
            print("ERROR: Can't decode the output, something went wrong")
            print(response.text)
            sys.exit()
        # pylint: enable=broad-except

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
