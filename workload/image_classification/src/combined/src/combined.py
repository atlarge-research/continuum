"""\
This is a combination of a publisher and subscriber,
modeling handling ML workload on the endpoint itself.
"""

import os
import time
import multiprocessing
import numpy as np
from PIL import Image

# pylint: disable-next=import-error
import tflite_runtime.interpreter as tflite


CPU_THREADS = int(os.environ["CPU_THREADS"])
FREQUENCY = int(os.environ["FREQUENCY"])

# Set how many imgs to send, and how often
DURATION = 300
SEC_PER_FRAME = float(1 / FREQUENCY)
MAX_IMGS = FREQUENCY * DURATION


def generate(queue):
    """Generate data to be processed

    Args:
        queue (object): Multiprocessing queue
    """
    print("Start generating")

    # Loop over the dataset of 60 images
    files = []
    for file in os.listdir("images"):
        if file.endswith(".JPEG"):
            files.append(file)

    for i in range(MAX_IMGS):
        start_time = time.time_ns()
        image = Image.open("images/" + files[i % len(files)])
        queue.put([start_time, image])

        # Try to keep a frame rate of X
        sec_frame = time.time_ns() - start_time
        sec_frame = float(sec_frame) / 10**9

        if sec_frame < SEC_PER_FRAME:
            # Wait until next frame should happen
            frame = 0.1 * (SEC_PER_FRAME - sec_frame)
            while sec_frame < SEC_PER_FRAME:
                time.sleep(frame)
                sec_frame = float(time.time_ns() - start_time) / 10**9
        else:
            print("Can't keep up with %f seconds per frame: Took %f" % (SEC_PER_FRAME, sec_frame))


def process(queue):
    """Process generated data

    Args:
        queue (object): Multiprocessing queue
    """
    # Load the labels
    with open("labels.txt", "r", encoding="utf-8") as f:
        labels = [line.strip() for line in f.readlines()]

    # Load the model
    interpreter = tflite.Interpreter(model_path="model.tflite", num_threads=CPU_THREADS)
    interpreter.allocate_tensors()

    # Get model input details and resize image
    input_details = interpreter.get_input_details()
    floating_model = input_details[0]["dtype"] == np.float32

    iw = input_details[0]["shape"][2]
    ih = input_details[0]["shape"][1]

    while True:
        # Get item from queue
        print("Get item")
        item = queue.get(block=True)
        start_process_time = time.time_ns()
        start_time = item[0]
        image = item[1]

        # Resize image and prepare data/model
        image = image.resize((iw, ih)).convert(mode="RGB")
        input_data = np.expand_dims(image, axis=0)

        if floating_model:
            input_data = (np.float32(input_data) - 127.5) / 127.5

        interpreter.set_tensor(input_details[0]["index"], input_data)

        # Do inference, parse and print output
        interpreter.invoke()

        output_details = interpreter.get_output_details()
        output_data = interpreter.get_tensor(output_details[0]["index"])
        results = np.squeeze(output_data)

        top_k = results.argsort()[-5:][::-1]
        for i in top_k:
            if floating_model:
                print("\t{:08.6f} - {}".format(float(results[i]), labels[i]))
            else:
                print("\t{:08.6f} - {}".format(float(results[i] / 255.0), labels[i]))

        # Time it took
        now = time.time_ns()
        print("Preparation, preprocessing and processing (ns): %i" % (now - start_process_time))
        print("Latency (ns): %i" % (now - start_time))


def main():
    """Create multiprocessing elements and start generator / processor functions."""
    # Start threads
    queue = multiprocessing.Queue()
    p2 = multiprocessing.Process(target=process, args=(queue,))
    p2.start()

    time.sleep(3)
    p1 = multiprocessing.Process(target=generate, args=(queue,))
    p1.start()

    # Wait for the generator to finish, then wait until the work queue is empty
    p1.join()
    while not queue.empty():
        time.sleep(5)

    p2.terminate()

    print("Finished, processed %i images" % (MAX_IMGS))


if __name__ == "__main__":
    main()
