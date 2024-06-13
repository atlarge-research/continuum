#!/bin/bash

CONFIG_PATH=curl_configs
CUTOFF=30
BARSIZE=50

# 1. Create all CURL config files beforehand so we don't need to do it at runtime
#    For each bincouont, create a file called $bincount.txt that holds exactly that many
#    url/output pairs for CURL to use. So, if we at runtime need to launch curl for X jobs,
#    we can use the X.txt config file as argument to accomplish that in CURL.
#    Do this only for the first 1 hour of trace
mkdir -p $CONFIG_PATH

echo "Create all config files required by CURL"

while IFS=$'\t' read -r starttime bincount; do
    # Skip initial header
    if [ $starttime = "starttime" ]; then
        continue
    fi

    # Skip 0
    if [ $bincount = "0" ]; then
        continue
    fi

    if (( starttime > CUTOFF )); then
      break
    fi

    if [ ! -f "$CONFIG_PATH/$bincount.txt" ]; then
        for i in $(seq 1 $bincount); do
          cat >> $CONFIG_PATH/$bincount.txt <<EOF 
url = "https://192.168.70.2:6443/apis/batch/v1/namespaces/default/jobs"
output = "/dev/null"
EOF
        done
    fi

    # Print a progress bar -- calculate % done, create done/todo tokens, build the bars, output
    percent="$(((starttime*100)/CUTOFF))"
    
    done="$((BARSIZE*percent/100))"
    todo="$((BARSIZE-done))"

    done_sub_bar=$(printf "%${done}s" | tr " " "#")
    todo_sub_bar=$(printf "%${todo}s" | tr " " "-")

    # output the bar
    echo -ne "\rProgress : [${done_sub_bar}${todo_sub_bar}] ${percent}%"

done < packing.csv

echo -e "\nDONE"
echo "Start executing CURL"

# 2. Start the actual program. Walk through the trace, for each bin sleep until the start of the
#    bin, and execute CURL with the amount of jobs present in that bin.
offset=$(date +%s%3N)
total_jobs=0
while IFS=$'\t' read -r starttime bincount; do  
    # Skip initial header
    if [ $starttime = "starttime" ]; then
        continue
    fi

    echo "Time (seconds): $starttime"
    total_jobs="$((total_jobs+bincount))"

    # Get time info
    now=$(date +%s%3N)
    now_relative="$((now-offset))"
    bin_start="$((starttime*1000))"

    # Sleep if we have to wait for bin to start
    if (( now_relative < bin_start )); then
        interval="$((bin_start-now_relative))"
        interval=$(echo "scale=3; $interval / 1000" | bc)
        sleep $interval
    fi

    # Print how much too late we started
    now=$(date +%s%3N)
    now_relative="$((now-offset))" 
    bin_start_offset="$((bin_start+100))" # Add 0.1 seconds where we don't care about being late

    if (( now_relative > bin_start_offset )); then
        interval="$((now_relative-bin_start))"
        interval=$(echo "scale=1; $interval / 1000" | bc)
        echo -e "\tTOO LATE (seconds): $interval"
    fi

    # Now execute CURL
    echo -e "\tJobs: $bincount"

    # Skip 0
    if [ $bincount = "0" ]; then
        continue
    fi

    # For CURL: Calculate the number of parallel handlers
    # Assume 1 handler per 20 jobs
    # At least 1 handler, at most 100
    PAR=$(( $bincount / 20 ))
    PAR=$(( $PAR > 1 ? $PAR : 1 ))
    PAR=$(( $PAR > 100 ? 200 : $100 ))

    # Execute as background process
    #-w "%{time_connect},%{time_total},%{speed_download},%{speed_upload},%{http_code},%{size_download},%{size_upload}\n" \
    ./curl \
      -s \
      --parallel \
      --parallel-immediate \
      --parallel-max $PAR \
      --cacert /tmp/kube-api-ca.pem \
      --cert /tmp/kube-api-cert.pem \
      --key /tmp/kube-api-key.pem \
      -X POST \
      --config $CONFIG_PATH/$bincount.txt \
      -H 'Content-Type: application/yaml' \
      -d '---
apiVersion: batch/v1
kind: Job
metadata:
  generateName: empty-
spec:
  template:
    metadata:
      name: empty
    spec:
      containers:
      - name: empty
        image: 192.168.1.101:5000/empty
        imagePullPolicy: Never
        resources:
          requests:
            memory: "400Mi"
            cpu: 0.08
        env:
        - name: SLEEP_TIME
          value: "0"
      restartPolicy: Never
'

    # For now, stop after X seconds
    if (( starttime == $CUTOFF )); then
        break
    fi

done < packing.csv

echo "Done, wait for all background processes to finish"

# Wait for all kubectl's to finish
# If they haven't we can't replay a trace for hours because work keeps stacking up
wait $(jobs -p)

echo "$total_jobs jobs launched in $starttime seconds"