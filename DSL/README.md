# Embedded DSL in Typescript
In this README we will explain how to use and/or extend the currently implemented EDSL (Embedded domain specific lanugage).
This implementation is extremely easy to use thanks to the custom VS-Code code snippets which are a core part of making this a productive tool.

## Requirements
To make use of the DSL itself any text editor and access to a terminal will do. With that being said the implementation highly leverages the usage of VS-Code features and thefore we highly recommend you use it.


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
(NOTE: all configuration need to be in the `DSL/` folder so the file has access to npm dependencies (node modules))

If you make any mistake when filling in a variable that only accept specific values, delete the quote marks and press `"`. VS-Code with automatically present you with a list of all possible values.




