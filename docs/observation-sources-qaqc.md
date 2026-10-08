# Lower Mississippi observations, discharge estimates, and QA/QC

The workbench loads USGS sediment/flow observations, configured USACE CWMS
series, and CSV/Excel archives. New integrations and stations are **candidate
queries**, not a claim that every station has every parameter or current records.
USGS, WQP and USACE endpoints could not be reached from this cloud environment
on October 8, 2026: the network proxy returned HTTP 403. Numerical/parser/GUI
tests use generated fixtures; live coverage and current API schemas require
verification on a machine with access to the services.

## Sources and added gages

| Source | What the tool requests | Interpretation |
| --- | --- | --- |
| [USGS Water Data API](https://api.waterdata.usgs.gov/) | Modern daily and continuous discharge; daily SSC and suspended load where present | Daily sediment series may be computed records rather than discrete measured samples; review qualifiers and station documentation |
| [Legacy NWIS services](https://waterservices.usgs.gov/) | Daily/subdaily fallback where the older endpoints remain available | Modern API is tried first; service availability may change |
| [Water Quality Portal](https://www.waterqualitydata.us/) | USGS activity records for SSC 80154, load 80155, percent fines 70331, sample Q 00061/00060, stage 00065, temperature 00010 | Parameters come from the same sample activity; reported units and detection-limit qualifiers are retained |
| [USACE CWMS](https://cwms-data.usace.army.mil/cwms-data/) | Flow, stage, and explicitly configured/discovered suspended sediment concentration/load | Only compatible units and an unambiguous catalog series are accepted; no sediment record is assumed to exist |
| [USACE New Orleans hydrologic archives](https://www.mvn.usace.army.mil/Missions/Engineering/Stage-and-Hydrologic-Data/) and agency data releases | Import downloaded CSV/Excel tables using the existing column/unit mapper | No automatic scraper of changing archive pages. Assign the actual sampling gage before filling missing Q |

The catalog now requests candidate daily SSC/load records for several existing
mainstem sediment stations and adds these USGS basin-budget references:

| USGS number | Gage | Use/caution |
| --- | --- | --- |
| 03611500 | Ohio River at Metropolis, IL | Major input at the Ohio confluence |
| 07077800 | White River at Clarendon, AR | Lower ungaged inflow and floodplain storage remain |
| 07263620 | Arkansas River at Pendleton, AR | Do not double count White flow in a combined downstream channel |
| 07288800 | Yazoo River at Redwood, MS | Already reflected in the Vicksburg mainstem reference |
| 07290000 | Big Black River near Bovina, MS | Required input below Vicksburg for configured Natchez/Union Point estimates |
| 07355500 | Red River at Alexandria, LA | Red inflow must be separated from diverted Mississippi water |
| 07381490 | Atchafalaya River at Simmesport, LA | Includes Red plus diverted Mississippi flow; not Old River outflow alone |
| 07381600 | Lower Atchafalaya River at Morgan City, LA | One lower distributary outlet; tidal/backwater effects matter |
| 07381590 | Wax Lake Outlet at Calumet, LA | Separate outlet; Morgan City alone is not total basin outflow |

New entries do not invent geographic coordinates or periods of record. Verify
site identities/metadata and use manual model mapping until coordinates are
reviewed. A parameter entry `[]` means "query without an asserted coverage
period." Empty requests and service failures are shown in the load report.

From the repository folder, generate a small live metadata report:

```powershell
.venv\Scripts\python tools\verify_observation_sources.py --site 07381490 --site 07295100 --output source-metadata.json
```

Omit `--site` to check the whole catalog. The tool checks USGS monitoring-location
and time-series metadata, the legacy NWIS catalog, and configured CWMS search
patterns. It downloads no flow or sediment time-series arrays. Errors and
pagination/truncation indicators are included, and failed requests produce a
nonzero exit status. Metadata alone does not establish instantaneous/daily
agreement, representative sediment sampling, or compatibility of datums.

### CWMS sediment and flow series

Tarbert Landing has candidate flow/SSC/load catalog patterns in
`config/stations.yaml`. If discovery finds several compatible series, the loader
**refuses to choose a revision** and reports the names. Configure the reviewed
series in a complete station override in `config/stations_user.yaml` (copy the
original station entry and replace its `cwms` block):

```yaml
cwms:
  office: MVN
  flow: <reviewed exact total-flow series name>
  ssc: <reviewed exact suspended-sediment-concentration series name>
  ssl: <reviewed exact suspended-sediment-load series name>
```

These placeholders are not usable series IDs. Explicit names take precedence
over search patterns. SSC must have concentration units and load must have
mass/time units; incompatible or absent units cause a visible error. CWMS UTC
timestamps are converted to the station clock (America/Chicago by default).
Quality codes remain in qualifiers; their bit fields are not blindly interpreted
as "all nonzero codes invalid."

Turbidity and total suspended solids (TSS) are **not silently substituted for
whole-water SSC**. A turbidity surrogate requires a validated station-specific
regression. Archived daily loads, bottle SSC and sediment fraction measurements
also differ in sampling/integration and need physical review before calibration.

## Filling missing sample discharge

**Estimate missing discharge** is enabled for station loads. Reported sample Q
is always retained. The preference order is:

1. Same-site subdaily Q, if **Use sample-day USGS subdaily flow** is enabled.
   Downloads are confined to missing-Q sample-day windows; interpolation is
   limited to three-hour gaps and does not extrapolate beyond source timestamps.
2. Same-site daily/USACE flow, using bounded interpolation. USGS daily means are
   placed at local noon for this approximation. They are not instantaneous sample
   measurements. Provisional/estimated flags should be reviewed.
3. An explicit river-budget recipe with every required component available.

For imported archives, select the **actual sampling station** in the station
selector and click **Fill missing Q for imported data**. This choice assigns a
hydrologic location; it does not infer one from a filename. Existing QA/QC
exclusions are retained. Raw provider caches are not changed by estimates.
Import one sampling location at a time. A mapped station column containing
multiple IDs is refused, and a recognized imported USGS ID must match the
selected proxy station.

The shipped recipes in `config/discharge_proxies.yaml` are conservative
approximations:

| Target | Budget / restriction |
| --- | --- |
| Natchez | Routed Vicksburg + Big Black; both required |
| Union Point | Routed Vicksburg + Big Black; target is upstream of Old River |
| St. Francisville | Baton Rouge routed upstream; both sites are below Old River and Morganza |
| Tarbert Landing | Prefer same-site flow; Baton Rouge fallback only during assumed closed-Morganza years through 2024; entire 1973/2011 operating years and later dates are blocked |

The Tarbert fallback assumes Morganza was closed outside its documented
1973/2011 operating years through 2024; **that is an assumption, not measured
zero diversion**. This fallback is not a substitute for verified operation/flow
records. Smaller lateral inflows (including Homochitto where relevant), floodplain
storage, travel through ungaged lower tributary reaches and flood-wave attenuation
are not fully represented. Estimates are not labeled as mass-balance closure.

Configured lag zero means a same-day budget approximation. Positive lags route
upstream records later; negative lags use downstream records later to estimate
an upstream sample time. The estimator may select a primary lag from the
configured candidates only with at least 20 distinct measured-Q dates/common
flow pairs: it selects on the first 70% and requires at least 10% RMSE improvement
on the last 30%. This adjusts timing only, never an arbitrary flow multiplier.
Tributary lags remain explicit assumptions until you calibrate/configure them.

Missing required tributary/diversion flow stays **unknown**, never zero. No
fixed 70/30 Old River allocation is used. Simmesport minus Alexandria is not
automatically declared Old River outflow. There is no automatic Baton Rouge to
Belle Chasse transfer without accounting for Bonnet Carré, other diversions and
lower-river storage/tidal effects. Above/below Old River sites cannot be treated
as interchangeable. The nine tributary/outlet gages provide reference data;
they are not all automatically applied to every mainstem sample.

You can add reviewed recipes to `discharge_proxies.yaml` using actual gage IDs:

```yaml
stations:
  <target-id>:
    - name: Reviewed upstream budget
      terms:
        - {station: <upstream-id>, coefficient: 1, lag_hours: 24}
        - {station: <tributary-id>, coefficient: 1, lag_hours: 12}
        - {station: <measured-diversion-id>, coefficient: -1, lag_hours: 6}
      max_gap_hours: 36
```

Each source must be in the station catalog with a usable flow source. These
example lags are illustrative, not recommended Mississippi routing parameters.
Every term is mandatory. Do not create simultaneous budgets that double count
tributaries, or omit managed outlets because their flow is unknown.

The preview/audit/sample exports retain `q_is_proxy`, `q_method`, `q_sources`,
`q_proxy_recipe`, `q_lag_hours`, and where complete `q_proxy_low_m3s` /
`q_proxy_high_m3s`. Bounds show sensitivity to candidate primary lags only;
they are **not confidence intervals** and do not quantify all measurement,
storage, attenuation or ungaged-flow uncertainty. `q_original_m3s` retains the
original sample discharge (including missing values). Derived SSC × Q loads
inherit discharge uncertainty. Fits using these Q values must be identified as
using estimates rather than exclusively measured pairs.

## Observation QA/QC

The Observations preview shows physical/qualifier flags after loading, without
discarding data. You can select a variable and review method, specify optional
minimum/maximum limits **in the displayed unit**, and click **Flag suspect
values**. Flags cover all records, even when only the first 2000 are previewed.
Use **Show flagged only** to inspect flagged records beyond the initial rows.

- Physical checks flag negative concentration, nonfinite numeric values and
  percent fines outside 0–100, plus negative load where registered Q is
  nonnegative. Negative river discharge is not automatically
  rejected, because tidal/backwater reversals can be real.
- Censoring checks flag detection-limit results as non-exact observations.
  WQP units are converted per result; conflicting results for one activity and
  parameter are omitted with a qualifier rather than silently choosing one.
  Existing WQP caches are rebuilt for the revised parser after a successful
  download; old coverage is reset so unrefetched ranges cannot appear validated.
- **Robust MAD** uses the modified z score `0.67449 × |x − median| / MAD`.
  The default threshold is 6, deliberately conservative. **Log values** supports
  strongly skewed positive sediment data. At least 10 usable records are required.
- **IQR** flags values outside `Q1 − k IQR` and `Q3 + k IQR`; `k` is the chosen
  threshold. A zero MAD/IQR does not justify automatically discarding deviations.
- **Rating residuals** examines robust deviations from a log-log sediment-versus-Q
  relationship (at least 10 positive pairs with flow variation). This can retain
  legitimate high sediment at high flow, but hysteresis and grain-size changes
  still require judgement. Proxy Q also affects these residuals.
- **Flag estimated Q** allows excluding proxy discharge deliberately.

Use **Exclude flagged values** to mask all currently flagged cells, or select
preview rows and use **Exclude selected values** to mask the selected QA/QC
variable in those rows. Whole rows are not deleted. Dependent derived loads and
fraction concentrations are also masked where their derivation is identified;
reported independent measurements remain available. Excluded values are not
silently rebuilt by concentration/load fallback formulas. Both calibration tabs
immediately use the reviewed observation set.

**Restore raw values** undoes QA/QC exclusions for the loaded set. **Export QA/QC
audit** writes original values, `used_` values, field-specific flags, excluded
fields, Q provenance and a metadata sidecar. Raw caches/files are not rewritten
by QA/QC. A high value alone is not proof of an error: floods, hysteresis,
sampling method changes and cross-section gradients can produce real extremes.
