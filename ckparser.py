# -*- coding: utf-8 -*-
"""
ckparser
~~~~~~~~

A lightweight Python parser for Paradox Jomini data files.

This module provides tools to parse Jomini-based script files used by
Paradox games such as Crusader Kings III and Europa Universalis V into
Python data structures, and to revert Python/JSON data back to a
Jomini-like text format.

Main features
-------------
- Parse raw Jomini text into Python dictionaries/lists
- Parse individual files or entire directories recursively
- Preserve comments optionally
- Resolve variables and formulas when possible
- Revert Python/JSON structures back to Jomini text (experimental)
- Parse localization files
- Provide helper utilities for color conversion, date conversion,
  encoding-aware file reading, and nested structure traversal

This project is primarily intended for modding, data inspection,
automation, and personal tooling around Paradox script files.

Author: Marc Debureaux (debnet)
Project: https://github.com/debnet/ckparser
License: MIT
"""

import argparse
import ast
import colorsys
import datetime
import functools
import json
import logging
import os
import re
import time

# Script version
__version__ = "0.3"

# Logger (because logging is awesome)
logger = logging.getLogger(__name__)

# Try to import chardet for encoding detection
try:
    from chardet import detect
except ImportError:
    detect = None
    logger.warning("chardet not installed, encoding detection is disabled!")


class JominiJSONEncoder(json.JSONEncoder):
    # JSON specific encoder for dates
    def default(self, obj):
        if isinstance(obj, datetime.date):
            return f"{obj.year}.{obj.month}.{obj.day}"
        return super().default(obj)


def jomini_object_hook(obj):
    # JSON specific decoder for dates
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str) and regex_date.fullmatch(value):
                obj[key] = convert_date(value) or value
            elif isinstance(value, list):
                obj[key] = jomini_object_hook(value)
    elif isinstance(obj, list):
        for index in range(len(obj)):
            item = obj[index]
            if isinstance(item, str) and regex_date.fullmatch(item):
                obj[index] = convert_date(item) or item
            elif isinstance(item, list):
                obj[index] = jomini_object_hook(item)
    return obj


json_load = functools.partial(json.load, object_hook=jomini_object_hook)
json_loads = functools.partial(json.loads, object_hook=jomini_object_hook)
json_dump = functools.partial(json.dump, cls=JominiJSONEncoder, indent=4)
json_dumps = functools.partial(json.dumps, cls=JominiJSONEncoder, indent=4)

# Boolean transformation
booleans = {"yes": True, "no": False}
# Tags which must be aggregate as a list in JSON (don't hesitate to add more if needed)
forced_list_keys = []  # "if", "else_if", "else", "not", "or", "and", "nor", "nand", "root", "from", "prev"
# Tags or tag couples which be forced as a string in revert parser
forced_string_keys = [("genes", None)]
# Special keywords
keywords = ("scripted_trigger", "scripted_effect")
# Variables collected in files
global_variables = {}

