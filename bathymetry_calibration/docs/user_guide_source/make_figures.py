"""Auditable, illustrative graphics for the Word guide; no project results."""
from pathlib import Path
import json
import sys
import time

import h5py
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.ticker import StrMethodFormatter

from guide_paths import ROOT, REPO
sys.path.insert(0, str(REPO))
from bathymetry_calibration.core import compare_profiles
from bathymetry_calibration.display_units import FT_PER_M, YD3_PER_M3, customary_frame
from bathymetry_calibration.plots import (
    draw_comparison, draw_diagnostics, draw_section, draw_variability, draw_time_series)
from bathymetry_calibration.workflow import load_config, run_comparison, run_time_series

FIG = ROOT/'figures'
FIG.mkdir(parents=True, exist_ok=True)
BLUE, ORANGE, NAVY, TEAL = '#2166ac', '#b35806', '#17354c', '#287c83'
GRAY, LIGHT = '#626d76', '#edf3f6'
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
                     'axes.titlesize': 10.5, 'axes.labelsize': 9,
                     'xtick.labelsize': 8.5, 'ytick.labelsize': 8.5,
                     'legend.fontsize': 8, 'figure.facecolor': 'white',
                     'savefig.facecolor': 'white', 'axes.spines.top': False,
                     'axes.spines.right': False})

def save(fig, name):
    fig.savefig(FIG/(name+'.png'), dpi=300, bbox_inches='tight', pad_inches=.09)
    fig.savefig(FIG/(name+'.svg'), bbox_inches='tight', pad_inches=.09)
    plt.close(fig)

def box(ax, x, y, w, h, title, detail='', color=NAVY):
    patch = FancyBboxPatch((x,y),w,h,boxstyle='round,pad=.018,rounding_size=.035',
        linewidth=.8, edgecolor=color, facecolor=LIGHT)
    ax.add_patch(patch)
    ax.text(x+w/2, y+h*.66 if detail else y+h/2, title, ha='center', va='center',
            color=color, weight='bold', fontsize=10)
    if detail:
        ax.text(x+w/2,y+h*.30,detail,ha='center',va='center',fontsize=8.7,color=NAVY)

def workflow():
    fig, ax=plt.subplots(figsize=(6.8,3.55))
    ax.set(xlim=(0,10),ylim=(0,5)); ax.axis('off')
    cards=[('1  Load','Configuration, model output and surveys; verify dates and units.'),
           ('2  Define support','Select reach; review profiles, shared footprint and exclusions.'),
           ('3  Calculate','Bed-elevation change → section area → reach volume → cumulative values.'),
           ('4  Review','Check magnitude, spatial pattern, lateral variability and sensitivity.')]
    for i,(title,detail) in enumerate(cards):
        y=3.85-i*.9
        patch=FancyBboxPatch((.18,y),2.45,.60,boxstyle='round,pad=.025,rounding_size=.06',
                            edgecolor=TEAL if i==1 else NAVY,facecolor=LIGHT,lw=.8)
        ax.add_patch(patch)
        ax.text(1.405,y+.30,title,ha='center',va='center',weight='bold',fontsize=9.2,
                color=TEAL if i==1 else NAVY)
        # Explicit wrapping keeps each step legible at the guide's seven-inch width.
        wrapped=[ 'Configuration, model output and surveys;\nverify dates and units.',
                  'Select reach; review profiles, shared footprint\nand exclusions.',
                  'Bed-elevation change → section area → reach volume\n→ cumulative values.',
                  'Check magnitude, spatial pattern, lateral variability\nand sensitivity.'][i]
        ax.text(2.98,y+.30,wrapped,ha='left',va='center',fontsize=9.2,color=NAVY,
                linespacing=1.25)
        if i<3:
            ax.annotate('',(1.405,y-.28),(1.405,y-.035),
                        arrowprops=dict(arrowstyle='->',color=GRAY,lw=1.1))
    ax.text(5,4.8,'Define what bed was compared before assessing agreement.',
            color=NAVY,ha='center',fontsize=10.8,weight='bold')
    ax.add_patch(Rectangle((.18,.10),9.55,.68,facecolor='#edf6f6',edgecolor=TEAL,lw=.7))
    ax.text(4.95,.51,'Preserve technical-review evidence',ha='center',weight='bold',color=TEAL,fontsize=9.5)
    ax.text(4.95,.26,'Plots, tables, support, exclusions, assumptions and input provenance',
            ha='center',fontsize=9,color=NAVY)
    save(fig,'01_workflow')

