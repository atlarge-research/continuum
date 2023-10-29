#!/bin/bash

folder="configuration/antonis_thesis/1_startup_performance"

for file_path in "$folder"/*.cfg; do
        
    python3 continuum.py "$file_path"

    file_name=$(basename "$file_path" .cfg)

    mkdir -p "logs/$file_name"

    mv logs/*.pdf "logs/$file_name/"
    mv logs/*.log "logs/$file_name/"
    mv logs/*.csv "logs/$file_name/"
done