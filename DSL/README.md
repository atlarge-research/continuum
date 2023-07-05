# Embedded DSL in Typescript
In this README we will explain how to use and/or extend the currently implemented EDSL (Embedded domain specific lanugage).
This implementation is quite simple to use thanks to the custom VS-Code code snippets which are a core part of making this a productive tool.

## Requirements
To make use of the DSL itself any text editor and terminal will do. With that being said the implementation highly leverages the use of VS-Code features and thefore we highly recommend you use it.


## Quick Start
1. Create a `<filename>.ts file` anywhere under the DSL folder. (we recommend makind a dedicated folder so your files don't get mixed with source code files).
2. Type in the letter cfg.
3. Select one of the snippets presented in VS-Code
4. Type in the name you want to give the configuration and it will automatically fill it in for you every where that its needed.
5. By pressing `TAB` or `SHIFT + TAB` you can navigate back and forth the different placeholders to quickly fill in the correct values. In cases where you can only specify certain values a dropdown with the possible options will be provided.
6. To execute Continuum with the DSL run:
```bash
python3 continuum.py <file_path>
```
NOTE: all configuration need to be in the `DSL/` folder so the file has access to npm dependencies (node modules)

If you make any mistake when filling in a variable that only accept specific values, delete the quote marks and type `"`. VS-Code with automatically present you with a list of all possible values.

## Using Code Snippets
If you would like the gain a better understanding of the code snippets and how to create them you can refer to `continuum/.vscode/dsl_snippets.code-snippets` where they are implemented. For the ease of use of this work, plesae only create files in the format of `cfg_<something>`. This is to keep this implementation simple and consistant to use.

`cfg_basic` can be used to generate the basic structure

## Using Typescript
This section is made for those who want to gain a deeper understandning of the source-code.

For the EDSL we completely use Typescript. Typescript is used for this implementation to impose a high level of type safety and error handling. while Typescript can by implicitly typed, explicitly typing is what makes this language so powerful for this use-case comapared to other programming languages.

### Structure

There are 4 Files That are of concern in this implementation. Each with its own purpose:
+ `Validator.ts` - Contains a custome error handler to keep the error concise and clean.
+ `generics.ts` - Contains the generic data types. The more complex ones are formed as Typescript `Object Types` denoted by the `type` keyword.
+  `validate_generics` - Contains functions made to validate the correctness of the different `generics`.
+  `configuration.ts - Contains a class that encapsulates all of these features and assigns default values according to the specification of continuum. (this means that if you do not specify a value for a non mandatory field it might still be assigned some default value).

### Extension
To extend the EDSL to account for new variables there are multiple things that need to be added.
1. If you can encapsulate all of the new structures you wish to add within the already existing types (either in the framework or in Typescript) you are encouraged to do so. This is to prevent any unnecessary complexity. If thats not possible, define a new type in the generics folder.
2. Add any needed validation functions to `validate_generics` to make sure the data is correct.
3. If some fields are mandatory, make sure to modify the existing code snippets so they still work correctly.
4. Add handling to all of the new types you added to the `configuration.ts` constructor and make sure they are assigned default values if necessary.
5. add the appropriate validations to the `validate()` function.
6. Done