def location():
    fig,axes=plt.subplots(2,1,figsize=(6.8,2.75),
                           gridspec_kw={'height_ratios':[1,1.05]},layout='constrained')
    ax=axes[0];ax.axis('off'); ax.set(xlim=(0,1),ylim=(0,1))
    left,right=.06,.94
    selected=left+(953.6-236.7)/(953.6+19.6)*(right-left)
    ax.plot([left,right],[.39,.39],color='#ced8df',lw=11,solid_capstyle='butt')
    ax.plot([selected,right],[.39,.39],color=TEAL,lw=11,solid_capstyle='butt')
    ax.scatter([left,selected,right],[.39]*3,s=24,color=NAVY,zorder=5)
    ax.text(left,.17,'RM 953.6',ha='center',fontsize=9,color=NAVY)
    ax.text(selected,.62,'RM 236.7',ha='center',fontsize=9,color=TEAL)
    ax.text(right,.17,'RM −19.6',ha='center',fontsize=9,color=TEAL)
    ax.text(.5,.97,'Full manifest: selected reach highlighted',ha='center',va='top',
            fontsize=10,color=NAVY,weight='bold')
    ax.annotate('Downstream',(right,.79),(.49,.79),ha='left',va='center',fontsize=9,
                arrowprops=dict(arrowstyle='->',color=GRAY,lw=1),color=GRAY)
    ax=axes[1];ax.axis('off');ax.set(xlim=(0,1),ylim=(0,1))
    ax.text(.5,.98,'Selected reach enlarged (schematic): 81 existing cross sections',
            ha='center',va='top',weight='bold',fontsize=9.5,color=TEAL)
    ax.plot([.08,.92],[.58,.58],color=TEAL,lw=3)
    for x in np.linspace(.08,.92,19):ax.plot([x,x],[.54,.62],color=TEAL,lw=.9)
    ax.text(.08,.41,'Upstream XS\nRM 236.7',ha='left',va='top',fontsize=9,color=NAVY)
    ax.text(.92,.41,'Downstream XS\nRM −19.6',ha='right',va='top',fontsize=9,color=NAVY)
    ax.text(.50,.38,'Station-label difference: 256.3 RM\nVerified channel integration length: 259.07 mi',
            ha='center',va='top',fontsize=9,color=NAVY,linespacing=1.25)
    save(fig,'02_river_mile')

def support():
    fig,ax=plt.subplots(figsize=(6.8,3.5),layout='constrained')
    ranges=[(0,100,'Manifest'),(0,100,'Model baseline'),(0,100,'Model target'),
            (10,90,'Survey baseline'),(20,80,'Survey target')]
    for i,(left,right,label) in enumerate(ranges):
        y=5-i
        ax.plot([left,right],[y,y],lw=8,color=BLUE if 'Model' in label else ORANGE if 'Survey' in label else GRAY,
                solid_capstyle='butt')
        ax.text(-3,y,label,ha='right',va='center',fontsize=9)
    ax.axvspan(20,80,color=TEAL,alpha=.10)
    ax.add_patch(Rectangle((40,.72),10,.56,facecolor='white',hatch='////',ec=GRAY,zorder=5))
    for bound in [40,50]:
        ax.plot([bound,bound],[.2,4.7],ls=':',lw=.7,color=GRAY,alpha=.7)
    ax.text(50,5.75,'Shared domain is 20–80 ft; target-survey gap is 40–50 ft.',
            ha='center',fontsize=9.2,color=NAVY,weight='bold')
    for left,right in [(20,40),(50,80)]:
        ax.plot([left,right],[.15,.15],lw=10,color=TEAL,solid_capstyle='butt')
    ax.text(-3,.15,'Accepted intervals',ha='right',va='center',fontsize=9,weight='bold',color=TEAL)
    ax.set(xlim=(-2,102),ylim=(-.5,6.1),xlabel='Lateral station (ft)',yticks=[])
    ax.spines['left'].set_visible(False)
    fig.supxlabel('Accepted width = 20 + 30 = 50 ft\nDomain coverage = 50/60 = 83%   |   Full-footprint coverage = 50/100 = 50%',
                  fontsize=9,color=NAVY,linespacing=1.3)
    save(fig,'03_support')

