# Configuration
The benchmark requires a configuration file to function. \
The configuration file contains all benchmark and infrastructure settings. \
Multiple configuration files are provided here as an example or for reproduction of research results. \
For a new user, see `template.cfg` for extended documentation.

The configuration file consists of three sections: infrastructure, resource_manager, and benchmark. The infrastructure section is mandatory, the other two are optional. Only include those sections in your configuration file that you use.
You can use the resource_manager section without the benchmark, in that case resource managers will be installed but no benchmarking will be performed on them. If you use the benchmark section, the resource_manager section is required. except if deploying in endpoint-only mode. Per section the following is mandatory, if you choose to use these sections:

* **Infrastructure**: Only network_preset and the network latency/throughput settings are optional. Use these settings to customize network emulation: Presets are provided to emulate wirless communication between endpoint and cloud/edge. All network settings can be customized, and overwrite default values and network presets. Set the network_emulation setting to disable/enable all network emulation.
* **Resource_manager**: The cloud/edge_rm options are required if you create cloud/edge VMs respectively. This entire section should be left out if using the endpoint deployment mode.
* **Benchmark**: ALl options are mandatory.