# Regex to find and replace quoted string
regex_string = re.compile(r"\"[^\"\n]*\"")
regex_string_multiline = re.compile(r"\"[^\"]*\"", re.MULTILINE)
# Regex for quoted strings inside quoted strings
regex_inner_string = re.compile(r"\|(?P<index>\d+)\|")
# Regex to remove comments in files
regex_comment = re.compile(r"(?P<space>\s*)(?P<comment>#.*)", re.MULTILINE)
# Regex to fix blocks with no equal sign
regex_missing = re.compile(r"^\s*([\w\.]+)\s+([{])", re.MULTILINE)
# Regex to remove "list" prefix
regex_list = re.compile(r"\s*=\s*list\s+([\{\"\|])", re.MULTILINE)
# Regex for color blocks (color = [rgb|hsv] { x y z })
regex_color = re.compile(r"=\s*(?P<type>\w+)\s*{", re.MULTILINE)
# Regex to parse items with format key=value
regex_inline = re.compile(r"([^\s\"]+\s*[?!<=>]+\s*(([^@\"]\[?[^\s]+\]?)|(\"[^\"]+\")|(@\[[^\]]+\]))|(@\w+))")
# Regex to parse blocks with bracket below the key/operator
regex_block = re.compile(r"(\s*([?!<=>]+)\s+\{)|(\s+\s*([?!<=>])+\s*\{)", re.MULTILINE)
# Regex to parse lines with format key=value
regex_line = re.compile(r"\"?(?P<key>[^\s\"]+)\"?\s*(?P<operator>[?!<=>]+)\s*(list\s*)?(?P<value>.*)")
# Regex to parse independent items in a list
regex_item = re.compile(r"(\"[^\"]+\"|[\d\.]+|[^\s]+)")
# Regex to parse dates
regex_date = re.compile(r"^(?:\d{1,4})\.(?:[1-9]|1[0-2])\.(?:[1-9]|[12]\d|3[01])$")
# Regex to remove empty lines
regex_empty = re.compile(r"(\n\s*\n)+", re.MULTILINE)
# Regex to parse locale files
regex_locale = re.compile(r"^\s*(?P<key>[^\:#]+)\:(\d+)?\s\"(?P<value>.+)\".*$")
# Regex for keywords
regex_keyword = re.compile(r"(" + "|".join(map(re.escape, sorted(keywords, key=len, reverse=True))) + r") ")
# Regex for fixing line count when bracket is below the key/operator
regex_count = re.compile(r"([?!<=>]+)\s*([§\n]+)\s*\{")
# Regex for string indexes
regex_index = re.compile(r"\|(\d+)\|")
# Regex for variables
regex_variables = re.compile(r"\b([\w]+)\b")


def convert_color(color):
    if not color:
        return ""
    if isinstance(color, str):
        return color
    if len(color) > 3 and isinstance(color[0], str):
        color_type, *color = color[:4]
        if color_type == "hsv360":
            color = [int(c) / 360 for c in color]
            color_type = "hsv"
        if color_type != "rgb":
            try:
                functions = {"hsv": colorsys.hsv_to_rgb, "hls": colorsys.hls_to_rgb}
                color = functions.get(color_type)(*color)
            except:  # noqa
                logger.warning(f"Unable to convert color {color} ({color_type}")
                return ""
    if any(isinstance(c, float) for c in color):
        color = [round(c * 255) for c in color]
    r, g, b = (hex(int(c)).split("x")[-1] for c in color[:3])
    return f"{r:>02}{g:>02}{b:>02}"


def convert_date(date, key=None):
    if not date:
        return None
    try:
        year, month, day = (int(d) for d in date.split("."))
        return datetime.date(year, month, day)
    except Exception as error:
        logger.error(f'Error converting date "{date}" for "{key}": {error}')
        return None


def read_file(path, encoding="utf_8_sig"):
    """
    Try to read file with encoding
    If chardet is installed, encoding will be automatically detected
    :param path: Path to file
    :param encoding: Encoding
    :return: File content
    """
    if not os.path.exists(path) or not os.path.isfile(path):
        return
    if detect:
        with open(path, "rb") as file:
            raw_data = file.read()
        if result := detect(raw_data):
            encoding = result["encoding"]
            logger.debug(f"Detected encoding: {result['encoding']} ({result['confidence']:0.0%})")
        del raw_data
    with open(path, "r", encoding=encoding) as file:
        return file.read()