def cross_area():
    u=np.linspace(0,100,401)
    baseline=np.interp(u,[0,50,100],[12,0,12])
    dz=np.interp(u,[0,50,100],[-3,3,-3])
    fig,axes=plt.subplots(2,1,figsize=(6.8,3.9),sharex=True,
                         gridspec_kw={'height_ratios':[1.15,1]},layout='constrained')
    axes[0].plot(u,baseline,':',color=GRAY,label='Baseline')
    axes[0].plot(u,baseline+dz,color=ORANGE,label='Target')
    axes[0].fill_between(u,baseline,baseline+dz,where=dz>=0,color=ORANGE,alpha=.22)
    axes[0].fill_between(u,baseline,baseline+dz,where=dz<=0,color=BLUE,alpha=.22)
    axes[0].set(ylabel='Bed elevation (ft)',title='Same section and lateral stations at two dates')
    axes[0].legend(loc='upper center',ncol=2)
    axes[1].plot(u,dz,color=NAVY)
    axes[1].fill_between(u,0,dz,where=dz>=0,color=ORANGE,alpha=.35)
    axes[1].fill_between(u,0,dz,where=dz<=0,color=BLUE,alpha=.35)
    axes[1].axhline(0,color=GRAY,lw=.8)
    axes[1].set(xlabel='Lateral station (ft)',ylabel='Target − baseline (ft)',yticks=[-3,0,3])
    axes[1].text(50,1.5,'Deposition\n+75 ft²',ha='center',color=ORANGE,weight='bold',fontsize=9)
    axes[1].text(10,-1.2,'Erosion\n−37.5 ft²',ha='center',color=BLUE,fontsize=9)
    axes[1].text(90,-1.2,'Erosion\n−37.5 ft²',ha='center',color=BLUE,fontsize=9)
    axes[1].set_xticks([0,25,50,75,100])
    axes[1].set_title('Net area = +75 − 37.5 − 37.5 = 0 ft²',fontsize=10,color=NAVY)
    for ax in axes: ax.grid(alpha=.15)
    save(fig,'04_area')

