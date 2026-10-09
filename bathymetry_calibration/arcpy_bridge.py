"""Standalone stdlib + ArcPy subprocess adapter. Never edit source geodatabases."""
import json
from pathlib import Path
import sys


def spatial_reference(arcpy, text):
    sr = arcpy.SpatialReference(int(text.split(':')[1])) if text.upper().startswith('EPSG:') else arcpy.SpatialReference()
    if not text.upper().startswith('EPSG:'):
        sr.loadFromString(text)
    if sr.type != 'Projected' or abs(sr.metersPerUnit - 1.0) > 1e-9:
        raise ValueError('Analysis CRS must be projected with metre horizontal units.')
    return sr


def sample_raster_batch(arcpy, dataset, knots, analysis_sr, raster_sr, transformation, sampling):
    """Sample a raster at many XY points with one ExtractValuesToPoints call; None = NoData."""
    arcpy.CheckOutExtension('Spatial')
    try:
        fc = arcpy.management.CreateFeatureclass('in_memory', 'xs_pts', 'POINT', spatial_reference=analysis_sr)
        arcpy.management.AddField(fc, 'pid', 'LONG')
        with arcpy.da.InsertCursor(fc, ['SHAPE@XY', 'pid']) as cursor:
            for i, knot in enumerate(knots):
                cursor.insertRow([(knot['x_m'], knot['y_m']), i])
        if analysis_sr.name != raster_sr.name:
            projected = 'in_memory\\xs_pts_proj'
            arcpy.management.Project(fc, projected, raster_sr, transformation or '')
            fc = projected
        out_fc = 'in_memory\\xs_pts_vals'
        arcpy.sa.ExtractValuesToPoints(fc, dataset, out_fc,
                                       'INTERPOLATE' if sampling == 'bilinear' else 'NONE', 'VALUE_ONLY')
        values = [None] * len(knots)
        with arcpy.da.SearchCursor(out_fc, ['pid', 'RASTERVALU']) as cursor:
            for pid, value in cursor:
                if value is not None and value > -9990:
                    values[pid] = float(value)
        return values
    finally:
        arcpy.CheckInExtension('Spatial')


