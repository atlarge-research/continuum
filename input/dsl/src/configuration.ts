import { NodeMap, ReadWriteSpeed, InfrastructureConfig, Connection, GCPConfig, defaultGCPConfig, BenchmarkConfig, applicationVars, ConfigurationMap } from "./generics";
import { checkValidator } from "./validator";
import { nodesValidator, coresValidator, quotaValidator, readWriteSpeedValidator, memoryValidator, connectionValidator as connectionValidator, prefixIPValidator, is8BitValidator, numberIsUnsignedValidator } from "./validate_generics"

export default class Configuration {

    constructor(config: ConfigurationMap) {

        this.infrastructure.provider = config.infrastructure.provider;
        this.infrastructure.nodes = config.infrastructure.nodes;
        this.infrastructure.cores = config.infrastructure.cores;
        this.infrastructure.memory = config.infrastructure.memory;
        this.infrastructure.quota = config.infrastructure.quota;

        this.infrastructure.readWriteSpeed = config.infrastructure.readWriteSpeed != null
            ? {
                readSpeed: config.infrastructure.readWriteSpeed.readSpeed != null
                    ? config.infrastructure.readWriteSpeed.readSpeed
                    : { cloud: 0, edge: 0, endpoint: 0 },
                writeSpeed: config.infrastructure.readWriteSpeed.writeSpeed != null
                    ? config.infrastructure.readWriteSpeed.writeSpeed
                    : { cloud: 0, edge: 0, endpoint: 0 },
            }
            : {
                readSpeed: { cloud: 0, edge: 0, endpoint: 0 },
                writeSpeed: { cloud: 0, edge: 0, endpoint: 0 }
            }

        this.infrastructure.infraOnly = config.infrastructure.infraOnly === true
        this.infrastructure.cpuPin = config.infrastructure.cpuPin === true
        this.infrastructure.networkEmulation = config.infrastructure.networkEmulation === true

        this.infrastructure.wirelessNetworkPreset = config.infrastructure.wirelessNetworkPreset != null
            ? config.infrastructure.wirelessNetworkPreset
            : '4g'


        this.infrastructure.cloudConnection = config.infrastructure.cloudConnection != null
            ? {
                latencyAvg: config.infrastructure.cloudConnection.latencyAvg != null
                    ? config.infrastructure.cloudConnection.latencyAvg
                    : 0,
                latencyVar: config.infrastructure.cloudConnection.latencyVar != null
                    ? config.infrastructure.cloudConnection.latencyVar
                    : 0,
                throughput: config.infrastructure.cloudConnection.throughput != null
                    ? config.infrastructure.cloudConnection.throughput
                    : 1000
            }
            : { latencyAvg: 0, latencyVar: 0, throughput: 1000 }

        this.infrastructure.edgeConnection = config.infrastructure.edgeConnection != null
            ? {
                latencyAvg: config.infrastructure.edgeConnection.latencyAvg != null
                    ? config.infrastructure.edgeConnection.latencyAvg
                    : 7.5,
                latencyVar: config.infrastructure.edgeConnection.latencyVar != null
                    ? config.infrastructure.edgeConnection.latencyVar
                    : 2.5,
                throughput: config.infrastructure.edgeConnection.throughput != null
                    ? config.infrastructure.edgeConnection.throughput
                    : 1000
            }
            : { latencyAvg: 7.5, latencyVar: 2.5, throughput: 1000 }

        this.infrastructure.cloudEdgeConnection = config.infrastructure.cloudEdgeConnection != null
            ? {
                latencyAvg: config.infrastructure.cloudEdgeConnection.latencyAvg != null
                    ? config.infrastructure.cloudEdgeConnection.latencyAvg
                    : 7.5,
                latencyVar: config.infrastructure.cloudEdgeConnection.latencyVar != null
                    ? config.infrastructure.cloudEdgeConnection.latencyVar
                    : 2.5,
                throughput: config.infrastructure.cloudEdgeConnection.throughput != null
                    ? config.infrastructure.cloudEdgeConnection.throughput
                    : 1000
            }
            : { latencyAvg: 7.5, latencyVar: 2.5, throughput: 1000 }

        this.infrastructure.cloudEndPointConnection = config.infrastructure.cloudEndPointConnection != null
            ? {
                latencyAvg: config.infrastructure.cloudEndPointConnection.latencyAvg != null
                    ? config.infrastructure.cloudEndPointConnection.latencyAvg
                    : 45,
                latencyVar: config.infrastructure.cloudEndPointConnection.latencyVar != null
                    ? config.infrastructure.cloudEndPointConnection.latencyVar
                    : 5,
                throughput: config.infrastructure.cloudEndPointConnection.throughput != null
                    ? config.infrastructure.cloudEndPointConnection.throughput
                    : 7.21
            }
            : { latencyAvg: 45, latencyVar: 5, throughput: 7.21 }

        this.infrastructure.edgeEndPointConnection = config.infrastructure.edgeEndPointConnection != null
            ? {
                latencyAvg: config.infrastructure.edgeEndPointConnection.latencyAvg != null
                    ? config.infrastructure.edgeEndPointConnection.latencyAvg
                    : 7.5,
                latencyVar: config.infrastructure.edgeEndPointConnection.latencyVar != null
                    ? config.infrastructure.edgeEndPointConnection.latencyVar
                    : 2.5,
                throughput: config.infrastructure.edgeEndPointConnection.throughput != null
                    ? config.infrastructure.edgeEndPointConnection.throughput
                    : 7.21
            }
            : { latencyAvg: 7.5, latencyVar: 2.5, throughput: 7.21 }

        this.infrastructure.externalPhysicalMachines = config.infrastructure.externalPhysicalMachines != null
            ? config.infrastructure.externalPhysicalMachines
            : []

        this.infrastructure.netperf = config.infrastructure.netperf === true
        this.infrastructure.basePath = config.infrastructure.basePath != null
            ? config.infrastructure.basePath
            : "~"

        this.infrastructure.prefixIP = config.infrastructure.prefixIP != null
            ? config.infrastructure.prefixIP
            : 192.168

        this.infrastructure.middleIP = config.infrastructure.middleIP != null
            ? config.infrastructure.middleIP
            : 100

        this.infrastructure.middleIPBase = config.infrastructure.middleIPBase != null
            ? config.infrastructure.middleIPBase
            : 90



        this.infrastructure.delete = config.infrastructure.delete === true

        this.infrastructure.gcpConfig = config.infrastructure.provider === "gcp"
            ? config.infrastructure.gcpConfig != null
                ? config.infrastructure.gcpConfig
                : defaultGCPConfig()
            : undefined

        this.benchmark = !config.infrastructure.infraOnly
            ? config.benchmark != null
                ? {
                    resourceManager: config.benchmark.resourceManager,
                    resourceManagerOnly: config.benchmark.resourceManagerOnly === true,
                    dockerPull: config.benchmark.dockerPull === true,
                    application: config.benchmark.application,

                    applicationWorkerCPU: config.benchmark.applicationWorkerCPU != null
                        ? config.benchmark.applicationWorkerCPU
                        : config.infrastructure.cores.cloud - 0.5,

                    applicationWorkerMemory: config.benchmark.applicationWorkerMemory != null
                        ? config.benchmark.applicationWorkerMemory
                        : config.infrastructure.cores.cloud - 0.5,

                    applicationEndpointCPU: config.benchmark.applicationEndpointCPU != null
                        ? config.benchmark.applicationEndpointCPU
                        : config.infrastructure.cores.endpoint,

                    applicationEndpointMemory: config.benchmark.applicationEndpointMemory != null
                        ? config.benchmark.applicationEndpointMemory
                        : config.infrastructure.cores.endpoint,

                    applicationsPerWorker: config.benchmark.applicationsPerWorker != null
                        ? config.benchmark.applicationsPerWorker
                        : 1,

                    applicationVars: config.benchmark.applicationVars != null
                        ? config.benchmark.applicationVars
                        : undefined,

                    cacheWorker: config.benchmark.cacheWorker === true,
                    observability: config.benchmark.observability === true,
                }
                : undefined
            : undefined,

            this.executionModel = config.infrastructure.executionMode != null
                ? config.infrastructure.executionMode
                : "openfaas"
    }



