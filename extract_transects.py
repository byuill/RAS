"""Extract one ordered HDF reach; verify profile-station alignment before use."""
import argparse
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

US_FT_M = 1200/3937


def _text(value):
    return value.decode().strip() if isinstance(value, bytes) else str(value).strip()


def extract_transects(hdf_path, output_csv, *, river=None, reach='LMR',
                      horizontal_scale_to_m=US_FT_M, channel_length_scale_to_m=.3048,
                      identity='full', overwrite=False):
    """Preserve native HDF order and columns; never infer downstream order from RS.

    Polyline XY and lateral distance use the same horizontal scale. Channel reach
    lengths have a separate explicit scale. The final *selected* XS has no next
    interval, even when more model reaches follow it. Export does not establish
    HDF result-column, station origin, CRS, or channel-footprint verification.
    """
    output_csv = Path(output_csv)
    if output_csv.exists() and not overwrite:
        raise ValueError('Output already exists; choose a new path or explicitly allow overwrite.')
    if not np.isfinite([horizontal_scale_to_m, channel_length_scale_to_m]).all() or min(horizontal_scale_to_m, channel_length_scale_to_m) <= 0:
        raise ValueError('Horizontal and channel-length scales must be positive and finite.')
    if identity not in ('full', 'station'):
        raise ValueError('identity must be full or station.')
    rows, chainage = [], 0.
    with h5py.File(hdf_path, 'r') as h5:
        attrs = h5['Geometry/Cross Sections/Attributes'][:]
        required = {'River', 'Reach', 'RS', 'Len Channel'}
        if not required <= set(attrs.dtype.names or ()):
            raise ValueError(f'Geometry attributes require {sorted(required)}.')
        selected = [i for i, row in enumerate(attrs) if _text(row['Reach']) == reach and
                     (river is None or _text(row['River']) == river)]
        if len(selected) < 2 or len({_text(attrs[i]['River']) for i in selected}) != 1 or (np.diff(selected) != 1).any():
            raise ValueError('Select at least two consecutive XS in exactly one river/reach.')
        info, points = h5['Geometry/Cross Sections/Polyline Info'], h5['Geometry/Cross Sections/Polyline Points']
        identities = set()
        for position, i in enumerate(selected):
            row = attrs[i]
            station = _text(row['RS'])
            xs_id = f'{_text(row["River"])}:{reach}:{station}' if identity == 'full' else station
            if xs_id in identities:
                raise ValueError('Duplicate XS identities; use full identities or select a smaller reach.')
            identities.add(xs_id)
            start, count = map(int, info[i, :2])
            if start < 0 or count < 2 or start+count > len(points):
                raise ValueError(f'{xs_id}: invalid polyline start/count.')
            xy = np.asarray(points[start:start+count, :2], float)*horizontal_scale_to_m
            distances = np.linalg.norm(np.diff(xy, axis=0), axis=1)
            if not np.isfinite(xy).all() or (distances <= 0).any():
                raise ValueError(f'{xs_id}: nonfinite or zero-length polyline segments.')
            u = np.r_[0., np.cumsum(distances)]
            length = float(row['Len Channel'])*channel_length_scale_to_m if position+1 < len(selected) else np.nan
            if position+1 < len(selected) and (not np.isfinite(length) or length <= 0):
                raise ValueError(f'{xs_id}: downstream channel length is missing or nonpositive.')
            rows.extend({'xs_id': xs_id, 'model_column': i, 'chainage_m': chainage,
                         'length_to_next_m': length, 'u_m': float(s), 'x_m': float(x), 'y_m': float(y)}
                        for s, (x, y) in zip(u, xy))
            if np.isfinite(length):
                chainage += length
    pd.DataFrame(rows).to_csv(output_csv, index=False)
    return output_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hdf')
    parser.add_argument('output')
    parser.add_argument('--river')
    parser.add_argument('--reach', default='LMR')
    parser.add_argument('--horizontal-scale-to-m', type=float, default=US_FT_M)
    parser.add_argument('--channel-length-scale-to-m', type=float, default=.3048)
    parser.add_argument('--identity', choices=['full', 'station'], default='full')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    try:
        output = extract_transects(args.hdf, args.output, river=args.river, reach=args.reach,
                                   horizontal_scale_to_m=args.horizontal_scale_to_m,
                                   channel_length_scale_to_m=args.channel_length_scale_to_m,
                                   identity=args.identity, overwrite=args.overwrite)
        print(f'Wrote {output}. Verify CRS, HDF/profile column order, and station origin before setting verification flags.')
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Transect extraction failed: {exc}\n')


if __name__ == '__main__':
    main()
