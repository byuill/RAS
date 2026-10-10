"""Direct raster sampling on fixed transects; NoData is never filled or downgraded."""
import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform
from rasterio.windows import Window

from .core import CalibrationError
from .qaqc import survey_frame


def read_raster(source, transects, settings):
    from .sources import densify_transects
    analysis = CRS.from_user_input(settings['analysis_crs'])
    if not analysis.is_projected or abs(analysis.linear_units_factor[1]-1) > 1e-9:
        raise CalibrationError('Raster transects require a projected metre analysis CRS.')
    method = source.get('sampling', 'nearest')
    if method not in ('nearest', 'bilinear'):
        raise CalibrationError('Raster sampling must be nearest or bilinear.')
    scale, offset = float(source.get('z_scale_to_m', 1)), float(source.get('z_offset_m', 0))
    if not np.isfinite([scale, offset]).all() or scale <= 0:
        raise CalibrationError('Raster vertical scale must be positive and finite; offset finite.')
    knots = densify_transects(transects, float(settings.get('integration', {}).get('sample_spacing_m', 10)))
    with rasterio.open(source['path']) as raster:
        if raster.crs is None or raster.count != 1:
            raise CalibrationError('Bathymetry raster requires a known CRS and one elevation band.')
        x, y = [k['x_m'] for k in knots], [k['y_m'] for k in knots]
        if raster.crs != analysis:
            # Datum transformations must be independently verified; do not infer a vertical transform.
            if source.get('horizontal_mapping_verified') is not True:
                raise CalibrationError('Different raster/analysis CRS requires verified horizontal mapping.')
            x, y = transform(analysis, raster.crs, x, y)
        rows = []
        if method == 'nearest':
            values = [np.nan if np.ma.is_masked(v[0]) or not np.isfinite(v[0]) else float(v[0])
                      for v in raster.sample(zip(x, y), indexes=1, masked=True)]
        else:
            values = []
            for a, b in zip(x, y):
                col, row = ~raster.transform * (a, b)
                col, row = col-0.5, row-0.5
                c0, r0 = int(np.floor(col)), int(np.floor(row))
                dx, dy = col-c0, row-r0
                weights = np.array([[(1-dx)*(1-dy), dx*(1-dy)], [(1-dx)*dy, dx*dy]])
                outside = not (0 <= c0 and c0+2 <= raster.width and 0 <= r0 and r0+2 <= raster.height)
                samples = raster.read(1, window=Window(c0, r0, 2, 2), masked=True, boundless=outside)
                required = weights > 1e-12
                invalid = np.ma.getmaskarray(samples) | ~np.isfinite(samples.data)
                values.append(np.nan if (invalid & required).any() else float(np.sum(samples.filled(0)*weights)))
        for knot, value in zip(knots, values):
            rows.append({**knot, 'z_m': value*scale+offset})
    return survey_frame(pd.DataFrame(rows))