    infrastructure: InfrastructureConfig = {
        provider: 'qemu',
        nodes: { cloud: 0, edge: 0, endpoint: 0 },
        cores: { cloud: 0, edge: 0, endpoint: 0 },
        memory: { cloud: 0, edge: 0, endpoint: 0 },
        quota: { cloud: 0, edge: 0, endpoint: 0 },
    }
    mode: string = "cloud"
    benchmark?: BenchmarkConfig

    executionModel: "openfaas"

    validate() {
        checkValidator(nodesValidator(this.infrastructure.nodes))
        checkValidator(coresValidator(this.infrastructure.nodes, this.infrastructure.cores))
        checkValidator(quotaValidator(this.infrastructure.nodes, this.infrastructure.quota))
        checkValidator(memoryValidator(this.infrastructure.nodes, this.infrastructure.memory))
        checkValidator(readWriteSpeedValidator(this.infrastructure.readWriteSpeed))
        checkValidator(connectionValidator(this.infrastructure.cloudConnection))
        checkValidator(connectionValidator(this.infrastructure.edgeConnection))
        checkValidator(connectionValidator(this.infrastructure.cloudEdgeConnection))
        checkValidator(connectionValidator(this.infrastructure.cloudEndPointConnection))
        checkValidator(connectionValidator(this.infrastructure.edgeEndPointConnection))
        checkValidator(prefixIPValidator(this.infrastructure.prefixIP))
        checkValidator(is8BitValidator("middleIP", this.infrastructure.middleIP))
        checkValidator(is8BitValidator("middleIPBase", this.infrastructure.middleIPBase))

        if (this.benchmark != null) {
            checkValidator(numberIsUnsignedValidator("applicationWorkerCPU", this.benchmark.applicationWorkerCPU!, false, 0.1))
            checkValidator(numberIsUnsignedValidator("applicationWorkerMemory", this.benchmark.applicationWorkerMemory!, false, 0.1))

            checkValidator(numberIsUnsignedValidator("applicationEndpointCPU", this.benchmark.applicationEndpointCPU!, false, 0.1))
            checkValidator(numberIsUnsignedValidator("applicationEndpointMemory", this.benchmark.applicationEndpointMemory!, false, 0.1))

            checkValidator(numberIsUnsignedValidator("applicationsPerWorker", this.benchmark.applicationsPerWorker!, true, 1))
        }
    }

