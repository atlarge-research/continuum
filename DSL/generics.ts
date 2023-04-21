export type Provider = "qemu" | "gcp" | "baremetal"
export type WirelessNetworkPreset = '4g' | '5g'

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

export type GCPConfiguration = {
    cloud: string
    edge: string
    endpoint: string
    region: string
    zone:string
    project:string
    credentials:string
}

// export type Benchmark = {
//     //# Options: kubernetes (cloud mode), kubeedge (edge mode), mist (no RM edge), none (local processing on endpoints), kubecontrol (experimental)
//     resourceManager: "kubernetes" | "kubeedge" | "mist" | "none" | "kubecontrol"
//     resourceManagerOnly: boolean
//     dockerPull: boolean // Default: false, Force docker pull for application updates
//     application: DEFINE THE APPLICATION TYPE HERE
// }

//made this for now dont know if is needed
export function defaultGCPConfig(): GCPConfiguration {
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

export type ConfigurationMap = {
    provider: Provider,
    infra_only?: boolean,
    nodes: NodeMap,
    cores: NodeMap,
    memory: NodeMap,
    quota: NodeMap,
    readWriteSpeed?: ReadWriteSpeed,
    wirelessNetworkPreset?: WirelessNetworkPreset
    cpuPin?: boolean
    networkEmulation?: boolean
    cloudConnection?: Connection
    edgeConnection?: Connection
    cloudEdgeConnection?: Connection
    cloudEndPointConnection?: Connection
    EdgeEndPointConnection?: Connection
    externalPhysicalMachines?: string[]
    netperf?: boolean
    basePath?: string
    gcpConfig?: GCPConfiguration
}

