"""Report HDF layout/units without loading result arrays or including their values."""
import argparse
import json
from pathlib import Path
import sys
import h5py

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ras.hdf_discovery import _attr_text


def metadata_report(path,limit=5000):
    if limit <= 0:
        raise ValueError('Dataset limit must be positive.')
    report = {'file_version':'','units_system':'','datasets':[],'truncated':False,
              'contents':'Dataset layout and Units/Grain Class attributes only; no result array values.'}
    with h5py.File(path,'r') as h5:
        report['file_version'] = _attr_text(h5,'File Version')
        report['units_system'] = _attr_text(h5,'Units System')
        def visit(name,obj):
            if not isinstance(obj,h5py.Dataset):
                return None
            if len(report['datasets']) >= limit:
                report['truncated'] = True
                return True
            report['datasets'].append({'path':name,'shape':list(obj.shape),'dtype':str(obj.dtype),
                'logical_bytes':int(obj.size*obj.dtype.itemsize),'chunks':obj.chunks,
                'compression':obj.compression,'units':_attr_text(obj,'Units'),
                'grain_class':_attr_text(obj,'Grain Class')})
        h5.visititems(visit)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hdf',type=Path)
    parser.add_argument('--output',type=Path,help='Write JSON here; otherwise print it.')
    parser.add_argument('--limit',type=int,default=5000)
    args = parser.parse_args()
    try:
        report = json.dumps(metadata_report(args.hdf,args.limit),indent=2)
        if args.output:
            args.output.write_text(report+'\n',encoding='utf-8')
        else:
            print(report)
    except (OSError,ValueError) as exc:
        parser.exit(1,f'Could not inspect HDF metadata: {exc}\n')


if __name__ == '__main__':
    main()
