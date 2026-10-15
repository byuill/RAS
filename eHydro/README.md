# Download Lower Mississippi eHydro survey packages

After downloading, use [the bathymetry post-processing script](POSTPROCESSING.md)
to extract packages, collect bathymetry in a geodatabase and create one GeoTIFF
mosaic. It runs in ArcGIS Pro Python and reports progress in the terminal.
Omit its master-folder argument to open a folder picker, then select the folder
containing `files/` and the downloaded ZIP archives.

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

The GUI first queries the live catalog for **all available acquisition years**
matching the selected districts and channel patterns. It reports the years and
distinct data-package counts, including counts by district in the year dropdown.
Years are discovered from actual records, not inferred as a continuous range.
Only matching records with package links and usable acquisition start dates
contribute to this list; excluded records are counted separately. This discovery
reads catalog metadata without downloading archives or inspecting every year's
file sizes.

Choose the year of interest in **Survey start year**. The GUI then automatically
lists **every matching archive for that year before any survey data are
downloaded**. No year is selected automatically. Each row shows the filename,
district, channel, acquisition date, size and local/transfer status. Select a row
to inspect its full download URL, coordinate-system metadata, and the complete
list of files USACE says the archive contains. The list represents downloadable
archives; choosing an archive downloads all its included files together.

All packages with download URLs start checked. Uncheck any unwanted packages or
use **Check all**, **Uncheck all**, and **Check new files only**. Packages missing
download URLs are reported but cannot be checked. Choose the destination before
downloading. Changing districts or channel patterns clears the old year list;
click **Refresh available years**, then select a year. Changing the destination
requires **Find files** again so existing-file checks apply to the correct folder.
The default destination follows the selected year (`output/ehydro_lmr_2020`, for
example). A manually chosen destination is preserved when the year changes.

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

To report every available year and district-specific package counts without
opening the GUI, downloading packages, or creating output files:

```bash
python eHydro/download_ehydro.py --list-years
```

`--list-years` uses the district/channel filters and ignores `--year`.

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
the initial planning speed. `--catalog-only`, `--list-channels` and `--list-years` remain terminal
commands and do not open the GUI. Headless downloads also report every matching
archive and its listed contents before transfers, check sizes/local files, and
print progress and ETA updates.

The district/channel defaults are Vicksburg (MVK), Memphis (MVM), and channel IDs
matching `CEMVK_LM_*` or `CEMVM_LM_*`. The headless workflow still defaults to
`--year 2025`; the GUI requires a choice from the live list. For any selected
year, the acquisition start date must be January 1 inclusive through the next
January 1 exclusive, using UTC. This does not select by upload date. Surveys
beginning in 2024 and ending in 2025 are excluded when selecting 2025 under this
start-date definition. All matching survey packages start checked; the script
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
- `manifest-recovery-*.json`: full progress snapshots created if Windows denies
  replacement of `manifest.json`. The next run automatically loads the newest
  valid saved report, including these snapshots. Keep them until the primary
  manifest updates successfully.
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

## Windows access-denied errors while saving reports

`[WinError 5] Access is denied: ... .tmp -> ... manifest.json` means Windows
denied replacing the report file. The script already closes its temporary writer
before renaming it. Another process holding the file open, a brief security or
sync scan, or file permissions can still prevent replacement; the error alone
does not identify which process caused it.

Atomic file replacement now retries Windows access/sharing errors a bounded
number of times. If the primary JSON manifest remains locked, the job saves a
uniquely named recovery snapshot and continues downloading. CSV exports are
written atomically too, so a report held open in Excel is preserved and reported
as a warning rather than truncating the CSV or aborting all remaining transfers.
The GUI shows report warnings in the Transfer log and final status. If both the
primary manifest and its recovery snapshots cannot be written, it explicitly
reports that central reports may be stale; completed-file receipts still support
restart recovery. Headless mode returns exit code `1` for unresolved report
warnings even when the selected package transfers succeeded.

Close any application using the JSON/CSV reports while downloading and check
that the destination is writable. Update the scripts, then rerun using the same
destination; completed archives are checked and skipped. Preserve the `files/`
folder, receipts and recovery snapshots. The script does not change permissions
or remove a locked destination file to force an overwrite. A genuinely unwritable
data folder or a full disk still requires fixing the underlying storage problem.

Regression tests simulate Windows errors 5, 32 and 33, including a lock appearing
mid-download, a permanently locked CSV, recovery from a newer snapshot than the
primary manifest, and restart skips. They also verify that disk-full errors are
not treated as harmless file locks. These checks run with simulated Windows
errors; validation on the affected Windows drive remains a local check.

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

Live year discovery returned matching acquisition years 2015–2026 for the default
district/channel filters. Selecting 2020 in the GUI loaded its 56 MVK packages
and updated the default destination to `output/ehydro_lmr_2020`. Availability and
counts can change as USACE updates the catalog; each GUI refresh queries it again.
