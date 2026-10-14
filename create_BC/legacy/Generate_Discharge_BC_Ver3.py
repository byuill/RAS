
# -*- coding: utf-8 -*-
# Historical reference only. Use python -m create_BC for the audited workflow.
"""
-----LMR Time series generator-------
formerly named, HydroStat_V14.py

V10-V11 Change: SWP added (flows for Pass A Lautre and South Pass)

Makes multiyear LMR discharge time series for quasi-unsteady simulations

INPUT:
    [1]data.csv: daily, continuous time series of discharge data (2 comma seperated columns with headers = date, discharge)
    or
    data_RF*.csv: many comma seperated columns with headers = date, Flow Date,discharge, Red_River, ORCC, Eflows (optional); these are decribed from
    an observed time series. These are the 'prescribed' flow values, this script basically calulates minor inflows, outflows, and MR&T operations based on these values.
        
    [2] ohio_split_wy.csv or ohio_split_cy.csv
    which are MMR/(Ohio+MMR) monthly averaged Q splits, rows are years columns are months, the only difference between
    files is wy is organized by water year, cy is organizaed by calender year
    
OUTPUT:
    [1] Boundary conditions for the LMRCS model in a .dss file
    [2] Excel file of ORCC flows called "For_Ron" [optional]
    [3] File logging which years or statistical category used to make time series [optional]
    

            Table of Contents: 
                
            1. REQUIRED LIBRARIES  
            2. USER INPUTS 
            3. FLOW PARTITIONING COEFFICIENTS
            4. FUNCTION DEFINITIONS
            5. INITIAL BOOKKEEPING 
            6. TIME SERIES GENERATION LOOPS
                6.1 Synthethic hydrographs
                6.2 Observational time series (Copeland's method)

Created on Fri May 10 10:35:05 2024
@author: brendan.yuill@usace.army.mil




Notes:
    
    3/7/2025 Fixed a bug in writing .dss due to additional outData column in outData
    3/7/2025 Added option to consider Low Sill head constraint
    3/10/2025 Added max length to crest regarding high sediment
    3/12/2025 Added an option to allow non-ron ORCC AND ron red river
    3/14/2025 Ensure the HydroPower has minimum required flow
    3/15/2025 Fixed Union Point instead of Tarbert Landing
    5/1/2025  Added Eflow Analysis option
                Eflow should be targeted Q at Simmesport
    1/9/2026 This file was renamed Generate_Discharge_BC.py from HydroStat_V14.py and edited for clarity for archival purposes.
    9/3/2026 Added option to use improved ORCC values from simulation
    9/7/2026 Used AI to QAQC mass balance
"""
# This loop clears all previously defined variables from the memory before the script runs.
# This prevents variables from a previous run from interfering with the current one.
for name in dir():
    if not name.startswith('__'):
        del globals()[name]

## __________________________________________________________________________________________________
## __________________________________________________________________________________________________


#-------------------------- 1. REQUIRED LIBRARIES----------------------------------------------------------
# This section imports all the necessary Python libraries for the script to function.
## __________________________________________________________________________________________________
## __________________________________________________________________________________________________

import pandas as pd  # Used for data manipulation and analysis, particularly for handling tabular data in DataFrames.
import numpy as np   # Fundamental package for numerical computation in Python; used for array and matrix operations.
import random, os    # 'random' is for generating random numbers; 'os' provides a way of using operating system dependent functionality.
from shutil import copyfile # Used for file operations, specifically for copying files.
# pydsstools is a library for reading and writing HEC-DSS files, which is a standard format for storing time-series data in hydrology.
# It must be installed manually from its source.
from pydsstools.heclib.dss import HecDss
from pydsstools.core import TimeSeriesContainer
from scipy.signal import savgol_filter # A function for smoothing data using the Savitzky-Golay filter.
import scipy.sparse as sparse # Used for creating and handling sparse matrices, which are memory-efficient for large matrices with many zeros.
from scipy.sparse.linalg import splu # A function for solving sparse linear systems, used in the Whittaker smoother.

# The following libraries are imported but currently not used in the script.
# from dateutil.relativedelta import relativedelta
import matplotlib.pyplot as plt
from datetime import datetime #,timedelta # Used for working with dates and times.
# import csv

## __________________________________________________________________________________________________
## __________________________________________________________________________________________________


#-------------------------- 2. USER INPUTS ----------------------------------------------------------
# This section contains all the user-configurable parameters that control the simulation.
## __________________________________________________________________________________________________
## __________________________________________________________________________________________________




## ---------------------- LMR SCENARIO DEVELOPMENT INPUTS =

#<<<<<<   BIRDS POINT FLOODWAY OPERATIONS
# Discharge (in cubic feet per second, cfs) above which the Birds Point floodway is operated.
BPthres = 1810000   
# Base travel time (in days) for water to pass through the floodway.
bpnmLag = 2
# Efficiency of flow through the floodway (1.0 = 100% flow passes, 0.5 = 50% loss).
bpnmEff = 1.0

#<<<<<<<   MORGANZA & BONNET CARRE SPILLWAY OPERATIONS
# A short name for the scenario being run (e.g., 'Eflow' for Environmental Flow).
MBCName = 'Cal'
# Discharge at Carrollton (cfs) above which the Morganza or Bonnet Carre spillways are opened.
MorBCthres = 1250000 
# Control style for spillway operation: 0 for ratio-based, 1 for discharge threshold-based.
BCOpStyle = 1
# For Ratio Control Style: Fraction of diverted flow to Bonnet Carre at low diversion rates.
BCUseRatio_Low = 0.75 
# For Ratio Control Style: Fraction of diverted flow to Bonnet Carre at high diversion rates.
BCUseRatio_High = 0.5 
# For Ratio Control Style: The discharge (cfs) that defines the switch from low to high diversion rates.
BC_HighUseThreshold = 250000 
# For Q Threshold Control Style: Flow goes to Bonnet Carre until its discharge reaches this threshold (cfs).
MorganzaQThres = 250000
# Option to route Bonnet Carre flow down the Old River Control Complex (ORCC) instead, if possible (0=no, 1=yes).
ORCCOverride = 0

#<<<<<<<   OLD RIVER CONTROL COMPLEX (ORCC) OPERATIONS
# Target ratio of latitude flow to be sent down the Lower Mississippi River (LMR).
ORCC_Ratio = 0.7
# Ratio for the rising limb of a flood hydrograph.
ORCC_Ratio_RisingLimb = 0.7
# Ratio for the falling limb of a flood hydrograph.
ORCC_Ratio_FallingLimb = 0.7
# Ratio during low water conditions.
ORCC_Ratio_LowWater = 0.7
# Maximum total flow allowed through the ORCC structures (cfs).
ORCC_Max_Total = 620000

# Option to consider the head constraint at the Low Sill structure (1=yes).
consider_head =0
# Adjusted ORCC ratio when the head constraint is active.
ORCC_Ratio_HeadConst = 0.67

# Discharge thresholds (cfs) that define different operational behaviors at ORCC.
Low_to_Mod = 300000 # Threshold from low to moderate flow.
Mod_to_High = 1000000 # Threshold from moderate to high flow.
HydroPow_CapA = 150000  # Typical hydropower diversion capacity (cfs).
HydroPow_CapB = 170000  # Maximum hydropower diversion capacity (cfs).
HydroPow_Min = 8000     # Minimum flow to maintain hydropower operations (cfs).
Overbank_Cap = 320000   # Maximum diversion capacity for overbank structures (cfs).
Lowsill_Cap = 130000    # Maximum diversion capacity for the low sill structure (cfs).

## ---------------------- FLOW CONTROLS  =

#<<<<<<   STATISTICAL FLOW CONTROLS
# Minimum allowable discharge at "Tarbert Landing" (cfs) to prevent unnaturally low flows.
threshold_low = 100000
# Minimum allowable discharge for both the Middle Mississippi River (MMR) and Ohio River (cfs).
MMROhio_low = 30000
# Option to apply a smoothing filter to the generated time series (0 = No, 1 = Yes).
filter_TS = 0
# The window size for the smoothing filter. A larger size results in a smoother curve.
filter_sz = 21 
# Scale factor for adjusting the peak discharge (Qpeak). 0 means use standard deviation, otherwise use a specific value.
QpeakMod = 0 
# Scale (in days) for randomly shifting the hydrograph in time to add variability.
QshapeShift = 7

#<<<<<<   Random/complex flow elements
# Use seasonally averaged (0) or variable seasonal (1) flow splits between MMR and Ohio River.
FlowSplitType = 0
# Adds additional random annual variance to the MMR/Ohio flow split. 0.1709 is the historical standard deviation.
MMROhio_RFL = 0 
# During ORCC daily optimization, this defines the partition of flow on the rising/falling limb.
dominateValue = 0.8 # The dominant structure gets this fraction.
subservientValue = 1 - dominateValue # The other structure gets the rest.
# A random flux limiter for ORCC as a fraction of its through-flow, to simulate daily operational uncertainty.
ORCC_RFL = 0 