def control():
    fig,ax=plt.subplots(figsize=(6.8,3.25))
    ax.set(xlim=(-220,3240),ylim=(-2.05,2.25));ax.axis('off')
    ax.text(1500,2.12,'Average-end-area method: equivalent allocation to section nodes',
            ha='center',color=NAVY,weight='bold',fontsize=10)
    for left,right,color,label,local in [
            (0,500,BLUE,'A: 500 ft','−500 yd³'),
            (500,2000,TEAL,'B: 1,500 ft','−3,000 yd³'),
            (2000,3000,ORANGE,'C: 1,000 ft','−3,000 yd³')]:
        ax.add_patch(Rectangle((left,-.78),right-left,1.0,color=color,alpha=.17))
        ax.text((left+right)/2,-.14,label,ha='center',color=color,fontsize=9.4,weight='bold')
        ax.text((left+right)/2,-.51,local,ha='center',color=color,fontsize=9.4)
    ax.plot([0,3000],[.65,.65],color=GRAY,lw=1.2)
    for x,label,area in [(0,'XS A','ΔA = −27 ft²'),(1000,'XS B','ΔA = −54 ft²'),(3000,'XS C','ΔA = −81 ft²')]:
        ax.plot([x,x],[.45,.85],color=NAVY,lw=2)
        ax.text(x,1.1,label,ha='center',weight='bold',color=NAVY)
        ax.text(x,1.55,area,ha='center',fontsize=9)
    for left,right,text in [(0,1000,'L₁ = 1,000 ft'),(1000,3000,'L₂ = 2,000 ft')]:
        ax.annotate('',(right,.28),(left,.28),arrowprops=dict(arrowstyle='<->',color=GRAY,lw=.9))
        ax.text((left+right)/2,.43,text,ha='center',fontsize=9)
    for x in [500,2000]:ax.plot([x,x],[-.78,.20],color=GRAY,ls='--',lw=.8)
    ax.text(1500,-1.17,'Each accepted reach gives half its length to each endpoint.',
            ha='center',color=NAVY,fontsize=9.5,weight='bold')
    ax.text(1500,-1.55,'Local volume = ΔA × allocation length ÷ 27  (ft² × ft → yd³)',
            ha='center',fontsize=9,color=NAVY)
    ax.text(1500,-1.94,'Colored blocks show algebraic weights; they do not imply uniform bed-change patches.',
            ha='center',fontsize=8.8,color=GRAY)
    save(fig,'05_control_lengths')

def cumulative():
    x=np.array([0,1000,3000])
    node=np.array([-500,-3500,-6500]);prefix=np.array([0,-1500,-6500])
    fig,ax=plt.subplots(figsize=(6.8,3.9),layout='constrained')
    ax.plot(x,node,'o-',color=BLUE,label='Node cumulative: current main curve')
    ax.plot(x,prefix,'s--',color=ORANGE,label='Completed-reach prefix')
    for a,b,c in zip(x,node,prefix):
        ax.annotate(f'{b:,.0f}',(a,b),xytext=(6,8) if a==1000 else (6,-18),
                    textcoords='offset points',fontsize=9,color=BLUE,
                    bbox=dict(facecolor='white',edgecolor='none',alpha=.85,pad=.4))
        if b!=c:ax.annotate(f'{c:,.0f}',(a,c),xytext=(6,9),textcoords='offset points',fontsize=9,color=ORANGE,
                            bbox=dict(facecolor='white',edgecolor='none',alpha=.85,pad=.4))
    ax.set(xticks=x,xticklabels=['XS A\n0 ft','XS B\n1,000 ft','XS C\n3,000 ft'],
           xlabel='Downstream distance from A (verified channel lengths)',
           ylabel='Signed cumulative change (yd³)',ylim=(-7550,1100),xlim=(-210,3470))
    ax.axhline(0,color=GRAY,lw=.8);ax.grid(alpha=.15);ax.legend(loc='lower left')
    ax.text(3120,-4200,'Same final total:\n−6,500 yd³',ha='right',color=NAVY,weight='bold',fontsize=9.4)
    ax.annotate('At B: stops after reach A→B',xy=(1000,-1500),xytext=(1410,-550),
                fontsize=9,color=ORANGE,ha='left',va='center',
                arrowprops=dict(arrowstyle='->',color=ORANGE,lw=.9))
    ax.annotate('At B: node sum includes\nB’s downstream half-reach\nallocation from B→C.',
                xy=(1000,-3500),xytext=(140,-4700),fontsize=9,color=BLUE,
                ha='left',va='center',arrowprops=dict(arrowstyle='->',color=BLUE,lw=.9),
                bbox=dict(facecolor='white',edgecolor='none',alpha=.95,pad=2))
    fig.supxlabel('Markers are discrete accounting values. Connecting lines guide the eye;\nthey do not define a continuously integrated bed-volume curve.',
                  fontsize=9,color=GRAY,linespacing=1.25)
    save(fig,'06_prefixes')

