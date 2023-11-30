#!/bin/bash

folder="configuration/experiment_kata/1_startup_performance/strong_scalability"

for file_path in "$folder"/*.cfg; do

    echo python3 continuum.py "$file_path"
    python3 continuum.py "$file_path"

    file_name=$(basename "$file_path" .cfg)

    mkdir -p "logs/$file_name"

    mv logs/*.pdf "logs/$file_name/"
    mv logs/*.log "logs/$file_name/"
    mv logs/*.csv "logs/$file_name/"
done

folder="configuration/experiment_kata/1_startup_performance/weak_scalability"

for file_path in "$folder"/*.cfg; do

    echo python3 continuum.py "$file_path"
    python3 continuum.py "$file_path"

    file_name=$(basename "$file_path" .cfg)

    mkdir -p "logs/$file_name"

    mv logs/*.pdf "logs/$file_name/"
    mv logs/*.log "logs/$file_name/"
    mv logs/*.csv "logs/$file_name/"
done