    print() {
        console.log(this)
    }

    formatted(){
        return {
            infrastructure: {
                provider: this.infrastructure.provider,
                infra_only: this.infrastructure.infraOnly,
                cloud_nodes: this.infrastructure.nodes.cloud,
                edge_nodes: this.infrastructure.nodes.edge,
                endpoint_nodes: this.infrastructure.nodes.endpoint,

                cloud_cores: this.infrastructure.cores.cloud,
                edge_cores: this.infrastructure.cores.edge,
                endpoint_cores: this.infrastructure.cores.endpoint,

                cloud_memory: this.infrastructure.memory.cloud,
                edge_memory: this.infrastructure.memory.edge,
                endpoint_memory: this.infrastructure.memory.endpoint,

                cloud_quota: this.infrastructure.quota.cloud,
                edge_quota: this.infrastructure.quota.edge,
                endpoint_quota: this.infrastructure.quota.endpoint,

                cloud_read_speed: this.infrastructure.readWriteSpeed?.readSpeed?.cloud,
                edge_read_speed: this.infrastructure.readWriteSpeed?.readSpeed?.edge,
                endpoint_read_speed: this.infrastructure.readWriteSpeed?.readSpeed?.endpoint,

                cloud_write_speed: this.infrastructure.readWriteSpeed?.writeSpeed?.cloud,
                edge_write_speed: this.infrastructure.readWriteSpeed?.writeSpeed?.edge,
                endpoint_write_speed: this.infrastructure.readWriteSpeed?.writeSpeed?.endpoint,

                cpu_pin: this.infrastructure.cpuPin,
                network_emulation: this.infrastructure.networkEmulation,

                wireless_network_preset: this.infrastructure.wirelessNetworkPreset,

                cloud_latency_avg: this.infrastructure.cloudConnection?.latencyAvg,
                cloud_latency_var: this.infrastructure.cloudConnection?.latencyVar,
                cloud_throughput: this.infrastructure.cloudConnection?.throughput,

                edge_latency_avg: this.infrastructure.edgeConnection?.latencyAvg,
                edge_latency_var: this.infrastructure.edgeConnection?.latencyVar,
                edge_throughput: this.infrastructure.edgeConnection?.throughput,

                cloud_edge_latency_avg: this.infrastructure.cloudEdgeConnection?.latencyAvg,
                cloud_edge_latency_var: this.infrastructure.cloudEdgeConnection?.latencyVar,
                cloud_edge_throughput: this.infrastructure.cloudEdgeConnection?.throughput,


                cloud_endpoint_latency_avg: this.infrastructure.cloudEndPointConnection?.latencyAvg,
                cloud_endpoint_latency_var: this.infrastructure.cloudEndPointConnection?.latencyVar,
                cloud_endpoint_throughput: this.infrastructure.cloudEndPointConnection?.throughput,

                edge_endpoint_latency_avg: this.infrastructure.edgeEndPointConnection?.latencyAvg,
                edge_endpoint_latency_var: this.infrastructure.edgeEndPointConnection?.latencyVar,
                edge_endpoint_throughput: this.infrastructure.edgeEndPointConnection?.throughput,

                external_physical_machines: this.infrastructure.externalPhysicalMachines,

                netperf: this.infrastructure.netperf,
                base_path: this.infrastructure.basePath,

                prefixIP: this.infrastructure.prefixIP,
                middleIP: this.infrastructure.middleIP,
                middleIP_base: this.infrastructure.middleIPBase,

                delete: this.infrastructure.delete,

                gcp_cloud: this.infrastructure.gcpConfig?.cloud,
                gcp_edge: this.infrastructure.gcpConfig?.edge,
                gcp_endpoint: this.infrastructure.gcpConfig?.endpoint,

                gcp_region: this.infrastructure.gcpConfig?.region,


                gcp_zone: this.infrastructure.gcpConfig?.zone,


                gcp_project: this.infrastructure.gcpConfig?.project,

                gcp_credentials: this.infrastructure.gcpConfig?.credentials,
            },
            mode: this.mode,
            // the "..." used below is to combine these two objects
            benchmark: {
                ...{
                    resource_manager: this.benchmark?.resourceManager,
                    resource_manager_only: this.benchmark?.resourceManagerOnly,

                    docker_pull: this.benchmark?.dockerPull,

                    application: this.benchmark?.application,

                    application_worker_cpu: this.benchmark?.applicationWorkerCPU,
                    application_worker_memory: this.benchmark?.applicationWorkerMemory,


                    application_endpoint_cpu: this.benchmark?.applicationEndpointCPU,
                    application_endpoint_memory: this.benchmark?.applicationEndpointMemory,

                    applications_per_worker: this.benchmark?.applicationsPerWorker,

                    cache_worker: this.benchmark?.cacheWorker,
                    observability: this.benchmark?.observability
                }, ...this.benchmark?.applicationVars
            }
        }
        
    }

    output() {
        console.log(JSON.stringify(this.formatted()))
    }
}