# Configuration
The Continuum framework requires a configuration file to function.
These configuration files contains all benchmark and infrastructure settings.
They consists of three sections: infrastructure, benchmark, and execution_model. 
The use of the infrastructure section is mandatory, and allows for the creation of the emulated environment.
The use of the benchmark and execution_model sections are optional, and enables the Continuum benchmark on top of the emulated environment.

A short explanation of the configuration structure:

* **/experiment_endpoint_scaling**: Configurations for Figure 7 in the CCGRID paper.
* **/experiment_large_deployments**: Configurations for Figure 6 in the CCGRID paper.
* **/model**: Configurations for the mathematical model and heatmap in Figure 8 of the CCGRID paper.
* **/tests**: A variety of configurations to test the GCP provider with in the Continuum framework.
* **gcp_cloud_kubernetes_benchmark.cfg**: Demo file for the Artifact Evaluation of CCGRID.
* **gcp_update.py**: Script to update the GCP-related info in all GCP configurations.
* **template.cfg**: Template configuration file listing all configuration options.
