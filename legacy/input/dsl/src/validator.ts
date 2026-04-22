import process from 'process'

export type Validator = { 
    success: boolean,
    errorMessage: string 
}

export function successValidator(): Validator {
    return { success: true, errorMessage: "" }
}

export function errorValidator(error: string): Validator {
    return { success: false, errorMessage: error + " " }
}

export function checkValidator(validator: Validator): void {
    try {
        if (!validator.success) {
            throw validator.errorMessage
        }
    } catch (errorMessage) {
        console.error(("Error: " + errorMessage))
        process.exit(1)
    }
}