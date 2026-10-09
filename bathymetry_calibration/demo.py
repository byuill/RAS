"""Generate known-answer fixtures, not representations of the user's model or surveys."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd


def create_demo(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError('Use an empty demo folder to preserve existing files.')
    u = np.array([0., 5., 10.])
    rows, before, after = [], [], []
    for column, xs_id in enumerate(['A', 'B', 'C']):
        for station in u:
            rows.append({'xs_id': xs_id, 'model_column': column, 'chainage_m': column*100.,
                         'length_to_next_m': 100. if column < 2 else None,
                         'u_m': station, 'x_m': 500000.+station, 'y_m': 3300000.-column*100.})
            before.append({'xs_id': xs_id, 'u_m': station, 'z_m': 0.})
            after.append({'xs_id': xs_id, 'u_m': station, 'z_m': 1.})
    pd.DataFrame(rows).to_csv(directory/'transects.csv', index=False)
    pd.DataFrame(before).to_csv(directory/'survey-before.csv', index=False)
    pd.DataFrame(after).to_csv(directory/'survey-after.csv', index=False)
    with h5py.File(directory/'synthetic.p01.hdf', 'w') as h5:
        h5.attrs['File Version'] = 'SYNTHETIC; not a real HEC-RAS output layout'
        h5.create_dataset('profile_station', data=np.tile(u, (3, 1)))
        h5.create_dataset('profile_elevation', data=np.array([np.zeros((3, 3)), np.ones((3, 3))]))
        h5.create_dataset('dates', data=np.array([b'2012-01-01', b'2025-01-01']))
        h5.create_dataset('native_local', data=[[7., 11., 13.], [507., 1011., 513.]])
        h5.create_dataset('native_spatial', data=np.cumsum([[7., 11., 13.], [507., 1011., 513.]], axis=1))
    source = {'kind': 'csv', 'vertical_datum': 'synthetic', 'vertical_alignment_verified': True}
    config = {'analysis_crs': 'EPSG:26915', 'vertical_datum': 'synthetic',
              'spatial_mapping_verified': True, 'temporal_alignment_verified': True,
              'transects': 'transects.csv', 'cache_dir': 'cache',
              'surveys': {'baseline': dict(source, path='survey-before.csv', date='2012-01-01'),
                          'target': dict(source, path='survey-after.csv', date='2025-01-01')},
              'model': {'profile_mapping_verified': True, 'vertical_alignment_verified': True,
                        'vertical_datum': 'synthetic', 'elevation_dataset': 'profile_elevation',
                        'station_dataset': 'profile_station', 'time_dataset': 'dates',
                        'z_scale_to_m': 1., 'u_scale_to_m': 1.},
              'native_volume': {'verified': True, 'evidence': 'Known-answer generated fixture only.',
                                'semantics': 'local_temporally_cumulative', 'basis': 'bulk_geometric',
                                'dataset': 'native_local', 'scale_to_m3': 1., 'deposition_sign': 1.},
              'integration': {'max_gap_m': 25., 'min_coverage': 1., 'max_reach_length_m': 10000.}}
    (directory/'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    return directory


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    print(create_demo(parser.parse_args().output))
