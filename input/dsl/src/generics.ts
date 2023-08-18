// A generic data map data type that associates numeric values to the 3 types of nodes in the framework. 
// This data type is used to describe different parts of the configuration

export type NodeMap = {
    cloud: number;
    edge: number;
    endpoint: number;
}

export type ReadWriteSpeed = {
    readSpeed?: NodeMap;
    writeSpeed?: NodeMap;
}

export type Connection = {
    latencyAvg?: number;
    latencyVar?: number;
    throughput?: number;
}

export type GCPConfig = {
    cloud: string
    edge: string
    endpoint: string
    region: string
    zone: string
    project: string
    credentials: string
}

// This is used if provider gcp is selected but these values are not provided
export function defaultGCPConfig(): GCPConfig {
    return {
        cloud: "e2-medium",
        edge: "e2-small",
        endpoint: "e2-micro",
        region: "europe-west4",
        zone: "europe-west4-a",
        project: "continuum-123456",
        credentials: "~/.ssh/continuum-123456-12a34b56c78d"
    }
}




export type InfrastructureConfig = {

    provider: "qemu" | "gcp" | "baremetal",
    infraOnly?: boolean,

    nodes: NodeMap; // x >= 0, number of VMs to spawn per tier, ONLY IF X_nodes > 0, then the corresponding X_cores, X_memory, and X_quota are mandatory
    cores: NodeMap; // cloud >= 2 (edge and/or endpoint) >= 1 (each), number of cores per VM
    memory: NodeMap; // x >= 1, Memory in GB per VM
    quota: NodeMap; // 0.1 <= x <= 1.0, CPU bandwidth quota (at 0.5 a VM will use a CPU core for half of the time)

    readWriteSpeed?: ReadWriteSpeed; // x >= 0, Default: 0 (unlimited) Read and write throughputs to disk in MB.
    wirelessNetworkPreset?: "4g" | "5g" // Options: 4g, 5g. Default: 4g

    cpuPin?: boolean // Default: false, Requires total_VM_cores < physical_cores_available (or add more external machines)
    networkEmulation?: boolean // Default: false, Connection instances are only relevant if this is set to true

    cloudConnection?: Connection
    edgeConnection?: Connection
    cloudEdgeConnection?: Connection
    cloudEndPointConnection?: Connection
    edgeEndPointConnection?: Connection

    externalPhysicalMachines?: string[]
    netperf?: boolean
    basePath?: string

    prefixIP?: number // Default: 192.168, format: XXX.XXX,
    middleIP?: number // Default: 100, Any number 1 - 254
    middleIPBase?: number // Default: 90, Any number 1 - 254
    delete?: boolean

    gcpConfig?: GCPConfig
    // benchmarkConfig?: BenchmarkConfig

    executionMode?: "openfaas"
}

export type BenchmarkConfig = {
    //# Options: kubernetes (cloud mode), kubeedge (edge mode), mist (no RM edge), none (local processing on endpoints), kubecontrol (experimental)
    resourceManager: "kubernetes" | "kubeedge" | "mist" | "none" | "kubecontrol"
    resourceManagerOnly?: boolean // Default: true, if true only resource manager, no benchmark executed.
    dockerPull?: boolean // Default: false, Force docker pull for application updates
    application: string // Options: image_classification, empty

    applicationWorkerCPU?: number
    applicationWorkerMemory?: number

    applicationEndpointCPU?: number
    applicationEndpointMemory?: number

    applicationsPerWorker?: number

    applicationVars?: Object

    cacheWorker?: boolean
    observability?: boolean

}

export type ConfigurationMap = {
    infrastructure: InfrastructureConfig,
    benchmark: BenchmarkConfig
}

export const applicationVars = (variables: Iterable<[PropertyKey, any]>) => Object.fromEntries(variables)

