import Configuration from "./configuration"
import { applicationVars } from "./generics"

// This is a simple example of a configuration (generated using snippets)
const configuration = new Configuration({
    infrastructure: {
        provider: 'qemu',
        nodes: { cloud: 2, edge: 0, endpoint: 1 },
        cores: { cloud: 4, edge: 0, endpoint: 1 },
        memory: { cloud: 4, edge: 0, endpoint: 1 },
        quota: { cloud: 1.0, edge: 0, endpoint: 0.5 },
        networkEmulation: true,
        wirelessNetworkPreset: "4g",
    },
    benchmark: {
        resourceManager: "kubernetes",
        application: "image_classification",
        applicationVars: applicationVars([
            ["frequency", 5],
        ])
    }
})

configuration.validate()
configuration.output()