#!/bin/bash

offset=$(date +%s%3N)
while IFS=$'\t' read -r starttime bincount; do  
    # Skip initial header
    if [ $starttime = "starttime" ]; then
        continue
    fi

    echo "Execute bin at $starttime seconds"

    # Get time info
    now=$(date +%s%3N)
    now_relative="$((now-offset))"
    bin_start="$((starttime*1000))"

    # Sleep if we have to wait for bin to start
    if (( now_relative < bin_start )); then
        interval="$((bin_start-now_relative))"
        interval=$(echo "scale=3; $interval / 1000" | bc)
        echo -e "\tSleep for $interval seconds"
        sleep $interval
    fi

    # Print how much too late we started
    now=$(date +%s%3N)
    now_relative="$((now-offset))"

    if (( now_relative > bin_start )); then
        interval="$((now_relative-bin_start))"
        interval=$(echo "scale=3; $interval / 1000" | bc)
        echo -e "\tToo late by $interval seconds"
    fi

    # Now execute kubectl
    echo -e "\t$bincount"
    for i in $(seq 1 $bincount); do
        id="${starttime}-$i"

        cat <<EOF | kubectl apply -f - >/dev/null 2>&1 &
apiVersion: batch/v1
kind: Job
metadata:
  name: empty-$id
spec:
  template:
    metadata:
      name: empty-$id
    spec:
      containers:
      - name: empty-$id
        image: 192.168.1.103:5000/empty
        imagePullPolicy: Never
        resources:
          requests:
            memory: "500Mi"
            cpu: "50m"
        env:
        - name: SLEEP_TIME
          value: "1"
      restartPolicy: Never
EOF
    done

    # Wait for all kubectl's to finish
    # If they haven't we can't replay a trace for hours because work keeps stacking up
    wait $(jobs -p)

    if (( starttime == 10 )); then
        break
    fi

done < packing.csv