def disconnected():
    fig,ax=plt.subplots(figsize=(6.8,3.15),layout='constrained')
    ax.plot([0,1],[500,1000],'o-',color=BLUE,lw=2,label='Segment 0')
    ax.plot([3,4],[1000,2000],'o-',color=TEAL,lw=2,label='Segment 1')
    ax.axvspan(1.5,2.5,color='#edf0f2',hatch='////',ec='white')
    ax.text(2,1320,'XS C missing\nB→C and C→D\nare not reconstructed',ha='center',color=GRAY,
            fontsize=9,linespacing=1.3)
    ax.set(xticks=range(5),xticklabels=['A','B','C','D','E'],ylabel='Node cumulative change (yd³)',
           xlabel='Cross sections in downstream order',ylim=(0,2500),xlim=(-.3,4.3))
    ax.grid(axis='y',alpha=.2);ax.legend(loc='upper left',ncol=2)
    ax.annotate('New sum at D:\nD allocation = 1,000 yd³',
                xy=(3,1000),xytext=(2.85,340),ha='right',fontsize=8.8,color=TEAL,
                arrowprops=dict(arrowstyle='->',color=TEAL,lw=.8))
    fig.supxlabel('Segment totals: 1,000 + 2,000 = 3,000 yd³ across all supported reaches.\nThe last point (E) represents only its segment: 2,000 yd³.',
                  fontsize=9,color=NAVY,linespacing=1.3)
    save(fig,'07_disconnected')

def cancellation():
    fig,panels=plt.subplots(2,2,figsize=(6.8,3.2),layout='constrained',
                           gridspec_kw={'height_ratios':[1,.40]})
    axes=panels[0];axes[1].sharey(axes[0])
    for ax,title,z in [(axes[0],'No change',[0,0,0]),(axes[1],'Opposing changes',[-3,3,-3])]:
        u=np.linspace(0,100,401);dz=np.interp(u,[0,50,100],z)
        ax.plot(u,dz,color=NAVY,lw=1.5)
        ax.fill_between(u,0,dz,where=dz>=0,color=ORANGE,alpha=.3)
        ax.fill_between(u,0,dz,where=dz<=0,color=BLUE,alpha=.3)
        ax.axhline(0,color=GRAY,lw=.6)
        ax.set(title=title,xlabel='Lateral station (ft)',ylim=(-3.7,3.7),xticks=[0,50,100])
        ax.grid(alpha=.15)
    axes[0].set_ylabel('Bed change (ft)')
    for axis in panels[1]:axis.axis('off')
    panels[1,0].text(.5,.53,'Net area = 0 ft²; mean = 0 ft\nGross area = 0 ft²; std = 0 ft\nCancellation is undefined (0/0).',
                    ha='center',va='center',fontsize=9,color=GRAY,linespacing=1.4)
    panels[1,1].text(.5,.53,'Net area = 75 − 75 = 0 ft²; mean = 0 ft\nGross area = 150 ft²; std = 1.73 ft\nCancellation = 100%.',
                    ha='center',va='center',fontsize=9,color=NAVY,linespacing=1.4)
    save(fig,'08_cancellation')

def estimator():
    fig,axes=plt.subplots(1,2,figsize=(6.8,3.1),layout='constrained')
    axes[0].plot([0,1000],[27,81],'o-',color=NAVY,label='Linear endpoint-area change')
    axes[0].plot([0,1000],[27,27],'--',color=BLUE,label='Hold upstream area')
    axes[0].plot([0,1000],[81,81],'--',color=ORANGE,label='Hold downstream area')
    axes[0].set(xlabel='Verified reach distance (ft)',ylabel='Change area (ft²)',ylim=(0,120),xticks=[0,1000],
                title='Assumed change area between sections')
    axes[0].set_yticks([0,27,54,81])
    axes[0].legend(fontsize=8.2,loc='upper left');axes[0].grid(alpha=.15)
    axes[1].bar(['Upstream','Average\nend area','Downstream'],[1000,2000,3000],color=[BLUE,TEAL,ORANGE],alpha=.8)
    axes[1].set(ylabel='Reach volume (yd³)',ylim=(0,3550),title='Reach-volume estimates')
    for i,value in enumerate([1000,2000,3000]):axes[1].text(i,value+100,f'{value:,}',ha='center',fontsize=9)
    axes[1].grid(axis='y',alpha=.15)
    fig.supxlabel('These estimates describe reconstruction sensitivity; they are not bounds on the unknown true volume.',
                  fontsize=8.8,color=GRAY)
    save(fig,'09_estimators')

