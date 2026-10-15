"""Extract eHydro ZIPs, collect bathymetry in a file GDB, and create a GeoTIFF.

Run with ArcGIS Pro's Python, not the workbench virtual environment. Only the
standard library and ArcPy are required. See POSTPROCESSING.md for examples.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fnmatch import fnmatchcase
import hashlib
import json
import math
import ntpath
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import threading
import time
import uuid
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile


TOOL = 'ras-ehydro-bathymetry'
EXTRACTED = 'bathymetry_extracted'
STATE = 'bathymetry_processing.json'
EXCLUDED = re.compile(r'hillshade|slope|aspect|intensity|uncertainty|stddev|density|mask|rgb|quality', re.I)
BATHY = re.compile(r'bathy|elev|terrain|depth|(?:^|_)(?:dem|dtm|mb|sb)(?:_|$)', re.I)


def log(message):
    print(f'[{time.strftime("%H:%M:%S")}] {message}', flush=True)


def gp(label, function, *args, **kwargs):
    """ArcPy stays on the main thread; a logger reports long-running operations."""
    log(label)
    started, stopped = time.monotonic(), threading.Event()

    def heartbeat():
        while not stopped.wait(30):
            log(f'  Still working: {label} ({time.monotonic()-started:,.0f} s elapsed)')

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        result = function(*args, **kwargs)
        log(f'  Finished in {time.monotonic()-started:,.1f} s')
        return result
    finally:
        stopped.set()
        thread.join()


def replace_file(source, target):
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.05 * 2**attempt)


def write_json(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
        replace_file(temporary, path)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def load_state(master):
    chosen, newest = None, ''
    for path in [master/STATE, *master.glob('bathymetry-processing-recovery-*.json')]:
        if not path.exists():
            continue
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            if state.get('tool') != TOOL or state.get('version') != 1:
                raise ValueError(f'Unrecognized processing report: {path}')
            if state.get('saved_at_utc', '') >= newest:
                chosen, newest = state, state.get('saved_at_utc', '')
        except (ValueError, OSError, AttributeError):
            if path.name == STATE:
                raise
    return chosen


def save_state(master, state):
    state['saved_at_utc'] = datetime.now(timezone.utc).isoformat()
    try:
        write_json(master/STATE, state)
    except PermissionError:
        recovery = master/f'bathymetry-processing-recovery-{uuid.uuid4().hex}.json'
        write_json(recovery, state)
        log(f'WARNING: {STATE} is locked; saved progress to {recovery.name}.')


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def archives_in(master):
    result = []
    for directory, folders, names in os.walk(master):
        folders[:] = [name for name in folders if name != EXTRACTED and not name.lower().endswith('.gdb')
                      and not name.startswith('bathy_work_')]
        result.extend(Path(directory)/name for name in names if name.lower().endswith('.zip'))
    return sorted(result, key=lambda path: str(path.relative_to(master)).casefold())


def safe_member(name):
    normalized = name.replace('\\', '/')
    path = PurePosixPath(normalized)
    if (not normalized or path.is_absolute() or ntpath.splitdrive(normalized)[0]
            or any(part in {'..', '.'} or ':' in part for part in path.parts)):
        raise ValueError(f'Unsafe ZIP member: {name!r}')
    return path


def extract_archive(archive, master, digest):
    root = master/EXTRACTED
    root.mkdir(exist_ok=True)
    destination = root/digest[:20]
    with ZipFile(archive) as package:
        members = package.infolist()
        paths = []
        seen = set()
        for member in members:
            path = safe_member(member.filename)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError(f'Symlinks are not supported in ZIPs: {member.filename}')
            key = str(path).casefold()
            if key in seen:
                raise ValueError(f'Duplicate/case-colliding ZIP member: {member.filename}')
            seen.add(key)
            paths.append(path)
        if destination.exists():
            marker = destination/'.extraction.json'
            if (marker.exists() and json.loads(marker.read_text()).get('sha256') == digest
                    and all(member.is_dir() or ((destination/path).is_file()
                            and (destination/path).stat().st_size == member.file_size)
                            for member, path in zip(members, paths))):
                log(f'  Already extracted: {archive.name}')
                return destination
            raise RuntimeError(f'Existing extracted input is incomplete or changed; preserve/move it aside and rerun: {destination}')
        required = sum(member.file_size for member in members)
        if shutil.disk_usage(master).free < required:
            raise RuntimeError(f'Not enough free disk space to extract {archive.name} ({required/1024**3:.2f} GiB).')
        temporary = Path(tempfile.mkdtemp(prefix='.unpack-', dir=root))
        try:
            done, last_percent = 0, -1
            for member, path in zip(members, paths):
                target = temporary/path
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as source, target.open('xb') as output:
                    for block in iter(lambda: source.read(1024*1024), b''):
                        output.write(block)  # ZipFile checks the member CRC while reading.
                        done += len(block)
                        percent = int(100*done/max(1, required))
                        if percent//20 > last_percent//20:
                            log(f'  Extracting: {percent}% ({done/1024**2:,.1f} MiB)')
                            last_percent = percent
            write_json(temporary/'.extraction.json', {'sha256': digest, 'archive': archive.name})
            replace_file(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return destination


def raster_info(arcpy, path):
    description, raster = arcpy.Describe(str(path)), arcpy.Raster(str(path))
    try:
        sr = description.spatialReference
        if not sr or sr.name in {'Unknown', ''}:
            raise ValueError(f'Raster has no known horizontal CRS: {path}')
        vcs = getattr(sr, 'VCS', None)
        extent = raster.extent
        return dict(path=str(path), bands=int(raster.bandCount), pixel_type=raster.pixelType,
                    width=int(raster.width), height=int(raster.height), cell_width=float(raster.meanCellWidth),
                    cell_height=float(raster.meanCellHeight), crs=sr.name, crs_wkt=sr.exportToString(),
                    vertical_crs=vcs.name if vcs and vcs.name not in {'Unknown', ''} else None,
                    extent=[extent.XMin, extent.YMin, extent.XMax, extent.YMax])
    finally:
        del raster, description


def select_rasters(arcpy, paths, patterns):
    selected, eligible, inventory = [], [], []
    for path in sorted(paths, key=lambda p: str(p).casefold()):
        info = raster_info(arcpy, path)
        name = Path(path).name
        info['selected'] = False
        if info['bands'] != 1:
            info['reason'] = 'Not single band'
        elif patterns:
            info['selected'] = any(fnmatchcase(name.lower(), pattern.lower()) for pattern in patterns)
            info['reason'] = 'Explicit name pattern' if info['selected'] else 'Name did not match'
        elif EXCLUDED.search(name):
            info['reason'] = 'Ancillary raster name (hillshade/slope/quality/etc.)'
        else:
            eligible.append(info)
            info['selected'] = bool(BATHY.search(name))
            info['reason'] = 'Bathymetry/elevation raster name' if info['selected'] else 'Unclassified raster name'
        inventory.append(info)
    selected = [item for item in inventory if item['selected']]
    if not patterns and not selected and len(eligible) == 1:
        eligible[0].update(selected=True, reason='Only eligible single-band raster')
        selected = eligible
    if not patterns and not selected and len(eligible) > 1:
        raise ValueError('Multiple unclassified rasters; use --raster-pattern to identify the bathymetry: '
                         +', '.join(Path(item['path']).name for item in eligible))
    for item in inventory:
        log(f'  Raster {Path(item["path"]).name}: {"SELECTED" if item["selected"] else "excluded"} '
            f'({item["reason"]}; {item["crs"]}; {item["bands"]} band(s))')
    return selected, inventory


def archive_date(archive, download_report):
    dates = []
    for survey in download_report.get('surveys', []):
        url, date = survey.get('sourcedatalocation'), survey.get('surveydatestart')
        if not url or not date:
            continue
        # Same deterministic name as the downloader, without importing requests.
        leaf = unquote(urlsplit(url).path.rsplit('/', 1)[-1]) or 'survey-data'
        leaf = re.sub(r'[^A-Za-z0-9._-]', '_', leaf)[-120:].strip('.') or 'survey-data'
        filename = hashlib.sha256(url.encode()).hexdigest()[:24]+'_'+leaf
        if archive.name not in {filename, leaf}:
            continue
        try:
            parsed = datetime.fromisoformat(str(date).replace('Z', '+00:00'))
            dates.append(parsed.date().isoformat())
        except ValueError:
            continue
    if dates:
        return max(dates), 'download manifest'
    match = re.search(r'_(\d{8})(?:_|$)', archive.stem)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y%m%d').date().isoformat(), 'archive filename'
        except ValueError:
            pass
    return '', 'unknown (lexical archive order)'


def download_manifest(master):
    reports = []
    for path in [master/'manifest.json', *master.glob('manifest-recovery-*.json')]:
        if not path.exists():
            continue
        try:
            report = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(report, dict) and isinstance(report.get('surveys'), list):
                reports.append((report.get('saved_at_utc', ''), report))
        except (ValueError, OSError) as exc:
            log(f'WARNING: Cannot read downloader dates in {path.name}: {exc}')
    return max(reports, key=lambda item: item[0])[1] if reports else {}


def select_tins(arcpy, paths):
    eligible = [path for path in sorted(paths) if not EXCLUDED.search(path.name)]
    selected = [path for path in eligible if BATHY.search(path.name)]
    if not selected:
        if len(eligible) > 1:
            raise ValueError('Multiple unclassified TINs; inspect/isolate the bathymetry TINs before conversion: '
                             +', '.join(path.name for path in eligible))
        selected = eligible
    result = []
    for path in selected:
        sr = arcpy.Describe(str(path)).spatialReference
        vcs = getattr(sr, 'VCS', None)
        result.append((path, 'tin', vcs.name if vcs and vcs.name not in {'Unknown', ''} else None))
    return result


def datum_key(sr):
    gcs = sr.GCS
    return getattr(gcs, 'factoryCode', 0) or gcs.name.casefold()


def same_crs(left, right):
    # Geodatabase storage can change the XY-domain suffix without changing CRS.
    left_code, right_code = getattr(left, 'factoryCode', 0), getattr(right, 'factoryCode', 0)
    if left_code and right_code:
        return left_code == right_code
    return left.exportToString().split(';')[0] == right.exportToString().split(';')[0]


def normalize(arcpy, source, kind, target, output_sr, args, scratch, snap):
    description = arcpy.Describe(str(source))
    source_sr = description.spatialReference
    if not source_sr or source_sr.name in {'Unknown', ''}:
        raise ValueError(f'Unknown source CRS: {source}')
    if datum_key(source_sr) != datum_key(output_sr) and not args.geographic_transformation:
        raise ValueError(f'Horizontal datums differ for {source}; specify --geographic-transformation. '
                         f'Available: {arcpy.ListTransformations(source_sr, output_sr)}')
    floating = str(scratch/'float_input')
    if arcpy.Exists(floating):
        arcpy.management.Delete(floating)
    if kind == 'tin':
        if source_sr.type != 'Projected':
            raise ValueError(f'TIN conversion requires a projected source CRS: {source}')
        license_status = arcpy.CheckExtension('3D')
        if license_status not in {'Available', 'CheckedOut'}:
            raise RuntimeError('3D Analyst is required for --tin-to-raster. Existing rasters do not need this extension.')
        checked_out_here = license_status == 'Available'
        if checked_out_here and arcpy.CheckOutExtension('3D') != 'CheckedOut':
            raise RuntimeError('Could not check out the 3D Analyst license for TIN conversion.')
        try:
            spacing = args.cell_size*output_sr.metersPerUnit/source_sr.metersPerUnit
            gp('  Convert bathymetry TIN to a floating-point raster', arcpy.ddd.TinRaster,
               str(source), floating, data_type='FLOAT', method='LINEAR',
               sample_distance=f'CELLSIZE {spacing:.12g}', z_factor=1)
        finally:
            if checked_out_here:
                arcpy.CheckInExtension('3D')
    else:
        gp('  Read raster as 32-bit floating point', arcpy.management.CopyRaster,
           str(source), floating, pixel_type='32_BIT_FLOAT')
    del description
    with arcpy.EnvManager(snapRaster=snap or '', cellSize=args.cell_size):
        if same_crs(source_sr, output_sr):
            gp('  Align raster to the common output grid', arcpy.management.Resample,
               floating, str(target), args.cell_size, 'BILINEAR')
        else:
            gp('  Project raster to the common output grid', arcpy.management.ProjectRaster,
               floating, str(target), output_sr, resampling_type='BILINEAR', cell_size=args.cell_size,
               geographic_transform=args.geographic_transformation or '')
    arcpy.management.Delete(floating)


def valid_output(arcpy, path, output_sr, cell_size):
    info = raster_info(arcpy, path)
    if (info['bands'] != 1 or info['pixel_type'] != 'F32' or info['width'] < 1 or info['height'] < 1
            or not math.isclose(info['cell_width'], cell_size, rel_tol=1e-5)
            or not math.isclose(info['cell_height'], cell_size, rel_tol=1e-5)
            or not same_crs(arcpy.Describe(str(path)).spatialReference, output_sr)):
        raise ValueError(f'Output raster does not match the requested single-band grid/CRS: {path}')
    if str(arcpy.management.GetRasterProperties(str(path), 'ALLNODATA').getOutput(0)) == '1':
        raise ValueError(f'Raster contains only NoData: {path}')
    return info


def mosaic(arcpy, master, sources, output_sr, args, state):
    sources.sort(key=lambda item: (item['date'], item['archive'].casefold(), item['source'].casefold()))
    paths = [item['output'] for item in sources]
    signature = hashlib.sha256(json.dumps([item['key'] for item in sources]).encode()).hexdigest()
    final = master/(master.name+'.tif')
    previous = state.get('mosaic', {})
    if arcpy.Exists(str(final)):
        if previous.get('status') == 'completed' and previous.get('signature') == signature and not args.rebuild:
            valid_output(arcpy, final, output_sr, args.cell_size)
            log(f'Already mosaicked and grid checked: {final}')
            return final
        if not args.rebuild or previous.get('path') != final.name:
            raise RuntimeError(f'Mosaic exists with different/unfinished inputs. Preserve it or use --rebuild: {final}')
    extent = [item['info']['extent'] for item in sources]
    cols = math.ceil((max(e[2] for e in extent)-min(e[0] for e in extent))/args.cell_size)
    rows = math.ceil((max(e[3] for e in extent)-min(e[1] for e in extent))/args.cell_size)
    cells = rows*cols
    log(f'Mosaic grid: approximately {rows:,} rows × {cols:,} columns; {cells:,} cells '
        f'({cells*4/1024**3:,.2f} GiB uncompressed), {shutil.disk_usage(master).free/1024**3:,.1f} GiB free.')
    if cells > args.max_cells:
        raise RuntimeError('Mosaic exceeds --max-cells. Choose a coarser --cell-size or explicitly increase the limit.')
    known_vcs = {item['vertical_crs'] for item in sources if item.get('vertical_crs')}
    if len(known_vcs) > 1:
        raise ValueError(f'Conflicting source vertical CRSs; normalize the vertical reference before mosaicking: {sorted(known_vcs)}')
    if any(not item.get('vertical_crs') for item in sources):
        log('WARNING: Some sources have no vertical CRS metadata. Z values are preserved; '
            'confirm consistent elevation/depth meaning, units and datum before using the mosaic.')
    for index, item in enumerate(sources, 1):
        log(f'  Mosaic order {index}/{len(sources)}: {item["date"] or "date unknown"} — {Path(item["output"]).name}')
    temporary = master/f'bathy_mosaic_work_{uuid.uuid4().hex[:12]}.tif'
    state['mosaic'] = dict(path=final.name, signature=signature, status='creating',
                           overlap=args.overlap, inputs=paths, temporary=temporary.name)
    save_state(master, state)
    with arcpy.EnvManager(snapRaster=paths[0], compression='LZW'):
        gp(f'Mosaic {len(paths)} raster(s) to GeoTIFF ({args.overlap} overlap)', arcpy.management.MosaicToNewRaster,
           input_rasters=paths, output_location=str(master), raster_dataset_name_with_extension=temporary.name,
           coordinate_system_for_the_raster=output_sr, pixel_type='32_BIT_FLOAT', cellsize=args.cell_size,
           number_of_bands=1, mosaic_method=args.overlap, mosaic_colormap_mode='FIRST')
    valid_output(arcpy, temporary, output_sr, args.cell_size)
    if arcpy.Exists(str(final)):
        backup = master/f'{master.name}_previous_{uuid.uuid4().hex[:8]}.tif'
        gp(f'Preserve previous mosaic as {backup.name}', arcpy.management.Rename,
           str(final), str(backup), 'RasterDataset')
    gp(f'Publish completed mosaic: {final.name}', arcpy.management.Rename, str(temporary), str(final), 'RasterDataset')
    state['mosaic'].update(status='completed', info=valid_output(arcpy, final, output_sr, args.cell_size))
    save_state(master, state)
    return final


def process(args, arcpy):
    master = args.master.expanduser().resolve()
    if not master.is_dir():
        raise ValueError(f'Master directory does not exist: {master}')
    output_gdb = master/(master.name+'.gdb')
    state = load_state(master)
    if state is None:
        if not args.inventory_only and (arcpy.Exists(str(output_gdb)) or arcpy.Exists(str(master/(master.name+'.tif')))):
            raise ValueError('A matching output GDB/TIFF exists without this script\'s processing report; preserving it.')
        state = dict(tool=TOOL, version=1, rasters={}, archives={})
    if (not args.inventory_only and arcpy.Exists(str(output_gdb))
            and state.get('owned_gdb') != output_gdb.name):
        raise ValueError(f'Output geodatabase is not recorded as created by this script; preserving it: {output_gdb}')
    output_sr = arcpy.SpatialReference(int(args.output_crs.split(':')[-1]) if args.output_crs.upper().startswith(('EPSG:', 'ESRI:'))
                                       or args.output_crs.isdigit() else args.output_crs)
    if output_sr.type != 'Projected':
        raise ValueError('--output-crs must be a known projected coordinate system.')
    config = dict(crs=output_sr.exportToString(), cell_size=args.cell_size, overlap=args.overlap,
                  transformation=args.geographic_transformation, tin_to_raster=args.tin_to_raster)
    config_key = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    state['config'] = config
    save_state(master, state)
    archives = archives_in(master)
    if not archives:
        raise ValueError('No ZIP archives were found under the master directory.')
    log(f'Found {len(archives)} ZIP archive(s). Output: {output_gdb}, {master.name}.tif')
    log(f'Output grid: {args.cell_size:g} {output_sr.linearUnitName}; {output_sr.name}. Z values will not be converted.')
    download_report = download_manifest(master)
    scratch_root = Path(tempfile.mkdtemp(prefix='bathy_work_', dir=master))
    scratch = scratch_root/'work.gdb'
    inputs, failures, skipped = [], [], []
    try:
        if not args.inventory_only:
            if not arcpy.Exists(str(output_gdb)):
                state['owned_gdb'] = output_gdb.name
                save_state(master, state)
                gp('Create destination geodatabase', arcpy.management.CreateFileGDB, str(master), output_gdb.name)
            gp('Create temporary processing workspace', arcpy.management.CreateFileGDB, str(scratch_root), scratch.name)
        with arcpy.EnvManager(overwriteOutput=False, extent=None, mask=None, snapRaster=None,
                              cellSize=None, outputCoordinateSystem=None, geographicTransformations=None):
            for number, archive in enumerate(archives, 1):
                log(f'Archive {number}/{len(archives)}: {archive.name} — hashing and extracting')
                relative = str(archive.relative_to(master))
                try:
                    digest = file_hash(archive)
                    extracted = extract_archive(archive, master, digest)
                    rasters, tins = [], []
                    for directory, _, names in arcpy.da.Walk(str(extracted), datatype=['RasterDataset', 'Tin']):
                        for name in names:
                            path = Path(directory)/name
                            kind = arcpy.Describe(str(path)).dataType
                            if kind == 'RasterDataset' and any(p.name.lower().endswith('.gdb') for p in path.parents):
                                rasters.append(path)
                            elif kind.lower() == 'tin':
                                tins.append(path)
                    selected, inventory = select_rasters(arcpy, rasters, args.raster_pattern)
                    sources = [(Path(item['path']), 'raster', item.get('vertical_crs')) for item in selected]
                    if not sources and args.tin_to_raster:
                        sources = select_tins(arcpy, tins)
                    state['archives'][relative] = dict(sha256=digest, extracted=str(extracted.relative_to(master)),
                                                      inventory=inventory, tins=[str(p) for p in tins])
                    if not sources:
                        reason = f'No selected bathymetry raster ({len(tins)} TIN(s) present; --tin-to-raster enables conversion).'
                        log('  SKIPPED: '+reason)
                        skipped.append(dict(archive=relative, reason=reason))
                    date, date_source = archive_date(archive, download_report)
                    for source_number, (source, kind, vertical_crs) in enumerate(sources, 1):
                        log(f'  Selected {kind} {source_number}/{len(sources)}: {source.name}')
                        if args.inventory_only:
                            continue
                        key = hashlib.sha256((digest+str(source.relative_to(extracted))+config_key).encode()).hexdigest()
                        name = arcpy.ValidateTableName(f'bathy_{archive.stem[:36]}_{key[:12]}', str(output_gdb))
                        target = output_gdb/name
                        previous = state['rasters'].get(key)
                        if arcpy.Exists(str(target)) and previous is None:
                            raise RuntimeError(f'Unrecorded output raster exists; preserving it: {target}')
                        if previous and previous.get('status') == 'completed' and arcpy.Exists(str(target)):
                            info = valid_output(arcpy, target, output_sr, args.cell_size)
                            log(f'  Already copied and grid checked: {name}')
                        else:
                            state['rasters'][key] = dict(source=str(source), output=str(target), status='creating',
                                                         archive=relative, date=date, date_source=date_source, kind=kind)
                            save_state(master, state)
                            if arcpy.Exists(str(target)):
                                gp('  Remove this script\'s incomplete raster copy', arcpy.management.Delete, str(target))
                            normalize(arcpy, source, kind, target, output_sr, args, scratch, inputs[0]['output'] if inputs else None)
                            info = valid_output(arcpy, target, output_sr, args.cell_size)
                            state['rasters'][key].update(status='completed', info=info)
                            save_state(master, state)
                        record = dict(key=key, source=str(source), output=str(target), archive=relative,
                                      date=date, vertical_crs=vertical_crs, info=info)
                        if not any(item['key'] == key for item in inputs):
                            inputs.append(record)
                except Exception as exc:
                    message = str(exc)
                    if hasattr(arcpy, 'GetMessages'):
                        message += '\n'+arcpy.GetMessages(2)
                    log('  FAILED: '+message)
                    failures.append(dict(archive=relative, error=message))
                state.update(failures=failures, skipped=skipped, copied_current_run=len(inputs))
                save_state(master, state)
            if args.inventory_only:
                log(f'Inventory complete. Report: {master/STATE}. No rasters copied or mosaicked.')
                return 1 if failures else 0
            if failures and not args.allow_partial:
                raise RuntimeError(f'{len(failures)} archive(s) failed. Copies are retained; fix errors and rerun. '
                                   '--allow-partial explicitly permits a mosaic of successful copies.')
            if not inputs:
                raise RuntimeError('No bathymetry rasters were copied. Inspect the report; consider --tin-to-raster or --raster-pattern.')
            result = mosaic(arcpy, master, inputs, output_sr, args, state)
            log(f'COMPLETE: {len(inputs)} raster(s) in {output_gdb}; {len(skipped)} archive(s) skipped; '
                f'{len(failures)} archive(s) failed. Mosaic: {result}')
            return 1 if failures else 0
    finally:
        arcpy.management.ClearWorkspaceCache()
        try:
            shutil.rmtree(scratch_root)
        except OSError:
            log(f'WARNING: Temporary workspace is still locked; remove it after ArcGIS releases it: {scratch_root}')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('master', type=Path, help='Master download folder, e.g. E:\\LMR\\ehydro_lmr_2025')
    parser.add_argument('--cell-size', type=float, default=5., help='Output grid spacing in output-CRS units (default: 5 metres).')
    parser.add_argument('--output-crs', default='EPSG:26915', help='Projected CRS, EPSG/ESRI code or .prj path (default: NAD83 / UTM zone 15N).')
    parser.add_argument('--geographic-transformation', help='Explicit ArcGIS transformation when horizontal datums differ.')
    parser.add_argument('--raster-pattern', action='append', help='Repeatable raster-name wildcard, e.g. "*Bathymetry*"; underscores are literal.')
    parser.add_argument('--tin-to-raster', action='store_true', help='Convert package TINs when no bathymetry raster is selected; requires 3D Analyst.')
    parser.add_argument('--overlap', choices=['LAST', 'FIRST', 'MEAN', 'MINIMUM', 'MAXIMUM'], default='LAST',
                        help='Overlap rule; inputs are oldest to newest where dates are known (default: LAST).')
    parser.add_argument('--inventory-only', action='store_true', help='Extract and report datasets without creating a GDB or mosaic.')
    parser.add_argument('--allow-partial', action='store_true', help='Permit a mosaic even if some archive processing fails.')
    parser.add_argument('--rebuild', action='store_true', help='Rebuild an owned mosaic, retaining the previous TIFF as a backup.')
    parser.add_argument('--max-cells', type=int, default=10_000_000_000, help='Maximum rectangular mosaic grid cells before requiring a coarser grid/explicit higher limit.')
    args = parser.parse_args(argv)
    if not math.isfinite(args.cell_size) or args.cell_size <= 0 or args.max_cells <= 0:
        parser.error('--cell-size and --max-cells must be positive and finite')
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        import arcpy
    except ImportError:
        print('Run this script with ArcGIS Pro Python (propy.bat). ArcPy is required to read/write geodatabase rasters.', file=sys.stderr)
        return 1
    try:
        return process(args, arcpy)
    except Exception as exc:
        log('FAILED: '+str(exc))
        if hasattr(arcpy, 'GetMessages'):
            messages = arcpy.GetMessages(2)
            if messages:
                log(messages)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
