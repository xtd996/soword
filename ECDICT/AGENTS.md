# Repository Guidelines

## Project Structure & Module Organization
This repository is data-first and lives in `ECDICT/`.
- `ecdict.csv`: primary dictionary dataset (large, UTF-8 CSV).
- `ecdict.mini.csv`: small sample dataset for quick checks.
- `stardict.py`: core read/write adapters for CSV, SQLite, and MySQL (`DictCsv`, `StarDict`, `DictMySQL`).
- `dictutils.py`: export/format utilities and dictionary maintenance helpers.
- `linguist.py`: WordNet/linguistic helper routines.
- `lemma.en.txt`, `resemble.txt`, `wordroot.txt`: supporting lexical resources.
- `del_bfz.py`: one-off cleanup/conversion script for `exchange` fields.

## Build, Test, and Development Commands
No formal build system is used; work is script-driven from `ECDICT/`.
- `python -m py_compile stardict.py dictutils.py linguist.py del_bfz.py`  
  Fast syntax validation before commit.
- `python stardict.py`  
  Runs built-in smoke code in `__main__` (writes local test artifacts like `test.csv`).
- `python -c "import stardict; db=stardict.open_dict('ecdict.csv'); print(db.count())"`  
  Verifies the main CSV can be loaded and counted.
- `python del_bfz.py`  
  Rewrites `ecdict.csv` via SQLite conversion; back up data first.

## Coding Style & Naming Conventions
- Python 2/3 compatible style is used in core scripts; keep compatibility unless intentionally dropping it.
- Follow existing file style to avoid noisy diffs (older files may use tabs; newer edits may use 4 spaces).
- Use `snake_case` for functions/variables and `CamelCase` for classes.
- Keep CSV field ordering intact; preserve UTF-8 encoding and line-level edit clarity.

## Testing Guidelines
- There is no `pytest`/`unittest` suite in this repository.
- Treat validation as smoke testing: compile scripts, run targeted script entrypoints, and verify changed words/rows manually.
- For data changes, sample-check both exact query and fuzzy behavior (`match(..., True)` in `stardict.py`).

## Commit & Pull Request Guidelines
- Match existing history: short, imperative commit subjects (for example: `fix typo in resemble`, `update README`).
- Keep commits focused: separate data corrections from script/tooling changes.
- PRs should include: change scope, data source/rationale, affected files, and verification commands run.
- If `ecdict.csv` is updated, call out row-level impact and avoid unrelated reformatting.