def grid():
    source_u=np.array([0,8,10,12,20]);z=np.array([0,0,3,0,0])
    fig,axes=plt.subplots(2,1,figsize=(6.8,3.3),sharex=True,layout='constrained')
    for ax,spacing,label in [(axes[0],5,'Added grid spacing: 5 ft'),(axes[1],2,'Added grid spacing: 2 ft')]:
        u=np.unique(np.r_[source_u,np.arange(0,20.001,spacing)])
        zz=np.interp(u,source_u,z)
        added=np.array([value not in source_u for value in u])
        ax.plot(u,zz,color=GRAY,lw=1.1)
        ax.fill_between(u,0,zz,color=BLUE,alpha=.13)
        ax.scatter(u[added],zz[added],facecolor='white',edgecolor=GRAY,s=23,zorder=4,label='Additional interpolation knots')
        ax.scatter(source_u,z,color=BLUE,s=26,zorder=5,label='Retained source knots')
        ax.set(ylabel='Change (ft)',title=f'{label}  |  Integrated area = 6 ft²',ylim=(-.25,4.0),yticks=[0,3])
        ax.grid(alpha=.15)
    axes[0].legend(loc='upper left',ncol=1,fontsize=8.2)
    axes[1].set_xticks([0,5,8,10,12,15,20])
    axes[1].set_xlabel('Lateral station (ft)')
    fig.supxlabel('Source knots at 8, 10 and 12 ft preserve the feature; adding knots does not improve survey resolution.',
                  fontsize=8.8,color=GRAY)
    save(fig,'10_grid')

def uncertainty():
    sigma=.2*np.sqrt(2)
    weights=np.array([50000.,100000.,50000.])
    coherent=sigma*weights.sum()/27
    independent=sigma*np.linalg.norm(weights)/27
    fig,ax=plt.subplots(figsize=(6.8,3.35),layout='constrained')
    for y,error,color in [(1,coherent,BLUE),(0,independent,TEAL)]:
        ax.errorbar(3000,y,xerr=1.96*error,fmt='o',color=color,capsize=6,lw=2,ms=6)
    ax.axvline(0,color=GRAY,lw=1.0,ls='--')
    ax.set(yticks=[0,1],yticklabels=['Across XS: independent\nSpatial correlation = 0','Across XS: fully correlated\nSpatial correlation = 1'],
           xlabel='Model − observed volume bias (yd³)',ylim=(-.52,1.64),xlim=(-2000,8200))
    ax.xaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    ax.grid(axis='x',alpha=.15)
    ax.set_title('Same +3,000 yd³ bias; different survey-error assumptions',fontsize=10,color=NAVY)
    for y,ss in [(1,coherent),(0,independent)]:
        lo,hi=3000-1.96*ss,3000+1.96*ss
        ax.text(3000,y+.24,f'Conditional 95% interval: [{lo:,.0f}, {hi:,.0f}] yd³',
                ha='center',fontsize=9,color=NAVY)
    fig.supxlabel('Each survey σ = 0.20 ft; temporal correlation = 0; error is coherent within each XS.\nBars show bias ± 1.96σᵥ. Model volume is treated as exact; omitted errors are not covered.',
                  fontsize=9,color=GRAY,linespacing=1.3)
    save(fig,'11_uncertainty')
    return {'sigma_change_ft':sigma,'coherent_sigma_yd3':coherent,'independent_sigma_yd3':independent,
            'coherent_interval':[3000-1.96*coherent,3000+1.96*coherent],
            'independent_interval':[3000-1.96*independent,3000+1.96*independent]}

