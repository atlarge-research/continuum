/*
custom error handling type
*/
import process from 'process'

export type Validator = { success: boolean, errorMessage: string }
export function successValidator(): Validator {
    return { success: true, errorMessage: "" }
}

export function errorValidator(error: string): Validator {
    return { success: false, errorMessage: error + "\n" }
}

export function checkValidator(validator: Validator): void {
    try {
        if (!validator.success) {
            throw new Error(validator.errorMessage)
        }
    } catch (error) {
        console.log(('\n' + error + '').split("\t")[0])
        // console.log(error)
        process.exit(1)
    }
}