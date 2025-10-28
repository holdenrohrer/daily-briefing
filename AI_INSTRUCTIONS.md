We are working with SILE v0.15.13. In SILE v0.15.13, \script is
deprecated, and \lua must be used instead.


Your code will automatically be compiled, linted, and tested.
DO NOT recommend the user run any shell commands.


Use pre-existing libraries.
DO NOT re-implement basic functionality that is available from a good-quality external library.


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


utils.sil (definitions accessible from any .sil file)
| % Bulletless lists with customizable spacing between items.
| % Usage: \itemize[itemsep=0.35em]{ \item{First} \item{Second} }
| % If itemsep is omitted, a default compact spacing is used.
...
| % Section box using typesetter:liner for per-line vertical gold rules.
| class:registerCommand("sectionbox", function (options, content)
...
| function SILE.scratch.load_json_file(path)
| -- Loads from "file.json" and returns a Lua object


When writing SILE, don't put all the functional code in a \lua environment.
Prefer using \command to SILE.call("command",...)
Write in a style that will be human-readable.


We have a content/format divide like in HTML/CSS.
sections/*.sil should call format schema (ex: \subtitle, \title, \sectionskip, \itemize, etc)
Formatting primitives (color, font size, skip, penalty, etc) should be managed in holden-report.sil.
Add formatting schema to holden-report.sil as needed.


When working in sections/, never include business logic in the SILE file, like ordering a list or grouping data.
Conditional formatting is okay.
SILE formats should be "dumb" formats.