#<<<<<<   Identify Rising Limb of Hydrograph
# Number of previous days to average for detecting a rise in discharge.
rlAvgPer = 30 
# The required increase in discharge (cfs) over the average to be considered a rising limb.
rlThres = 100000 
# The minimum discharge (cfs) required to trigger a rising limb operational response.
rl_minQ = 1000000
# A discharge threshold (cfs) related to expected sediment transport characteristics.
rl_minQs = 600000
# A discharge threshold (cfs) that defines low water conditions for ORCC operations.
rl_LowWater = 300000
# Red River discharge threshold (cfs) below which a head constraint at ORCC might be triggered.
RRStageThres = 29000 
# Maximum duration (in days) of a flood crest, simulating a limit on high sediment supply.
crestMaxLength = 30

## ---------------------- I/O MANAGEMENT  =

# Toggle to generate a synthetic test hydrograph designed to stress-test mass balance limits
Run_QAQC_Tests = 0

# Generate Water Level boundary conditions based on WL_data.csv (0=no, 1=yes).
Generate_WL = 1

# A flag to indicate if this is an Environmental Flow (E-flow) analysis (0=no, 1=yes).
Eflows = 0

# Total length of the time series to be generated (in years).
TimeSeriesLength = 150
# Type of time series to generate:
# 1: Based on the shape of observed individual years.
# 2: Synthetic, based on statistical properties of observed data.
# 3: Write only the processed observational time series.
TimeSeriesType = 3

# IF TimeSeriesType is 3, this selects the format of the input observational data.
# 0: Original format (based on Tarbert Landing discharge).
# 1: "Ron Format" (based on Union Point discharge and includes Red River time series).
# 2: NEW!!! Ron Format ---- Modified with HydroTool and complex ORCC flows and Rising Limbs
RonFormat = 1
if RonFormat == 2:
    #Use Hydro-Tool Rising Limb (1) or default (0)
    useHydroToolRL = 1
    
# Option for handling ORCC and Red River flows when using Ron Format.
# 1: Use prescribed ORCC and Red River flows from the input file.
# 2: Use prescribed Red River flow but calculate ORCC flows.
RonFormatORCC = 1
# Selects the input data file based on the chosen format.
if RonFormat == 1:
    dataFile = 'new_data_RF.csv' 
    if Eflows == 1:
        dataFile = 'data_RF_V4wEflows2.csv' 
        print('Eflow Analysis Selected')
elif RonFormat == 2:
    dataFile = 'Flow_TimeSeries_new.csv' 
    if Eflows == 1:
        # dataFile = 'Flow_TimeSeries_newwEflows.csv' 
        print('Eflow NOT implemented for RonFormat == 2 ')
else:
    dataFile = 'data.csv'
    
# Select whether to use a water year (starts Oct 1) or calendar year (starts Jan 1). (1=water year, 0=calendar year).
WY = 1
# Sets the base date for the time series and reads the appropriate Ohio/MMR split data.
if WY == 1:
  base_date = datetime(2000,10,1,0,0) 
  ohioSplit =  pd.read_csv('ohio_split_wyV2.csv')
else:
  base_date = datetime(2000,1,1,0,0)
  ohioSplit = pd.read_csv('ohio_split_cy.csv')
# Number of time series to generate.
Num_TimeSeries = 1

#<<<<<<   BOOKKEEPING AND LESS IMPORTANT STUFF
# Name of the empty .dss template file.
emptyDSS = 'empty'
# Name for the new .dss file that will be created.
newDSS =        'NEW'
# Not used in the current script version.
timeColumn =    'Trib_0_T'
dataColumn =    'Trib_0_Q'
# Flag to calculate tributary flows for the LMR (should likely remain 1).
TribCalc = 1 
# Flag to calculate flows for the lower passes of the LMR (should likely remain 1).
PassCalc = 1 

## __________________________________________________________________________________________________
## __________________________________________________________________________________________________


#--------------------------  3. FLOW PARTITIONING COEFFICIENTS ------------------------------------------------
# This section defines the constants used to partition flow throughout the river system.
# These coefficients are derived from historical data or previous hydraulic modeling studies.
## __________________________________________________________________________________________________
## __________________________________________________________________________________________________

# Naming convention: Coeff_LocationA_LocationB converts discharge at Location A to discharge at Location B.
# Tarbert Landing = TL
# Union Point = UP
# Middle Mississippi River = MMR

# Converts discharge from Union Point to Tarbert Landing.
UnionPoint_TarbertLanding = 0.764089

# Coefficients to estimate MMR (Thebes) discharge from Tarbert Landing (TL) or Union Point (UP).
TL_MMR =  0.457126  
UP_MMR = 0.352646 
# Coefficients to estimate Ohio River (Olmsted) discharge from TL or UP.
TL_Ohio = 0.56002
UP_Ohio = 0.432026
# Coefficients to estimate the contribution of minor tributaries from TL or UP.
TL_MinorTribs = 0.279125
UP_MinorTribs = 0.156022
# Coefficients to estimate "Latitude Flow" (flow at the latitude of Red River Landing) from TL or UP.
TL_LatFlow = 1.43
UP_LatFlow = 1.10219
# Coefficients to estimate Red River discharge from TL or UP.
TL_RedRiver = 0.132
UP_RedRiver = 0.10219

# Distribution of flow among the minor tributaries.
MinorTribs_UpperTribs = 0.0625          # Homochitto River and others.
MinorTribs_MiddleTribs = 0.505          # Arkansas and White Rivers.
MinorTribs_LowerTribs = 0.432           # Yazoo River and others.

# Binary (on/off) diversion extractions.
DiversionExtractionTrig = 300000        # Discharge (cfs) above which these diversions are activated.
DavisPondMax = -3055                    # Maximum diversion at Davis Pond (cfs, negative for extraction).
CaernarvonMax = -1742                   # Maximum diversion at Caernarvon (cfs).
LMR_SiphonsMax = -2000                  # Maximum diversion for LMR siphons (cfs).

# Lower Pass extraction rating curves. These define how much flow is lost to smaller distributary channels.
# Logarithmic models of the form: Q_out = A * log(Q_in) - B
# Mardi Gras Pass
MG_A = 24000
MG_B = 325029
# Point a la Hache
PALH_A =52877
PALH_B =715899

# Linear models of the form: Q_out = A * Q_in - B
# Ostrica and Neptune Passes
OstNep_A = 0.1043            
OstNep_B = 8130
# Fort Saint Phillip
FSP_A = 0.1412
FSP_B = 38667
# Baptist Collette
BapCol_A = 0.1124
BapCol_B = 1365
# Grand Pass
GP_A = 0.0821
GP_B = 9377
# Cubits Gap and West Bay
CGWB_A =0.1683 
CGWB_B = 9122

# NOTE: Pass A Loutre and South Pass extractions are calculated directly in the code, not with these coefficients.

 ## __________________________________________________________________________________________________
 ## __________________________________________________________________________________________________


 #--------------------------  4. FUNCTION DEFINITIONS ------------------------------------------------
 # This section defines reusable functions, primarily for data smoothing.
 ## __________________________________________________________________________________________________
 ## __________________________________________________________________________________________________                   

# This is a utility function used by the Whittaker smoother.
def speyediff(N, d, format='csc'):
    """
    Construct a d-th order sparse difference matrix.
    This matrix is used to calculate the differences between adjacent elements in a data series,
    which is a key part of the smoothing algorithm.
    """
    
    assert not (d < 0), "d must be non negative"
    shape     = (N-d, N)
    diagonals = np.zeros(2*d + 1)
    diagonals[d] = 1.
    for i in range(d):
        diff = diagonals[:-1] - diagonals[1:]
        diagonals = diff
    offsets = np.arange(d+1)
    spmat = sparse.diags(diagonals, offsets, shape, format=format)
    return spmat

def whittaker_smooth(y, lmbd, d = 2):
    """
    Implementation of the Whittaker smoothing algorithm. This function smooths a time series
    by balancing fidelity to the data with the roughness of the smoothed curve.
    
    The larger the 'lmbd' (lambda) parameter, the smoother the resulting data will be.
    """
    m = len(y)
    E = sparse.eye(m, format='csc') # Identity matrix
    D = speyediff(m, d, format='csc') # Difference matrix
    # This sets up the linear system to be solved for the smoothed data.
    coefmat = E + lmbd * D.conj().T.dot(D) 
    # Solves the system to get the smoothed data vector 'z'.
    z = splu(coefmat).solve(y)
    return z   

 ## __________________________________________________________________________________________________
 ## __________________________________________________________________________________________________


 #--------------------------  5. INITIAL BOOKKEEPING ------------------------------------------------
 # This section prepares the environment for the simulation, such as creating output folders and setting up the DSS file.
 ## __________________________________________________________________________________________________
 ## __________________________________________________________________________________________________  

## GET CURRENT TIME --- make output folder to hold metadata and results.
current_time = datetime.now()
print("Calculation time recorded as "+ current_time.strftime("%Y-%m-%d %H:%M:%S"))
folder2write = 'output '+current_time.strftime("%Y%m%d_%H%M%S")
os.makedirs(folder2write) 

