import h5py
import numpy as np
import pandas as pd
import sys

US_FT_M = 1200 / 3937  # model .prj unit is Foot_US

def extract_transects(hdf_path, output_csv):
    with h5py.File(hdf_path, 'r') as h5:
        attrs = h5['Geometry/Cross Sections/Attributes'][:]
        
        info = h5['Geometry/Cross Sections/Polyline Info'][:]
        pts = h5['Geometry/Cross Sections/Polyline Points'][:]
        
        rows = []
        chainage = 0.0
        
        for i in range(len(attrs)):
            if attrs['Reach'][i].decode().strip() != 'LMR':
                continue
            rs = attrs['RS'][i].decode().strip()
            
            start, count = info[i][:2]
            xs_pts = pts[start:start+count]
            
            # calculate u_m for each point along the segment
            diff = np.diff(xs_pts, axis=0)
            dist = np.linalg.norm(diff, axis=1)
            u = np.insert(np.cumsum(dist), 0, 0.0)
            
            # Channel length is Len Channel
            length_to_next = np.nan_to_num(attrs['Len Channel'][i]) * 0.3048 # feet to m
            
            for j in range(count):
                rows.append({
                    'xs_id': rs,
                    'model_column': i,
                    'chainage_m': chainage,
                    'length_to_next_m': length_to_next if i < len(attrs)-1 else None,
                    'u_m': u[j] * 0.3048, # geometry in feet to m
                    'x_m': xs_pts[j, 0] * US_FT_M, # Albers (USGS) US survey feet -> m
                    'y_m': xs_pts[j, 1] * US_FT_M
                })
            chainage += length_to_next
            
    pd.DataFrame(rows).to_csv(output_csv, index=False)
    print(f'Wrote {len(rows)} points to {output_csv}')

if __name__ == '__main__':
    extract_transects(sys.argv[1], sys.argv[2])
