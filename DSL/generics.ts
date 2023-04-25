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
    zone:string
    project:string
    credentials:string
}

//made this for now dont know if is needed
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

    applicationVars?: Object
}


export type ConfigurationMap = {

    provider: "qemu" | "gcp" | "baremetal",
    infra_only?: boolean,
    
    nodes: NodeMap,
    cores: NodeMap,
    memory: NodeMap,
    quota: NodeMap,

    readWriteSpeed?: ReadWriteSpeed,
    wirelessNetworkPreset?: "4g" | "5g"

    cpuPin?: boolean
    networkEmulation?: boolean

    cloudConnection?: Connection
    edgeConnection?: Connection
    cloudEdgeConnection?: Connection
    cloudEndPointConnection?: Connection
    EdgeEndPointConnection?: Connection

    //Continue: validate from here//

    externalPhysicalMachines?: string[]
    netperf?: boolean
    basePath?: string

    prefixIP?: number // Default: 192.168, format: XXX.XXX,
    middleIP?: number // Default: 100, Any number 1 - 254
    middleIPBase?: number // Default: 90, Any number 1 - 254
    delete?: boolean

    gcpConfig?: GCPConfig
    benchmarkConfig?: BenchmarkConfig
}

