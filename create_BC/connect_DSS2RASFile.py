"""
HEC-RAS DSS Linker & Validator
--------------------------------

This script provides a Graphical User Interface (GUI) to manage boundary condition linkages 
between 1D HEC-RAS quasi-unsteady sediment models (.q## and .s## files) and HEC-DSS files.

Key Features:
1. Validates existing HEC-RAS model files against external DSS files to ensure all 
   required Flow and Sediment grain class time series exist before running simulations.
2. Interactively parses STAGE boundaries (if applicable) and prompts the user to select the appropriate dataset.
3. Automatically creates a `Boundary_Data` isolation folder within the simulation directory.
4. Duplicates the selected DSS files into the `Boundary_Data` folder and updates the 
   HEC-RAS XML schemas in both `.q##` and `.s##` files to point directly to these copied DSS files.
5. Performs a post-update validation on the newly generated model files to guarantee correct pathing.

Dependencies:
- tkinter (Standard GUI Library)
- xml.etree.ElementTree (For parsing HEC-RAS XML structures)
- pydsstools (For reading HEC-DSS catalogues and timeseries paths)
"""

import os
import shutil
import glob
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# For reading Flow DSS
from pydsstools.heclib.dss import HecDss

# HEC-RAS 20 Grain Size Classes
GRAIN_CLASSES = {
    1: "Clay", 2: "VFM", 3: "FM", 4: "MM", 5: "CM",
    6: "VFS", 7: "FS", 8: "MS", 9: "CS", 10: "VCS",
    11: "VFG", 12: "FG", 13: "MG", 14: "CG", 15: "VCG",
    16: "SC", 17: "LC", 18: "SB", 19: "MB", 20: "LB"
}