def parse_text(text, return_text_on_error=False, comments=False, dates=False, filename=None, is_global=False):
    """
    Parse raw text
    :param text: Text to parse
    :param return_text_on_error: (default false) Return working text document if parsing fails
    :param comments: (default false) Include comments?
    :param dates: (default false) Include dates?
    :param filename: (default none) Filename (only for debugging)
    :param is_global: (default false) Are variables global?
    :return: Parsed data as dictionary
    """

    def replace(match):
        nonlocal strings, strings_index
        strings_index = len(strings)
        strings[str(strings_index)] = match.group(0).replace("\n", "\\n")
        return f"|{strings_index}|"

    def replace_comment(match):
        nonlocal strings, strings_index
        strings_index = len(strings)
        value, space = match.group("comment").replace('"', "'").strip(), match.group("space")
        strings[str(strings_index)] = f'"{value}"'
        if not value.strip():
            return ""
        return f"\n{space}#{strings_index}=|{strings_index}|"

    def set_variable(key, value, is_global=is_global):
        global global_variables
        nonlocal variables
        lkey = key.lstrip("@")
        variables[key] = variables[lkey] = value
        if is_global:
            global_variables[key] = global_variables[lkey] = value

    root = {}
    nodes = [("", root)]
    strings, strings_index = {}, 0
    variables = global_variables.copy()
    # Cleaning document
    text = text.replace("\n", "\n§\n")
    text = regex_string.sub(replace, text)
    if comments:
        text = regex_comment.sub(replace_comment, text)
    else:
        text = regex_comment.sub("", text)
    text = regex_string_multiline.sub(replace, text)
    if missings := regex_missing.findall(text):
        if filename:
            logger.warning(f"Filename: {filename}")
        for key, val in missings:
            logger.warning(f"Potential missing `=` operator between `{key}` and `{val}` needs to be fixed.")
        text = regex_missing.sub(r"\g<1>=\g<2>", text)
    text = regex_color.sub(r"={\n\g<1>", text)
    text = regex_list.sub(r"|list=\g<1>", text)
    text = text.replace("{", "\n{\n").replace("}", "\n}\n")
    text = regex_inline.sub(r"\g<1>\n", text)
    text = regex_block.sub(r"\g<2>\g<4>{", text)
    text = regex_empty.sub(r"\n", text)
    text = regex_keyword.sub(r"\1|", text)
    text = regex_count.sub(r"\g<1>{\n\g<2>", text)
    text = regex_index.sub(lambda match: strings[match.group(1)], text)

    # Parsing document line by line
    line_number = 1
    for line_text in text.splitlines():
        try:
            line_text = line_text.strip()
            # Line number
            if count := line_text.count("§"):
                line_number += count
                line_text = line_text.rstrip("§")
            # Nothing to do if line is empty
            if not line_text:
                continue
            # Get the current node
            node_name, node = nodes[-1]
            # If line is key=value
            if match := regex_line.fullmatch(line_text):
                key, operator, _, value = match.groups()
                value = value.strip()
                if subindexes := key.startswith("#") and regex_inner_string.findall(value):
                    for subindex in subindexes:
                        value = value.replace(f"|{subindex}|", strings[subindex], 1)
                    value = value.strip('"')  # Removing extra quotes
                # If value is a new block
                if value.endswith("{"):
                    item = {}
                    # If key is duplicate with inner block
                    if key in node:
                        if not isinstance(node[key], list):
                            node[key] = [node[key]]
                        if operator != "=":
                            node[key].append({"@operator": operator, "@value": item})
                        else:
                            node[key].append(item)
                    # If this block name must be forced as list
                    elif key.lower() in forced_list_keys:
                        node[key] = [item]
                    elif isinstance(node, list):  # Only for on_actions...
                        node.append(item)
                    elif operator != "=":
                        node[key] = {"@operator": operator, "@value": item}
                    else:
                        node[key] = item
                    # Change current node for next lines
                    nodes.append((key, item))
                    continue
                elif (val := booleans.get(value.lower())) is not None:
                    # Convert to boolean
                    value = val
                elif value:
                    # Try to convert value to Python value
                    if dates and regex_date.fullmatch(value):
                        value = convert_date(value) or value
                    else:
                        try:
                            value = ast.literal_eval(value)
                        except:  # noqa
                            pass
                # If key is duplicate with direct value
                if key in node:
                    if node[key] != value:  # Avoid single duplicates
                        if not isinstance(node[key], list):
                            node[key] = [node[key]]
                        if isinstance(value, str) and (value.startswith("@") or value in variables):
                            if (result := variables.get(value)) is None:
                                if filename:
                                    logger.warning(f"Filename: {filename}")
                                logger.warning(f'Value for "{value}" cannot be found (line: {line_number})')
                            node[key].append({"@type": "variable", "@value": value, "@result": result})
                        else:
                            node[key].append(value)
                # If this key must be forced as list
                elif key.lower() in forced_list_keys:
                    node[key] = [value]
                else:
                    # If operator is not equal
                    if operator != "=":
                        node[key] = {"@operator": operator, "@value": value}
                        if isinstance(value, str):
                            if value == "":
                                node[key]["@value"] = item = {}
                                nodes.append(("@", item))
                            elif value.startswith("@[") and value.endswith("]"):
                                formula = value.lstrip("@[").rstrip("]")
                                if variables:
                                    repl = lambda match: str(variables.get(match.group(1), match.group(1)))
                                    formula = regex_variables.sub(repl, formula)
                                try:
                                    result = eval(formula, None, variables)
                                except Exception as exception:
                                    if filename:
                                        logger.warning(f"Filename: {filename}")
                                    logger.warning(
                                        f"Formula [{formula}] (line: {line_number}) can't be evaluated: {exception}"
                                    )
                                    result = None
                                if isinstance(result, float):
                                    result = round(result, 5)
                                node[key]["@value"] = {"@type": "formula", "@value": value, "@result": result}
                            elif value.startswith("@") or value in variables:
                                if (result := variables.get(value)) is None:
                                    if filename:
                                        logger.warning(f"Filename: {filename}")
                                    logger.warning(f'Value for "{value}" cannot be found (line: {line_number})')
                                node[key]["@value"] = {"@type": "variable", "@value": value, "@result": result}
                    # If value is a formula
                    elif isinstance(value, str) and not key.startswith("#"):
                        if value.startswith("@[") and value.endswith("]"):
                            formula = value.lstrip("@[").rstrip("]")
                            if variables:
                                repl = lambda match: str(variables.get(match.group(1), match.group(1)))
                                formula = regex_variables.sub(repl, formula)
                            try:
                                result = eval(formula, None, variables)
                            except Exception as exception:
                                if filename:
                                    logger.warning(f"Filename: {filename}")
                                logger.warning(
                                    f"Formula [{formula}] (line: {line_number}) can't be evaluated: {exception}"
                                )
                                result = None
                            if isinstance(result, float):
                                result = round(result, 5)
                            node[key] = {"@type": "formula", "@value": value, "@result": result}
                            if result is not None and (key.startswith("@") or len(nodes) == 1):
                                set_variable(key, result)
                        elif value.startswith("@"):
                            if (result := variables.get(value)) is None:
                                if filename:
                                    logger.warning(f"Filename: {filename}")
                                logger.warning(f'Value for "{value}" cannot be found (line: {line_number})')
                            node[key] = {"@type": "variable", "@value": value, "@result": result}
                            if result is not None and (key.startswith("@") or len(nodes) == 1):
                                set_variable(key, result)
                        elif (result := variables.get(value)) is not None:
                            if not isinstance(result, str):
                                node[key] = {"@type": "variable", "@value": value, "@result": result}
                                if result is not None and (key.startswith("@") or len(nodes) == 1):
                                    set_variable(key, result)
                        elif key.startswith("#") and isinstance(node, list):
                            if subindexes := regex_inner_string.findall(value):
                                for subindex in subindexes:
                                    value = value.replace(f"|{subindex}|", strings[subindex], 1)
                                value = value.strip('"')  # Removing extra quotes
                            node.append(f"#{value}#")
                        else:
                            node[key] = value
                            if value is not None and (key.startswith("@") or len(nodes) == 1):
                                set_variable(key, value)
                    elif isinstance(node, list) and key.startswith("#"):
                        if subindexes := regex_inner_string.findall(value):
                            for subindex in subindexes:
                                value = value.replace(f"|{subindex}|", strings[subindex], 1)
                            value = value.strip('"')  # Removing extra quotes
                        node.append(f"#{value}#")
                    else:
                        node[key] = value
                        if value is not None and not key.startswith("#") and (key.startswith("@") or len(nodes) == 1):
                            set_variable(key, value)
            # If line is opening bracket inside an operator
            elif line_text == "{" and node_name == "@":
                continue
            # If line is closing block
            elif line_text == "}":
                # Return to previous node
                nodes.pop()
            # If line is a list or list item
            else:
                # Ensure previous data are treated as list
                if not isinstance(node, list):
                    if len(nodes) < 2:
                        raise SyntaxError("Incorrect file format or syntax!")
                    _, prev = nodes[-2]
                    if node_name:
                        if node and isinstance(node, dict):
                            (key, value), *_ = node.items()
                            if key.startswith("#"):
                                if subindexes := regex_inner_string.findall(value):
                                    for subindex in subindexes:
                                        value = value.replace(f"|{subindex}|", strings[subindex], 1)
                                    value = value.strip('"')  # Removing extra quotes
                                prev[node_name] = node = [f"#{value}#"]
                            elif node_name in ("on_actions", "events"):  # Only for on_actions/events...
                                prev[node_name] = node = []
                            else:
                                if filename:
                                    logger.warning(f"Filename: {filename}")
                                logger.warning(
                                    f"Single value cannot be added to a dictionary "
                                    f"(line {line_number}: {line_text})"
                                )
                                continue
                        elif isinstance(prev, dict):
                            prev[node_name] = node = []
                    elif isinstance(prev, list):
                        prev[-1] = node = []
                    nodes[-1] = (node_name, node)
                # If list is composed of blocks
                if line_text == "{":
                    item = {}
                    node.append(item)
                    nodes.append(("", item))
                # Or if list is composed of plain values
                else:
                    # Find every couple of key=value
                    for item in regex_item.findall(line_text):
                        if item.startswith("@[") and item.endswith("]"):
                            formula = item.lstrip("@[").rstrip("]")
                            if variables:
                                repl = lambda match: str(variables.get(match.group(1), match.group(1)))
                                formula = regex_variables.sub(repl, formula)
                            try:
                                result = eval(formula, None, variables)
                            except Exception as exception:
                                if filename:
                                    logger.warning(f"Filename: {filename}")
                                logger.warning(
                                    f"Formula [{formula}] (line: {line_number}) can't be evaluated: {exception}"
                                )
                                result = None
                            if isinstance(result, float):
                                result = round(result, 5)
                            node.append({"@type": "formula", "@value": value, "@result": result})
                        elif item.startswith("@"):
                            if (result := variables.get(item)) is None:
                                if filename:
                                    logger.warning(f"Filename: {filename}")
                                logger.warning(f'Value for "{value}" cannot be found (line: {line_number})')
                            node.append({"@type": "variable", "@value": item, "@result": result})
                        elif dates and regex_date.fullmatch(item):
                            item = convert_date(item) or item
                            node.append(item)
                        else:
                            try:
                                item = ast.literal_eval(item)
                            except:  # noqa
                                pass
                            node.append(item)
        except Exception as error:
            if filename:
                logger.error(f"Filename: {filename}")
            logger.error(f"Line {line_number}: {line_text}")
            logger.error(f"Parse error: {error}")
            logger.debug("Exception:", exc_info=True)
            return text if return_text_on_error else None
    return root


