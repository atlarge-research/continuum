import Configuration from "./configuration"
import { applicationVars } from "./generics"

//TODO: press tab to quickly fill in placeholder values
const newConfiguration = new Configuration(
    {
        infrastructure: {
            provider: 'qemu',
            nodes: { cloud: 2, edge: 0, endpoint: 3 },
            cores: { cloud: 2, edge: 2, endpoint: 2 },
            memory: { cloud: 5, edge: 1, endpoint: 8 },
            quota: { cloud: 0.5, edge: 0.8, endpoint: 0.4 },

        },
        //if infra only is set to true benchmarkConfig can be removed
        benchmark: {
            resourceManager: "kubernetes",
            application: "image_classification", // has to correspond to an existing application module
            applicationVars: applicationVars([
                ["sleep_time", 60], //variable in the sleep application
                // key value pair syntax: ["frequency", 5]
            ])
        }
    }

)

newConfiguration.validate()
newConfiguration.output()


//TODO: press tab to quickly fill in placeholder values
const configList = [
    new Configuration({
        infrastructure: {
            provider: 'qemu',
            nodes: { cloud: 2, edge: 2, endpoint: 2 },  // Options: x >= 0
            cores: { cloud: 2, edge: 2, endpoint: 2 }, // Options: cloud >= 2, edge & endpoint >= 1 (each)
            memory: { cloud: 2, edge: 2, endpoint: 2 }, // x >= 1
            quota: { cloud: 0.3, edge: 0.4, endpoint: 0.8 }, // Options: 0.1 <=x <= 1.0
        },
        benchmark: {
            resourceManager: "kubernetes",
            application: "empty", // has to correspond to an existing application module
            applicationVars: applicationVars([
                ["sleep_time", 60], //variable in the sleep application
                // key value pair syntax: ["frequency", 5]
            ])
        }
    }),
    // more configurations can be placed below,
]

configList.forEach((config) => config.validate())
console.log(JSON.stringify(configList.map(config => config.formatted())))
