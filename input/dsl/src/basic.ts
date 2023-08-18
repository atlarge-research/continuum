import Configuration from "./configuration"
import { applicationVars } from "./generics"


// this is a simple example of a configuration (generated using snippets)
const configuration = new Configuration({
    infrastructure: {
        provider: 'qemu',
        nodes: { cloud: 0, edge: 1, endpoint: 1 }, 
        cores: { cloud: 1, edge: 1, endpoint: 11 }, 
        memory: { cloud: 2, edge: 1, endpoint: 1 }, 
        quota: { cloud: 0.4, edge: 0.3, endpoint: 0.5 }, 
    },
    benchmark: {
        resourceManager: "kubernetes",
        application: "empty", 
        applicationVars: applicationVars([
            ["sleep_time", 60], 
            
        ])
    }
})
configuration.validate()
configuration.output()
































//TODO: press tab to quickly fill in placeholder values
// const configList = [
//     new Configuration({
//         infrastructure: {
//             provider: 'qemu',
//             nodes: { cloud: 2, edge: 2, endpoint: 2 },  // Options: x >= 0
//             cores: { cloud: 2, edge: 2, endpoint: 2 }, // Options: cloud >= 2, edge & endpoint >= 1 (each)
//             memory: { cloud: 2, edge: 2, endpoint: 2 }, // x >= 1
//             quota: { cloud: 0.3, edge: 0.4, endpoint: 0.8 }, // Options: 0.1 <=x <= 1.0
//             middleIP: 244,
//             middleIPBase: 246
            
//         },
//         benchmark: {
//             resourceManager: "kubernetes",
//             application: "empty", // has to correspond to an existing application module
//             applicationVars: applicationVars([
//                 ["sleep_time", 60], //variable in the sleep application
//                 // key value pair syntax: ["frequency", 5]
//             ])
//         }
//     }),
//     // more configurations can be placed below,
// ]

// configList.forEach((config) => config.validate())
// console.log(JSON.stringify(configList.map(config => config.formatted())))

