# Changelog

## 0.3.4

- Fixing nested operators in parsing.

## 0.3.4

- Fixing `objectify` operators, formulas, variables and comments.

## 0.3.3

- Adding `objectify` function to transform dict to object-like.

## 0.3.2

- Making error output a little bit readable.
- Fixing regression on color blocks when reversion.
- Fixing array comments in reversion.
- Trying to parse array-only files.

## 0.3.1

- Fixing regression on color blocks.
- Detect missing operator before block.

## 0.3

- Counting lines from original file when parsing.
- Fixing transformation regex.
- Keeping system path separators.
- Forcing encoding for JSON and error outputs.

## 0.2.1

- Fixing argument shadowing in `parse_all_locales`.
- Fixing date conversion in JSON lists.

## 0.2

- Jomini date convertion in parsing and reversion.
- JSON dump(s)/load(s) functions to handle Python dates.

## 0.1

- Initial public release.
- Parse Jomini text, files, and directories.
- Experimental JSON/Python to Jomini reversion.
- Utilities for colors, dates, locales, and nested structure traversal.