def parse_file(
    path,
    output_dir=None,
    encoding="utf_8_sig",
    base_dir=None,
    save=False,
    comments=False,
    dates=False,
    is_global=False,
    patch=None,
):
    """
    Parse file
    :param path: Path to file to parse
    :param output_dir: Directory where to save parsed file
    :param encoding: Encoding used to read file
    :param base_dir: Base directory (for debug)
    :param save: (default false) Save parsed file in output directory
    :param comments: Include comments?
    :param dates: Include dates?
    :param is_global: (default false) Are file's variables global?
    :param patch: String replacement patterns
    :return: Parsed data as dictionary or text if parsing fails
    """
    start_time = time.monotonic()
    if base_dir:
        base_dir = os.sep.join(str(base_dir).rstrip(os.sep).split(os.sep)[:-1]) + os.sep
        base_dir = os.path.dirname(path.replace(base_dir, ""))
    base_dir = base_dir or "."
    text = read_file(path, encoding)
    if not text or not text.strip():
        return None
    for pattern, replacement in patch or []:
        text = re.sub(pattern, replacement, text)
    filename = os.path.join(base_dir, os.path.basename(path))
    logger.debug(f"Parsing {filename}")
    data = parse_text(
        text, return_text_on_error=True, comments=comments, dates=dates, filename=filename, is_global=is_global
    )
    if save:
        filename, _ = os.path.splitext(os.path.basename(path))
        directory = os.path.join(output_dir or "output", *base_dir.split(os.sep))
        os.makedirs(directory, exist_ok=True)
        if not isinstance(data, dict):
            filename = os.path.join(directory, filename + ".error")
            try:
                with open(filename, "w", encoding=encoding) as file:
                    file.write(data)
            except UnicodeEncodeError as error:
                logger.error(f"Unable to write file {filename}: {error}")
        else:
            filename = os.path.join(directory, filename + ".json")
            with open(filename, "w", encoding="utf-8") as file:
                json_dump(data, file)
    total_time = time.monotonic() - start_time
    logger.debug(f"Elapsed time: {total_time:0.3f}s!")
    return data


