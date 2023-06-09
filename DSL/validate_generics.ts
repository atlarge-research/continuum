/* 
This implementation encapsulates The different attributes the continuum configuration
suppororts with the use of an EDSL (Embedded Domain Specific Language). 
TS was chosen as it is has many type safety features, which is helpful to complicated systems.

*/
import { ConfigurationMap, NodeMap, ReadWriteSpeed, Connection } from "./generics"
import { Validator, successValidator, errorValidator } from "./validator"

function isUnsignedInt(num: number): boolean {
    return num === Math.floor(num) && num >= 0
}

function isUnsigned(num: number): boolean {
    return num >= 0
}

// 0.1 <=x <= 1.0 for quota NodeMap
function betweenZeroPointOneAndOne(num: number): boolean {
    return num >= 0.1 && num <= 1
}


export function numberIsUnsignedValidator(variableName: string, num: number, isInteger: boolean, minimalValue?: number): Validator {
    return isInteger
        ? isUnsignedInt(num) && (minimalValue == null || num >= minimalValue)
            ? successValidator()
            : errorValidator(`${variableName} needs to have a non-negative Integer value. Current value is ${num}. ${minimalValue != null ? `minimal value is ${minimalValue}`:``}`)
        : isUnsigned(num) && (minimalValue == null || num >= minimalValue)
            ? successValidator()
            : errorValidator(`${variableName} needs to have a non-negative numeric value. Current value is ${num}. ${minimalValue != null ? `minimal value is ${minimalValue}`:``}`)
}

//takes either the Nodes or the Cores and checks that all values are integers.
// the  variable name is used do describe what nodeMap instance causing an error (if it occurs)
function nodeMapUnsignedIntValidator(nodeMap: NodeMap, variableName: string): Validator {
    if (isUnsignedInt(nodeMap.cloud) &&
        isUnsignedInt(nodeMap.edge) &&
        isUnsignedInt(nodeMap.endpoint)) {
        return successValidator()
    }
    return errorValidator("Invalid values passed in " + variableName + ": cloud, edge and endpoint values must be unsigned integers")
}

// function nodeMapUnsigedFloatValidator(nodeMap?: NodeMap, ): Validator {
//     return nodeMap == null || nodeMap.cloud >= 0 && nodeMap.edge >= 0 && nodeMap.endpoint >= 0
// }

function nodeMapUnsignedFloatValidator(nodeMap: NodeMap, variableName: string): Validator {
    if (isUnsigned(nodeMap.cloud) &&
        isUnsigned(nodeMap.edge) &&
        isUnsigned(nodeMap.endpoint)) {
        return successValidator()
    }
    return errorValidator("Invalid value passed in " + variableName + ": cloud, edge and endpoint values must be >= 0")
}

function atleastOneNodeValidator(nodes: NodeMap): Validator {
    if (nodes.cloud + nodes.edge + nodes.endpoint > 0) {
        return successValidator()
    }
    return errorValidator("Atleast 1 node needs to be created")
}

//if there is atleast 1 node, there needs to be atleast 1 core for that node.
function checkNumberOfCoresPerNode(numberOfNodes: number, numberOfCores: number): boolean {
    return numberOfNodes === 0 || (numberOfNodes > 0 && numberOfCores >= 1)
}

function checkQuotaPerNode(numberOfNodes: number, quotaValue: number): boolean {
    return numberOfNodes === 0 || betweenZeroPointOneAndOne(quotaValue)
}

function checkMemoryPerNode(numberOfNodes: number, memoryValue: number): boolean {
    return numberOfNodes === 0 || memoryValue >= 1
}

function NullOrBiggerThanZero(num?: number): boolean {
    return num == null || num >= 0
}

function NullOrBiggerThanOne(num?: number): boolean {
    return num == null || num >= 1
}

export function nodesValidator(nodes: NodeMap): Validator {

    const atleastOneNodeValid = atleastOneNodeValidator(nodes)
    const integerValid = nodeMapUnsignedIntValidator(nodes, "nodes")

    return {
        success: atleastOneNodeValid.success && integerValid.success,
        errorMessage: atleastOneNodeValid.errorMessage + integerValid.errorMessage
    }
}