## ------------ DSS PREPROCESSING
# HEC-DSS requires specific pathnames to store data. This section sets up those path components.
# The 'pathname' identifies a specific data record in the DSS file.
if TimeSeriesType  == 1:
    dataTypeA = 'IRREGULAR'    # A-part: Data type (e.g., IRREGULAR for irregular time steps)
elif TimeSeriesType == 2:
    dataTypeA = 'IRREGULAR'
elif TimeSeriesType == 3:
    dataTypeA = 'IRREGULAR'        
dataTypeB = 'TL'   # B-part: Location or parameter name (e.g., Tarbert Landing Q)
dataTypeC = 'FLOW'         # C-part: Data parameter (e.g., FLOW)
interval = '1DAY'         # E-part: Time interval (e.g., 1DAY)
identifier = 'placeholder' # F-part: Scenario or run identifier

# Additional information for the DSS record.
units = 'cfs' # Units of the data.

# A counter used to ensure an Excel file is written only once.
excelswritten = 0 

# Defines the working directory and creates a new DSS file by copying an empty template if it doesn't already exist.
cwd = os.getcwd()
if os.path.exists(os.path.join(cwd,newDSS+'.dss')) == False:
    copyfile(emptyDSS+'.dss', newDSS+'.dss')
    print('writing new DSS file: '+newDSS+'.dss')
dss_file = newDSS+'.dss'


 ## __________________________________________________________________________________________________
 ## __________________________________________________________________________________________________


 #------------------------6. TIME SERIES GENERATION LOOPS ------------------------------------------------
 # This is the main part of the script where the discharge time series are generated and processed.
 ## __________________________________________________________________________________________________
 ## __________________________________________________________________________________________________  



## <<<<<<<<<<<<<<<<<<<<<<<< 6.2 LOOP FOR OBSERVED HYDROGRAPH GENERATION (TimeSeriesType 3)
# This section does not generate a synthetic hydrograph. Instead, it reads a historical/observed time series
# from the input file and applies all the same operational logic (ORCC, spillways, etc.) to it.
if TimeSeriesType == 3:
    k = 00
    # Create the unique identifier for this run.
    identifier_ = 'TST'+str(TimeSeriesType)+'_'+'WY'+str(WY)+'S'+str(filter_TS)+'_OR'+str(ORCC_Ratio)+str(ORCC_Ratio_RisingLimb)+str(ORCC_Ratio_FallingLimb)+str(ORCC_Ratio_LowWater)+'BC'+MBCName+'_RF'+str(RonFormat)+str(RonFormatORCC)+'_'+str(k)
    identifier = identifier_.replace(".","")
    print('currently processing ' + identifier)
    
    #__________________________________________________________________________________________
    # Import the main observed flow time series.
    
    if Run_QAQC_Tests == 1:
        print('--- RUNNING QAQC TEST MODE ---')
        # Generate a synthetic hydrograph (365 days)
        test_dates = pd.date_range(start=base_date, periods=365, freq='D')
        
        # Create a discharge curve that sweeps from 50k to 2.5M to hit all thresholds
        t = np.arange(365)
        test_discharge = 50000 + 1450000 * (np.sin(t * np.pi / 180)**2)
        test_flood_spike = np.exp(-((t - 180) / 10)**2) * 1000000
        test_discharge += test_flood_spike
        
        # Create Red River logic. Normal is ~50k. Drop it during rising limb to force headconst.
        test_red_river = np.full(365, 50000.0)
        test_red_river[80:100] = 20000.0 # Drop below RRStageThres to force headconst
        
        df = pd.DataFrame({
            'date': test_dates,
            'DOY': test_dates.dayofyear,
            'discharge': test_discharge,
            'Red_River': test_red_river,
            'ORCC': test_discharge * 0.25, # Arbitrary target for tests
            'state': np.zeros(365) # For HydroTool RL compatibility
        })
        df['year'] = df['date'].dt.year
        
        if RonFormat >= 1:
            Rons_ORCC = df['ORCC'].copy(deep=True)
            if RonFormat == 2:
                state_col = df['state'].copy(deep=True)
            df = df[['date','DOY','discharge','Red_River','year']]
        else:
            df = df[['date','DOY','discharge','year']]
            
    if Run_QAQC_Tests == 0 and RonFormat == 0: # Original format
        df = pd.read_csv (dataFile)
        df['DOY']=pd.to_datetime(df['date']).dt.dayofyear
        df = df[['date','DOY','discharge']]
        df['date'] = pd.to_datetime(df['date'])
        df['year'] = df['date'].dt.year

    if Run_QAQC_Tests == 0 and RonFormat == 1: # "Ron Format" with Union Point Q and Red River Q
        df = pd.read_csv(dataFile)
        df['DOY']=pd.to_datetime(df['date']).dt.dayofyear
        Rons_ORCC = df['ORCC'].copy(deep=True)
        if Eflows == 1:
            Eflow_ORCC = df['Eflows'].copy(deep=True) # E-flow targets for ORCC.
        df = df[['date','DOY','discharge','Red_River']]
        df['date'] = pd.to_datetime(df['date'])
        df['year'] = df['date'].dt.year
        # Note: In this mode, 'discharge' is kept as Union Point Q, not converted to Tarbert Landing.
        
    if Run_QAQC_Tests == 0 and RonFormat == 2: # HydroTool output with state column and different date header
        df = pd.read_csv(dataFile)
        
        # Determine the simulation dates
        if 'date' not in df.columns:
            print("Warning: Simulated time period is not defined")
            if 'Flow Date' in df.columns:
                start_date = pd.to_datetime(df['Flow Date'].iloc[0])
            else:
                start_date = base_date
            df['date'] = pd.date_range(start=start_date, periods=len(df), freq='D')
        else:
            df['date'] = pd.to_datetime(df['date'])
            
        df['DOY'] = df['date'].dt.dayofyear
        
        # Load ORCC from sim or original depending on what's available
        if 'ORCC_sim' in df.columns:
            Rons_ORCC = df['ORCC_sim'].copy(deep=True)
        elif 'ORCC' in df.columns:
            Rons_ORCC = df['ORCC'].copy(deep=True)
            
        if Eflows == 1 and 'Eflows' in df.columns:
            Eflow_ORCC = df['Eflows'].copy(deep=True)
            
        # Store state column if it exists for risLimb calculation later
        if 'state' in df.columns:
            state_col = df['state'].copy(deep=True)
            
        # keep standard columns
        df = df[['date','DOY','discharge','Red_River']]
        df['date'] = pd.to_datetime(df['date'])
        df['year'] = df['date'].dt.year
                                    
    # Set up the output DataFrame and identify the hydrograph limbs
    outData = df.copy(deep=True)
    tempQ_A = outData['discharge'].copy(deep=True)
    tempQ = outData['discharge'].copy(deep=True)

    # <<<< Identify Rising Limb in Hydrograph 
    #create risLimb array with '1'=rise '2'=fall '3'=low water
    risLimb = np.zeros(len(tempQ_A))
    headconst = np.zeros(len(tempQ_A))
    inflood = 0
    crestCTR = 0
    
    # If we imported a state column from HydroTool, use it (and translate it if needed)
    if RonFormat == 2 and useHydroToolRL == 1 and 'state' in locals():
        # HydroTool states: 1 = rising, 2 = falling, 0 = baseline.
        # This script uses 3 for low water. We will map HydroTool states directly:
        risLimb = state_col.values
    else:
        # Otherwise calculate it the traditional way
        for ctrRL in range(rlAvgPer,len(tempQ_A)):
            preQ = np.mean(tempQ_A[ctrRL-rlAvgPer:ctrRL-1])
            
            #RISE
            if tempQ_A[ctrRL] > preQ + rlThres and tempQ_A[ctrRL] > rl_minQ:
                risLimb[ctrRL] = 1  
                inflood = 1
            #Flood crest
            elif tempQ_A[ctrRL] > rl_minQ and inflood == 1 and tempQ_A[ctrRL] <= preQ + rlThres:
                if crestCTR < crestMaxLength:
                    risLimb[ctrRL] = 1
                else:
                    risLimb[ctrRL] = 1.5
                crestCTR = crestCTR + 1
            #Flood Falling
            elif np.mean(tempQ_A[ctrRL-7:ctrRL-1]) > tempQ_A[ctrRL] and np.mean(tempQ_A[ctrRL-6:ctrRL]) > rl_minQs and inflood == 1:
                risLimb[ctrRL] = 2
                crestCTR = 0
            #Low water
            elif np.mean(tempQ_A[ctrRL-6:ctrRL]) < rl_LowWater:
                risLimb[ctrRL] = 3
                inflood = 0
            else:
                risLimb[ctrRL] = 0
                inflood = 0
                crestCTR = 0
                
            #Head constraint present?
            if consider_head == 1:
                if tempQ_A[ctrRL] > preQ + rlThres and tempQ_A[ctrRL] < rl_minQ and df['Red_River'].values[ctrRL] < RRStageThres:
                    headconst[ctrRL] = 1
            
