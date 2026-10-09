import arcpy
import json
import os
import sys

def explore_gdb(gdb_path):
    arcpy.env.workspace = gdb_path
    
    datasets = arcpy.ListDatasets("*", "Feature")
    datasets = [''] + datasets if datasets is not None else ['']
    
    inventory = []
    
    for ds in datasets:
        for fc in arcpy.ListFeatureClasses(feature_dataset=ds):
            desc = arcpy.Describe(fc)
            inventory.append({
                "type": "FeatureClass",
                "name": fc,
                "dataset": ds,
                "crs": desc.spatialReference.name if desc.spatialReference else "Unknown",
                "crs_factoryCode": desc.spatialReference.factoryCode if desc.spatialReference else "Unknown",
                "fields": [f.name for f in desc.fields]
            })

    rasters = arcpy.ListRasters()
    if rasters:
        for r in rasters:
            desc = arcpy.Describe(r)
            inventory.append({
                "type": "Raster",
                "name": r,
                "dataset": "",
                "crs": desc.spatialReference.name if desc.spatialReference else "Unknown",
                "crs_factoryCode": desc.spatialReference.factoryCode if desc.spatialReference else "Unknown",
                "cell_x": desc.meanCellWidth,
                "cell_y": desc.meanCellHeight
            })
            
    with open('gdb_inventory.json', 'w') as f:
        json.dump(inventory, f, indent=2)
        
    print("Inventory completed.")

if __name__ == '__main__':
    explore_gdb(sys.argv[1])