def parse_all_files(
    path,
    output_dir=None,
    encoding="utf_8_sig",
    keep_data=False,
    save=False,
    comments=False,
    dates=False,
    variables_first=True,
    _variables_only=False,
):
    """
    Parse all text files in a directory
    :param path: Path where to find files to parse
    :param output_dir: Directory where to save parsed files
    :param encoding: Encoding used to read files
    :param keep_data: (default false) Return parsed data of all files in a dictionary
    :param save: (default false) Save every parsed data in output directory
    :param comments: Include comments?
    :param dates: Include dates?
    :param variables_first: Try to parse variables first
    :return: Dictionary (key: file, value: parsed data if keep_data=True)
    """
    start_time = time.monotonic()
    success, errors = {}, []
    if variables_first and not _variables_only:
        success.update(
            parse_all_files(
                path=path,
                output_dir=output_dir,
                encoding=encoding,
                keep_data=keep_data,
                save=save,
                comments=comments,
                dates=dates,
                variables_first=False,
                _variables_only=True,
            )
        )
    for current_path, _, all_files in os.walk(path):
        is_script_values = current_path.endswith("script_values")
        if (_variables_only and not is_script_values) or (not _variables_only and variables_first and is_script_values):
            continue
        for filename in all_files:
            if not filename.lower().endswith(".txt"):
                continue
            filepath = os.path.join(current_path, filename)
            data = parse_file(
                filepath,
                output_dir=output_dir,
                encoding=encoding,
                base_dir=path,
                save=save,
                comments=comments,
                dates=dates,
                is_global=_variables_only,
            )
            if isinstance(data, str):
                errors.append(filepath)
                continue
            filepath = filepath.replace(str(path), "").lstrip(os.sep)
            success[filepath] = data if keep_data else True
    total_time = time.monotonic() - start_time
    logger.info(f"{len(success)} parsed file(s) and {len(errors)} errors in {total_time:0.3f}s!")
    for error in errors:
        logger.warning(f"Error detected in: {error}")
    return success