def fixture():
    folder=ROOT/'illustrative_data'
    folder.mkdir(parents=True,exist_ok=True)
    u_ft=np.array([0,100,350,650,900,1000.])
    b_ft=np.array([18,-28,-44,-42,-20,20.])
    changes_ft=np.array([-1.2,-.8,-.2,.2,.5,.3,-.4,-.7])
    lateral_ft=np.array([-.8,-1,1,1,-1,-.8])-.12
    profiles={}; rows=[];model=[]
    dates=['2020-01-15','2022-07-15','2025-01-15']
    for epoch,fraction in enumerate([0,.5,1]):
        survey=[]; model_epoch=[]
        for i,mean in enumerate(changes_ft):
            xs=f'{100-i:.1f}'
            dz=mean+lateral_ft
            survey.extend({'xs_id':xs,'u_m':u*.3048,'z_m':(b+fraction*c)*.3048}
                          for u,b,c in zip(u_ft,b_ft,dz))
            model_epoch.append((b_ft+.15+2*fraction*dz)*.3048)
            if epoch==0:
                rows.extend(dict(xs_id=xs,model_column=i,river_mile=100-i,
                    chainage_m=i*5280*.3048,length_to_next_m=5280*.3048 if i<7 else np.nan,
                    u_m=u*.3048,x_m=500000+u*.3048,y_m=3300000-i*5280*.3048) for u in u_ft)
        name=['baseline','intermediate','target'][epoch]
        profiles[name]=pd.DataFrame(survey)
        profiles[name].to_csv(folder/(name+'.csv'),index=False)
        model.append(model_epoch)
    pd.DataFrame(rows).to_csv(folder/'transects.csv',index=False)
    with h5py.File(folder/'illustration.hdf','w') as h5:
        h5.attrs['File Version']='SYNTHETIC USER-GUIDE EXAMPLE; not a native HEC-RAS file'
        h5.create_dataset('profile_station',data=np.tile(u_ft*.3048,(8,1)))
        h5.create_dataset('profile_elevation',data=np.array(model))
        h5.create_dataset('dates',data=np.array([d.encode() for d in dates]))
    common={'kind':'csv','vertical_datum':'Illustrative datum','vertical_alignment_verified':True}
    settings={'analysis_crs':'EPSG:26915','vertical_datum':'Illustrative datum',
        'spatial_mapping_verified':True,'temporal_alignment_verified':True,
        'transects':str(folder/'transects.csv'),'cache_dir':str(folder/'cache'),
        'survey_alignment_tolerance_days':0,
        'surveys':{name:dict(common,path=str(folder/(name+'.csv')),date=date)
                   for name,date in zip(profiles,dates)},
        'model':dict(profile_mapping_verified=True,vertical_alignment_verified=True,
            vertical_datum='Illustrative datum',elevation_dataset='profile_elevation',
            station_dataset='profile_station',time_dataset='dates',z_scale_to_m=1,u_scale_to_m=1),
        'integration':{'max_gap_m':100,'min_coverage':1,'grid_spacing_m':10}}
    (folder/'config.json').write_text(json.dumps(settings,indent=2))
    result,provenance=run_comparison(settings,folder/'illustration.hdf','baseline','target',0,2)
    assert np.isclose(result.metrics['change_shape_correlation'],1)
    assert np.isclose(result.metrics['change_amplitude_ratio'],2)
    assert np.isclose(result.metrics['zone_agreement_fraction'],1)
    pairs=[('12_main',draw_comparison,(result,provenance),(6.8,4.3)),
           ('13_diagnostics',draw_diagnostics,(result,),(6.8,6.6)),
           ('14_profiles',draw_section,(result,'97.0'),(6.8,4.4)),
           ('15_variability',draw_variability,(result,),(6.8,4.5))]
    for name,draw,args,size in pairs:
        fig=plt.figure(figsize=size,layout='constrained')
        draw(fig,*args)
        if name=='12_main':
            fig.axes[0].set_ylabel('Node cumulative volume (yd³)')
            fig.axes[0].yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
            # This default annotation lies over the synthetic model trough.
            # The guide explains the same accounting convention in §§09–12.
            for annotation in list(fig.axes[0].texts):
                annotation.remove()
        elif name=='13_diagnostics':
            titles=['a  Mean change and zones','b  Same zone: green; different: red',
                    'c  Standardized spatial pattern','d  Baseline and target bed',
                    'e  Downstream slope (unsmoothed)','f  Downstream concavity (unsmoothed)']
            for axis,title in zip(fig.axes,titles):
                axis.set_title(title,fontsize=9.5)
                if axis.get_legend() is not None:
                    for text in axis.get_legend().get_texts():
                        text.set_text(text.get_text().replace('within_threshold','within threshold'))
            for i in [0,2,3,4,5]:
                fig.axes[i].set_xlabel('Model river mile (downstream →)',fontsize=8.5)
            fig.axes[3].set_ylabel('Mean bed elevation (ft)')
            fig.axes[4].set_ylabel('Slope (ft/mi)')
            fig.axes[5].set_ylabel('Concavity (ft/mi²)')
        elif name=='15_variability':
            # The illustrative amplitude scaling leaves cancellation unchanged.
            # A dashed observed trace keeps the coincident model line visible.
            for line in fig.axes[1].lines:
                if line.get_label()=='Observed':
                    line.set_linestyle('--')
            fig.axes[0].set_ylabel('Lateral std (ft)')
            fig.axes[1].set_ylabel('Cancellation')
        save(fig,name)
    series=run_time_series(settings,folder/'illustration.hdf')
    fig=plt.figure(figsize=(6.8,4.4),layout='constrained');draw_time_series(fig,series)
    for axis in fig.axes:
        if axis.get_ylabel().startswith('Bed change rate'):
            axis.set_ylabel('Mean change rate (ft/yr)',fontsize=9)
    save(fig,'16_series')
    facts=customary_frame(pd.DataFrame([result.metrics])).iloc[0].to_dict()
    facts={k: None if pd.isna(v) else v for k,v in facts.items()}
    # Hand-check the customary worked example against the actual calculation engine.
    t=[];before=[];after=[]
    for i,area in enumerate([-27.,-54.,-81.]):
        for u in [0.,100.]:
            t.append(dict(xs_id=f'Example-{i}',model_column=i,chainage_m=[0,1000,3000][i]*.3048,
                length_to_next_m=[1000,2000,np.nan][i]*.3048,u_m=u*.3048,x_m=u*.3048,y_m=i*1000*.3048))
            before.append(dict(xs_id=f'Example-{i}',u_m=u*.3048,z_m=0.))
            after.append(dict(xs_id=f'Example-{i}',u_m=u*.3048,z_m=area/100*.3048))
    checked=compare_profiles(pd.DataFrame(t),pd.DataFrame(before),pd.DataFrame(after),
        pd.DataFrame(before),pd.DataFrame(after),max_gap_m=40)
    np.testing.assert_allclose(checked.sections.observed_cumulative_m3*YD3_PER_M3,[-500,-3500,-6500])
    np.testing.assert_allclose(checked.sections.observed_interval_prefix_m3*YD3_PER_M3,[0,-1500,-6500])
    assert np.isclose(checked.metrics['observed_total_m3']*YD3_PER_M3,-6500)
    return facts

if __name__=='__main__':
    workflow();location();support();cross_area();control();cumulative();disconnected()
    cancellation();estimator();grid()
    facts={'uncertainty':uncertainty(),'illustrative_comparison':fixture()}
    (ROOT/'verified_examples.json').write_text(json.dumps(facts,indent=2))
    print('Generated 16 figures; example values verified against the calculation engine.')
