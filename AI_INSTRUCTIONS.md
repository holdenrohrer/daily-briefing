We are working with SILE v0.15.13. In SILE v0.15.13, \script is
deprecated, and \lua must be used instead.

Your code will automatically be compiled, linted, and tested.
DO NOT recommend the user run any shell commands.

Use pre-existing libraries.
DO NOT re-implement basic functionality that is available from a good-quality external library.

If you need to access JSON from Lua inside SILE, you NEED TO USE THE
PREDEFINED FUNCTION TO DO THIS.
The predefined function is named SILE.scratch.load_json_file(path).

When writing Python code, DO NOT use environment variables to inherit config.
Instead, use tools/config.py. Import with "from tools import config"
Add your default configuration to tools/config.py
DO NOT manage default configuration inside any other files.
DO NOT get configuration information from anywhere except tools/config.py

This code base follows a FAIL-FAST policy.

Make function requirements explicit.
Use type hints.
Add docstrings that specify what happens when requirements aren't met.
Fail fast if the contract is violated.
Assert that the contract is met.

Avoid patterns like:
- except Exception: pass
- value = input_value or 'default'
- if not config: config = {}
Instead, explicitly check what you expect and fail if it's not there.

Write code that will be easy to debug when it breaks. I'd rather have a clear stack trace pointing to the real problem than code that silently does the wrong thing.
