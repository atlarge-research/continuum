# Configuration
The Continuum framework requires a configuration file to function. \
The configuration file contains all benchmark and infrastructure settings. \
Multiple configuration files are provided here as an example or for reproduction of research results. \
For new users, see `template.cfg` for extended documentation.

The configuration file consists of two sections: infrastructure and benchmark. 
The use of the infrastructure section is mandatory, and allows for the creation of the emulated environment.
The use of the benchmark section is optional, and enables the Continuum benchmark on top of the emulated environment. \
Per section the following is mandatory, if you choose to use these sections:

* **Infrastructure**: All options are mandatory, except wireless_network_preset and the following custom network latency/throughput settiongs. For emulating networks, the following applies: The network_emulation setting enables/disables network emulation altogether. When set to True, wired network connections (i.e. cloud and edge networks) will be emulated using default values. The wireless_network_preset can be used to also include wireless network emulation between endpoints and clouds/edges. All network settings can be overwritten with the custom cloud_ / edge_ latency/throughput settings.
* **Benchmark**: ALl options are mandatory, however the resource_manager setting is optional when benchmarking an endpoint-only configuration.
