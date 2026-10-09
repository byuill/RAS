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


def execute(request):
    import arcpy
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
    source = request['source']
    dataset = str(Path(source['path']) / source['layer'])
    if not arcpy.Exists(dataset):
        raise ValueError(f'Geodatabase dataset does not exist: {dataset}')
    rows = []
    scale, offset = float(source['z_scale_to_m']), float(source['z_offset_m'])
    if source['kind'] == 'gdb_raster':
        if source.get('sampling', 'nearest') != 'nearest':
            raise ValueError('Starter ArcPy raster adapter supports explicitly labelled nearest-cell sampling only.')
        analysis_sr = spatial_reference(arcpy, request['analysis_crs'])
        raster_sr = arcpy.Describe(dataset).spatialReference
        if not raster_sr or raster_sr.name == 'Unknown':
            raise ValueError('Raster has no known horizontal CRS.')
        transformation = source.get('horizontal_transformation', '')
        if analysis_sr.GCS.name != raster_sr.GCS.name and not transformation:
            raise ValueError('Different horizontal datums require an explicit ArcPy transformation.')
        for knot in request['knots']:
            point = arcpy.PointGeometry(arcpy.Point(knot['x_m'], knot['y_m']), analysis_sr)
            point = point.projectAs(raster_sr, transformation) if transformation else point.projectAs(raster_sr)
            value = arcpy.management.GetCellValue(dataset, f'{point.firstPoint.X} {point.firstPoint.Y}', '1').getOutput(0)
            raw = None if value.strip().lower() in ('nodata', 'no data', '') else float(value)
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
    else:
        raise ValueError('Unsupported geodatabase source kind.')
    if not rows:
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
