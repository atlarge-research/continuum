# Tests
This directory contains a wide variety of configurations that use almost all of Continuum's features. You can run continuum with all these configurations using the following command:

```bash
for i in configuration/tests/*.cfg; do
    python3 main.py $i || break
done
```
A run is succesful if it prints one or multiple `ssh vm_name@ip_address -i path/to/ssh/key` at the end.
You can also check the log files in `/logs` to validate the runs.
