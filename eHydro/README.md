# Download Lower Mississippi eHydro survey packages

`eHydro/download_ehydro.py` downloads the **All Data** packages linked by the
public [USACE eHydro survey layer](https://services7.arcgis.com/n1YM8pTrFmm7L4hs/arcgis/rest/services/eHydro_Survey_Data/FeatureServer/0).
It requires Python 3.10+ and `requests`; the desktop GUI also uses `PySide6`.
Both dependencies are included in the repository's Python 3.12 environment.
Run the following commands from the repository root
with that environment activated. The script also works from another directory
when invoked by its full path; relative output paths follow the working directory.

Open the desktop downloader:

```bash
python eHydro/download_ehydro.py
```

The GUI automatically finds the matching surveys and lists **every matching
archive before any survey data are downloaded**. Each row shows the filename,
district, channel, acquisition date, size and local/transfer status. Select a row
to inspect its full download URL, coordinate-system metadata, and the complete
list of files USACE says the archive contains. The list represents downloadable
archives; choosing an archive downloads all its included files together.

All packages with download URLs start checked. Uncheck any unwanted packages or
use **Check all**, **Uncheck all**, and **Check new files only**. Packages missing
download URLs are reported but cannot be checked. Choose the destination before
downloading. Changing the destination or query settings requires **Find files**
again so existing-file checks apply to the correct folder and selection.

The GUI estimates the remaining size and download time using each server file's
reported size and an adjustable **Planning speed (Mbps)**, initially 50 megabits
per second. This is an assumption, not a speed test. Verified completed packages
are excluded from this estimate. Unknown sizes are identified explicitly; the
pre-download estimate is then a lower bound. The size inspection uses HEAD
requests and does not fetch archive payloads.

Click **Download checked files** to begin. Current-file and overall progress
bars, bytes transferred, measured effective speed, processed-file counts and an
ETA update during the transfer. Once bytes arrive, the overall ETA uses measured
throughput. It remains indeterminate while remaining file sizes are unknown.
The transfer log distinguishes downloads, verified skips and failures. **Stop**
cancels between read operations; the current network read must return first.
Closing the window stops the operation and waits for its worker to finish.
Completed files and their receipts remain available for the next run.

For a terminal-only inventory of channel IDs and package links:

```bash
python eHydro/download_ehydro.py --list-channels
```

To download all matched packages without the GUI:

```bash
python eHydro/download_ehydro.py --headless
```

The explicit equivalent is:

```bash
python eHydro/download_ehydro.py --headless --year 2025 --districts MVK MVM \
  --channel-pattern 'CEMVK_LM_*' --channel-pattern 'CEMVM_LM_*' \
  --output output/ehydro_lmr_2025
```

Use `--gui` to explicitly request the desktop, and `--estimate-mbps 100` to set
the initial planning speed. `--catalog-only` and `--list-channels` remain terminal
commands and do not open the GUI. Headless downloads also report every matching
archive and its listed contents before transfers, check sizes/local files, and
print progress and ETA updates.

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
  It also records the checked URL selection, overall outcome and completed,
  skipped, failed and unfinished counts. Unchecked packages are `not_selected`.
- `manifest.csv`: a compact view of the current selection, with acquisition dates
  in UTC, coordinate-system metadata, package/PDF URLs, and download outcomes.
- `files/`: the original downloaded packages. Names include a URL hash to avoid
  collisions between identically named server files. Archives are not extracted;
  separate PDF plotsheets are listed in the manifest but not downloaded.
- `files/*.download.json`: a durable size/checksum receipt for each completed
  package. Keep these receipts with the downloaded archives.

`--catalog-only` writes the inventory and manifest without package downloads.
`--list-channels` does the same and prints the complete channel inventory.
No authentication token is needed for the public catalog. The script discovers
matching object IDs first and fetches attributes in checked batches, rather than
assuming one ArcGIS query returns all records. A truncated batch is split and
retried; missing IDs cause an error rather than a silent partial inventory.

Repeated package URLs are downloaded once. HTTP transient errors use bounded
retries. Files stream to temporary paths and are promoted only after the transfer
finishes; empty files, HTML error pages, and detectable length mismatches fail.
TLS certificate verification stays enabled. Inventory checks and subsequent
download runs verify existing files against their recorded size and SHA-256 hash
before skipping them. A receipt is written before a completed file is promoted
to its final name, allowing recovery if the process stops before the main
manifest is updated. A valid receipt can recover a completed file even without
the main manifest. Existing downloads from the earlier version of the script
remain recognizable through that version's manifest.
An interrupted package restarts from the beginning on the next run; partially
downloaded bytes are not resumed. Unverified existing files are preserved and
reported as errors: move them aside before retrying. The local hashes detect
later file changes; they are not independent publisher-supplied checksums.

Headless exit codes: `0` completed download or successful catalog-only run; `1` API,
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

The GUI was also validated against the live 178-package catalog, including all
remote sizes (about 3.2 GiB total), a checked 1,522,069-byte package transfer and
ZIP CRC validation, followed by a second GUI run that skipped the completed file
with zero bytes transferred. Automated offscreen tests exercise selection,
progress, Stop/restart, receipt recovery without a manifest, and safe window
closure during a transfer. ETA figures are estimates, not promised durations.
