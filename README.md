# ckparser

`ckparser` is a small Python utility for modding Paradox games that use the **Jomini** data format, such as *Crusader Kings III* or *Europa Universalis V*.

Its purpose is to convert Jomini data as faithfully as possible into Python data structures (`dict`, `list`, and native scalar types), and, when possible, convert Python/JSON data back into Jomini text.

The project can be used in two main ways:

- as a **command-line tool** to parse files or directories;
- as a **Python library** inside personal modding scripts.

It is primarily intended for modders who want to inspect, transform, export, or automate work on Paradox script data.

## Features

### Jomini → Python / JSON

- parse raw Jomini text into Python data structures;
- parse a single Jomini file into a dictionary;
- parse all `.txt` files in a directory recursively;
- optionally preserve comments;
- optionally detect file encodings automatically with `chardet`;
- partially resolve variables and inline formulas;
- collect global variables from `script_values` before parsing the rest of a mod directory.

### Python / JSON → Jomini

- convert Python dictionaries back into Jomini text;
- revert a JSON file into a Jomini-style text file;
- apply heuristic rules to decide whether a structure should be rendered as a list, a block, or repeated key/value pairs.

> **Important**  
> Reverse conversion is currently **experimental**. It can work well on many simple or moderately structured cases, but it cannot guarantee a perfect reconstruction of all Jomini files.

### Utilities

- convert `HSV` / `HLS` colors to `RGB`;
- convert Jomini dates (`YYYY.MM.DD`) to Python `datetime.date`;
- read files safely with encoding detection;
- walk deeply nested structures;
- parse Paradox localization files (`.yml`).

---

## Installation

### From PyPI

```bash
pip install ckparser
```

### Optional dependency

ckparser does not require external dependencies to run, but it can use chardet for automatic encoding detection.

```bash
pip install chardet
```

Without `chardet`, the parser still works, but encoding detection is disabled.

## Command-line usage

The module can be executed directly with:

```bash
python -m ckparser <path>
```

### Help

```
usage: ckparser.py [-h] [--encoding ENCODING] [--output OUTPUT] [--revert] [--comments] [--debug] path

Parse data from Paradox files in JSON or revert JSON files to Paradox format

positional arguments:
  path                 path to a file or a directory to parse/revert

options:
  -h, --help           show this help message and exit
  --encoding ENCODING  encoding for reading/writing files
  --output OUTPUT      output directory for parsing results
  --revert             revert JSON files?
  --comments           include comments?
  --debug              debug mode?
```

### Examples

Parse a single Jomini file:

```bash
python -m ckparser common/culture/cultures/my_cultures.txt
```

Parse a directory recursively and write JSON output:

```bash
python -m ckparser my_mod/common --output output
```

Include comments and/or dates in the parsed output:

```bash
python -m ckparser my_mod/common --comments --dates
```

Revert a JSON file back to Jomini format:

```bash
python -m ckparser data.json --revert
```

Enable debug logging:

```bash
python -m ckparser my_mod/common --debug
```

### Output behavior

* in parsing mode, each `.txt` file can be converted to `.json`;
* if parsing fails, the intermediate processed text can be saved as a `.error` file for debugging;
* a `ckparser.log` file is generated;
* collected global variables can be saved to `_variables.json`.

## Library usage

### Import

```python
import ckparser
```

### `parse_text`

Convert raw Jomini text into a Python structure.

```python
from ckparser import parse_text

text = """
my_trigger = {
    has_trait = brave
    age >= 16
}
"""

data = parse_text(text)
print(data)
```

### `parse_file`

Convert a Jomini file into a Python dictionary.

```python
from ckparser import parse_file

data = parse_file("common/scripted_triggers/my_triggers.txt")
```

### `parse_all_files`

Parse all .txt files in a directory recursively.

```python
from ckparser import parse_all_files

result = parse_all_files("my_mod/common", keep_data=True)
```

Exmple with JSON export:

```python
result = parse_all_files(
    "my_mod/common",
    output_dir="output",
    save=True,
    keep_data=False,
)
```

### `revert`

Convert a Python structure back into Jomini text.

```python
from ckparser import revert

data = {
    "my_effect": {
        "add_prestige": 100
    }
}

text = revert(data)
print(text)
```

### `revert_file`

Convert a JSON file into a Jomini text file.

```python
from ckparser import revert_file

text = revert_file("my_data.json", save=True, output_dir="output")
```

### `convert_color`

Convert supported color notations into an RGB hex string.

```python
from ckparser import convert_color

print(convert_color(["hsv", 0.5, 0.8, 0.9]))
print(convert_color(["hsv360", 180, 80, 90]))
print(convert_color(["rgb", 255, 128, 0]))
```

### `convert_date`

Convert a Jomini date into datetime.date.

```python
from ckparser import convert_date

date = convert_date("1066.9.15")
print(date)
```

### `read_file`

Read a file using the most appropriate encoding.

```python
from ckparser import read_file

content = read_file("common/landed_titles/00_landed_titles.txt")
```

### `walk`

Traverse a complex nested structure and yield terminal values with their logical path.

```python
from ckparser import walk

for value, path in walk(data):
    print(path, value)
```
	
### `parse_all_locales`

Parse Paradox localization files.

```python
from ckparser import parse_all_locales

locales = parse_all_locales("localization", language="english")
print(locales.get("my_key"))
```

## Data model and design choices

Jomini is flexible, ambiguous, and not always internally consistent from the perspective of conventional programming data structures. ckparser therefore makes a number of practical decisions to produce useful Python output.

### 1. A `{}` block may represent either a dictionary or a list

In Jomini, the same block syntax can represent:

* a dictionary-like structure;
* a list of plain values;
* a list of nested blocks;
* or, in some cases, a mixed structure.

