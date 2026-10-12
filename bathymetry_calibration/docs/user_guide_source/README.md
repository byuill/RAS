# Rebuilding and reviewing the user guide

These are the editable manuscript, document layout, scientific diagram sources,
and numerical checks for guide version 1.1. The published files are one directory
above this folder. The described tool implementation is `e435355`; the guide
revision number is independent of the tool version.

From a RAS checkout, use its Python 3.12 scientific environment and install the
additional document dependencies:

```bash
python -m pip install -r requirements.txt
python -m pip install -r bathymetry_calibration/docs/user_guide_source/requirements-docs.txt
python bathymetry_calibration/docs/user_guide_source/verify_guide_examples.py
python bathymetry_calibration/docs/user_guide_source/make_figures.py
python bathymetry_calibration/docs/user_guide_source/build_guide.py
```

The default output folder is `user_guide_source/build/`, which is ignored by Git.
Set the `BATHY_GUIDE_OUTPUT` environment variable to use another directory. Figure
generation writes illustrative inputs, PNGs at 300 dpi, SVGs, and checked example
values there. It uses the installed checkout's calculation engine; it needs no
project HDF, survey geodatabase, ArcGIS license, or network access. Synthetic HDF
files are explicitly labeled as synthetic and contain only illustrative data.

Convert the generated Word file to PDF using Word's PDF export or LibreOffice:

```bash
soffice --headless --convert-to pdf --outdir bathymetry_calibration/docs/user_guide_source/build bathymetry_calibration/docs/user_guide_source/build/Bathymetry_Calibration_User_Guide.docx
python bathymetry_calibration/docs/user_guide_source/inspect_document.py
```

If using a different output folder, use its paths in the PDF conversion command.
`inspect_document.py` checks the 36-page layout, contents links, six-part outline,
section destinations, diagram alt text, and page edges. It renders every page and
a contact sheet in `qa/`. Page layout depends on available fonts and the Word/PDF
renderer. Inspect the full-size pages and figures before publishing; automated
checks cannot detect overlapping labels inside a diagram. Update the layout and
contents together if a renderer causes overflow.

`verify_guide_examples.py` checks zero-crossing integration, moments and
cancellation, endpoint-method volumes, disconnected segments, survey shifts,
grid invariance, uncertainty intervals, and undefined significance cases against
the package. `make_figures.py` additionally checks the hand-calculated cumulative
curves and the illustrative model–survey metrics. These checks verify the guide's
examples and implementation descriptions, rather than project data or model
adequacy.

`verification_record.json` records the published revision's example results,
navigation/layout checks, and SHA-256 hashes of the Word and PDF artifacts.
Refresh that record when publishing a rebuilt revision.

Edit prose in `guide_content.py`, typography/navigation in `build_guide.py`, and
diagrams in `make_figures.py`. Keep source examples and captions explicit about
accepted support, units, reconstruction assumptions, and conditional uncertainty.
After numerical, structural, and visual review, copy the generated `.docx` and
`.pdf` to `bathymetry_calibration/docs/`. Generated figures and QA records need
not be committed.
