# The results archive

Up to commit `7a2205d` (2026-10-31), the repository tracked every file the
studies exported under `results/`: 15,454 files, 330 MB. It now tracks 279 of
them, 28 MB. Those 279 are what a reader needs to read and check a result:
the reports, the summary tables, the figures and what each study froze. The
other 15,175 files are the raw exports of the runs, and they are in one
archive attached to a GitHub Release. No history was rewritten, so every
archived file is also in the git history at `7a2205d`.

| | |
| --- | --- |
| Release | [`results-archive-2026-10-31`](https://github.com/paulrivaudd/quant-backtester/releases/tag/results-archive-2026-10-31) |
| Asset | `quant-backtester-results-7a2205d.tar.gz`, 103,233,316 bytes |
| SHA-256 | `475440c48634efec917ea1e0a11397cc2ac2b917e631d09f672346a60e8a0583` |
| Content | the whole `results/` tree at `7a2205d6690ea5aa759710de9fe35a032d22b972`, 15,454 files |

The archive is built from the commit alone, and the build is deterministic.
Running the same command again gives the same digest:

```bash
git archive --format=tar 7a2205d results | gzip -n -9 > quant-backtester-results-7a2205d.tar.gz
```

## What the repository keeps

The rules are in `.gitignore`. The repository keeps:

- every report (`*.md`): `study.md`, `analysis.md`, `validation.md`, the
  audits, and the generated `tables.md`;
- the summary tables `metrics.csv` and `yearly.csv`, and all of
  `results/summary/`;
- the figures (`*.png`);
- what a study froze:
  - `selected.json` and `verdict.json`;
  - the `*.sha256` files;
  - the frozen drivers and inputs (`*_frozen.json`, `frozen_inputs.json`);
  - the mechanism pilot's `manifest.json`, which its `manifest.sha256` covers;
- the session history and fills (`history.csv`, `fills.csv`) of the
  catalogued strategies SA1 to SA14, which their `analysis.md` cites.

The other files of SA15 and SA16 are only in the archive:

- the per-trial and per-candidate folders;
- the equity curves, weights, orders, fills, rejects and decisions;
- the caches, robustness and comparison tables;
- the source archives (`source.zip`) and the manifests.

| Folder | Kept | Archive only |
| --- | ---: | ---: |
| `SA1` to `SA14`, `summary/` | 170 | 0 |
| `SA15_GPT-6.1` (series 1) | 11 | 603 |
| `SA15_GPT-6.1_mechanism_pilot` | 8 | 372 |
| `SA15_GPT-6.1_R2` | 12 | 628 |
| `SA15_GPT-6.1_R3` | 14 | 584 |
| `SA15_GPT-6.1_R4` | 16 | 1,793 |
| `SA15_GPT-6.1_R5` | 38 | 10,579 |
| `SA15_GPT-6.1_R5_attempt01_audit_timestamp_error` | 2 | 15 |
| `SA16` | 8 | 601 |
| **Total** | **279** | **15,175** |

`SA15_GPT-6.1_R5_attempt01_audit_timestamp_error/` keeps two files:
`failure.md`, which says why the attempt was abandoned, and the
`frozen_inputs.json` it ran on.

## Restoring it

Run from the repository root:

```bash
gh release download results-archive-2026-10-31 -R paulrivaudd/quant-backtester
sha256sum quant-backtester-results-7a2205d.tar.gz   # 475440c4...0583
tar -xzf quant-backtester-results-7a2205d.tar.gz --skip-old-files
```

A clone that has the history can also restore the same files without the
Release:

```bash
git archive 7a2205d results | tar -xf - --skip-old-files
```

`--skip-old-files` keeps the tracked files as they are now. Some reports were
edited after `7a2205d`, for example to add their links to this archive. The
restored files are ignored by git, so `git status` stays clean.

## What needs the archive

Nothing in `src/`, `tests/` or the CI reads `results/`.
`scripts/write_strategy_reports.py` and `scripts/run_review_diagnostics.py`
read the exports under `runs/` and write only files the repository keeps.

The following scripts need the archive restored first:

- **The SA15 report, robustness and diagnostics scripts**
  (`scripts/SA15_report_*.py`, `SA15_robustness_gpt61.py`,
  `SA15_diagnostics_gpt61_round4.py`) re-read the exports of their own series.
- **`SA15_report_gpt61_round4.py`** also reads the validation curves of series
  1 to 3 to compute R4's deflated Sharpe ratio. When they are missing, it
  computes the ratio on fewer curves instead of failing, and only lists the
  missing trials in `selection_diagnostics.json`. Restore the whole archive,
  not one folder.
- **`scripts/SA16_report.py`** draws its figures from the curves under
  `results/SA16/final/` and `results/SA16/references/`.
- **`scripts/SA16_run_study.py reproduce`** compares its rerun with the
  archived curves of `results/SA15_GPT-6.1_R4/full/`. Without them it records
  the rerun alone and says nothing. The other subcommands rerun into an
  `--output` folder, as `results/SA16/study.md` explains.

## Reports left as they were

The reports whose digest a study recorded are not edited:

- the R2 and R3 `study.md`, recorded as `study_sha256` in their
  `reporting_manifest.json`;
- the reports of the mechanism pilot and of the R5 mechanisms, listed in
  their manifests. They link to no archived file.

The relative links of the R2 and R3 reports to archived files are broken in
the repository. Restore the archive to follow them, or read the reports at
`7a2205d`:

- [R2](https://github.com/paulrivaudd/quant-backtester/tree/7a2205d6690ea5aa759710de9fe35a032d22b972/results/SA15_GPT-6.1_R2)
- [R3](https://github.com/paulrivaudd/quant-backtester/tree/7a2205d6690ea5aa759710de9fe35a032d22b972/results/SA15_GPT-6.1_R3)

The series 1 and R4 reports link to their archived files through permalinks
to `7a2205d`.
