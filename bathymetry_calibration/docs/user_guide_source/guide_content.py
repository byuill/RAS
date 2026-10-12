"""Reader-oriented content checked against the implementation at e435355."""
import json
from pathlib import Path
from guide_paths import ROOT

def write_content(g):
    facts=json.loads((ROOT/'verified_examples.json').read_text())
    m=facts['illustrative_comparison']

    g.page('Quick start')
    g.p('For an existing, verified project configuration, follow this sequence. The most important decision is '
        'the bed footprint and time interval being compared; a visually convincing curve cannot establish those inputs.')
    g.steps([
        '**Start the workbench.** Open a terminal at the RAS repository root, activate the scientific Python environment, '
        'and launch the command below. Keep this environment separate from ArcGIS Pro’s managed environment.',
        '**Load data.** Browse to the configuration JSON and the RAS plan-result HDF. Use the geodatabase override only '
        'when intentionally replacing configured GDB paths. Click Load data and dates.',
        '**Select dates and reach.** Choose the baseline and target surveys and check the matched model output dates. '
        'Enable the river-mile range when needed. Confirm the actual selected end stations and XS count.',
        '**Review survey QA/QC.** Inspect flags, original and used elevations, duplicates and gaps. Apply only '
        'documented decisions. Save a configuration copy to preserve the review.',
        '**Calculate the reference.** Click Calculate selected interval. Read warnings and support coverage before '
        'judging model agreement. For multiple survey epochs, use Calculate all survey intervals.',
        '**Inspect and test assumptions.** Open Cross-section profiles, Pattern diagnostics, then Audit calculations / '
        'explore assumptions. Verify one section, one reach and one cumulative prefix by hand.',
        '**Export evidence.** Export the reference, retain scenario instructions and results, and prepare figures with '
        'captions that state dates, units, footprint, reconstruction method and uncertainty assumptions.'
    ])
    g.code('python -m bathymetry_calibration --config "C:/Project/config.json"\n'
           '    --hdf "C:/Project/plan.p01.hdf"\n'
           '(Enter as one command; the line break above is for readability.)')
    g.callout('First review pass',
        'Check section counts, excluded reaches, minimum full-transect footprint coverage, the sign convention, '
        'model/survey dates and whether the native audit ran or was skipped. Then inspect the shape and magnitude of disagreement.')
    g.p('**Expected output:** a reproducible comparison on the supported sampled bed, not an automatically fitted model. '
        'The tool does not run HEC-RAS, optimize sediment parameters or convert geometric bed change into sediment transport.')

    g.page('What the comparison can establish')
    g.p('The workbench compares changes in evolving model cross-section bed geometry against two or more dated bathymetric '
        'surveys. For each interval, both sources are evaluated over the same accepted lateral intervals at the same '
        'cross sections. Section change areas are then combined using verified channel lengths.')
    g.image('01_workflow','A defensible review starts with inputs and support, then evaluates agreement and assumption sensitivity.')
    g.h('Three complementary questions')
    g.bullets([
        '**Magnitude:** Does the model reproduce the signed net volume and mean elevation change on the compared bed?',
        '**Location and pattern:** Does it reproduce where mean erosion and deposition occur and how change varies downstream?',
        '**Variability:** Does a similar net change conceal different amounts of opposing erosion, deposition or lateral heterogeneity?'
    ])
    g.p('Survey-derived volume is also an estimate. It depends on data quality, sampled footprint, section spacing and '
        'longitudinal reconstruction. The comparison therefore evaluates the model and the observational calculation '
        'under stated assumptions; it does not make the measured reconstruction an exact representation of all intervening morphology.')
    g.p('A mismatch does not uniquely identify a sediment-model parameter. Geometry, sediment supply, transport '
        'assumptions, flow timing and survey limitations can have similar effects. Use process-informed HEC-RAS runs '
        'and independent evidence to diagnose causes; the workbench evaluates the resulting bed-change comparison.')
    g.callout('Calibration versus validation',
        'A good fit to surveys used to adjust model parameters is calibration evidence. Independent validation requires '
        'additional evidence, such as a withheld survey interval or a separately evaluated reach. Identify which role each dataset serves.')
    g.p('**Terms used throughout:** an **integration reach** joins two adjacent accepted XS; it is distinct from a named '
        'HEC-RAS Reach. A **date interval** spans baseline to target epochs. **Accepted support** comprises the usable lateral '
        'runs shared by every required profile; their width can vary from section to section.')

    g.page('Preparing the inputs')
    g.p('Start with a copy of the configuration. Treat verification flags as a record of completed checks, not as switches '
        'to bypass missing information. The real_config.json file contains project paths and assumptions that must be '
        'checked against the data on the analyst’s machine.')
    g.table(['Input','Required meaning / review check'],[
        ('Plan-result HDF','Evolving bed Station Elevation profiles at the selected dates; verify XS result-column mapping, '
            'units, station origin and orientation. Static initial geometry cannot stand in for both dates.'),
        ('Transect manifest','One ordered river/reach. Required fields: xs_id, model_column, chainage_m, '
            'length_to_next_m, u_m, x_m, y_m. At least two lateral knots per XS. Optional river_mile maps text IDs.'),
        ('Bathymetric surveys','Actual acquisition dates, common verified datum, explicit elevation units and known horizontal registration.'),
        ('Projected analysis CRS','Projected horizontal metre units are required internally for XY geometry and proximity calculations. '
            'Display conversion to feet does not change the CRS requirement.'),
        ('QA/QC decisions','Duplicate policy, evidence for exclusions and any documented elevation correction; retain raw and used values.'),
        ('Uncertainty evidence','Per-survey one-sigma vertical uncertainty when defensible; correlation assumptions need a stated basis.'),
        ('Cache and export folders','Writable locations outside source geodatabases / protected dataset folders; retain exports by run.')
    ],[1.55,5.45])
    g.h('Supported survey sources')
    g.p('Normalized cross-section CSVs, projected XYZ CSVs, single-band rasters and ArcGIS geodatabase rasters/points '
        'are supported. Raster/CSV work does not require ArcGIS. GDB extraction uses a separately configured, licensed ArcGIS '
        'Python interpreter; some sampling operations also require Spatial Analyst.')
    g.p('Normalized CSV profiles already use xs_id, u_m and z_m in metres. Raw XYZ and raster sources require their own '
        'field/CRS/unit mappings. Preserve NoData. Verify curved-transect stationing and left/right orientation against '
        'physical landmarks rather than assuming that the first polyline vertex is the model station origin.')
    g.callout('Horizontal mismatch can resemble bed change',
        'A small lateral displacement near steep banks or a scour hole can create apparent elevation change. '
        'Agreement with the model cannot independently verify survey registration.')

    g.page('Choosing the river-mile extent')
    g.p('Longitudinal plots use the model cross-section station labels as river-mile locations. For this project, '
        'labels such as 236.7, −19.6 or River:Reach:236.7 identify RM. A trailing HEC-RAS asterisk is accepted. '
        'Numbers embedded in text IDs such as XS-3 are not interpreted as river miles.')
    g.image('02_river_mile','Project manifest context and the configured selection. Lower ticks are schematic; not every XS is shown. This figure describes geometry.')
    g.p('The checked-in manifest covers RM 953.6 to −19.6. The supplied project configuration selects '
        '**RM 236.7 to −19.6**, which contains **81 existing cross sections**. Their verified channel lengths total '
        'about **259.07 miles**; the difference between station labels is **256.3 RM**. These quantities need not be identical.')
    g.h('How to select a reach')
    g.steps([
        'Enable Limit to a river-mile range. Enter the upstream and downstream bounds; negative stations are valid.',
        'Read the note showing actual selected end stations and count. Bounds select existing XS inclusively; '
        'a bound between sections does not create a new interpolated endpoint.',
        'Save a configuration copy. A valid range needs at least two sections and, for this range selector, '
        'downstream-decreasing RM. Out-of-manifest configured bounds are rejected.'
    ])
    g.p('For text IDs, supply a consistent river_mile manifest column. Without a mapping, plots show clearly '
        'labeled downstream distance in miles. They do not invent an absolute RM origin.')
    g.p('The parser reads a number; it cannot verify its geographic meaning or units. This project uses RM names. '
        'For another model using feet or arbitrary station numbers, verify the naming convention and supply an explicit '
        'river_mile mapping before interpreting the axis as river miles.')
    g.callout('Location is separate from integration length',
        'Use RM to identify where a result occurs. Use verified channel lengths to compute volume. Changing the '
        'selected end sections also changes their reconstructed control weights; it is more than cropping a plot.')

    g.page('Dates, units and vertical datum')
    g.h('Match the comparison interval')
    g.p('The baseline survey must precede the target survey, and the selected model outputs must be distinct and ordered. '
        'Selecting a survey proposes its nearest model date; the calculation still enforces survey_alignment_tolerance_days. '
        'Record all four dates and the tolerance. A survey collected over many weeks may require additional treatment '
        'beyond representing it by one date.')
    g.callout('Project date check',
        'The supplied configuration labels the target raster MB_2025 but assigns its survey date as 2024-10-31 '
        '(baseline: 2012-10-31). Check acquisition metadata before using those dates in a review. A layer name is not proof of acquisition date.')
    g.h('Displayed units versus stored units')
    g.table(['Quantity','GUI / customary exports','Calculation / configuration'],[
        ('Elevation, lateral station, width, reach length','ft','m; fields ending _m'),
        ('Change area / sampled bed area','ft²','m²; fields ending _m2'),
        ('Geometric bed volume','yd³','m³; fields ending _m3'),
        ('Longitudinal location','Model XS river mile','RM is a station label; canonical chainage remains m'),
        ('Annual mean change','ft/year','m/year'),
        ('Slope / concavity','ft per downstream mi / mi²','m per km / km²'),
        ('Correlation, coverage, cancellation','Dimensionless','Dimensionless')
    ],[2.25,2.35,2.4])
    g.p('One foot is exactly 0.3048 m; 1 yd³ = 27 ft³ = 0.9144³ m³. GUI limits and shift/error controls accept feet. '
        'Saved JSON and reproducible scenario instructions retain SI-named values. Do not enter feet into a _m configuration field.')
    g.p('Displayed feet are international feet. Source coordinates in US survey feet use a different conversion '
        '(1200/3937 m per US survey foot); preserve the declared source/CRS units during normalization rather than inferring them from the GUI.')
    g.h('Check a common datum independently')
    g.p('Verify vertical scaling and transformations for every source. A uniform model–survey offset can be a datum '
        'problem or an initial-bed modeling difference. A coherent observed change can be real deposition/erosion or '
        'an epoch datum shift. Use benchmarks or independently justified stable controls before applying a correction.')

    g.page('Reviewing survey QA/QC')
    g.p('Open **Review survey QA/QC** before selecting a model HDF if needed. It examines extracted samples along the transects, '
        'not every cell of the source terrain. Review full-raster seams, stripes, coverage edges and registration in GIS as well.')
    g.steps([
        'Choose the survey and cross section. Initially, Show flagged/excluded only is checked; turn it off to see context.',
        'Compare original and used elevations. Set physically justified limits in feet; slope limits use ft/ft.',
        'Click 1 Preview limits. A flag identifies a value needing review, not a proven measurement error.',
        'Use Exclude selected points for documented individual decisions, or explicitly choose exclusion of elevation/spike/slope flags. '
        'Excluded elevations become missing-data barriers rather than being filled.',
        'Resolve duplicate stations with an explicit mean/median policy when appropriate. The default error policy prevents an ambiguous comparison.',
        'Click 2 Apply reviewed decisions, then recalculate the main comparison. Save configuration copy and export the QA/QC audit.'
    ])
    g.table(['Flag / decision','Interpretation'],[
        ('Missing / nonfinite','Unavailable survey elevation; not an observation of zero change.'),
        ('Elevation / slope limits','Check plausibility, banks and real scour before excluding a finite point.'),
        ('Robust spike','Deviation from neighboring linear interpolation exceeding both a physical limit and robust MAD-based limit. '
            'Short profiles may have too few residuals to flag spikes.'),
        ('Duplicate station','Explicit aggregation is required; missing or excluded duplicates remain a barrier and are not resurrected by averaging.'),
        ('Datum correction','A signed addition to the survey elevation; nonzero correction requires recorded independent evidence.')
    ],[1.55,5.45])
    g.p('The **Restore raw values and decisions** action clears the selected survey’s session decisions. Source files are never edited. '
        'Changing sources or the selected reach prevents an already-open QA/QC window from applying stale decisions; reopen it for the new inputs.')
    g.callout('Preserve judgment, not just limits',
        'Record why a point was excluded or retained, what benchmark evidence supports a correction, and whether '
        'retained flagged values materially affect the result. Save the reviewed configuration with the run.')

    g.page('How the shared bed footprint is defined')
    g.p('The calculation uses four profiles: model baseline, model target, survey baseline and survey target. '
        'Only lateral intervals supported by all required profiles are integrated. Time-series processing also requires '
        'support from every additional selected epoch.')
    g.image('03_support','Illustrative overlap: a gap in the target survey removes that interval from both model and observed calculations.')
    g.p('The default intersection domain is the overlap of profile extents and the selected manifest transect. '
        'Transect mode instead tests the selected manifest extent against the configured coverage requirement. '
        'Setting transect mode alone does not force complete coverage if minimum coverage is less than one.')
    g.table(['Reported quantity','Definition / example'],[
        ('Common-domain coverage','Accepted effective width ÷ comparison-domain width. Here: 50 ÷ 60 = 0.833.'),
        ('Full-transect footprint coverage','Accepted effective width ÷ original manifest width. Here: 50 ÷ 100 = 0.50.'),
        ('Minimum accepted width','Applies after unsupported lateral intervals are removed, not just to the end-to-end overlap.')
    ],[2.3,4.7])
    g.p('Explicit NaN/NoData knots remain barriers. Finite source intervals wider than the allowed source gap are not '
        'interpolated across. Supported interior is checked as well as endpoints. Original source knots remain in the '
        'integration grid, so a coarse added grid cannot silently erase a known hole or sharp breakpoint.')
    g.callout('Why coverage needs two percentages',
        '100% coverage of a narrow overlap is not 100% of the full channel bed. Partial coverage is never scaled '
        'up to infer unmeasured bed volume. Footprint width can also vary between neighboring sections.')
    g.p('“Sampled bed area” is the endpoint-weighted estimate ΣWᵢℓᵢ, using accepted width Wᵢ and nodal control length ℓᵢ '
        '(§09). It is an integration-area proxy, not a surveyed two-dimensional polygon. Shared support makes the two '
        'sources comparable at each XS; it does not establish the morphology or coverage between them.')

    g.page('From elevation change to section area')
    g.p('Trace **elevation difference → section area → reach volume → cumulative accounting**, separately for model and '
        'survey on shared support. **Positive change is deposition; negative change is erosion.**')
    g.equations([
        ('Δz(u) = z_{a}(u) − z_{b}(u)', 'After minus before (ft)'),
        ('ΔA_{i} = Σ_{j} w_{j} (Δz_{j} + Δz_{j+1}) / 2', 'Signed change area (ft²)'),
        ('W_{i} = Σ_{j} w_{j};   mean change_{i} = ΔA_{i} / W_{i}', 'Accepted width / mean (ft)'),
    ])
    g.p('j indexes accepted lateral intervals of width wⱼ; i identifies the XS. Sums include separate accepted runs around holes.')
    g.image('04_area','Illustrative section. Orange shading is deposition; blue shading is erosion. The signed areas cancel although the bed changed.')
    g.p('Trapezoids integrate the piecewise-linear profile exactly. Accuracy relative to the actual bed depends on '
        'sampling. Missing intervals contribute no area and remain unmeasured.')
    g.h('Hand check for the illustrated change profile')
    g.p('At stations 0, 50 and 100 ft, changes are −3, +3 and −3 ft. Four triangles each have area '
        '½ × 25 × 3 = 37.5 ft². Deposition and erosion magnitudes are each 75 ft²; signed ΔA and mean change are zero.')
    g.p('Gross components split at the interpolated zero crossing. Clipping negative endpoints before trapezoidal '
        'integration would overestimate deposition. Check contributions in the lateral ledger.')

    g.page('From section area to reach volume')
    g.p('Average end area combines signed change areas at neighboring accepted XS over their verified channel length. '
        'Divide ft² × ft by 27 to obtain yd³.')
    g.equations([
        ('V_{i} = L_{i} (ΔA_{i} + ΔA_{i+1}) / (2 × 27)', 'Completed-reach volume (yd³)'),
        ('v_{i} = ΔA_{i} ℓ_{i} / 27', 'Local nodal contribution (yd³)'),
    ])
    g.p('Lᵢ is the verified i→i+1 reach length; ℓᵢ is the nodal control length. '
        'Vᵢ is reach volume; vᵢ is an assigned section contribution.')
    g.image('05_control_lengths','Illustrative default control lengths for two unequal reaches. End sections receive only the adjacent half-length.')
    g.p('At an interior XS, ℓᵢ = (L_upstream + L_downstream)/2. A supported-segment endpoint receives half its '
        'single accepted neighboring length, including at selection boundaries and unsupported gaps.')
    g.h('Why those weights matter')
    g.p('Within a supported segment, **Σvᵢ = ΣVᵢ**. Check this identity in the ledgers; it does not verify unsampled '
        'morphology or native RAS accounting. Average end area integrates a linear interpolation of section change '
        'areas. The equivalent nodal weights do not reconstruct uniform rectangular bed patches. '
        'No porosity correction is applied to these geometric volumes.')
    g.callout('Changed selection, changed endpoint accounting',
        'A new upstream boundary removes that section’s allocation from the reach outside the selection. '
        'Recalculate; cropping an existing cumulative plot does not reproduce the new endpoint accounting.')
    g.p('Upstream-held and downstream-held scenarios use the selected endpoint’s full reach weight instead of default '
        'half-length weights. Their local contributions and prefixes must be interpreted using that selected estimator.')

    g.page('A complete hand calculation')
    g.p('This illustrative example follows one source through three sections, change areas −27, −54 and −81 ft², and verified reach lengths '
        '1,000 and 2,000 ft. All source profiles are supported. The numbers below were checked against the tool’s calculation engine.')
    g.table(['XS','ΔA\n(ft²)','Control\nlength (ft)','Local V\n(yd³)','Node sum\n(yd³)','Reach prefix\n(yd³)'],[
        ('A','−27','500','−500','−500','0'),
        ('B','−54','1,500','−3,000','−3,500','−1,500'),
        ('C','−81','1,000','−3,000','−6,500','−6,500')
    ],[.45,.85,1.25,1.20,1.25,2.0],font=9.5)
    g.h('Calculate each completed reach')
    g.code('A → B: 1,000 × (−27 − 54) / 2 / 27 = −1,500 yd³\n'
           'B → C: 2,000 × (−54 − 81) / 2 / 27 = −5,000 yd³\n'
           'Total: −1,500 − 5,000 = −6,500 yd³')
    g.h('Calculate each local control contribution')
    g.code('A: −27 × 500 / 27   = −500 yd³\n'
           'B: −54 × 1,500 / 27 = −3,000 yd³\n'
           'C: −81 × 1,000 / 27 = −3,000 yd³')
    g.p('The node running sum is −500, −3,500, −6,500 yd³. The completed-reach prefix is 0, −1,500, −6,500 yd³. '
        'Both end at the same total, but the intermediate values are different quantities.')
    g.h('Use the audit tables to repeat this check')
    g.steps([
        'In Lateral ledger, sum accepted signed-area contributions for one section.',
        'In Reach ledger, check the two endpoint areas, estimator weights, verified length and reach volume.',
        'In Section accounting, check the control length, local contribution and both prefixes.',
        'At each supported segment end, compare the reach-volume sum, local-volume sum and final prefix.'
    ])
    g.callout('Do not infer a completed-reach volume from node differences',
        'Node(C) − Node(B) is −3,000 yd³ here: C’s local contribution. The completed B→C reach volume is −5,000 yd³. '
        'Use the reach ledger or completed-reach prefixes when discussing specific reach volumes.')

    g.page('Why two cumulative curves are available')
    g.p('The main calibration curve is the **node control-volume cumulative sum**. The audit selector also offers '
        'a **completed-reach prefix**. Neither should be silently relabeled as the other in a technical review.')
    g.image('06_prefixes','Illustrative node sum and completed-reach prefix for the hand calculation. Different intermediate values are expected.')
    g.table(['Curve','Meaning at the plotted XS'],[
        ('Node control-volume sum','Sum of local control-volume contributions through that XS. Under average end area, '
            'the first point includes the first half-reach contribution.'),
        ('Completed-reach prefix','Sum of completed reach integrals from the segment’s upstream XS to this XS. '
            'It starts at zero and adds a whole reach at each downstream endpoint.')
    ],[2.0,5.0])
    g.p('Both conventions reset at unsupported longitudinal gaps. Their final totals agree within each supported '
        'segment because they are rearrangements of the same selected estimator. Their mid-reach interpretation differs.')
    g.p('Under average end area, an interior node also includes its assigned half of the downstream reach. '
        'At B, the −3,500-yd³ node value includes B’s downstream allocation; the completed-reach value −1,500 yd³ '
        'ends at B. A station locates an accounting value: the node prefix is not strictly the volume physically upstream of that XS. '
        'Lines join discrete samples; they do not define an unsampled continuous volume profile.')
    g.h('Suggested caption wording')
    g.p('“Signed bed-volume change is shown as the node control-volume cumulative sum on the common sampled footprint. '
        'For the average-end-area estimator, the first plotted node includes a half-reach contribution; the curve resets at unsupported gaps.”')
    g.p('If you use the boundary convention, say “completed-reach prefix” and note that it begins at zero. '
        'If you change the estimator to an endpoint-held alternative, describe its full endpoint weights instead of a default half-reach start.')

    g.page('What happens at unsupported gaps')
    g.p('An unusable section disconnects integration. The tool does not interpolate a longitudinal volume across it. '
        'Sections with no accepted adjacent section are isolated and removed from volume integration.')
    g.image('07_disconnected','Illustrative disconnected segments. Each cumulative curve resets; a final point is not automatically the total for all supported segments.')
    g.h('Read segment totals correctly')
    g.p('In this example, segment A–B contributes +1,000 yd³ and segment D–E contributes +2,000 yd³. The all-supported '
        'total is +3,000 yd³. The last plotted point is +2,000 yd³ because it belongs to the final segment. '
        'Do not add every node prefix; that would count the same local contributions repeatedly.')
    g.h('What a gap means in the review')
    g.bullets([
        'Report both usable and excluded XS counts, supported segment count and integrated supported channel length.',
        'Use excluded_sections.csv to explain missing sections and coverage failures. Do not characterize an excluded reach as stable.',
        'Describe totals as the supported sampled portions if coverage is disconnected or partial.',
        'Derivatives, longitudinal zone runs and prefixes do not cross the excluded section.'
    ])
    g.callout('No gap filling by a larger reach limit',
        'A source gap limit concerns interpolation within a lateral profile. A reach-length limit rejects an '
        'entire comparison if an accepted channel interval is overlong; it does not exclude that interval and continue. '
        'Raising either setting does not turn an explicitly missing XS into supported data.')
    g.p('The error model can nevertheless assume coherent elevation error across supported sections in separate segments '
        'when spatial correlation is set to one. That is an uncertainty assumption, not geometric bridging.')

    g.page('Reading the main comparison plot')
    g.p('The illustrative dataset compares 15 January 2020 with 15 January 2025 at eight fully supported, '
        '1,000-ft-wide sections from RM 100 to 93, connected by seven verified 1-mile reaches. Modeled changes are '
        'twice the observed changes by construction.')
    g.image('12_main','Tool plot of an illustrative eight-section dataset, with axes formatted for print. Blue is model; orange dashed is observed. These are not project results.')
    g.h('Upper panel: cumulative volume')
    g.p('Read the overall signed amount, where the modeled and observed curves separate, and whether errors accumulate '
        'systematically downstream. A rising node curve adds positive local contribution; a falling one adds negative '
        'local contribution. Use reach-ledger values for the exact completed-reach interpretation.')
    g.h('Lower panel: mean bed change')
    g.p('This is section signed change area divided by accepted lateral width, in feet. It identifies mean erosion '
        'and deposition on the sampled section, not thalweg movement or the strongest local scour/deposition. '
        'The gray band is the classification threshold; changes inside it still enter all volume calculations.')
    g.p(f'In this illustrative case, observed net volume is {m["observed_total_yd3"]:,.0f} yd³ and model net volume is '
        f'{m["model_total_yd3"]:,.0f} yd³. Bias, defined as model minus observed, is {m["total_bias_yd3"]:,.0f} yd³. '
        'The model has twice the change magnitude despite reproducing its downstream mean-change pattern.')
    g.callout('Caption essentials',
        'State the four dates, actual RM bounds, common sampled footprint, supported segments, estimator, cumulative convention, '
        'sign convention and units. Mention any exclusions and material coverage changes.')

    g.page('Reading the pattern-diagnostic panels')
    g.image('13_diagnostics','Tool-generated diagnostics for the same illustrative case, with shorter print labels. Panels a–f separate magnitude, pattern and bed-shape questions.',width=6.70)
    g.p('Read panels left to right, top to bottom: **(a)** mean change and observed zones; **(b)** model versus observed '
        'change with the equality line; **(c)** standardized change; **(d)** mean baseline/target bed elevations; '
        '**(e)** downstream slope; **(f)** downstream concavity.')
    g.p('The quantity selector switches derivatives among change, target bed and baseline bed. '
        'Derivatives remain based on downstream-increasing physical chainage even when RM decreases to the right. '
        'The default exported diagnostics image uses change; save other views explicitly.')

    g.page('Interpreting the performance metrics')
    g.p('First verify support and dates; then assess magnitude, downstream pattern and lateral variability. '
        'Finally examine sensitivity and conditional uncertainty. Use a small set of complementary metrics. Acceptance criteria should reflect '
        'the review objective, survey uncertainty and consequences of prediction error. The tool does not supply a universal “calibrated” threshold.')
    g.table(['Metric','What it answers / main limitation'],[
        ('Total volume bias (yd³)','Model total − observed total. Positive bias means a more positive modeled result '
            '(more deposition or less erosion); negative means a more negative result. Opposing reach errors can cancel.'),
        ('Completed-reach volume RMSE / MAE (yd³)','Typical magnitude of completed-reach volume errors; each accepted interval enters '
            'these summaries equally. Longer reaches can naturally have larger volume errors.'),
        ('Mean-change RMSE / bias (ft)','Elevation-change error weighted by accepted width × control length. '
            'RMSE measures magnitude; signed mean bias measures average direction.'),
        ('Demeaned change RMSE (ft)','Pattern error after removing each series’ weighted mean. This is a diagnostic, '
            'not an applied datum correction.'),
        ('Shape / rank correlation','Similarity of downstream mean-change pattern. Perfect correlation can coexist '
            'with a large uniform offset or multiplicative error. Rank correlation uses the section-value ranks.'),
        ('Amplitude ratio / regression gain','Amplitude ratio compares weighted spreads; gain is the weighted model-on-observed '
            'slope after demeaning. A value of two indicates excessive modeled variation in the illustrated proportional case.'),
        ('Zone agreement / zone IoU','Control-length-weighted agreement in section mean-change classes and their '
            'erosion/deposition overlap. Depends on threshold and can hide lateral cancellation.'),
        ('Cumulative volume RMSE (yd³)','Descriptive discrepancy between node prefixes. Prefix residuals share contributions '
            'and are strongly correlated; they are not independent error samples.')
    ],[2.05,4.95],font=9.0)
    g.h('The illustrative counterexample')
    g.p(f'The example has shape correlation 1.00, amplitude ratio 2.00, mean-change zone agreement 100%, and mean-change '
        f'RMSE about {m["mean_change_rmse_ft"]:.3f} ft. Its net volume bias is {m["total_bias_yd3"]:,.0f} yd³. '
        'The correct interpretation is good pattern reproduction with a substantial magnitude error.')
    g.p('A constant series has undefined correlation or spread-based skill when the denominator vanishes. '
        'Undefined values appear as null/undefined, not a perfect score. Zone IoU is undefined if neither source contains that class.')

    g.page('Using cross-section and bed-shape plots')
    g.image('14_profiles','Tool-generated profiles for illustrative RM 97.0. Dots include interpolated common-grid points, not just original samples. The lower panel reveals lateral opposition.')
    g.h('Inspect profiles before explaining a residual')
    g.bullets([
        'Use the baseline and target elevations to distinguish initial-bed mismatch from an error in subsequent change.',
        'Check that the same lateral positions represent the same bed. Look for bank displacement, mismatched station origins and survey coverage edges.',
        'Use the change panel to locate local erosion and deposition within the sampled section.',
        'A line gap marks unsupported lateral intervals; it should not be interpreted as a flat bed or zero change.'
    ])
    g.p('Finite markers in the upper elevation panel may be visible outside accepted intervals. A visible point '
        'alone is not proof that it entered the area integral; verify connected accepted runs or the lateral ledger.')
    g.p('Pattern diagnostics summarizes bed elevations as an accepted-width mean. Its “bed shape” is a longitudinal '
        'series of sampled mean elevations; it is not a thalweg profile or a continuous two-dimensional terrain.')
    g.callout('Derivative interpretation',
        'Slope and concavity are unsmoothed finite differences within supported segments. Concavity needs at least '
        'three consecutive supported XS. Noise, irregular spacing and changes in lateral footprint can all produce apparent features. '
        'Report ft per downstream mile and ft per downstream mile², not derivatives with respect to decreasing RM.')

    g.page('Why small net change can hide activity')
    g.p('The signed integral combines areas of erosion, deposition and little change. It can be small when '
        'substantial opposing changes cancel. Gross components and variability distinguish that situation from a genuinely unchanged sampled bed.')
    g.image('08_cancellation','Two illustrative sections with the same zero mean change but very different observed bed-change distributions.')
    g.equations([
        ('D = ∫ max(Δz, 0) du;   E = ∫ max(−Δz, 0) du', 'Positive magnitudes (ft²)'),
        ('Net = D − E;   gross = D + E', 'Section change areas (ft²)'),
        ('Cancellation = 1 − |net| / gross', 'Fraction; undefined if gross = 0'),
    ])
    g.p('The cancellation fraction is zero for one sign only, one for equal opposing magnitudes, and undefined '
        'when gross change is zero. Erosion components are stored as positive magnitudes, even though some plots draw '
        'them below zero for visual comparison with deposition.')
    g.h('Two levels of cancellation')
    g.p('Opposing changes can occur laterally within one section, or longitudinally between sections. '
        'The reach and overall indicators include both mechanisms through the chosen endpoint-section quadrature. '
        'A zero reach mean therefore does not imply that each section or each part of the bed was stable.')
    g.callout('Use “two-date turnover,” not sediment transport',
        'Gross geometric turnover is a useful activity indicator between the two sampled bed states. '
        'It is not transported sediment volume, sediment-solid volume, event count or the total erosion/refilling that occurred between surveys.')

    g.page('Reading variability and active-width plots')
    g.image('15_variability','Tool-generated variability for the illustrative case. Dashed observed cancellation coincides with the model curve; scaling change by two preserves cancellation but doubles its standard deviation.')
    g.table(['Indicator','How to interpret it'],[
        ('Lateral change standard deviation (ft)','Spread of local change about that section’s accepted-width mean. '
            'Computed from the exact linear-profile second moment, not from treating interpolated knots as independent observations.'),
        ('Reach / overall spatial std (ft)','Combines within-section change and differences between section means '
            'using accepted width × control weight. It is spatial heterogeneity, not the time variability of bed activity.'),
        ('Erosion / deposition width fraction','Accepted width where local change is strictly below −threshold or above +threshold. '
            'The remaining accepted width is within threshold. A mean-change class is a different quantity.'),
        ('Gross volume and cancellation','Endpoint-section estimates of opposing geometric changes; not reconstruction of unsampled two-dimensional morphology.')
    ],[2.15,4.85],font=9.0)
    g.p('The same threshold must be stated when comparing fractions between models or runs. Missing bed is excluded '
        'from the denominator; do not interpret the plotted fractions as fractions of the entire channel when support is partial.')
    g.p('For linear endpoint changes a and b across width w, the second moment is w(a² + ab + b²)/3. '
        'Sum these moments over accepted intervals, divide by total accepted width, subtract the squared section mean, '
        'and take the square root to obtain lateral standard deviation.')

    g.page('Operating the assumption explorer')
    g.p('After calculating a reference pair, open Audit calculations / explore assumptions. The explorer reuses '
        'the original reviewed model and survey profiles. It does not edit source files, apply QA/QC decisions to the main run or replace the reference.')
    g.steps([
        'Keep a named reference configuration and export its results before experimenting.',
        'Select one scientific assumption to test. Enter changes in the left-hand controls and click Calculate and keep scenario.',
        'Use the scenario selector to switch between Reference and retained scenarios. New controls describe the next experiment, '
        'not necessarily the selected historical scenario.',
        'Compare Calculation stages, Variability / cancellation and Assumption sensitivity. The calculation plot overlays '
        'the reference as faint dotted curves when a scenario is shown.',
        'Read support_changed before interpreting any volume delta. Inspect section, reach and lateral ledgers for changed support.',
        'Export scenario comparison and audits and Save scenario instructions. Use a separate run log to map auto-numbered GUI scenarios '
        'to meaningful scientific labels.',
        'Use Clear scenarios / restore reference only after saving any needed history; it discards retained experiments.'
    ])
    g.h('Read the scenario summary')
    g.table(['Field','Meaning'],[
        ('Status','An unavailable scenario has a recorded reason, such as insufficient support. It is not a zero-result calculation.'),
        ('support_changed','The accepted XS set or accepted lateral runs differ from the reference. A delta can then mix estimator and sampling effects.'),
        ('Observed delta / bias delta','Change from the reference under that scenario. The difference is sensitivity, not proof of a better method.'),
        ('Gross turnover / cancellation / std','Whether a similar net total conceals altered opposing change or variability.'),
        ('Conditional bias interval / flag','Survey-error screening under stated assumptions; not a model-validation test.')
    ],[2.2,4.8])
    g.p('Uncertainty controls apply to all retained summary rows during recomputation. Failed scenarios remain in the '
        'exported ledger; selecting one shows its reason and displays the reference. Tables preview up to 2,000 rows; '
        'exports contain the full rows.')

    g.page('Knobs for support and reconstruction')
    g.table(['Control','Scientific meaning / useful test'],[
        ('Longitudinal estimator','Average end area is the default. Holding upstream or downstream area throughout '
            'each reach tests endpoint reconstruction sensitivity; control weights change consistently.'),
        ('Lateral domain','Intersection uses common overlap. Transect evaluates the selected manifest extent with '
            'the coverage requirement. Check both domain and full-footprint coverage.'),
        ('Maximum source gap (ft)','Largest finite lateral source interval permitted for interpolation. '
            'Explicit NaN barriers remain regardless of this limit. Base the setting on sampling density and bed features.'),
        ('Minimum domain coverage','Fraction of comparison-domain width that must be accepted. A value of 0.80 means 80%, not 0.8%. '
            'Changing it can remove XS and disconnect segments.'),
        ('Minimum accepted width (ft)','Minimum usable lateral width after gaps are removed. Do not use it to scale a narrow footprint up to the full bed.'),
        ('Trim fraction per bank','Symmetric fraction of original manifest width removed from each end. 0.05 trims 5% per bank '
            'and retains at most 90% of original width. It does not automatically identify the active channel.'),
        ('Integration grid spacing (ft)','Adds interpolation knots while retaining source knots. Test invariance; '
            'it does not change source raster resolution or extraction spacing.')
    ],[2.0,5.0],font=9.0)
    g.image('09_estimators','Illustrative endpoint-method sensitivity: 27 and 81 ft² over 1,000 ft produce 1,000, 2,000 or 3,000 yd³.',width=6.70)
    g.p('Upstream and downstream alternatives are not guaranteed bounds on the true volume. An unsurveyed scour '
        'hole or deposit between sections could fall outside the endpoint range. No method should be selected solely because it reduces model bias.')

    g.page('Knobs for classification, shifts and error')
    g.table(['Control','What changes / how to document it'],[
        ('Classification threshold (ft)','Changes zones and active-width fractions. Values strictly beyond ±threshold '
            'classify as erosion/deposition; equality is within threshold. Signed and gross volume retain all supported change.'),
        ('Hypothetical target shift (ft)','Adds a uniform elevation to the reviewed target survey for an experiment. '
            'It changes observed volume and model-minus-observed bias. It is not an approved datum correction.'),
        ('Baseline / target error σ (ft)','Assumed one-sigma elevation errors. Supply evidence-based values for the main run; '
            'explorer values are scenarios unless justified. These do not perturb the profiles.'),
        ('Before/after error correlation','Allowed range −1 to 1. Positive correlation can reduce difference error; '
            'equal sigmas with correlation one cancel under this model. Explain why the epochs share error.'),
        ('Between-XS error correlation','Allowed range 0 to 1. Zero assumes independent section errors; one assumes '
            'coherent error over all accepted sections. The default is one.'),
    ],[2.05,4.95])
    g.h('Know which settings are upstream of the explorer')
    g.p('Raster nearest/bilinear sampling, extraction sample spacing, point-to-XS mapping, acquisition dates, '
        'QA/QC exclusions and real datum corrections require changes to source/configuration settings and a new main comparison. '
        'The explorer deliberately reuses already reviewed profiles.')
    g.h('Separate classification from error bands')
    g.p('In the main workflow, supplied survey uncertainties and temporal correlation can raise the change threshold to '
        'the conditional 95% difference limit. In the explorer, the classification threshold is its own explicit control; '
        'changing error controls updates uncertainty for all summary rows and does not automatically recompute that threshold from the new sigmas.')
    g.callout('A simple shift calculation',
        'On an unchanged supported footprint of 200,000 ft², a +0.10-ft target shift increases observed net volume '
        'by 0.10 × 200,000 / 27 = 740.74 yd³. With model volume unchanged, model-minus-observed bias decreases by 740.74 yd³. '
        'That predictable effect is a sensitivity check, not evidence that the survey datum is wrong.')
    g.p('Test one control at a time, then selected combinations. Record footprint, exclusions and method alongside the '
        'volume response; a changed-support scenario cannot isolate estimator bias by its total alone.')

    g.page('Numerical QA and the integration grid')
    g.p('The lateral integrator preserves every source knot and integrates the resulting piecewise-linear functions. '
        'Adding a denser grid supplies more interpolation points, not more measured information.')
    g.image('10_grid','Illustrative coarse and fine added grids. Retained source knots preserve the feature and the same 6-ft² integral.')
    g.h('A useful convergence check')
    g.steps([
        'Hold source profiles, QA/QC, footprint, gap rules and reconstruction method fixed.',
        'Run coarser and finer integration-grid scenarios.',
        'Compare accepted support, signed/gross areas, total volumes and variability moments.',
        'Expect agreement within floating-point tolerance for the same piecewise-linear support. Investigate material differences '
        'before treating either run as an improvement.'
    ])
    g.p('The effective added-grid spacing is bounded by half the maximum source gap internally, and all source knots '
        'are still retained. A user grid value therefore does not mean that the integral ignores finer source features.')
    g.h('Three different resolutions')
    g.table(['Resolution','What it represents'],[
        ('Source raster / sounding resolution','The information in the original survey. New interpolation knots do not improve it.'),
        ('Transect extraction spacing','Where the source raster is sampled along the geometry. A new extraction can change sampled elevations or NoData encounters.'),
        ('Integration grid spacing','Supplemental numerical knots on the already extracted, reviewed profiles.')
    ],[2.1,4.9])
    g.callout('No artificial precision gain',
        'Refining the integration grid does not increase the independent observation count or reduce the tool’s conditional '
        'survey-volume uncertainty. Keep practical report rounding distinct from internal numerical precision.')

    g.page('How survey-volume uncertainty is calculated')
    g.p('The tool uses a conditional Gaussian error model with one sigma per survey, common to every section. '
        'Elevation error is coherent across a section’s accepted width. Temporal correlation links before/after errors; '
        'one between-XS correlation applies to every section pair, regardless of distance or segment separation. '
        'This is a homogeneous section-error model, not a distance-dependent covariance model.')
    g.equations([
        ('σ_{c}² = σ_{b}² + σ_{a}² − 2ρ_{t}σ_{b}σ_{a}', 'Before/after difference variance (ft²)'),
        ('a_{i} = W_{i}ℓ_{i}', 'Endpoint area coefficient (ft²)'),
        ('σ_{V} = (σ_{c} / 27) [(1 − ρ_{s})Σa_{i}² + ρ_{s}(Σa_{i})²]^{1/2}', 'Volume standard uncertainty (yd³)'),
        ('Bias interval = (V_{model} − V_{observed}) ± 1.96σ_{V}', 'Conditional 95% interval (yd³)'),
    ])
    g.p('b/a denote before/after; σc is change-error standard deviation. ρₜ is temporal and ρₛ between-XS correlation; '
        'defaults are 0 and 1. Coefficients aᵢ use accepted support and estimator weights; their sum is a quadrature '
        'area proxy, not a surveyed polygon (§07).')
    g.h('A worked error example')
    g.p('Three 100-ft-wide sections span two 1,000-ft reaches. Average end area gives ℓ = [500, 1,000, 500] ft '
        'and a = [50,000, 100,000, 50,000] ft², totaling 200,000 ft². Both survey sigmas are 0.20 ft; temporal correlation is zero.')
    g.table(['Assumption','Computed value'],[
        ('Difference error σc','√(0.20² + 0.20²) = 0.283 ft'),
        ('Spatial correlation 1','σV = 2,095.13 yd³; 95% margin = 4,106.46 yd³'),
        ('Spatial correlation 0','σV = 1,283.00 yd³; 95% margin = 2,514.68 yd³'),
        ('Main-workflow classification limit','1.96 σc ≈ 0.554 ft, using unrounded σ; applied if larger than configured threshold')
    ],[2.9,4.1],font=9.5)
    g.h('What is outside this interval')
    g.p('The model is treated as exact. The interval excludes model uncertainty, unresolved between-XS morphology, '
        'horizontal registration error, date mismatch and unknown systematic bias. Correlation one is conservative within '
        'this restricted correlation model; it is not a guarantee of conservative total uncertainty.')
    g.callout('Use measured uncertainty evidence',
        'A survey accuracy statement must be converted to a defensible one-sigma elevation uncertainty before using it '
        'as σ. Do not silently substitute a 95% accuracy bound for one sigma or assume that all error is independent because the survey contains many points.')

    g.page('Bias screening and conditional significance')
    g.image('11_uncertainty','Illustrative ±1.96σ survey-error intervals for the same +3,000-yd³ bias. Correlation assumptions change whether zero is included.')
    g.p('With spatial correlation one, the worked interval is approximately **−1,106 to +7,106 yd³** and includes zero. '
        'With correlation zero, it is approximately **+485 to +5,515 yd³** and excludes zero. The model and observed '
        'totals did not change; the uncertainty assumption did.')
    g.h('What the tool’s flag means')
    g.p('bias_exceeds_survey_error_95 is true when |bias| exceeds 1.96σ_volume under declared positive conditional '
        'variance. It is a survey-error screen for that calculation. It does not establish the overall statistical '
        'validity of the model or include all reasons why model and survey reconstructions may differ.')
    g.bullets([
        '**Both sigmas zero / unspecified:** no error interval or significance claim is supported; the flag is undefined.',
        '**Supplied errors cancel to zero conditional variance:** a zero-width interval can be displayed, but significance '
        'remains undefined. Perfect cancellation is an assumption, not proof of zero real uncertainty.',
        '**Cumulative residuals:** shared contributions make them correlated. Do not treat every plotted node as an '
        'independent replicate for a t-test or use the number of interpolation knots as sample size.',
        '**Changed footprint:** first resolve what was compared. A conditional interval does not repair a support mismatch.'
    ])
    g.callout('Suggested review wording',
        '“The model-minus-observed bias [does / does not] exceed the conditional 95% survey-error margin under the stated '
        'epoch and spatial correlation assumptions. This interval excludes model error, unresolved morphology, '
        'registration error and unquantified systematic bias.”')

    g.page('Multiple surveys and annual change rates')
    g.p('Calculate all survey intervals sorts configured surveys by acquisition date and compares consecutive pairs. '
        'Every interval uses a fixed common footprint across all selected survey and model epochs. This supports '
        'temporal comparison without attributing changed sampling width to changed bed behavior.')
    g.image('16_series','Tool-generated rates for three illustrative epochs, with shorter colorbar labels. Red is positive; blue is negative. Equal-width cells represent discrete XS samples.',width=6.50)
    g.h('Interpret the rates and support')
    g.p('A section mean-change rate is that section’s mean change divided by its source-specific elapsed years. '
        'Model rates use model dates and observed rates use survey dates; elapsed years use 365.25 days. '
        'A temporal match within tolerance can therefore still leave slightly different durations.')
    g.p('The heatmap’s columns are equally displayed sample cells labeled by XS river mile, not a uniform physical '
        'RM grid. Black dividers mark disconnected supported segments. Report the common footprint and any sections '
        'lost when a less complete epoch is added.')
    g.callout('Two surveys are endpoints, not a history',
        'Erosion followed by refilling may leave little net difference between surveys. More epochs can reveal temporal '
        'reversals at sampled sections, but this workbench still does not reconstruct unobserved event history or continuous two-dimensional activity.')
    g.p('The GUI uses all configured surveys. Restrict epochs with a configuration copy or headless --surveys. '
        'For a GUI interval inspection, calculate a separate pair; it may have more support because other epochs no '
        'longer constrain it. Use archived series results for fixed-support comparisons.')

    g.page('Native HEC-RAS volume as a separate audit')
    g.p('Reconstructed profile volume is the quantity compared on the common survey footprint. A native RAS bed-volume '
        'output can be an additional accounting check only when its variable definition and integration footprint '
        'are independently matched to that reconstruction.')
    g.table(['Recorded project variable','Meaning to verify locally'],[
        ('Vol Bed Change Cum','Recorded as local, time-cumulative bed-volume change in ft³. Subtract baseline from '
            'target before comparing an interval, then convert units and verify sign/bulk basis.'),
        ('Long. Cum Vol Change','Recorded as a spatial and time cumulative sum of local volume within a river/reach. '
            'Respect branch resets; do not sum a spatial cumulative series again.'),
        ('Geometric reconstruction','Integrates modeled bed-elevation changes on the same supported lateral footprint as observations. '
            'It is not automatically identical to every native sediment output.')
    ],[2.0,5.0])
    g.h('Conditions for the tool to run the audit')
    g.bullets([
        'Verified native semantics, deposition sign, units and bulk geometric basis, with recorded evidence.',
        'Full manifest lateral footprint, one contiguous supported segment and no excluded XS.',
        'Explicit native time_dataset with the selected profile dates present. Sediment SE and native volume row indices can differ.',
        'The native path must refer to the selected model HDF.'
    ])
    g.p('Incomplete footprint, segments, exclusions, or missing time/footprint gates skip the audit with a recorded reason. '
        'Invalid verification evidence, variable semantics, sign/units or native date matching can instead stop the calculation with an error. '
        'The supplied real_config.json does not currently '
        'include the native time_dataset and footprint_verified gates, so configuration of the native variable alone '
        'does not establish a completed audit. Do not set those flags until the required checks are documented.')
    g.callout('Endpoint and footprint equivalence are essential',
        'A selected interior upstream XS receives only its downstream half-reach in the reconstruction. Its native '
        'RAS control volume may include an upstream half outside the selection. Also verify lateral sediment-bed extent, '
        'bank treatment and bulk versus solid basis. An accounting mismatch is not, by itself, a model morphologic prediction error.')
    g.p('The supplied native-accounting notes record project assertions; this guide has not reproduced them from the '
        'real HDF. Verify variable definitions against the installed HEC-RAS version, metadata and numerical local exports.')

    g.page('Exporting evidence and preparing figures')
    g.p('Export results and plots creates a new timestamped directory. Use customary tables for review and retain the '
        'original SI tables and report for reproducibility. Timestamps are UTC; record local dates separately if needed.')
    g.table(['Output','Use in a technical review'],[
        ('comparison.png','Default node cumulative volume and section mean change.'),
        ('diagnostics.png','Default change-oriented six-panel diagnostic view. Other bed-shape views require explicit saving.'),
        ('calculation_audit.png / variability.png','Calculation stages for the first accepted XS and spatial variability. '
            'To show a different section or boundary convention, save the current audit canvas explicitly.'),
        ('sections / intervals / lateral_audit CSVs','Section weights and prefixes; exact completed-reach operands; accepted lateral contributions. '
            'Customary companions use _customary.csv.'),
        ('profiles / survey_qaqc / excluded_sections CSVs','Matched profile support, original/used survey values and recorded exclusions; excluded_sections is present when needed.'),
        ('report.json / metrics_customary.json','SI metrics and provenance; customary metric companion. Keep both.'),
        ('transects / source_profiles / support_profiles','Calculation geometry and reviewed inputs. Extra fixed-support epochs are exported when present.'),
        ('Scenario / series exports','Reference and scenario folders, sensitivity tables/instructions/plot; per-interval series tables and heatmap.')
    ],[2.55,4.45],font=9.0)
    g.h('Print-ready plot handling')
    g.p('Automatic PNGs are saved at 150 dpi. The Matplotlib toolbar can save the active canvas as a vector PDF/SVG '
        'or another supported format, including selected XS and alternate views. For publication PNGs, regenerate '
        'from retained inputs at the intended figure size and 300 dpi or higher; do not merely upscale the 150-dpi file.')
    g.p('In Word, keep aspect ratio, avoid stretching a small raster, and use File → Options → Advanced → Image Size '
        'and Quality → Do not compress images / High fidelity when available. Keep labels readable at final print size. '
        'Use line style as well as color, and explain gaps and resets in the caption.')
    g.p('Archive source plots and numerical tables before editorial resizing. Model and observed dates, units and '
        'cumulative convention should survive cropping and placement in the review document.')

    g.page('A technical-review evidence checklist')
    g.p('Complete this checklist for each reported comparison. Where evidence is unavailable, describe the limitation '
        'and its effect on the inference rather than relying on a verification flag.')
    g.table(['Review item','Evidence to retain'],[
        ('Purpose and independence','Calibration objective, decision criteria, parameter adjustments, and whether '
            'each interval is calibration or independent validation evidence.'),
        ('Identity and dates','Model/plan/version/run identity; survey layers and acquisition windows; all four '
            'comparison dates and alignment tolerance.'),
        ('Datum and registration','Elevation units, vertical datum/transformation, benchmark checks, horizontal CRS '
            'and registration evidence, station origin and orientation.'),
        ('Extent and support','Actual RM ends, XS count and column mapping, channel-length source, accepted widths, '
            'full-footprint coverage, integrated supported length, segments and exclusions.'),
        ('Method and accounting','Domain, gaps, coverage/width limits, extraction versus integration spacing, '
            'longitudinal estimator, cumulative convention and endpoint rules.'),
        ('QA/QC','Raw/used elevations, duplicate policy, retained flags, exclusion reasons, datum-correction evidence and saved configuration.'),
        ('Performance','Net bias, local/interval magnitude error, shape/gain, zone agreement, gross components, cancellation and spatial variability.'),
        ('Sensitivity and uncertainty','Scenario rationale, support_changed, failure reasons, survey sigmas/correlations, '
            'conditional interval limitations and any unquantified uncertainties.'),
        ('Native audit','Ran or skipped; actual variable semantics, date mapping, bulk basis, footprint and endpoint equivalence; local checks.'),
        ('Reproducibility','Exact settings, software commit/environment, original or immutable survey/HDF inputs, '
            'manifest, outputs, file hashes where needed and figure captions.')
    ],[1.8,5.2],font=9.2)
    g.h('Recommended review figure set')
    g.p('Use the main comparison with a clear support statement, completed-reach or interval errors, representative '
        'cross-section changes, a variability/gross-change summary and selected sensitivity results. Add the native audit '
        'only if its equivalence is documented. A single cumulative plot rarely supports the whole conclusion.')
    g.p('The report records settings, the model fingerprint, cache identities and review decisions. Retain the source '
        'dataset identities and manifest independently; add explicit human-readable hashes for all key inputs when required '
        'by the review process.')

    g.page('Review-ready methods and interpretation text')
    g.p('Adapt the following language to actual exported results. Bracketed text is a placeholder, not a verified '
        'statement about this project. Keep distinctions between supported-bed evidence and whole-river inference.')
    g.h('Methods paragraph')
    g.p('“Bed-elevation change between [baseline survey date] and [target survey date] was compared with HEC-RAS '
        'profile outputs at [baseline model date] and [target model date] over RM [upstream] to [downstream]. '
        'Profiles were registered to [datum and projected CRS] and reviewed under [QA/QC protocol]. At each '
        'section, signed change areas were integrated on lateral intervals supported by all required profiles. '
        'Adjacent section areas were combined by [estimator] using verified channel lengths. Volumes are bulk '
        'geometric bed changes in cubic yards, with deposition positive and erosion negative.”')
    g.h('Support and cumulative convention')
    g.p('“The comparison included [used] cross sections, excluded [count] and integrated [length] miles across '
        '[segments] supported segments. Minimum full-transect footprint coverage was [fraction]. Results describe '
        '[full verified / partial] sampled support. The plotted node cumulative sums reset at gaps; [for average end area] '
        'the first point includes a half-reach control contribution. Completed-reach quantities were checked in the interval ledger.”')
    g.h('Results and limitations')
    g.p('“Observed and modeled net changes were [observed] and [model] yd³; model-minus-observed bias was [bias] yd³. '
        'Mean-change RMSE was [value] ft, weighted shape correlation [value], and amplitude ratio [value]. '
        'Observed gross erosion/deposition were [values], with cancellation [fraction]. These diagnostics indicate '
        '[interpretation of magnitude, pattern and variability], subject to [coverage, datum, spacing and unresolved morphology limitations].”')
    g.h('Assumption sensitivity and uncertainty')
    g.p('“Under [scenarios], observed volume varied by [range] and bias by [range]. [State whether support changed.] '
        'The conditional 95% survey-error interval used [sigmas], temporal correlation [value] and spatial correlation '
        '[value], treating the model as exact. Bias [did / did not] exceed that conditional margin. The interval does '
        'not include model uncertainty or unquantified registration, datum, timing and reconstruction errors.”')
    g.callout('State the strength of evidence proportionately',
        'Prefer “reproduced the sampled downstream pattern but overpredicted change magnitude” to an unqualified '
        '“validated.” Avoid “zero change” for missing support, “sediment transport” for geometric turnover, '
        'and significance claims based only on many correlated cumulative points.')

    g.page('Troubleshooting and interpretation traps')
    g.table(['Symptom','Likely explanation / appropriate response'],[
        ('Calculate is disabled','Load dates and check ordered distinct surveys/model outputs, date tolerance '
            'and a range containing at least two XS. Read the status strip.'),
        ('Dates fail alignment','Check acquisition metadata, common local clock and model output availability. '
            'Document any defensible tolerance change; do not shift dates just to enable the calculation.'),
        ('Few or no usable XS','Check profile extents, units/origin/orientation, NoData, source gaps, accepted '
            'width and coverage. Do not automatically relax controls to manufacture continuity.'),
        ('A narrow result has 100% coverage','The domain overlap may be narrow. Read full-transect footprint coverage '
            'and effective width as well as domain coverage.'),
        ('Prefixes restart / last point differs from total','Unsupported XS split segments. Sum segment final totals '
            'or use reported all-supported totals; do not sum all node prefixes.'),
        ('Mean change is small but turnover is large','Opposing lateral or longitudinal changes cancel. Inspect gross '
            'components, profiles, variability and active-width fractions.'),
        ('Correlation is perfect but bias is large','Correlation assesses pattern. Check magnitude error, gain, '
            'uniform bias and interval errors. Constant-series null values are expected.'),
        ('Manual exclusion no longer matches a point','Source data or selected reach may have changed. Use a '
            'configuration copy for the intended extent and review the retained exclusion decisions for that run.'),
        ('A scenario is unavailable','Read its exported reason. Failed support is not a zero volume. Retain the failed '
            'case as sensitivity evidence rather than selecting it as a best fit.'),
        ('Native audit is skipped or differs','Check dates and audit gates, lateral bed extent, sign/units/bulk basis '
            'and selected-boundary weights. A native difference can be an accounting difference.'),
        ('GDB or bilinear extraction fails','Confirm ArcGIS Python path, licenses/Spatial Analyst and transformation '
            'mappings. The tool does not silently replace a failed sampling method.'),
        ('Error interval is absent / zero width','Check declared sigmas and correlations. Missing or perfectly '
            'canceling error assumptions do not establish statistical significance.')
    ],[2.0,5.0],font=9.1)
    g.p('If the bed-change result changes materially with integration-grid refinement on identical support, investigate '
        'numerical or input problems. If it changes with extraction spacing or footprint, investigate the scientific '
        'sampling assumption and report that sensitivity.')

    g.page('Setup and reproducible command-line use')
    g.p('Use Python 3.12 and the repository requirements in a separate scientific environment. For geodatabases, '
        'keep the configured ArcGIS interpreter separate; do not install the repository stack into ArcGIS Pro’s default environment.')
    g.code('python -m venv .venv\n'
           '.venv\\Scripts\\Activate.ps1       # Windows PowerShell\n'
           'python -m pip install -r requirements.txt\n'
           'python -m bathymetry_calibration --config "C:/Project/config.json"')
    g.h('A reproducible pair comparison')
    g.code('python -m bathymetry_calibration --config "C:/Project/config.json"\n'
           '  --hdf "C:/Project/plan.p01.hdf" --headless\n'
           '  --before-survey baseline --after-survey target\n'
           '  --output "C:/Project/review_exports"')
    g.h('Consecutive epochs or survey QA/QC only')
    g.code('python -m bathymetry_calibration --config "C:/Project/config.json"\n'
           '  --series --surveys baseline intermediate target\n'
           '  --output "C:/Project/series_exports"\n\n'
           'python -m bathymetry_calibration --config "C:/Project/config.json"\n'
           '  --qaqc-only --output "C:/Project/qaqc_exports"')
    g.h('Replay saved assumption instructions')
    g.code('python -m bathymetry_calibration --config "C:/Project/config.json"\n'
           '  --headless --before-survey baseline --after-survey target\n'
           '  --sensitivity "C:/Project/scenarios.json"\n'
           '  --output "C:/Project/scenario_exports"')
    g.p('Each multi-line example above is one command; join its lines when pasting. Survey names must be configuration '
        'keys. Model HDF can be supplied by model.path. Optional --before-index and --after-index are zero-based '
        'output indices and still undergo date checks. Scenario JSON values with _m units are metres, even though the GUI displays feet.')
    g.h('Repeating model calibration')
    g.p('Archive the reference, adjust scientifically justified HEC-RAS parameters outside this tool, rerun HEC-RAS, '
        'reload the new HDF and repeat the same supported comparison. Keep a run log. Cache reuse concerns raw survey '
        'extraction, not a guarantee that the model, geometry or review assumptions are unchanged.')

    g.page('Key fields in the exported tables')
    g.p('Customary files are companions to canonical SI exports. Use the filename and unit suffix together. '
        'The following exact field names help a reviewer trace a plotted value back to the operands.')
    g.table(['File / field','Meaning'],[
        ('sections_customary.csv: river_mile','Model station location when mapped; not the integration length.'),
        ('effective_width_ft / footprint_coverage','Accepted lateral width and its fraction of original manifest width.'),
        ('coverage / common_width_ft','Accepted-width fraction of the comparison domain and the domain width.'),
        ('control_length_ft','Selected-estimator nodal weight; half-neighbor weights for average end area.'),
        ('observed_area_change_ft2','Signed lateral area integral; model_area_change_ft2 is the modeled counterpart.'),
        ('observed_local_control_volume_yd3','Signed observed area × nodal weight ÷ 27.'),
        ('observed_cumulative_yd3','Node cumulative sum within that supported segment.'),
        ('observed_interval_prefix_yd3','Completed-reach prefix, beginning at zero in each segment.'),
        ('observed_mean_change_ft','Signed change area ÷ effective width; not a maximum local change.'),
        ('observed_lateral_std_ft','Accepted-width-weighted lateral change standard deviation.'),
        ('observed_cancellation_fraction','Opposition of gross components at the section; undefined at zero gross change.'),
        ('intervals_customary.csv: length_ft','Verified channel length for that accepted completed reach.'),
        ('upstream_weight / downstream_weight','0.5/0.5 for average end area, 1/0 upstream-held, 0/1 downstream-held.'),
        ('observed_volume_change_yd3 / residual_yd3','Completed-reach observed volume and model-minus-observed residual.'),
        ('lateral_audit_customary.csv: accepted','Whether the lateral interval contributed; reason identifies failing support.'),
        ('observed_signed_area_ft2','Accepted interval signed contribution; unsupported intervals have zero integrated contribution, not measured zero change.'),
        ('observed_second_moment_ft3','Integral of Δz² du. This is a change-distribution moment in ft³, not bed volume in yd³.'),
        ('segment_id / downstream_distance_mi','Supported-segment identity and a physical-distance companion distinct from RM.')
    ],[3.3,3.7],font=8.85)
    g.p('Most observed fields have corresponding model fields. Threshold-related fractions and gross components are '
        'also available in section/reach tables. report.json retains SI metrics and assumptions; metrics_customary.json '
        'converts dimensional metrics. Counts, correlations and fractions stay dimensionless.')
    g.p('Read explicit unit suffixes rather than assuming units from the filename alone. In the current exclusion '
        'ledger, profile-extent fields ending _u_min / _u_max have no unit suffix and retain metres, including in the customary companion.')

    g.page('Glossary and notation')
    g.table(['Term','Meaning in this workbench'],[
        ('Accepted support','Lateral intervals with finite endpoints and supported interior in every required profile/epoch.'),
        ('Bulk geometric volume','Bed-geometry volume change that includes pore space; not sediment-solid volume or transported load.'),
        ('Chainage','Downstream-increasing physical distance used for ordering and derivative calculations.'),
        ('Integration reach / date interval','An adjacent accepted XS pair / the elapsed time between baseline and target epochs; neither denotes a named HEC-RAS Reach.'),
        ('Common domain','Candidate overlap or selected transect extent before unsupported intervals are removed.'),
        ('Control length, ℓ','Nodal reconstruction weight derived from accepted neighboring reaches and the selected estimator.'),
        ('Cumulative prefix','Running sum under either the node-control or completed-reach convention, with explicit segment resets.'),
        ('Datum correction','Documented elevation addition backed by independent alignment evidence.'),
        ('Gross turnover','Erosion magnitude plus deposition magnitude between observed/model bed states.'),
        ('Mean change','Signed lateral change area divided by accepted lateral width.'),
        ('Native audit','Separate comparison against a verified RAS bed-volume output on an equivalent accounting basis.'),
        ('River mile / RM','Location from model XS stationing or explicit manifest mapping; not a substituted channel length.'),
        ('Scenario','A retained assumption experiment recomputed from the reviewed profiles.'),
        ('Spatial correlation, ρ_s','Assumed coherence of section elevation-difference errors in the conditional volume-error model.'),
        ('Temporal correlation, ρ_t','Assumed correlation of baseline and target survey elevation errors.'),
        ('Threshold','Symmetric limit for classifying change; does not delete signed or gross volume.'),
        ('Width fraction','Fraction of accepted lateral width in a local-change class; distinct from the section mean-change class.')
    ],[2.0,5.0],font=9.0)
    g.p('**Symbols:** u = lateral station; z = bed elevation; Δz = target minus baseline; ΔA = section signed change area; '
        'L = verified completed-reach length; ℓ = nodal control weight; V = volume; W = accepted lateral width; '
        'σ = one-sigma uncertainty; ρ = correlation. Default formulas use average end area unless stated otherwise.')
    g.p('**Color and line conventions:** main change and scenario comparisons use blue for model and orange for observed. '
        'Four-profile/elevation views use additional colors and styles. Concept diagrams label erosion and deposition '
        'explicitly. In time-series heatmaps, red is positive rate and blue negative. Use each legend rather than '
        'transferring one figure’s color meaning to another.')

    g.page('Version, sources and verification record')
    g.p('This guide describes **byuill/RAS → bathymetry_calibration → sunday_improvements**, '
        '**commit e43535537c5374700bb065aecd48eba98e2bbf0a**, as reviewed for guide version 1.1, 12 October 2026. '
        'Record the implementation used for each technical-review run; future changes may alter controls, definitions or exports.')
    g.p('**Revision 1.1:** six-part organization and reader routes; redesigned concept diagrams; editable equation panels; '
        'clearer node accounting, support-area estimates and conditional error assumptions. The tool implementation is unchanged.')
    g.h('Primary implementation references')
    g.table(['Source file','Guide topics checked against it'],[
        ('core.py','Matched support, signed areas, segment connectivity, estimator weights, prefixes and core metrics.'),
        ('diagnostics.py','Weighted magnitude/pattern metrics, classifications, derivatives and zone runs.'),
        ('calculation_audit.py','Exact positive/negative integrals, moments, variability, scenario support and conditional survey error.'),
        ('workflow.py / sources.py','Date alignment, readers, cache identity, native-audit gates, rate calculations, provenance and export scope.'),
        ('gui.py / calculation_gui.py / qaqc_gui.py','Workflow, current action labels, scenario controls, review decisions and table-preview limits.'),
        ('display_units.py','Exact customary conversions, river-mile selection and preservation of unedited canonical control values.'),
        ('README.md / docs/calculation-diagnostics.md','Repository operating and methodological notes.'),
        ('docs/bathymetry-native-accounting.md','Recorded project native-variable assertions; these require independent local verification.')
    ],[2.7,4.3],font=9.1)
    g.h('What was checked for this guide')
    g.p('The hand-calculated −6,500-yd³ example was reproduced by the calculation engine. The illustrative model–survey '
        'figures were generated with the tool from synthetic, fully supported profiles. Their reported shape correlation, '
        'amplitude ratio and mean-change zone agreement were numerically checked. Gross components, standard deviation, '
        'endpoint methods, gap resets, shift response, grid invariance and uncertainty intervals were verified against the engine. '
        'The project’s 81-XS range and channel-length total were '
        'read from the checked-in manifest.')
    g.p('These checks verify the examples and guide’s implementation descriptions. They do not verify the real HDF, '
        'GDB acquisition dates, datum transformations, ArcGIS licensing, native output equivalence or model adequacy for the project.')
    g.h('Model documentation to use alongside this guide')
    g.p('Use the sediment technical manual, output definitions and release notes applicable to the installed HEC-RAS '
        'version. The HEC documentation portal is https://www.hec.usace.army.mil/confluence/rasdocs. '
        'Cite the actual version and sections used to verify native variable basis and accounting.')
    g.callout('Reuse in a formal review',
        'The explanatory diagrams can accompany a methods discussion when labeled as illustrative. Replace example '
        'model–survey plots with the actual archived project outputs. Every performance conclusion should be traceable '
        'to a defined interval, sampled footprint, reconstruction method and documented assumptions.')
