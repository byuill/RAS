"""Real GIS pixel/NoData integration check, run with licensed ArcGIS Pro Python."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

import pytest

from eHydro import process_bathymetry as bathy


def test_real_geodatabase_rasters_mosaic_and_resume(tmp_path):
    arcpy = pytest.importorskip('arcpy', reason='Requires licensed ArcGIS Pro Python')
    np = pytest.importorskip('numpy')
    master = tmp_path/'ehydro_lmr_2025'
    (master/'files').mkdir(parents=True)
    sr = arcpy.SpatialReference(26915)
    datasets = [
        ('old', 'z_20250101.zip', [[1., 0.], [-9999., 3.]]),
        ('new', 'a_20251231.zip', [[9., -9999.], [-9999., 8.]]),
    ]
    with arcpy.EnvManager(overwriteOutput=False, outputCoordinateSystem=sr):
        for name, archive, values in datasets:
            gdb = tmp_path/(name+'.gdb')
            arcpy.management.CreateFileGDB(str(tmp_path), gdb.name)
            dataset = str(gdb/'Bathymetry')
            raster = arcpy.NumPyArrayToRaster(np.array(values, dtype='float32'),
                                             arcpy.Point(500000., 3300000.), 5., 5., -9999.)
            raster.save(dataset)
            del raster
            arcpy.management.DefineProjection(dataset, sr)
            arcpy.management.ClearWorkspaceCache()
            with ZipFile(master/'files'/archive, 'w', compression=ZIP_DEFLATED) as package:
                for path in gdb.rglob('*'):
                    if path.is_file() and not path.name.lower().endswith('.lock'):
                        package.write(path, str(Path(gdb.name)/path.relative_to(gdb)))
        args = bathy.parse_args([str(master)])
        assert bathy.process(args, arcpy) == 0
        result = str(master/(master.name+'.tif'))
        pixels = arcpy.RasterToNumPyArray(result, nodata_to_value=-9999.)
        np.testing.assert_array_equal(pixels, np.array([[9., 0.], [-9999., 8.]], dtype='float32'))
        assert bathy.load_state(master)['mosaic']['status'] == 'completed'
        assert bathy.process(args, arcpy) == 0
        assert len(bathy.load_state(master)['rasters']) == 2