#_____________________________________________________________________ 
# PARTION INFLOWS AND OUTFLOWS BASED ON MAIN DISCHARGE TIME SERIES
#_____________________________________________________________________ 

    if TribCalc == 1:
        
        # MAKE OUTFLOWS NEGATIVE VALUES
        DirCof = -1 
        
        #<<<< DEFINE LARGE TRIBUTARY DISCHARGES
        
        #Create variable MMR/Ohio ratios from observed matrix in file
        temp = df['date'].copy(deep=True)
        Oratio = np.zeros([len(temp),5])
        
        #Create FIRST discharge split before looping through time series
        #to use observed seasonal splits
        if FlowSplitType == 1:
            season = random.randint(0,29)
            yeari = temp.dt.year[0]
            moni = temp.dt.month[0]
            
            #Get combined split from data file
            Oratio[0,0] = ohioSplit[str(moni)].values[season]
            #Calculate Ohio River split
            Oratio[0,1] = 1 / (1 + Oratio[0,0])
            #Calculate MMR split
            Oratio[0,2] = Oratio[0,1] * Oratio[0,0]
            #Record time metadata for debugging
            Oratio[0,3] = moni
            Oratio[0,4] = season
        #to use temporalloy averaged seasonal splits    
        elif FlowSplitType == 0:
            moni = temp.dt.month[0]
            
            #Get combined split from data file
            Oratio[0,0] = np.mean(ohioSplit[str(moni)].values[:])
            #Calculate Ohio River split
            Oratio[0,1] = 1 / (1 + Oratio[0,0])
            #Calculate MMR split
            Oratio[0,2] = Oratio[0,1] * Oratio[0,0]
            #Record time metadata for debugging
            Oratio[0,3] = moni
            Oratio[0,4] = 999
        
        #PROGRESS REPORT
        progresstrackerA = round(len(temp)/10) 
        doneSoFar = 10
        
        #Create all subsequent discharge splits while looping through time series
        if FlowSplitType == 1:
            for ctrOs in range(1,len(temp)):
                
                #PROGRESS REPORT
                if progresstrackerA > 0 and ctrOs % progresstrackerA == 0:
                    print('Assigning MMROhio Ratios is '+str(doneSoFar)+' % finished')
                    doneSoFar = doneSoFar + 10
    
                if temp.dt.year[ctrOs] != yeari:
                    season = random.randint(0,29)
                yeari = temp.dt.year[ctrOs]
                moni = temp.dt.month[ctrOs]
                Oratio[ctrOs,0] = ohioSplit[str(moni)].values[season]
                #Calculate Ohio River split
                Oratio[ctrOs,1] = 1 - Oratio[ctrOs,0]
                #Calculate MMR split
                Oratio[ctrOs,2] = Oratio[ctrOs,0]
                #Record time metadata for debugging
                Oratio[ctrOs,3] = moni
                Oratio[ctrOs,4] = season
                
        elif FlowSplitType == 0:  
            for ctrOs in range(1,len(temp)):
                
                #PROGRESS REPORT
                if progresstrackerA > 0 and ctrOs % progresstrackerA == 0:
                    print('Assigning MMROhio Ratios is '+str(doneSoFar)+' % finished')
                    doneSoFar = doneSoFar + 10
    
                moni = temp.dt.month[ctrOs]
                Oratio[ctrOs,0] = np.mean(ohioSplit[str(moni)].values[:])
                #Calculate Ohio River split
                Oratio[ctrOs,1] = 1 - Oratio[ctrOs,0]
                #Calculate MMR split
                Oratio[ctrOs,2] = Oratio[ctrOs,0]
                #Record time metadata for debugging
                Oratio[ctrOs,3] = moni
                Oratio[ctrOs,4] = 999
        
        del temp    
  
        #__________________________________________________________________
        #calculate ANNUAL variation in inflow partitioning       
        temp = df.groupby('year')['discharge'].mean()
        temp = temp.to_frame()
        temp = temp.reset_index()
        RFA = np.zeros(len(temp))
        RFB = np.zeros(len(temp))
        
        for ctrRF in range(len(temp)-1):
            #random flux A is bounded by observed standard deviation of the observed deviance
            RFA[ctrRF] = temp['discharge'].values[ctrRF] * random.uniform(-MMROhio_RFL,MMROhio_RFL)
            #random flux B is bounded by 1/2 observed standard deviation of the observed deviance
            RFB[ctrRF] = temp['discharge'].values[ctrRF] * random.uniform(-MMROhio_RFL*0.5, MMROhio_RFL*0.5)
        temp['RandomFlux_A']  = RFA 
        temp['RandomFlux_B'] = RFB
        
        #Create 'temp_RF' dataframe to log random flux values for debugging
        temp_RF = pd.merge(outData,temp, on='year', how='left')
        
        #-----This approach uses temprally dynamic flow splits based on input data file
        
        if RonFormat >= 1:
            rawMMROhioQ = tempQ_A * (UP_MMR +  UP_Ohio)
        elif RonFormat == 0:
            rawMMROhioQ = tempQ_A * (TL_MMR +  TL_Ohio)
        outData['Thebes'] = (rawMMROhioQ  * Oratio[:,2]) + temp_RF['RandomFlux_A'] + temp_RF['RandomFlux_B']/2
        outData['Ohio'] = (rawMMROhioQ  * Oratio[:,1]) - temp_RF['RandomFlux_A']  + temp_RF['RandomFlux_B']/2        
        
        #____________________________________________________________________________
        #<<<<<<<<<ENSURE THAT FLOW DOES NOT DROP BEYOND USER SET THRESHOLD = MMROhio_low
        equilizer = np.zeros(len(outData))
        thebes_vals = outData['Thebes'].values.copy()
        ohio_vals = outData['Ohio'].values.copy()
        for i in range(len(outData)-1):
            if thebes_vals[i] < MMROhio_low:
                equilizer[i] = MMROhio_low - thebes_vals[i] 
                thebes_vals[i] = thebes_vals[i] + equilizer[i]
                ohio_vals[i] = ohio_vals[i] - equilizer[i]
            elif ohio_vals[i] < MMROhio_low:
                equilizer[i] = MMROhio_low - ohio_vals[i] 
                thebes_vals[i] = thebes_vals[i] - equilizer[i]
                ohio_vals[i] = ohio_vals[i] + equilizer[i]
        outData['Thebes'] = thebes_vals
        outData['Ohio'] = ohio_vals

        outData['Combined_Inflows'] = outData['Thebes'] + outData['Ohio']  
        if RonFormat >= 1:
            #WRITE ADDITIONAL TRIBUTARY INFLOW TIME SERIES
            outData['LMR_Tribs'] = (tempQ_A * UP_MinorTribs) - temp_RF['RandomFlux_B'] 
            #WRITE ADDITIONAL USEFUL TIME SERIES                
            outData['Lat_Flow'] = tempQ_A * UP_LatFlow
        elif RonFormat == 0:
            #WRITE ADDITIONAL TRIBUTARY INFLOW TIME SERIES
            outData['LMR_Tribs'] = (tempQ_A * TL_MinorTribs) - temp_RF['RandomFlux_B'] 
            #WRITE ADDITIONAL USEFUL TIME SERIES                
            outData['Lat_Flow'] = tempQ_A * TL_LatFlow
                                 
        #________________________________________________________________________________
        #<<<< ----------- DEFINE LARGE TRIBUTARY DISCHARGES
        
        #BIRDS POINT / NEW MADRID FLOODWAY OPERATIONS
        bp = np.zeros(len(outData))
        nm = np.zeros(len(outData))
                    
        #This code adds a partial lag to some of the flow as it passes thru the floodway
        for ctr2 in range(len(outData)):
            
            if outData['Combined_Inflows'].values[ctr2] > BPthres:
                bp[ctr2] = outData['Combined_Inflows'].values[ctr2] - BPthres
                
                if (ctr2 + bpnmLag + 7 + 1) < len(outData):
                    # FIX: Normalized return coefficients to sum to 1.0 (previously summed to 2.0, creating water)
                    nm[ctr2 + bpnmLag] = bp[ctr2] * 0.50 * bpnmEff 
                    nm[ctr2 + bpnmLag + 1] = bp[ctr2] * 0.25 * bpnmEff 
                    nm[ctr2 + bpnmLag + 2] = bp[ctr2] * 0.10 * bpnmEff
                    nm[ctr2 + bpnmLag + 3] = bp[ctr2] * 0.05 * bpnmEff
                    nm[ctr2 + bpnmLag + 4] = bp[ctr2] * 0.05 * bpnmEff
                    nm[ctr2 + bpnmLag + 5] = bp[ctr2] * 0.025 * bpnmEff
                    nm[ctr2 + bpnmLag + 6] = bp[ctr2] * 0.015 * bpnmEff
                    nm[ctr2 + bpnmLag + 7] = bp[ctr2] * 0.01 * bpnmEff      
                
        outData['BirdsPoint'] = bp * DirCof 
        outData['NewMadrid'] = nm
        

        #________________________________________________________________________________
        # <<<----  ORCC OPERATIONS
        hp = np.zeros(len(outData))
        ls = np.zeros(len(outData))
        aux = np.zeros(len(outData))
        overb = np.zeros(len(outData))
        BCMG_Excess = np.zeros(len(outData))
        Tarbert_Flow = np.zeros(len(outData))
        
        # DEFINE RED RIVER Q & ORCC total
        if RonFormatORCC == 0:
            RedRiver = tempQ_A * TL_RedRiver
            ORCC = tempQ_A * 0 #<== This should be written over in code just below
        if RonFormatORCC >= 1:    
            RedRiver = outData['Red_River'].copy(deep=True)
            ORCC = np.array(Rons_ORCC)
            #If Eflow Analysis, give preference to Eflow ORCC ratios
            if Eflows == 1 and 'Eflow_ORCC' in locals():
                
                temp = []
                eflow_miss = 0
                for eflowi in range(len(tempQ_A)):
                    
                    #Convert Eflow Target to ORCC Target
                    ORCC_Target = Eflow_ORCC[eflowi] - RedRiver[eflowi]
                    #Make sure Eflow is a plausible alternative ORCC flow
                    if (1250000 < (tempQ_A[eflowi] -  ORCC_Target) and (tempQ_A[eflowi] -  ORCC_Target) < 150000) or ORCC_Target < 100000:
                        temp.append(Rons_ORCC[eflowi])
                        eflow_miss = eflow_miss + 1
                    else:
                        temp.append(ORCC_Target)
                ORCC = np.array(temp)
                print('Days when Eflows were not possible = '+str(eflow_miss))
                                             
            
        #<<<--- Loop through time series to operate ORCC based on local flow conditions
        for ctr3 in range(len(outData)):
            
            #ORCC Ratio calulated based on Tarbert Landing
            if RonFormat == 0:
                if RonFormatORCC == 0 or RonFormatORCC == 2:
                    if risLimb[ctr3] == 0:
                        ORCC[ctr3] = tempQ_A[ctr3] * (1/ORCC_Ratio - 1) - RedRiver[ctr3]
                    elif risLimb[ctr3] == 1 or risLimb[ctr3] == 1.5:
                        ORCC[ctr3] = tempQ_A[ctr3] * (1/ORCC_Ratio_RisingLimb - 1) - RedRiver[ctr3]
                    elif risLimb[ctr3] == 2:
                        ORCC[ctr3] = tempQ_A[ctr3] * (1/ORCC_Ratio_FallingLimb - 1) - RedRiver[ctr3]
                    elif risLimb[ctr3] == 3:
                        ORCC[ctr3] = tempQ_A[ctr3] * (1/ORCC_Ratio_LowWater - 1) - RedRiver[ctr3]
                        
                    if headconst[ctr3] == 1:
                        ORCC[ctr3] = tempQ_A[ctr3] * (1/ORCC_Ratio_HeadConst - 1) - RedRiver[ctr3]
                        
                Tarbert_Flow[ctr3] = tempQ_A[ctr3]
                
            #ORCC Ratio calulated based on Union Point
            elif RonFormat >= 1:
                if RonFormatORCC == 0 or RonFormatORCC == 2:
                    if risLimb[ctr3] == 0:
                        ORCC[ctr3] = (tempQ_A[ctr3] + RedRiver[ctr3]) * (1 - ORCC_Ratio) - RedRiver[ctr3]
                    elif risLimb[ctr3] == 1 or risLimb[ctr3] == 1.5:
                        ORCC[ctr3] = (tempQ_A[ctr3] + RedRiver[ctr3]) * (1 - ORCC_Ratio_RisingLimb ) - RedRiver[ctr3]
                    elif risLimb[ctr3] == 2:
                        ORCC[ctr3] = (tempQ_A[ctr3] + RedRiver[ctr3]) * (1 - ORCC_Ratio_FallingLimb) - RedRiver[ctr3]
                    elif risLimb[ctr3] == 3:
                        ORCC[ctr3] = (tempQ_A[ctr3] + RedRiver[ctr3]) * (1 -ORCC_Ratio_LowWater) - RedRiver[ctr3]
                        
                    if headconst[ctr3] == 1:
                        ORCC[ctr3] = (tempQ_A[ctr3] + RedRiver[ctr3]) * (1 - ORCC_Ratio_HeadConst) - RedRiver[ctr3]
                        
                # Compute preliminary Tarbert_Flow for ORCCOverride threshold check
                Tarbert_Flow[ctr3]= tempQ_A[ctr3] - ORCC[ctr3] 

            # Save the preliminary ORCC to determine how much it changes due to constraints
            ORCC_pre_constraints = ORCC[ctr3]

            #If override is active, divert excess flow down ORCC instead of BC/MORG
            if ORCCOverride == 1:
                
                if Tarbert_Flow[ctr3] > MorBCthres :
                    BCMG_Excess[ctr3] = Tarbert_Flow[ctr3]- MorBCthres
                    ORCC[ctr3] = ORCC[ctr3] + BCMG_Excess[ctr3]
            
            #Ensure that ORCC does not pass > PDF
            if ORCC[ctr3] > ORCC_Max_Total:
                ORCC[ctr3] = ORCC_Max_Total
            
            #Ensure that Hydropower has enough flow for min operations
            if ORCC[ctr3] < HydroPow_Min:
                ORCC[ctr3] = HydroPow_Min
            
            # FIX: Adjust Tarbert_Flow by the amount ORCC was capped, floored, or overridden.
            # This perfectly conserves volume for both RonFormat == 0 (where Tarbert_Flow starts 
            # as the observed value) and RonFormat >= 1 (where it starts as a mass balance).
            Tarbert_Flow[ctr3] = Tarbert_Flow[ctr3] + (ORCC_pre_constraints - ORCC[ctr3])
                       
            #This adds a random daily flux to some of the ORCC operations to simulate daily uncertainities
            randomflux = random.uniform(-ORCC_RFL, ORCC_RFL) * ORCC[ctr3]
            
            #ORCC operations at LOW FLOW
            if Tarbert_Flow[ctr3] < Low_to_Mod:
                
                if ORCC[ctr3] <= HydroPow_CapA:
                    hp[ctr3] = ORCC[ctr3] * 1.0 
                    ls[ctr3] = ORCC[ctr3] * 0.0
                    aux[ctr3] = ORCC[ctr3] * 0.0 
                    overb[ctr3] =  ORCC[ctr3] * 0.0 
                else:
                    hp[ctr3] = HydroPow_CapA
                    ls[ctr3] = ORCC[ctr3] * 0.0
                    aux[ctr3] = ORCC[ctr3] - HydroPow_CapA
                    overb[ctr3] =  ORCC[ctr3] * 0.0 

            #ORCC operations at Moderate FLOW                    
            elif Tarbert_Flow[ctr3] < Mod_to_High:
                
                if ORCC[ctr3] <= HydroPow_CapA:
                    hp[ctr3] = ORCC[ctr3] * 1.0 
                    ls[ctr3] = ORCC[ctr3] * 0.0 
                    aux[ctr3] = ORCC[ctr3] * 0.0 
                    overb[ctr3] =  ORCC[ctr3] * 0.0 
                    
                else:
                
                    hp[ctr3] = HydroPow_CapA 
                    excess_flow = ORCC[ctr3] - HydroPow_CapA
                    
                    if excess_flow <= Lowsill_Cap:
                        overb[ctr3] =  ORCC[ctr3] * 0.0     
                        #Rising Limb operation matrix
                        if risLimb[ctr3] == 1:                                           
                            ls[ctr3] = excess_flow * dominateValue + randomflux
                            aux[ctr3] = excess_flow * subservientValue - randomflux
                        else:
                            ls[ctr3] = excess_flow * subservientValue + randomflux
                            aux[ctr3] = excess_flow * dominateValue - randomflux
                            
                        if headconst[ctr3] == 1: 
                            ls[ctr3] = excess_flow 
                            aux[ctr3] = 0
                         
                    elif excess_flow > Lowsill_Cap and excess_flow <= (Lowsill_Cap + Overbank_Cap):
                        overb[ctr3] =  excess_flow  - Lowsill_Cap    
                        #Rising Limb operation matrix
                        if risLimb[ctr3] == 1:                                           
                            ls[ctr3] = Lowsill_Cap * dominateValue + randomflux
                            aux[ctr3] = Lowsill_Cap * subservientValue  - randomflux
                        else:
                            ls[ctr3] = Lowsill_Cap * subservientValue + randomflux
                            aux[ctr3] = Lowsill_Cap * dominateValue - randomflux
                            
                        if headconst[ctr3] == 1: 
                            ls[ctr3] = Lowsill_Cap 
                            aux[ctr3] = 0
                            
                    elif excess_flow > (Lowsill_Cap + Overbank_Cap):
                        overb[ctr3] =  Overbank_Cap    
                        #Rising Limb operation matrix
                        if risLimb[ctr3] == 1:                                           
                            ls[ctr3] = Lowsill_Cap  + randomflux
                            aux[ctr3] =  excess_flow - (Lowsill_Cap + Overbank_Cap)- randomflux
                        else:
                            ls[ctr3] = excess_flow - (Lowsill_Cap + Overbank_Cap)+ randomflux
                            aux[ctr3] = Lowsill_Cap - randomflux
                            
                        if headconst[ctr3] == 1: 
                            # FIX: Changed from excess_flow - (Lowsill_Cap + Overbank_Cap) to
                            # excess_flow - Overbank_Cap to conserve volume (was losing Lowsill_Cap)
                            ls[ctr3] = excess_flow - Overbank_Cap 
                            aux[ctr3] = 0
                                
    
            #ORCC operations at High FLOW  
            elif Tarbert_Flow[ctr3] >= Mod_to_High:
                    hp[ctr3] = HydroPow_CapB
                    excess_flow = ORCC[ctr3] - HydroPow_CapB
                    
                    if excess_flow <= Lowsill_Cap:
                        overb[ctr3] =  ORCC[ctr3] * 0.0     
                        #Rising Limb operation matrix
                        if risLimb[ctr3] == 1:                                           
                            ls[ctr3] = excess_flow * dominateValue + randomflux
                            aux[ctr3] = excess_flow * subservientValue  - randomflux
                        else:
                            ls[ctr3] = excess_flow * subservientValue + randomflux
                            aux[ctr3] = excess_flow * dominateValue - randomflux
                            
                        if headconst[ctr3] == 1: 
                            ls[ctr3] = excess_flow 
                            aux[ctr3] = 0
                        
                            
                    elif excess_flow > Lowsill_Cap and excess_flow <= (Lowsill_Cap + Overbank_Cap):
                        overb[ctr3] =  excess_flow - Lowsill_Cap    
                        #Rising Limb operation matrix
                        if risLimb[ctr3] == 1:                                           
                            ls[ctr3] = Lowsill_Cap * dominateValue + randomflux
                            aux[ctr3] = Lowsill_Cap * subservientValue  - randomflux
                        else:
                            ls[ctr3] = Lowsill_Cap * subservientValue + randomflux
                            aux[ctr3] = Lowsill_Cap * dominateValue - randomflux
                            
                        if headconst[ctr3] == 1: 
                            ls[ctr3] = Lowsill_Cap 
                            aux[ctr3] = 0
                            
                    elif excess_flow > (Lowsill_Cap + Overbank_Cap):
                        overb[ctr3] =  Overbank_Cap    
                        #Rising Limb operation matrix
                        if risLimb[ctr3] == 1:                                           
                            ls[ctr3] = Lowsill_Cap  + randomflux
                            aux[ctr3] =  excess_flow - (Lowsill_Cap + Overbank_Cap)- randomflux
                        else:
                            ls[ctr3] = excess_flow - (Lowsill_Cap + Overbank_Cap) + randomflux
                            aux[ctr3] = Lowsill_Cap - randomflux
                            
                        if headconst[ctr3] == 1: 
                            # FIX: Changed from excess_flow - (Lowsill_Cap + Overbank_Cap) to
                            # excess_flow - Overbank_Cap to conserve volume (was losing Lowsill_Cap)
                            ls[ctr3] = excess_flow - Overbank_Cap
                            aux[ctr3] = 0     
                                       
        ##<<<<----- LOG ALL ORCC DATA INTO outData DATAFRAME
        outData['ORCC_HydroP'] = hp * DirCof 
        outData['ORCC_LowSill'] = ls * DirCof 
        outData['ORCC_Auxil'] = aux * DirCof 
        outData['overBank'] = overb * DirCof
        outData['ORCC_HydroP'] = outData['ORCC_HydroP'].apply(lambda x: 0 if x >= 0 else x)
        outData['ORCC_LowSill'] = outData['ORCC_LowSill'].apply(lambda x: 0 if x >= 0 else x)
        outData['ORCC_Auxil'] = outData['ORCC_Auxil'].apply(lambda x: 0 if x >= 0 else x)
        outData['overBank'] = outData['overBank'].apply(lambda x: 0 if x >= 0 else x)
        outData['Red_River'] = RedRiver
        
        #Morganza and Bonnet Carre Operations
        Morg = np.zeros(len(outData))
        BonCar = np.zeros(len(outData))
        
        for ctr4 in range(len(outData)):
            if Tarbert_Flow[ctr4] > MorBCthres:
                temp = Tarbert_Flow[ctr4] - MorBCthres
                if temp < BC_HighUseThreshold:
                    if BCOpStyle == 0:
                        BonCar[ctr4] = temp * BCUseRatio_Low
                        Morg[ctr4] = temp * (1 - BCUseRatio_Low)
                    else:
                        BonCar[ctr4] = temp 
                        Morg[ctr4] = 0                       
                else:
                    if BCOpStyle == 0:
                        BonCar[ctr4] = temp * BCUseRatio_High
                        Morg[ctr4] = temp * (1 - BCUseRatio_High)
                    else:
                        BonCar[ctr4] = MorganzaQThres 
                        Morg[ctr4] = temp - MorganzaQThres   
                        
         #________________________________________________________________________________
         # <<<----  MORGANZA AND BONNET CARRE OPERATIONS             
        outData['Morganza'] = Morg * DirCof 
        outData['BonnetCarre'] = BonCar * DirCof 

                        
         #________________________________________________________________________________
         # <<<----  LOWERMOST LMR PASS DISCHARGES 

        #CONTROLLED DIVERSIONS
        outData['Davis_Pond'] = np.where(tempQ_A < DiversionExtractionTrig, 0, DavisPondMax)
        outData['Caernarvon'] = np.where(tempQ_A < DiversionExtractionTrig, 0, CaernarvonMax)
        outData['Siphons'] = np.where(tempQ_A < DiversionExtractionTrig, 0, LMR_SiphonsMax)
         
        #LOWER PASS RATING CURVES
        LMQ = Tarbert_Flow - (Morg + BonCar - outData['Davis_Pond'].values - outData['Caernarvon'].values - outData['Siphons'].values )
        LMQ_pos = np.maximum(LMQ, 1.0)
        MG = (MG_A  * np.log(LMQ_pos) - MG_B) * DirCof 
        LMQ_MG_pos = np.maximum(LMQ + MG, 1.0)
        PALH = (PALH_A * np.log(LMQ_MG_pos) - PALH_B) * DirCof 
        OstNep = (OstNep_A * (LMQ + MG + PALH ) - OstNep_B)* DirCof 
        FSP = (FSP_A * (LMQ + MG + PALH + OstNep ) - FSP_B )* DirCof 
        BapCol = (BapCol_A * (LMQ + MG + PALH + OstNep + FSP ) - BapCol_B)* DirCof 
        GrandPass = (GP_A * (LMQ + MG + PALH + OstNep + FSP + BapCol ) - GP_B)* DirCof 
        CubitsGapWB = (CGWB_A* (LMQ + MG + PALH + OstNep + FSP + BapCol + GrandPass ) - CGWB_B)* DirCof 
        
        #Terminal Pass Calculations
        HOPQ = LMQ + MG + PALH + OstNep + FSP + BapCol + GrandPass + CubitsGapWB
        SWP = np.zeros(len(HOPQ))
        TermPass = np.zeros(len(HOPQ))
        for i in range(len(HOPQ)):
            if HOPQ[i] < 200000:
                SWP[i] = (7.5 * 10**-12) * HOPQ[i]**2 + (1.25 * 10**-6) * HOPQ[i] + 0.1
                TermPass[i] = (1 - SWP[i])/2 * HOPQ[i] * DirCof 
            else:
                SWP[i] = (6.0 * 10**-8) * HOPQ[i] + 0.6375
                TermPass[i] = (1 - SWP[i])/2 * HOPQ[i] * DirCof 
        
        ##<<<<----- LOG ALL LOWER PASSES DATA INTO outData DATAFRAME
        outData['MGP'] = MG
        outData['MGP'] = outData['MGP'].apply(lambda x: 0 if x >= 0 else x)
        outData['PALH'] = PALH
        outData['PALH'] = outData['PALH'].apply(lambda x: 0 if x >= 0 else x)
        outData['OstNep'] = OstNep
        outData['OstNep'] = outData['OstNep'].apply(lambda x: 0 if x >= 0 else x)
        outData['FSP'] = FSP
        outData['FSP'] = outData['FSP'].apply(lambda x: 0 if x >= 0 else x)
        outData['BapCol'] = BapCol
        outData['BapCol'] = outData['BapCol'].apply(lambda x: 0 if x >= 0 else x)
        outData['GrandPass'] = GrandPass
        outData['GrandPass'] = outData['GrandPass'].apply(lambda x: 0 if x >= 0 else x)
        outData['CubitsGapWB'] =CubitsGapWB
        outData['CubitsGapWB'] = outData['CubitsGapWB'].apply(lambda x: 0 if x >= 0 else x)
        
        ##<<<<----- LOG MINOR TRIB DATA INTO outData DATAFRAME
        #This is in an unexpected place because of where it sits in the outData file
        outData['Hatchie'] = outData['LMR_Tribs'] * MinorTribs_UpperTribs
        outData['Arkansas'] = outData['LMR_Tribs'] * MinorTribs_MiddleTribs
        outData['Yazoo'] = outData['LMR_Tribs'] * MinorTribs_LowerTribs
        #Terminal Passes = Pass A Loutre and South Pass (they are effectively the same)
        outData['Terminal_Passes'] = TermPass
        outData['Terminal_Passes'] = outData['Terminal_Passes'].apply(lambda x: 0 if x >= 0 else x)
        
        # Log SWP for mass balance QAQC
        outData['SWP_Flow'] = SWP * HOPQ * DirCof
        outData['SWP_Flow'] = outData['SWP_Flow'].apply(lambda x: 0 if x >= 0 else x)
        
        ##<<<<----- DEFINE STRUCTURE OF DSS OUTPUT
        outData_cols = ['discharge','Thebes','Ohio','LMR_Tribs','BirdsPoint','NewMadrid',
                        'ORCC_HydroP','ORCC_LowSill','ORCC_Auxil','overBank','Red_River',
                        'Morganza','BonnetCarre','Davis_Pond','Caernarvon','Siphons',
                        'MGP','PALH','OstNep','FSP','BapCol','GrandPass','CubitsGapWB',
                        'Hatchie','Arkansas','Yazoo','Terminal_Passes']
        tempn = ['TL_UP','Thebes','Ohio','Minor_Tribs','Birds_Point','NewMadrid','ORCC_HydroP','ORCC_LowSill','ORCC_Aux','ORCC_Overbank','RedRiver','Morganza','BonnetCarre','Davis_Pond','Caernarvon','Siphons','MGP','PALH','OstNep','FSP','BapCol','GP','CubitsGapWestBay','Hatchie','Arkansas','Yazoo','Terminal_Passes']

        for i in range(len(tempn)):
            columnName = outData_cols[i]
            nm = tempn[i]
            
            dataTypeB = nm
            pathname = "/"+dataTypeA+"/"+dataTypeB+"/"+dataTypeC+"//"+interval+"/"+identifier+"/"
            
            val = outData[columnName] if filter_TS == 0 else savgol_filter(outData[columnName], filter_sz, 3)
            inter = -1 if dataTypeA == 'IRREGULAR' else 1
            tsc = TimeSeriesContainer(pathname, len(val), inter)
            tsc.data_units = units
            tsc.data_type = "INST-VAL"
            tsc.values = np.array(val)
            if inter == -1:
                tsc.times = [d.strftime('%d%b%Y %H:%M:%S') for d in pd.to_datetime(outData['date'])]
            else:
                tsc.start_time = pd.to_datetime(outData['date']).iloc[0].strftime('%d%b%Y %H:%M:%S')
            
            with HecDss.Open(dss_file) as fid:
                status = fid.put_ts(tsc)  
   
                
