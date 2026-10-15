# Download Lower Mississippi eHydro survey packages

`eHydro/download_ehydro.py` downloads the **All Data** packages linked by the
public [USACE eHydro survey layer](https://services7.arcgis.com/n1YM8pTrFmm7L4hs/arcgis/rest/services/eHydro_Survey_Data/FeatureServer/0).
It requires Python 3.10+ and `requests`, already included in the repository's
Python 3.12 environment. Run the following commands from the repository root
with that environment activated. The script also works from another directory
when invoked by its full path; relative output paths follow the working directory.

First inspect the candidate channel IDs and package links without downloading
potentially large survey archives:

```bash
python eHydro/download_ehydro.py --list-channels
```

Download all matched packages:

```bash
python eHydro/download_ehydro.py
```

The explicit equivalent is:

```bash
python eHydro/download_ehydro.py --year 2025 --districts MVK MVM \
  --channel-pattern 'CEMVK_LM_*' --channel-pattern 'CEMVM_LM_*' \
  --output output/ehydro_lmr_2025
```

The defaults select Vicksburg (MVK) and Memphis (MVM), **survey acquisition start
dates from January 1, 2025 inclusive through January 1, 2026 exclusive**, and
channel IDs matching `CEMVK_LM_*` or `CEMVM_LM_*`. They do not select by upload
date. Surveys beginning in 2024 and ending in 2025 are excluded under this
start-date definition. All matching survey packages are selected; the script
does not discard older surveys of the same channel in favor of the latest one.
The API stores districts as `CEMVK` and `CEMVM`; the script translates the short
`--districts MVK MVM` arguments to those full symbols for its server query.

## Channel identifiers and wildcards

The channel-ID attribute in USACE's published survey map configuration is
`channelareaidfk`. The supplied channel-prefix patterns are starting assumptions;
inspect `channels.csv` or `--list-channels` to confirm the actual identifiers
used in the live catalog. Empty or missing channel IDs are excluded and reported
as `(missing)` in the channel inventory. If the IDs differ, supply the verified
pattern with repeatable `--channel-pattern` arguments. `--channel-field` can
select another verified attribute if necessary; it defaults to `channelareaidfk`.

Patterns are matched **in Python**, case-insensitively: `*` means any sequence,
`?` means one character, and underscores are literal. Quote patterns so the
shell does not expand them. ArcGIS SQL `LIKE` instead uses `%` for any sequence
and `_` for one character. This script filters districts/dates on the server
and applies channel patterns locally to avoid treating the underscores in
`CEMVK_LM_*` as SQL wildcards. Use `*`, not `%`, in this script's arguments.

## Outputs and reruns

Use a dedicated output directory. The default `output/ehydro_lmr_2025` is ignored
by Git. Outputs include:

- `channels.csv`: all candidate channel IDs and counts for the selected districts
  and year, including channels that did not match the patterns.
- `manifest.json`: query, time of discovery, full selected survey attributes,
  per-survey status, package URLs, local paths, sizes, and SHA-256 hashes. It is
  updated after every package and retains download records from earlier runs.
- `manifest.csv`: a compact view of the current selection, with acquisition dates
  in UTC, coordinate-system metadata, package/PDF URLs, and download outcomes.
- `files/`: the original downloaded packages. Names include a URL hash to avoid
  collisions between identically named server files. Archives are not extracted;
  separate PDF plotsheets are listed in the manifest but not downloaded.

`--catalog-only` writes the inventory and manifest without package downloads.
`--list-channels` does the same and prints the complete channel inventory.
No authentication token is needed for the public catalog. The script discovers
matching object IDs first and fetches attributes in checked batches, rather than
assuming one ArcGIS query returns all records. A truncated batch is split and
retried; missing IDs cause an error rather than a silent partial inventory.

Repeated package URLs are downloaded once. HTTP transient errors use bounded
retries. Files stream to temporary paths and are promoted only after the transfer
finishes; empty files, HTML error pages, and detectable length mismatches fail.
TLS certificate verification stays enabled. Rerunning the same command verifies
existing files against their recorded size and SHA-256 hash before skipping them.
An interrupted package restarts from the beginning on the next run; partially
downloaded bytes are not resumed. Unverified existing files are preserved and
reported as errors: move them aside before retrying. The local hashes detect
later file changes; they are not independent publisher-supplied checksums.

Exit codes: `0` completed download or successful catalog-only run; `1` API,
transfer, or filesystem failure, including matched surveys with missing package
URLs during a download run; `2` no matching surveys (also used by argparse for
invalid arguments). Failed packages do not stop other selected packages from
being attempted. Review all failures and missing URLs before treating a run as
complete. Keep the reports alongside the data for provenance.

## Coverage and cloud access

These are the packages available through eHydro, not a guarantee of full-width,
district-wide, or decadal bathymetric coverage. Review footprint, survey type,
source units and vertical datum before combining them for bed-change analysis.
`sourceprojection` alone does not establish the vertical datum.

The API requires `services7.arcgis.com`. USACE's published map also references
the storage host `ehydroprod.blob.core.usgovcloudapi.net`; package URLs may use
additional hosts, which will be visible in the manifest. A restricted cloud
environment must permit the actual API and package destinations. A saved network
draft does not enable runtime access until applied through environment settings.

Development validation found **178 matching 2025 packages: 121 CEMVK and 57
CEMVM**, with no missing data-package links. Their channel IDs use the
`CEMVK_LM_*` and `CEMVM_LM_*` patterns above. These are catalog observations,
not permanent counts; later uploads or corrections can change the selection.
A 31,446,014-byte MVM ZIP was downloaded as a transfer check, all archive CRCs
were checked, an XYZ member was confirmed, and a repeat download was skipped
after local checksum verification. The entire 178-package collection was not
downloaded during validation. Regression tests separately cover API batching,
literal channel patterns, duplicate URLs, failed transfers, and reruns.

Run the downloader's regression tests from the repository root:

```bash
python -m pytest -q eHydro/tests
```