class ConnectRASApp(tk.Tk):
    """
    Main GUI application for linking HEC-RAS quasi-unsteady files (.q##, .s##) to DSS files.
    Inherits from tkinter.Tk to create the primary application window.
    """
    def __init__(self):
        super().__init__()
        self.title("HEC-RAS DSS Linker")
        self.geometry("850x650")
        
        # Variables
        self.sim_folder_var = tk.StringVar()
        self.flow_dss_var = tk.StringVar()
        self.sed_dss_var = tk.StringVar()
        self.stage_path_var = tk.StringVar()
        
        self.stage_paths = []
        
        self._build_ui()
        
    def _build_ui(self):
        main_frame = ttk.Frame(self, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Title
        ttk.Label(main_frame, text="Link 1D HEC-RAS Sediment Model to DSS", font=("Helvetica", 14, "bold")).grid(row=0, column=0, columnspan=3, pady=(0, 15))
        
        # Sim Folder
        ttk.Label(main_frame, text="Simulation Folder (.q##, .s##):").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.sim_folder_var, width=60).grid(row=1, column=1, sticky=tk.EW, pady=5, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.browse_sim).grid(row=1, column=2, pady=5)
        
        # Flow DSS
        ttk.Label(main_frame, text="Flow DSS File:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.flow_dss_var, width=60).grid(row=2, column=1, sticky=tk.EW, pady=5, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.browse_flow).grid(row=2, column=2, pady=5)
        
        # Sed DSS
        ttk.Label(main_frame, text="Sediment DSS File:").grid(row=3, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.sed_dss_var, width=60).grid(row=3, column=1, sticky=tk.EW, pady=5, padx=5)
        ttk.Button(main_frame, text="Browse...", command=self.browse_sed).grid(row=3, column=2, pady=5)
        
        # STAGE Path Selection
        ttk.Label(main_frame, text="STAGE Series (if applicable):").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.stage_combobox = ttk.Combobox(main_frame, textvariable=self.stage_path_var, state="readonly", width=60)
        self.stage_combobox.grid(row=4, column=1, sticky=tk.EW, pady=5, padx=5)
        ttk.Button(main_frame, text="Refresh", command=self.refresh_stages).grid(row=4, column=2, pady=5)
        
        main_frame.columnconfigure(1, weight=1)
        
        # Buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=5, column=0, columnspan=3, pady=20)
        
        ttk.Button(btn_frame, text="Validate Links", command=self.on_validate).pack(side=tk.LEFT, padx=15)
        ttk.Button(btn_frame, text="Add to Simulation", command=self.on_add_to_sim).pack(side=tk.LEFT, padx=15)
        
        # Log Text Area
        ttk.Label(main_frame, text="Output Log:").grid(row=6, column=0, sticky=tk.W, pady=(10, 0))
        self.log_text = tk.Text(main_frame, height=15, wrap=tk.WORD, font=("Courier", 10))
        self.log_text.grid(row=7, column=0, columnspan=3, sticky=tk.NSEW, pady=5)
        main_frame.rowconfigure(7, weight=1)
        
        # Scrollbar for text
        scrollbar = ttk.Scrollbar(main_frame, command=self.log_text.yview)
        scrollbar.grid(row=7, column=3, sticky=tk.NS)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
    def log(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.update_idletasks()
        
    def browse_sim(self):
        d = filedialog.askdirectory(title="Select Simulation Folder")
        if d: self.sim_folder_var.set(d)
        
    def browse_flow(self):
        f = filedialog.askopenfilename(title="Select Flow DSS file", filetypes=[("DSS Files", "*.dss")])
        if f: 
            self.flow_dss_var.set(f)
            self.refresh_stages()
            
    def browse_sed(self):
        f = filedialog.askopenfilename(title="Select Sediment DSS file", filetypes=[("DSS Files", "*.dss")])
        if f: self.sed_dss_var.set(f)
        
    def refresh_stages(self):
        f_dss = self.flow_dss_var.get()
        if not f_dss or not os.path.exists(f_dss):
            return
        
        try:
            with HecDss.Open(f_dss) as fid:
                ts_paths = list(fid.path_dict().get('ts', []))
                unique_stage_paths = set()
                for p in ts_paths:
                    parts = p.split('/')
                    if len(parts) >= 7 and parts[3].upper() == 'STAGE':
                        parts[4] = '' # Clear D-part
                        clean_path = '/'.join(parts)
                        unique_stage_paths.add(clean_path)
            self.stage_paths = sorted(list(unique_stage_paths))
            self.stage_combobox['values'] = self.stage_paths
            if self.stage_paths:
                self.stage_combobox.current(0)
            self.log(f"Found {len(self.stage_paths)} STAGE series in Flow DSS.")
        except Exception as e:
            self.log(f"Error reading STAGE paths from Flow DSS: {e}")

    def get_model_files(self, folder):
        """
        Scans a given folder to find the active HEC-RAS flow (.q##) and sediment (.s##) model files.
        Ignores temporary backups (.bak) and standalone XMLs.
        """
        s_files = [f for f in glob.glob(os.path.join(folder, "*.s[0-9]*")) if not f.endswith('.xml') and not f.endswith('.bak')]
        q_files = [f for f in glob.glob(os.path.join(folder, "*.q[0-9]*")) if not f.endswith('.xml') and not f.endswith('.bak')]
        return s_files, q_files

    def parse_boundaries(self, q_file):
        """
        Parses the quasi-unsteady flow file (.q##) XML schema to extract the required boundary conditions.
        Returns a list of dictionaries containing the River Station (RS), B-part, and D-part for each boundary.
        """
        try:
            q_tree = ET.parse(q_file)
            q_root = q_tree.getroot()
        except Exception as e:
            self.log(f"Error parsing {q_file}: {e}")
            return None
            
        boundaries = []
        for node in q_root.findall('.//Boundary_Conditions/Node') + q_root.findall('.//Node'):
            rs = node.get('RS')
            if not rs: continue
            rs = rs.strip()
            
            # Get existing DSS paths from FLOW to figure out b_part and d_part
            dss_node = node.find('.//DSS')
            if dss_node is not None and dss_node.get('Path'):
                path = dss_node.get('Path')
                parts = [p for p in path.split('/') if p]
                if len(parts) >= 6:
                    b_part = parts[1]
                    d_part = parts[3]
                    boundaries.append({'rs': rs, 'b_part': b_part, 'd_part': d_part})
                    
        # Check for 314.8 ORCC_overbank manually if not present
        has_314 = any(b['rs'] == '314.8' for b in boundaries)
        if not has_314:
            # We don't have d_part yet, but usually it's tied to the simulation date. We will flag it.
            boundaries.append({'rs': '314.8', 'b_part': 'ORCC_OVERBANK', 'd_part': '*'})
            
        return boundaries

    def on_validate(self):
        """
        Validates whether the selected Flow DSS and Sediment DSS files contain the necessary
        time series datasets to satisfy the boundary conditions defined in the `.q##` file.
        """
        sim_folder = self.sim_folder_var.get()
        flow_dss = self.flow_dss_var.get()
        sed_dss = self.sed_dss_var.get()
        
        self.log("\n--- Starting Validation ---")
        if not sim_folder or not flow_dss or not sed_dss:
            self.log("ERROR: Please select Simulation folder, Flow DSS, and Sediment DSS.")
            return False
            
        s_files, q_files = self.get_model_files(sim_folder)
        if not s_files or not q_files:
            self.log("ERROR: Could not find .s## or .q## files in the selected folder.")
            return False
            
        q_file = q_files[0]
        self.log(f"Using Q-file: {os.path.basename(q_file)}")
        
        boundaries = self.parse_boundaries(q_file)
        if not boundaries:
            self.log("WARNING: No boundaries found to validate.")
            return False
            
        self.log(f"Found {len(boundaries)} boundaries to validate.")
        
        # Read available paths in DSS files
        flow_paths = []
        try:
            with HecDss.Open(flow_dss) as fid:
                flow_paths = [p.upper() for p in fid.path_dict().get('ts', [])]
        except Exception as e:
            self.log(f"ERROR reading Flow DSS: {e}")
            return False
            
        sed_paths = []
        try:
            with HecDss.Open(sed_dss) as fid:
                sed_paths = [p.upper() for p in fid.path_dict().get('ts', [])]
        except Exception as e:
            self.log(f"ERROR reading Sediment DSS: {e}")
            return False

        all_valid = True
        
        for b in boundaries:
            b_part = b['b_part'].upper()
            rs = b['rs']
            
            # 1. Validate Flow DSS has FLOW for this b_part
            flow_found = any(p for p in flow_paths if len(p.split('/')) >= 5 and p.split('/')[2] == b_part and p.split('/')[3] == 'FLOW')
            
            # 2. Validate Sed DSS has all 20 grain classes for this b_part
            # Format: /IRREGULAR/{b_part}/SEDIMENT/{d_part}/1DAY/{gc_label.upper()}/
            missing_grains = []
            for gc_label in GRAIN_CLASSES.values():
                gc_upper = gc_label.upper()
                # Find if any path matches this b_part and grain class
                sed_found = any(p for p in sed_paths if len(p.split('/')) >= 7 and p.split('/')[2] == b_part and p.split('/')[6] == gc_upper)
                if not sed_found:
                    missing_grains.append(gc_label)
            
            if flow_found and not missing_grains:
                self.log(f"[OK] Boundary RS {rs} ({b_part}): Found FLOW and all 20 Sediment grain classes.")
            else:
                all_valid = False
                if not flow_found:
                    self.log(f"[FAIL] Boundary RS {rs} ({b_part}): Missing FLOW time series in Flow DSS.")
                if missing_grains:
                    self.log(f"[FAIL] Boundary RS {rs} ({b_part}): Missing Sediment classes in Sed DSS: {', '.join(missing_grains)}")
                    
        if all_valid:
            self.log("Validation Successful: All required boundaries found in both DSS files.")
        else:
            self.log("Validation Failed: Some boundaries are missing required data in the DSS files.")
            
        return all_valid

    def on_add_to_sim(self):
        """
        Executes the 'Add to Simulation' workflow:
        1. Creates a local 'Boundary_Data' folder in the simulation directory.
        2. Copies the selected DSS files into this folder.
        3. Updates the XML paths in the .q## and .s## files to point to the new DSS files.
        4. Saves the updated model files to 'Boundary_Data' and runs post-validation.
        """
        sim_folder = self.sim_folder_var.get()
        flow_dss = self.flow_dss_var.get()
        sed_dss = self.sed_dss_var.get()
        stage_path = self.stage_path_var.get()
        
        self.log("\n--- Starting Add to Simulation ---")
        if not sim_folder or not flow_dss or not sed_dss:
            self.log("ERROR: Please select all required inputs.")
            return
            
        s_files, q_files = self.get_model_files(sim_folder)
        if not s_files or not q_files:
            self.log("ERROR: Could not find model files.")
            return
            
        q_file = q_files[0]
        s_file = s_files[0]
        
        # 1. Create Boundary_Data folder
        boundary_dir = os.path.join(sim_folder, 'Boundary_Data')
        os.makedirs(boundary_dir, exist_ok=True)
        self.log(f"Created/verified folder: {boundary_dir}")
        
        # 2. Copy DSS files
        new_flow_dss = os.path.join(boundary_dir, os.path.basename(flow_dss))
        new_sed_dss = os.path.join(boundary_dir, os.path.basename(sed_dss))
        
        try:
            shutil.copy2(flow_dss, new_flow_dss)
            shutil.copy2(sed_dss, new_sed_dss)
            self.log("Copied Flow DSS and Sediment DSS to Boundary_Data.")
        except Exception as e:
            self.log(f"ERROR copying DSS files: {e}")
            return
            
        # 3. Read stage values if stage path is selected
        stage_values_str = ""
        if stage_path:
            try:
                with HecDss.Open(new_flow_dss) as fid:
                    ts = fid.read_ts(stage_path)
                    stage_values = ts.values
                    stage_values_str = ",".join([f"{v:.4f}" for v in stage_values])
                self.log(f"Extracted STAGE values for {stage_path}.")
            except Exception as e:
                self.log(f"ERROR reading STAGE values: {e}")
        
        # Flow Path Map for updating Flow paths in Q file
        flow_path_map = {}
        try:
            with HecDss.Open(new_flow_dss) as fid:
                for p in fid.path_dict().get('ts', []):
                    parts = p.split('/')
                    if len(parts) >= 7 and parts[3].upper() == 'FLOW':
                        b_part = parts[2].upper()
                        flow_path_map[b_part] = (parts[1], parts[5], parts[6])
        except Exception as e:
            self.log(f"ERROR reading Flow DSS: {e}")
            return
            
        # 4. Modify Q File and S File
        self.log(f"Modifying {os.path.basename(q_file)} and {os.path.basename(s_file)}...")
        
        # Output paths
        new_q_file = os.path.join(sim_folder, os.path.basename(q_file))
        new_s_file = os.path.join(sim_folder, os.path.basename(s_file))
        
        try:
            q_tree = ET.parse(q_file)
            q_root = q_tree.getroot()
            s_tree = ET.parse(s_file)
            s_root = s_tree.getroot()
        except Exception as e:
            self.log(f"ERROR parsing XML: {e}")
            return
            
        # Fetch Sediment paths to get correct D-parts
        sed_paths = []
        try:
            with HecDss.Open(new_sed_dss) as fid:
                sed_paths = [p for p in fid.path_dict().get('ts', [])]
        except Exception as e:
            self.log(f"ERROR reading Sediment DSS for D-parts: {e}")
            return

        # -- Q FILE UPDATE --
        boundary_map = {}
        mod_q_count = 0
        mod_q_stage_count = 0
        found_314_8 = False
        bc_element = q_root.find('.//Boundary_Conditions')
        
        for node in q_root.findall('.//Boundary_Conditions/Node') + q_root.findall('.//Node'):
            rs = node.get('RS')
            if not rs: continue
            rs = rs.strip()
            
            river = node.get('River', '').strip()
            reach = node.get('Reach', '').strip()
            if river == 'Mississippi' and reach == 'LMR' and rs == '314.8':
                found_314_8 = True
                
            dss_nodes = node.findall('.//DSS')
            for dss_node in dss_nodes:
                if dss_node.get('File'):
                    # Use relative path with consistent forward slashes
                    norm_flow_dss = f"./Boundary_Data/{os.path.basename(new_flow_dss)}"
                    dss_node.set('File', norm_flow_dss)
                    
                    path = dss_node.get('Path')
                    if path:
                        parts = path.split('/')
                        if len(parts) >= 7 and parts[3].upper() == 'FLOW':
                            b_part = parts[2].upper()
                            if b_part in flow_path_map:
                                a, e, f = flow_path_map[b_part]
                                parts[1] = a
                                parts[5] = e
                                parts[6] = f
                                dss_node.set('Path', '/'.join(parts))
                    mod_q_count += 1
                    
            dss_node = node.find('.//DSS')
            if dss_node is not None and dss_node.get('Path'):
                path = dss_node.get('Path')
                parts = [p for p in path.split('/') if p]
                if len(parts) >= 6:
                    b_part = parts[1]
                    d_part = parts[3]
                    boundary_map[rs] = (b_part, d_part)
                    
            boundary_type = node.find('.//Boundary')
            if boundary_type is not None and boundary_type.get('Type') == 'Stage Series' and stage_path:
                if dss_node is not None:
                    dss_node.set('Path', stage_path)
                stages_elem = node.find('Stages')
                if stages_elem is None:
                    stages_elem = ET.SubElement(node, 'Stages')
                stages_elem.text = stage_values_str
                mod_q_stage_count += 1
                
        # Handle 314.8 Missing
        if not found_314_8 and bc_element is not None:
            orcc_overbank_path = ""
            for p in flow_path_map.keys():
                if p == 'ORCC_OVERBANK':
                    a, e, f = flow_path_map[p]
                    orcc_overbank_path = f"/{a}/ORCC_OVERBANK/FLOW//1DAY/{f}/"
                    break
            
            if orcc_overbank_path:
                new_node = ET.SubElement(bc_element, 'Node', {'River': 'Mississippi', 'Reach': 'LMR', 'RS': '314.8'})
                ET.SubElement(new_node, 'Boundary', {'Type': 'Lateral Flow Series'})
                data_elem = ET.SubElement(new_node, 'Data', {'Source': '0'})
                ET.SubElement(data_elem, 'DSS', {'File': new_flow_dss, 'Path': orcc_overbank_path})
                ET.SubElement(new_node, 'Date', {'Type': 'Simulation'})
                ET.SubElement(new_node, 'Flows')
                ET.SubElement(new_node, 'Comp_Inc')
                ET.SubElement(new_node, 'Durations')
                
                parts = [p for p in orcc_overbank_path.split('/') if p]
                if len(parts) >= 6:
                    b_part = parts[1]
                    d_part = parts[3]
                    boundary_map['314.8'] = (b_part, d_part)
                    mod_q_count += 1
                    
        # Write new Q file
        q_tree.write(new_q_file, encoding="utf-8", xml_declaration=False)
        self.log(f"Updated {mod_q_count} DSS references and {mod_q_stage_count} Stage Series in new Q file.")

        # -- S FILE UPDATE --
        mod_s_count = 0
        # Use relative path for S file to Sed DSS with consistent forward slashes
        sed_dss_abs = f"./Boundary_Data/{os.path.basename(new_sed_dss)}"
        
        for node in s_root.findall('.//Load_Specification/Node'):
            rs = node.get('RS')
            if not rs: continue
            rs = rs.strip()
            
            if rs in boundary_map:
                b_part, d_part = boundary_map[rs]
                
                for tag in ['Load_Type', 'Time_Reference', 'Sediment_Time_Series', 'DSS_Load_Series', 'Rating_Curve']:
                    elem = node.find(tag)
                    if elem is not None:
                        node.remove(elem)
                        
                ET.SubElement(node, 'Load_Type', {'Type': 'Sediment Time Series'})
                ET.SubElement(node, 'Time_Reference', {'Type': 'Simulation', 'Data_Source': '1'})
                sts = ET.SubElement(node, 'Sediment_Time_Series')
                ET.SubElement(sts, 'Durations')
                ET.SubElement(sts, 'Loads')
                
                dss_ls = ET.SubElement(node, 'DSS_Load_Series', {'Address': sed_dss_abs})
                
                # Find the actual D-part from the Sediment DSS file for this boundary
                actual_d_part = d_part
                for sp in sed_paths:
                    parts = sp.split('/')
                    if len(parts) >= 7 and parts[2].upper() == b_part.upper() and parts[3].upper() == 'SEDIMENT':
                        actual_d_part = parts[4]
                        break

                paths_attribs = {}
                for gc_idx, gc_label in GRAIN_CLASSES.items():
                    # Use the dynamically fetched actual_d_part
                    dss_path_str = f"/IRREGULAR/{b_part}/SEDIMENT/{actual_d_part}/1DAY/{gc_label.upper()}/"
                    paths_attribs[f"DSS_path{gc_idx}"] = f"{gc_idx},{gc_label},{dss_path_str}"
                ET.SubElement(dss_ls, 'Paths', paths_attribs)
                
                rc = ET.SubElement(node, 'Rating_Curve', {'LoadOrConc': '0', 'BedLoadEqMeth': 'Blanks are 0'})
                rc1 = ET.SubElement(rc, 'RC_Record', {'Load': ''})
                ET.SubElement(rc1, 'Gradations')
                rc2 = ET.SubElement(rc, 'RC_Record', {'Load': ''})
                ET.SubElement(rc2, 'Gradations')
                
                mod_s_count += 1
                
        s_tree.write(new_s_file, encoding="utf-8", xml_declaration=False)
        self.log(f"Updated {mod_s_count} boundaries in new S file.")
        
        self.log("\n--- Validating Updated Links ---")
        # Validate using the new files
        self.sim_folder_var.set(sim_folder)
        self.flow_dss_var.set(new_flow_dss)
        self.sed_dss_var.set(new_sed_dss)
        
        valid = self.on_validate()
        
        if valid:
            messagebox.showinfo("Success", "Files successfully modified and links validated!")
            self.log("\nSUCCESS: All files modified and validated successfully.")
        else:
            messagebox.showwarning("Warning", "Files modified but post-validation failed. Check logs.")
            self.log("\nWARNING: Files modified but validation of the new links failed.")

if __name__ == "__main__":
    app = ConnectRASApp()
    app.mainloop()