export function coresValidator(nodes: NodeMap, cores: NodeMap): Validator {
    var success: boolean = true
    var errorMessage: string = ""

    const unsignedIntValidator = nodeMapUnsignedIntValidator(cores, "cores")

    if (!unsignedIntValidator.success) {
        success = false
        errorMessage += unsignedIntValidator.errorMessage
    }

    if (!checkNumberOfCoresPerNode(nodes.cloud, cores.cloud)) {
        success = false
        errorMessage += "Atleast one core is needed per cloud node \n"
    }
    if (!checkNumberOfCoresPerNode(nodes.edge, cores.edge)) {
        success = false
        errorMessage += "Atleast one core is needed per edge node \n"

    }
    if (!checkNumberOfCoresPerNode(nodes.endpoint, cores.endpoint)) {
        success = false
        errorMessage += "Atleast one core is needed per endpoint node \n"
    }
    return success ? successValidator() : errorValidator(errorMessage)
}

export function quotaValidator(nodes: NodeMap, quota: NodeMap): Validator {
    if (checkQuotaPerNode(nodes.cloud, quota.cloud) &&
        checkQuotaPerNode(nodes.edge, quota.edge) &&
        checkQuotaPerNode(nodes.endpoint, quota.endpoint)) {
        return successValidator()
    }
    return errorValidator("Quota values must be: 0.1 <= x <= 1.0")
}

// TODO: ask if should be integer or not
export function memoryValidator(nodes: NodeMap, memory: NodeMap): Validator {
    if (checkMemoryPerNode(nodes.cloud, memory.cloud) &&
        checkMemoryPerNode(nodes.edge, memory.edge) &&
        checkMemoryPerNode(nodes.endpoint, memory.endpoint)) {
        return successValidator()
    }
    return errorValidator("Memory values must be atleast 1")
}

export function readWriteSpeedValidator(readWriteSpeed: ReadWriteSpeed | undefined): Validator {
    if(!readWriteSpeed) return errorValidator("Invalid Read/Write Speed")
    const readSpeedValidator = nodeMapUnsignedIntValidator(readWriteSpeed.readSpeed!, "read speed")
    const writeSpeedValidator = nodeMapUnsignedIntValidator(readWriteSpeed.writeSpeed!, "write speed")

    if (readSpeedValidator.errorMessage.length > 0) readSpeedValidator.errorMessage += '\nError: '

    return {
        success: readSpeedValidator.success && writeSpeedValidator.success,
        errorMessage: readSpeedValidator.errorMessage + writeSpeedValidator.errorMessage,
    }
}

export function connectionValidator(connection: Connection | undefined): Validator {
    const errorMessage = "Invalid connection settings value/s. The following needs to hold:\nlatency avg >= 0, latency var >= 0 and throughput >= 1"
    if(!connection) return errorValidator(errorMessage);
    if (NullOrBiggerThanZero(connection.latencyAvg) &&
        NullOrBiggerThanZero(connection.latencyVar) &&
        NullOrBiggerThanOne(connection.throughput)) {
        return successValidator()
    }
    return errorValidator(errorMessage)
}

//between 0 and 255
function is8BitNumber(num: number | undefined): boolean {
    if(!num) return false
    return isUnsignedInt(num) && num <= 255
}

export function prefixIPValidator(prefixIP: number | undefined): Validator {
    if(!prefixIP) return errorValidator("Invalid Prefix IP")
    const first = Math.floor(prefixIP)
    const second = prefixIP * 1000 % 1000
    if (is8BitNumber(first) && is8BitNumber(second)) {
        return successValidator()
    }
    return errorValidator("Prefix IP needs to be of the format XXX.XXX where each XXX is between 0 and 255")
}

export function is8BitValidator(variableName: string, num: number | undefined): Validator {
    if(!num) return errorValidator(`${variableName} needs to be between 0 and 255`)
    return is8BitNumber(num) ? successValidator() : errorValidator(`${variableName} needs to be between 0 and 255, actual value: ${num}`)
}