###### WRITE ASSORTED OUTPUTS   
   
    #_____________________________________________________________________ 
    # Write out miscel excel file for debugging or transfering data to Atchafalaya model
    #_____________________________________________________________________ 

        #Write first output to an excel spreadsheet
        if RonFormat >= 1 and excelswritten == 0:
            excelswritten = 1
            
            exceldf = outData[['date','Red_River','ORCC_HydroP','overBank','ORCC_LowSill','ORCC_Auxil']]
            exceldf.insert(6,'Simmesport', ORCC + RedRiver)
            exceldf.insert(7,'TarbertLanding', Tarbert_Flow)
            exceldf.insert(8,'Rising_ID', risLimb)
            ExcelSheetName = datetime.now().strftime("%Y%m%d%H%M%S")
            exceldf.to_excel(folder2write+'/ForRon.xlsx', sheet_name=ExcelSheetName, index=False)
         
        #output a bunch of QAQC stuff
            Oratio_check = pd.DataFrame(Oratio)
            Oratio_check.to_csv(folder2write+'/'+"Oratio_check_"+folder2write+".csv")
            # outData_check = pd.DataFrame(outData)
            # outData_check.to_csv("outData_check.csv")
            temp_RF.to_csv(folder2write+'/'+"RandomFlux_check_"+folder2write+".csv")
            equlizer_check = pd.DataFrame(equilizer)
            equlizer_check .to_csv(folder2write+'/'+"equlizer_check_"+folder2write+".csv")
            
        #archive outData data frame
        outData.to_csv(folder2write+'/'+'outData_'+folder2write+'.csv', index=False)

        # QAQC Report Generation
        report_path = folder2write + '/' + 'QAQC_Report_' + identifier + '.txt'
        with open(report_path, 'w') as rep:
            rep.write(f"QAQC Report for {identifier}\n")
            rep.write(f"File written {current_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            rep.write("="*50 + "\n\n")
            rep.write("--- Run Configuration ---\n")
            rep.write(f"RonFormat: {RonFormat}\n")
            rep.write(f"Eflows: {Eflows}\n")
            rep.write(f"TimeSeriesType: {TimeSeriesType}\n")
            rep.write(f"Water Year (1=WY, 0=CY): {WY}\n\n")
            
            rep.write("--- Key Operational Thresholds ---\n")
            rep.write(f"Rising Limb Threshold (rlThres): {rlThres}\n")
            rep.write(f"Morganza/Bonnet Carre Threshold (MorBCthres): {MorBCthres}\n")
            rep.write(f"Birds Point Threshold (BPthres): {BPthres}\n")
            rep.write(f"Morganza Q Threshold (MorganzaQThres): {MorganzaQThres}\n\n")
            
            rep.write("--- ORCC Flow Splits ---\n")
            rep.write(f"ORCC_Ratio: {ORCC_Ratio}\n")
            rep.write(f"ORCC_Ratio_RisingLimb: {ORCC_Ratio_RisingLimb}\n")
            rep.write(f"ORCC_Ratio_FallingLimb: {ORCC_Ratio_FallingLimb}\n")
            rep.write(f"ORCC_Ratio_LowWater: {ORCC_Ratio_LowWater}\n\n")
            
            rep.write("--- Calculated Matrices Summary ---\n")
            rep.write(f"Mean MMR Split (Oratio[:,2]): {np.mean(Oratio[:,2]):.4f}\n")
            rep.write(f"Std MMR Split (Oratio[:,2]): {np.std(Oratio[:,2]):.4f}\n")
            rep.write(f"Total days Normal (risLimb=0): {np.sum(risLimb==0)}\n")
            rep.write(f"Total days Rising (risLimb=1): {np.sum(risLimb==1)}\n")
            rep.write(f"Total days Crest (risLimb=1.5): {np.sum(risLimb==1.5)}\n")
            rep.write(f"Total days Falling (risLimb=2): {np.sum(risLimb==2)}\n")
            rep.write(f"Total days Low Water (risLimb=3): {np.sum(risLimb==3)}\n")
            if Eflows == 1 and 'eflow_miss' in locals():
                rep.write(f"Eflow target misses: {eflow_miss}\n")
            rep.write(f"Random Flux A Mean: {np.mean(temp_RF['RandomFlux_A']):.2f}\n")
            rep.write(f"Random Flux B Mean: {np.mean(temp_RF['RandomFlux_B']):.2f}\n\n")
            
            # --- WATER BUDGET QAQC ---
            # ORCC Mass Balance
            sum_orcc_structures = np.abs(outData['ORCC_HydroP']) + np.abs(outData['ORCC_LowSill']) + np.abs(outData['ORCC_Auxil']) + np.abs(outData['overBank'])
            orcc_error = ORCC - sum_orcc_structures
            max_orcc_error = np.max(np.abs(orcc_error))
            
            # Lower River Mass Balance
            lower_river_out = (np.abs(outData['Morganza']) + np.abs(outData['BonnetCarre']) + 
                               np.abs(outData['Davis_Pond']) + np.abs(outData['Caernarvon']) + np.abs(outData['Siphons']) +
                               np.abs(outData['MGP']) + np.abs(outData['PALH']) + np.abs(outData['OstNep']) + 
                               np.abs(outData['FSP']) + np.abs(outData['BapCol']) + np.abs(outData['GrandPass']) + 
                               np.abs(outData['CubitsGapWB']) + np.abs(outData['SWP_Flow']) + 2 * np.abs(outData['Terminal_Passes']))
            lr_error = Tarbert_Flow - lower_river_out
            max_lr_error = np.max(np.abs(lr_error))
            
            rep.write("--- Water Budget QAQC ---\n")
            rep.write(f"Max ORCC Mass Balance Error (cfs): {max_orcc_error:.4f}\n")
            rep.write(f"Max Lower River Mass Balance Error (cfs): {max_lr_error:.4f}\n\n")
            
            rep.write("--- Original Script Header (Parameters Archive) ---\n")
            with open(__file__, 'r') as infile:
                for i, line in enumerate(infile):
                    if i < 300:
                        rep.write(line)
                    else:
                        break

        # QAQC Figure Generation
        fig, axs = plt.subplots(4, 1, figsize=(12, 16), sharex=True)
        dates = pd.to_datetime(outData['date'])
        
        # Panel 1: Main Inflows
        axs[0].plot(dates, outData['discharge'], label='Main Discharge', color='black')
        axs[0].plot(dates, outData['Red_River'], label='Red River', color='red')
        axs[0].plot(dates, outData['Ohio'], label='Ohio River', color='blue')
        axs[0].plot(dates, outData['Thebes'], label='Thebes (MMR)', color='green')
        axs[0].set_title('Main Inflows')
        axs[0].set_ylabel('Discharge (cfs)')
        axs[0].legend()
        axs[0].grid(True)
        
        # Panel 2: ORCC Operations
        axs[1].plot(dates, np.abs(outData['ORCC_HydroP']), label='HydroPower', color='blue')
        axs[1].plot(dates, np.abs(outData['ORCC_LowSill']), label='Low Sill', color='orange')
        axs[1].plot(dates, np.abs(outData['ORCC_Auxil']), label='Auxiliary', color='green')
        axs[1].plot(dates, np.abs(outData['overBank']), label='Overbank', color='red')
        axs[1].set_title('ORCC Operations')
        axs[1].set_ylabel('Discharge (cfs)')
        axs[1].legend()
        axs[1].grid(True)
        
        # Panel 3: Major Spillways
        axs[2].plot(dates, np.abs(outData['Morganza']), label='Morganza', color='purple')
        axs[2].plot(dates, np.abs(outData['BonnetCarre']), label='Bonnet Carre', color='cyan')
        axs[2].axhline(y=MorBCthres, color='r', linestyle='--', label='MorBC Threshold')
        axs[2].set_title('Major Spillways')
        axs[2].set_ylabel('Discharge (cfs)')
        axs[2].legend()
        axs[2].grid(True)
        
        # Panel 4: Lower Passes and Hydrograph State
        axs[3].plot(dates, np.abs(outData['MGP']), label='Main Gulf Pass', color='blue')
        axs[3].plot(dates, np.abs(outData['PALH']), label='Pass A Loutre / Head of Passes', color='green')
        axs[3].plot(dates, np.abs(outData['OstNep']), label='Oyster/Neptune', color='orange')
        axs[3].set_title('Lower Passes & Hydrograph State')
        axs[3].set_ylabel('Discharge (cfs)')
        axs[3].legend(loc='upper left')
        
        # Overlay hydrograph state colors
        ymin, ymax = axs[3].get_ylim()
        axs[3].fill_between(dates, ymin, ymax, where=(risLimb==1), color='red', alpha=0.1, label='Rising')
        axs[3].fill_between(dates, ymin, ymax, where=(risLimb==2), color='blue', alpha=0.1, label='Falling')
        axs[3].fill_between(dates, ymin, ymax, where=(risLimb==3), color='orange', alpha=0.1, label='Low Water')
        
        # Add secondary legend for background colors
        handles, labels = axs[3].get_legend_handles_labels()
        axs[3].legend(handles, labels, loc='upper right', bbox_to_anchor=(1.0, 1.0))
        
        plt.tight_layout()
        fig.savefig(folder2write + '/' + 'QAQC_Figure_' + identifier + '.png')
        plt.close(fig)

        # QAQC Water Budget Figure Generation
        fig2, axs2 = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
        
        # Panel 1: ORCC Mass Balance
        ax1 = axs2[0]
        ax1.plot(dates, ORCC, label='ORCC Target (Input)', color='black', linewidth=2)
        ax1.plot(dates, sum_orcc_structures, label='Sum of Structures (Output)', color='cyan', linestyle='--')
        ax1.set_title('ORCC Mass Balance')
        ax1.set_ylabel('Discharge (cfs)')
        ax1.grid(True)
        ax1.legend(loc='upper left')
        
        ax1_twin = ax1.twinx()
        ax1_twin.plot(dates, orcc_error, label='Error (Input - Output)', color='red', alpha=0.5)
        ax1_twin.set_ylabel('Error (cfs)', color='red')
        ax1_twin.tick_params(axis='y', labelcolor='red')
        ax1_twin.legend(loc='upper right')

        # Panel 2: Lower River Mass Balance
        ax2 = axs2[1]
        ax2.plot(dates, Tarbert_Flow, label='Tarbert Flow (Input)', color='black', linewidth=2)
        ax2.plot(dates, lower_river_out, label='Sum of Distributaries (Output)', color='orange', linestyle='--')
        ax2.set_title('Lower River Mass Balance')
        ax2.set_ylabel('Discharge (cfs)')
        ax2.grid(True)
        ax2.legend(loc='upper left')
        
        ax2_twin = ax2.twinx()
        ax2_twin.plot(dates, lr_error, label='Error (Input - Output)', color='red', alpha=0.5)
        ax2_twin.set_ylabel('Error (cfs)', color='red')
        ax2_twin.tick_params(axis='y', labelcolor='red')
        ax2_twin.legend(loc='upper right')
        
        plt.tight_layout()
        fig2.savefig(folder2write + '/' + 'QAQC_WaterBudget_' + identifier + '.png')
        plt.close(fig2)

        #_____________________________________________________________________
        # WATER LEVEL BOUNDARY CONDITIONS GENERATION
        #_____________________________________________________________________
        if Generate_WL == 1:
            print('Generating Water Level Boundary Conditions...')
            Seasonal_Adjustment = 1
            
            ## READ HOURLY OBSERVED WL FROM FILE
            hourly_data = pd.read_csv('WL_data.csv', names=['water_level'])
            szHourly_data = len(hourly_data)
            
            ## AVERAGE HOURLY DATA INTO DAILY DATA
            daily_data = []
            for i in range(12, szHourly_data - 12, 24):
                temp = hourly_data['water_level'].values[i-12:i+12].mean()
                daily_data.append(temp)
                
            msl = hourly_data['water_level'].values.mean()
            
            if Seasonal_Adjustment == 1:
                sa = pd.read_csv('Seasonal_Adjustment.csv', names=['month_num','adj_value']) 
                sa['variance'] = sa['adj_value'] - sa['adj_value'].mean()
                sa['std_var'] = sa['variance']/sa['adj_value'].mean()
            
            for SLRs in range(0, 4):
                print('Processing WL Data Series with SLR = ' + str(SLRs))
                identifier_wl = 'Obs_SLR' + str(SLRs) + 'SA' + str(Seasonal_Adjustment)
                
                dataTypeB_wl = 'TIMESERIES'
                dataTypeC_wl = 'STAGE'
                units_wl = 'ft NAVD88'
                
                dates = outData['date'].tolist()
                WL = []
                
                for datei in dates:
                    temp = random.sample(daily_data, 1)[0]
                    WL.append(temp)
                    
                WL_df = pd.DataFrame({'date': dates, 'water_level': WL})
                
                if Seasonal_Adjustment == 1:
                    WL_mod = []
                    for i in range(len(WL_df)):
                        moni = WL_df['date'].iloc[i].month
                        adj_val = sa[sa['month_num']==moni]['std_var'].values[0]
                        wl_modi = (adj_val * msl) + WL_df['water_level'].values[i]
                        WL_mod.append(wl_modi)
                    WL_df['water_level_adj'] = WL_mod
                
                if SLRs > 0:
                    if SLRs == 1:
                        SLR_daily = 0.027 / 365
                    elif SLRs == 2:
                        SLR_daily = 0.037 / 365
                    elif SLRs == 3:
                        SLR_daily = 0.057 / 365
                        
                    WL_mod_SLR = [0]
                    for i in range(1, len(WL_df)):
                        WL_mod_SLR.append(WL_mod_SLR[-1] + SLR_daily)
                        
                    if Seasonal_Adjustment == 1:
                        WL_df['water_level_final'] = WL_df['water_level_adj'] + WL_mod_SLR
                    else:
                        WL_df['water_level_final'] = WL_df['water_level'] + WL_mod_SLR
                else:
                    if Seasonal_Adjustment == 1:
                        WL_df['water_level_final'] = WL_df['water_level_adj']
                    else:
                        WL_df['water_level_final'] = WL_df['water_level']
                        
                if SLRs == 0:
                    output_wl = pd.DataFrame({'Date': WL_df['date']})
                
                column_name = 'SLR_' + str(SLRs)
                output_wl[column_name] = WL_df['water_level_final'].round(4)
                
                # write to DSS
                pathname_wl = "/IRREGULAR/" + dataTypeB_wl + "/" + dataTypeC_wl + "//1DAY/" + identifier_wl + "/"
                tsc = TimeSeriesContainer(pathname_wl, len(WL_df), -1)
                tsc.data_units = units_wl
                tsc.data_type = "INST-VAL"
                tsc.values = np.array(WL_df['water_level_final'])
                tsc.times = [d.strftime('%d%b%Y %H:%M:%S') for d in pd.to_datetime(WL_df['date'])]
                
                with HecDss.Open(dss_file) as fid:
                    status = fid.put_ts(tsc)
            
            ExcelSheetNameWL = datetime.now().strftime("%Y%m%d%H%M%S")
            output_wl.to_excel(folder2write + '/WaterLevels.xlsx', sheet_name=ExcelSheetNameWL, float_format="%.2f", index=False)