def execute(request):
    import arcpy
    arcpy.env.workspace = "in_memory"
    arcpy.env.scratchWorkspace = "in_memory"
    try:
        arcpy.SetLogHistory(False)
    except:
        pass
    try:
        arcpy.env.logHistory = False
    except:
        pass
    if request['operation'] == 'inventory':
        items = []
        for directory, _, names in arcpy.da.Walk(request['gdb'], datatype=['FeatureClass', 'RasterDataset']):
            for name in names:
                path = str(Path(directory) / name)
                description = arcpy.Describe(path)
                items.append({'name': str(Path(path).relative_to(request['gdb'])),
                              'type': description.dataType,
                              'fields': [f.name for f in arcpy.ListFields(path)] if description.dataType != 'RasterDataset' else []})
        return items
    elif request['operation'] == 'fingerprint':
        source = request['source']
        dataset = str(Path(source['path']) / source['layer'])
        if not arcpy.Exists(dataset):
            raise ValueError(f'Geodatabase dataset does not exist: {dataset}')
        desc = arcpy.Describe(dataset)
        if desc.dataType == 'RasterDataset':
            try:
                mean = float(arcpy.management.GetRasterProperties(dataset, 'MEAN').getOutput(0))
            except Exception:
                mean = 0.0
            return {'path': dataset, 'layer': source['layer'], 'type': 'raster', 'mean': mean}
        else:
            return {'path': dataset, 'layer': source['layer'], 'type': desc.dataType, 'count': int(arcpy.management.GetCount(dataset).getOutput(0))}

    source = request['source']
    dataset = str(Path(source['path']) / source['layer'])
    if not arcpy.Exists(dataset):
        raise ValueError(f'Geodatabase dataset does not exist: {dataset}')
    rows = []
    scale, offset = float(source['z_scale_to_m']), float(source['z_offset_m'])
    if source['kind'] == 'gdb_raster':
        sampling = source.get('sampling', 'nearest')
        if sampling not in ('nearest', 'bilinear'):
            raise ValueError('Raster sampling must be nearest or bilinear.')
            
        analysis_sr = spatial_reference(arcpy, request['analysis_crs'])
        raster_sr = arcpy.Describe(dataset).spatialReference
        if not raster_sr or raster_sr.name == 'Unknown':
            raise ValueError('Raster has no known horizontal CRS.')
        transformation = source.get('horizontal_transformation', '')
        if analysis_sr.GCS.name != raster_sr.GCS.name and not transformation:
            raise ValueError('Different horizontal datums require an explicit ArcPy transformation.')
            
        knots = request['knots']
        values = None
        try:
            values = sample_raster_batch(arcpy, dataset, knots, analysis_sr, raster_sr, transformation, sampling)
        except Exception as exc:
            sys.stderr.write(f'Batch raster sampling failed ({exc}); falling back to per-point sampling.\n')
        if values is None:
            values = []
            for knot in knots:
                point = arcpy.PointGeometry(arcpy.Point(knot['x_m'], knot['y_m']), analysis_sr)
                point = point.projectAs(raster_sr, transformation) if transformation else point.projectAs(raster_sr)
                value = arcpy.management.GetCellValue(dataset, f'{point.firstPoint.X} {point.firstPoint.Y}', '1').getOutput(0)
                values.append(None if value.strip().lower() in ('nodata', 'no data', '') else float(value))
        for knot, raw in zip(knots, values):
            rows.append({'xs_id': knot['xs_id'], 'u_m': knot['u_m'],
                         'z_m': None if raw is None else raw * scale + offset})
    elif source['kind'] == 'gdb_points':
        if source.get('transect_station_mapping_verified') is not True:
            raise ValueError('SB points require verified cross-section IDs and lateral station mapping; XY nearest matching is not assumed.')
        fields = source['fields']
        names = [fields['xs_id'], fields['u'], fields['z']]
        available = {f.name for f in arcpy.ListFields(dataset)}
        if not set(names) <= available:
            raise ValueError(f'Required SB fields absent: {set(names)-available}')
        selected = {k['xs_id'] for k in request['knots']}
        with arcpy.da.SearchCursor(dataset, names) as cursor:
            for xs_id, u, z in cursor:
                if str(xs_id) in selected:
                    if u is None:
                        raise ValueError('SB point has no lateral station.')
                    rows.append({'xs_id': str(xs_id), 'u_m': float(u) * float(source['u_scale_to_m']),
                                 'z_m': None if z is None else float(z) * scale + offset})
    elif source['kind'] == 'gdb_points_raw':
        # New mode: extract all (x,y,z) for spatial mapping in python
        elevation_field = source.get('elevation_field', 'Elevation')
        available = {f.name for f in arcpy.ListFields(dataset)}
        if elevation_field not in available:
            if 'Z' in available:
                elevation_field = 'Z'
            else:
                raise ValueError(f'Required SB elevation field {elevation_field} absent.')
        
        raster_sr = arcpy.Describe(dataset).spatialReference
        analysis_sr = spatial_reference(arcpy, request['analysis_crs'])
        transformation = source.get('horizontal_transformation', '')

        with arcpy.da.SearchCursor(dataset, ['SHAPE@XY', elevation_field]) as cursor:
            for shape, z in cursor:
                if shape and z is not None:
                    pt = arcpy.PointGeometry(arcpy.Point(shape[0], shape[1]), raster_sr)
                    if raster_sr.name != analysis_sr.name:
                        pt = pt.projectAs(analysis_sr, transformation) if transformation else pt.projectAs(analysis_sr)
                    rows.append({'x_m': pt.firstPoint.X, 'y_m': pt.firstPoint.Y, 'z_m': float(z) * scale + offset})
    else:
        raise ValueError('Unsupported geodatabase source kind.')
    if not rows and source['kind'] != 'gdb_points_raw':
        raise ValueError('No survey points matched the selected model cross sections.')
    return rows


if __name__ == '__main__':
    try:
        request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        result = execute(request)
        Path(sys.argv[2]).write_text(json.dumps({'result': result}, allow_nan=False), encoding='utf-8')
    except Exception as exc:
        Path(sys.argv[2]).write_text(json.dumps({'error': str(exc)}), encoding='utf-8')
        raise SystemExit(1)