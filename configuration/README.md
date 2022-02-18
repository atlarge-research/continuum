# Configuration
The benchmark requires a configuration file to function. \
The configuration file contains all benchmark and infrastructure settings. \
Multiple configuration files are provided here as an example or for reproduction of research results. \
For a new user, see `template.cfg` for extended documentation.

The configuration file consists of three sections: infrastructure, resource_manager, and benchmark. The infrastructure section is mandatory, the other two are optional. Only include those sections in your configuration file that you use.
You can use the resource_manager section without the benchmark, in that case resource managers will be installed but no benchmarking will be performed on them. If you use the benchmark section, the resource_manager section is required. Per section the following is mandatory, if you choose to use these sections:

* **Infrastructure**: All options are mandatory, but you should use either network_preset or cloud/endpoint latency/throughput, not both.
* **Resource_manager**: The cloud/edge_rm options are required if you create cloud/edge VMs respectively.
* **Benchmark**: ALl options are mandatory.