def parse_all_locales(path, encoding="utf_8_sig", language="english", save=False, output="_locales.json"):
    """
    Parse all locales strings
    :param path: Path where to find locale files
    :param encoding: Encoding for reading files
    :param language: Target language
    :param save: (default false) save locales in file
    :param output: locales output file location
    :return: Locales in dictionary
    """
    locales = {}
    if os.path.isfile(path):
        with open(path, encoding=encoding) as file:
            while line := file.readline():
                if line.strip().lower() == f"l_{language}:":
                    break
            for line in file:
                if match := regex_locale.match(line):
                    key, _, value = match.groups()
                    locales[key] = value
    else:
        for current_path, _, all_files in os.walk(path):
            for filename in all_files:
                if not filename.lower().endswith(".yml"):
                    continue
                filepath = os.path.join(current_path, filename)
                with open(filepath, encoding=encoding) as file:
                    while line := file.readline():
                        if line.strip().lower() == f"l_{language}:":
                            break
                    for line in file:
                        if match := regex_locale.match(line):
                            key, _, value = match.groups()
                            locales[key] = value
    if save:
        with open(output, "w", encoding="utf-8") as file:
            json_dump(locales, file, sort_keys=True)
    return locales


def walk(obj, *from_keys):
    """
    Walk through a complex dictionary struct
    :param obj: Dictionary
    :param from_keys: (only used by recursion) Key of the parent sections
    :return: Yield key and value during iteration
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from walk(value, key, *from_keys)
    elif isinstance(obj, list) and any(isinstance(subitem, (list, dict)) for subitem in obj):
        for item in obj:
            yield from walk(item, *from_keys)
    else:
        yield obj, from_keys


# Tags which are always a list when reverting
list_keys_rules = [
    # Colors
    re.compile(r"^\w+_color$", re.IGNORECASE),
    re.compile(r"^color\w*$", re.IGNORECASE),
    # DNA
    re.compile(r"^gene_\w+$", re.IGNORECASE),
    re.compile(r"^face_detail_\w+$", re.IGNORECASE),
    re.compile(r"^expression_\w+$", re.IGNORECASE),
    re.compile(r"^\w+_accessory$", re.IGNORECASE),
    re.compile(r"^complexion$", re.IGNORECASE),
    # Plural keys
    re.compile(r"^(?!(h_|e_|k_|d_|c_|b_))[^\.\:\s]+s$", re.IGNORECASE),
    # GFX
    re.compile(r"^\w+_gfx$", re.IGNORECASE),
    # Object=
    re.compile(r"^[^=]+=$", re.IGNORECASE),
]


def revert(obj, from_key=None, prev_key=None, depth=-1, sep="\t", sort=False):
    """
    /!\\ Work in progress /!\\
    Try to revert a dict-struct to Paradox format
    :param obj: Dictionary
    :param from_key: (only used by recursion) Key of the parent section
    :param prev_key: (only used by recursion) Key of the great-parent section
    :param depth: (only used by recursion) Depth of the current section
    :param sep: Line-start separator
    :param sort: Sort key/values (can mess with comments)
    :return: Text
    """
    lines = []
    tabs = sep * depth
    if isinstance(obj, dict):
        if special := revert_special(obj, from_key, prev_key, sep=sep, sort=sort):
            special = special if isinstance(special, list) else [special]
            for line in sorted(special) if sort else special:
                lines.append(f"{tabs}{line}")
        else:
            if from_key:
                from_key = str(from_key).replace("|", " ")
                lines.append(f"{tabs}{from_key} = {{")
            elif depth > 0:
                lines.append(f"{tabs}{{")
            for key, value in sorted(obj.items()) if sort else obj.items():
                lines.extend(revert(value, from_key=key, prev_key=from_key, depth=depth + 1, sep=sep, sort=sort))
            if from_key or depth > 0:
                lines.append(f"{tabs}}}")
    elif isinstance(obj, list):
        if from_key and (from_key.lower() == "this" or not any(regex.match(from_key) for regex in list_keys_rules)):
            for value in sorted(obj) if sort else obj:
                lines.extend(revert(value, from_key=from_key, prev_key=prev_key, depth=depth, sep=sep, sort=sort))
        elif not any(isinstance(o, (dict, list)) for o in obj):
            prefix = f"{tabs}{from_key} = {{"
            # Only for color modes
            if from_key == "color" and len(obj) == 4 and isinstance(obj[0], str):
                prefix = f"{tabs}{from_key} {obj[0]} = {{"
                obj = obj[1:]
            func = functools.partial(revert_value, from_key=from_key, prev_key=prev_key, sep=sep, sort=sort)
            values = " ".join(map(str, map(func, obj)))
            lines.append(f"{prefix} {values} }}")
        else:
            if from_key:
                key = str(from_key).replace("|", " ")
                lines.append(f"{tabs}{key} = {{")
            else:
                lines.append(f"{tabs}{{")
            for value in sorted(obj) if sort else obj:
                lines.extend(revert(value, depth=depth + 1, sep=sep, sort=sort))
            lines.append(f"{tabs}}}")
    elif isinstance(obj, (int, float)) or obj:
        if from_key:
            if from_key.startswith("#") or (isinstance(obj, str) and obj.startswith("#") and obj.endswith("#")):
                value = obj.strip("#")
                lines.append(f"{tabs}#{value}")
            else:
                from_key = str(from_key).replace("|", " ")
                value = revert_value(obj, from_key, prev_key, sep=sep, sort=sort)
                lines.append(f"{tabs}{from_key} = {value}")
        else:
            lines.append(f"{tabs}{revert_value(obj, sep=sep, sort=sort)}")
    if depth < 0:
        return "\n".join(lines)
    return lines


def revert_value(value, from_key=None, prev_key=None, **kwargs):
    """
    /!\\ Work in progress /!\\
    Revert values utility for revert function
    :param value: Value to revert
    :param from_key: Key of the parent section
    :param prev_key: Key of the great-parent section
    :return: Reverted value
    """
    if isinstance(value, bool):
        return "yes" if value else "no"
    elif isinstance(value, str):
        if value.startswith("#") and value.endswith("#"):
            return f"#{value}"
        elif (
            " " in value
            or (value.startswith("$") and value.endswith("$"))
            or from_key in forced_string_keys
            or (prev_key and (prev_key, from_key) in forced_string_keys)
            or (prev_key and (prev_key, None) in forced_string_keys)
        ):
            value = value.replace('"', '\\"')
            return f'"{value}"'
    elif isinstance(value, dict):
        value = revert(value, from_key=from_key, prev_key=prev_key, depth=0, **kwargs)
    elif isinstance(value, datetime.date):
        value = f"{value.year}.{value.month}.{value.day}"
    return value


def revert_special(obj, from_key=None, prev_key=None, **kwargs):
    """
    /!\\ Work in progress /!\\
    Revert special values utility for revert function
    :param obj: Special object to revert
    :param from_key: Key of the parent section
    :param prev_key: Key of the great-parent section
    :return: Reverted object
    """
    if "@operator" in obj:
        operator, value = obj["@operator"], obj["@value"]
        value = revert_value(value, from_key, prev_key, **kwargs)
        if isinstance(value, list):
            value[0] = value[0].replace("=", operator, 1)
            return value
        else:
            return f"{from_key} {operator} {value}"
    elif "@type" in obj:
        value, result = obj["@value"], obj["@result"]
        return f"{from_key or value} = {value}"


def revert_file(path, output_dir=None, encoding="utf_8_sig", base_dir=None, save=False):
    """
    Revert JSON file to Paradox format
    :param path: Path to JSON file to revert
    :param output_dir: Directory where to save reverted files
    :param encoding: Encoding used to write files
    :param base_dir: Base directory (for debug)
    :param save: (default false) Save every reverted data in output directory
    """
    start_time = time.monotonic()
    if base_dir:
        base_dir = os.sep.join(str(base_dir).rstrip(os.sep).split(os.sep)[:-1]) + os.sep
        base_dir = os.path.dirname(path.replace(base_dir, ""))
    base_dir = base_dir or "."
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    filename = os.path.join(str(base_dir), os.path.basename(path))
    logger.debug(f"Reverting {filename}")
    text = revert(data)
    if save:
        filename, _ = os.path.splitext(os.path.basename(path))
        directory = os.path.join(output_dir or "output", *base_dir.split(os.sep))
        os.makedirs(directory, exist_ok=True)
        filename = os.path.join(directory, filename + ".txt")
        with open(filename, "w", encoding=encoding) as file:
            file.write(text)
    total_time = time.monotonic() - start_time
    logger.debug(f"Elapsed time: {total_time:0.3}s!")
    return text


def load_variables(filepath="_variables.json"):
    """
    Load variables from a local file variables.json
    """
    global global_variables
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as file:
        global_variables = json.load(file)


def save_variables(filepath="_variables.json"):
    """
    Save variables in local file variables.json
    """
    if not global_variables:
        return
    with open(filepath, "w", encoding="utf-8") as file:
        json_dump(global_variables, file, sort_keys=True)


def main():
    """
    Command-line main entrypoint
    """
    parser = argparse.ArgumentParser(
        description="Parse data from Paradox files in JSON or revert JSON files to Paradox format"
    )
    parser.add_argument("path", type=str, help="path to a file or a directory to parse/revert")
    parser.add_argument("--encoding", type=str, help="encoding for reading/writing files")
    parser.add_argument("--output", type=str, help="output directory for parsing results")
    parser.add_argument("--revert", action="store_true", help="revert JSON files?")
    parser.add_argument("--comments", action="store_true", help="include comments?")
    parser.add_argument("--dates", action="store_true", help="include dates?")
    parser.add_argument("--debug", action="store_true", help="debug mode?")
    args = parser.parse_args()

    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s")
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    if args.debug:
        console_handler.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler("ckparser.log")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if args.revert:
        if os.path.isdir(args.path):
            logger.error("Reverting many files is not implemented yet!")
        else:
            revert_file(args.path, encoding=args.encoding, output_dir=args.output, save=True)
    else:
        load_variables()
        if os.path.isdir(args.path):
            parse_all_files(
                args.path,
                encoding=args.encoding,
                output_dir=args.output,
                comments=args.comments,
                dates=args.dates,
                save=True,
            )
        else:
            parse_file(
                args.path,
                encoding=args.encoding,
                output_dir=args.output,
                comments=args.comments,
                dates=args.dates,
                save=True,
            )
        save_variables()


if __name__ == "__main__":
    main()
