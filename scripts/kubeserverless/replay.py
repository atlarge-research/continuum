"""\
Replay trace files and produce real Kubernetes workload via kubectl

TODO if kubectl uses too much cpu, can we investigate sending direct HTTP messages to the API
     server instead? That should be much quicker.

     Use these:
     - https://iximiuz.com/en/posts/kubernetes-api-call-simple-http-client/
     - https://kubernetes.io/docs/tasks/administer-cluster/access-cluster-api/
     - https://python.plainenglish.io/python-performance-in-kubernetes-http-libraries-vs-kubernetes-clients-88706b21a0de
        - Use an async library to send requests in parallel
            - Similar to sending with kubectl &
"""

import time

import pandas as pd
from kubernetes import client, config, utils

FILE = "packing.csv"
JOB_NAME = "empty"


def create_job_object(job_id):
    # Configure Pod template container
    container = client.V1Container(
        name="empty-%s" % (job_id),
        image="192.168.1.101:5000/empty",
        image_pull_policy="IfNotPresent",
        resources=client.V1ResourceRequirements(requests={"memory": "500Mi", "cpu": "50m"}),
        env=[client.V1EnvVar(name="SLEEP_TIME", value="1")],
    )

    # Create and configure a spec section
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(name="empty-%s" % (job_id)),
        spec=client.V1PodSpec(restart_policy="Never", containers=[container]),
    )
    # Create the specification of deployment
    spec = client.V1JobSpec(
        template=template,
    )

    # Instantiate the job object
    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name="empty-%s" % (job_id)),
        spec=spec,
    )

    return job


def main():
    # ----------------------------------------------------------
    # Read the file to pandas dataframe
    df = pd.read_csv(FILE, sep="\t")
    print(df.info)

    config.load_kube_config()
    batch_v1 = client.BatchV1Api()

    time_offset = time.time_ns()
    for _, row in df.iterrows():
        time_now = time.time_ns() - time_offset
        bin_start = row["starttime"] * 10**9

        print("Waiting to execute bin at %i seconds" % (row["starttime"]))

        # Check if and how long we have to sleep until the next bin should start executing
        if time_now < bin_start:
            interval = float(bin_start - time_now) / 10**9
            print("\tSleep for %f seconds" % (interval))
            time.sleep(interval)

        # Check how much too slow we are in starting the next bin. Should be milliseconds.
        time_now = time.time_ns() - time_offset
        if time_now > bin_start:
            interval = float(time_now - bin_start) / 10**9
            print("\tToo late by %f seconds" % (interval))

        # -------------------------------------------------------------
        # Now execute calls within this bin
        bin_count = row["bincount"]
        for i in range(bin_count):
            job_id = "%s-%s" % (row["starttime"], i)
            job = create_job_object(job_id)

            api_response = batch_v1.create_namespaced_job(body=job, namespace="default")
            # print(f"Job created. status='{str(api_response.status)}'")
            print("\tSend request for job %i" % (i))


if __name__ == "__main__":
    main()