The parser attempts to infer the most reasonable Python representation from context.

### 2. Duplicate keys are converted into lists

In Jomini, the same key may appear multiple times inside the same block:

```
modifier = { factor = 2 }
modifier = { factor = 3 }
```

Since Python dictionaries cannot store duplicate keys, `ckparser` converts the value into a list:

```python
{
    "modifier": [
        {"factor": 2},
        {"factor": 3}
    ]
}
```

This is especially useful for structures involving repeated logical operators such as `if`, `else_if`, `or`, `and`, and similar constructs.

### 3. Non-standard operators are stored explicitly

Jomini supports operators such as:

* `=` (for affectation and comparison)
* `!=`
* `>`
* `<`
* `>=`
* `<=`
* `?=` (exists = ...)
* ... and others

When an operator other than = is encountered, ckparser stores it explicitly:

```python
{
    "age": {
        "@operator": ">=",
        "@value": 16
    }
}
```

This makes the original condition easier to preserve and inspect.

### 4. Variables and formulas

Jomini supports variable references and inline formulas, for example with `@var` or `@[ ... ]`.

`ckparser` attempts to preserve:

* the original expression;
* the semantic type (`variable` or `formula`);
* the evaluated result, when available.

Example:

```json
{
    "some_value": {
        "@type": "variable",
        "@value": "@my_var",
        "@result": 42
    }
}
```

Or:

```json
{
    "scaled_value": {
        "@type": "formula",
        "@value": "@[base_value * 2]",
        "@result": 84
    }
}
```

### 5. Global variables and parsing order

Variable resolution often depends on:

* mod structure;
* file loading order;
* definitions stored in `script_values`;
* previously collected values.

For that reason, `parse_all_files()` can first parse files from `script_values` and register them as global variables before parsing the rest of the directory.

### Comments

By default, comments are removed during parsing.

With `comments=True` or `--comments`, the parser attempts to preserve them in an internal technical representation so they remain available for debugging or later processing.

Comment preservation should be considered practical rather than perfectly lossless.

### Dates

By default, dates are not converted in Python `datetime.date` objects in parsing. 

While convenient, Jomini date format (`Y[YYY].M[M].D[D]`) does not enforce validation and can be invalid.

With `dates=True` or `--dates`, the parser attempts to convert these dates if possible and keeps invalid dates as text.

### Localization parsing

`ckparser` also includes a dedicated parser for Paradox localization files:

```python
from ckparser import parse_all_locales

locales = parse_all_locales("localization", language="english")
```

This supports:

* parsing a single `.yml` file or an entire directory;
* selecting a target language;
* building a `{key: value}` dictionary.

The result can also be saved as JSON.

### Example

#### Jomini input

```
my_entry = {
    name = "Example"
    age >= 16
    is_active = yes
    values = { 1 2 3 }
}
```

#### Python output

```python
{
    "my_entry": {
        "name": "Example",
        "age": {
            "@operator": ">=",
            "@value": 16
        },
        "is_active": True,
        "values": [1, 2, 3]
    }
}
```

#### JSON export

```python
import json
from ckparser import parse_file

data = parse_file("example.txt")
print(json.dumps(data, indent=4, ensure_ascii=False))
```

## Known limitations

### Jomini is inherently ambiguous

Some Jomini blocks mix list-like and dictionary-like behavior in ways that cannot be represented perfectly in Python without making assumptions.

### Reverse conversion is heuristic

The reverse transformation back to Jomini is still heuristic. It works on many straightforward cases, but it may not:

* reconstruct the exact original syntax;
* know whether a structure should be rendered as a list or as repeated keys;
* match the exact conventions expected by a specific game subsystem without additional rules.

### Variable resolution depends on context

Formula and variable evaluation depends on:

* which files have already been parsed;
* what variables are known;
* the order in which parsing occurs;
* the mod’s internal structure.

As a result, some `@result` values may be missing or incomplete if the necessary context is not yet available.

### Edge cases in Paradox scripting

Paradox scripting languages include many practical exceptions, formatting variants, and subsystem-specific conventions. ckparser aims to cover the most useful general cases, but not every possible edge case.

## Typical use cases

* analyzing a mod programmatically;
* exporting Paradox files to JSON for inspection or diffing;
* writing migration or validation scripts;
* extracting data from landed_titles, script_values, events, and similar files;
* building personal Python tooling for Paradox modding workflows.

## API summary

### Parsing

* `parse_text(text, return_text_on_error=False, comments=False, dates=False, filename=None, is_global=False)`
* `parse_file(path, output_dir=None, encoding="utf_8_sig", base_dir=None, save=False, comments=False, dates=False, is_global=False, patch=None)`
* `parse_all_files(path, output_dir=None, encoding="utf_8_sig", keep_data=False, save=False, comments=False, dates=False, variables_first=True)`

### Reversion

* `revert(obj, from_key=None, prev_key=None, depth=-1, sep="\t", sort=False)`
* `revert_file(path, output_dir=None, encoding="utf_8_sig", base_dir=None, save=False)`

### Utilities

* `convert_color(color)`
* `convert_date(date, key=None)`
* `read_file(path, encoding="utf_8_sig")`
* `walk(obj, *from_keys)`
* `parse_all_locales(path, encoding="utf_8_sig", language="english", save=False)`
* `load_variables(filepath="_variables.json")`
* `save_variables(filepath="_variables.json")`

## Project status

`ckparser` is intended as a practical modding tool rather than a formal reference implementation of the Jomini format. The parser is already useful for real automation tasks, while some parts, especially reverse conversion, remain intentionally pragmatic and experimental.

Real-world examples, edge cases, and mod-specific rules are valuable for improving coverage over time.
