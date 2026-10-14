"""Inspectable outflow relations, evaluated with the engine's shared formulas."""
import numpy as np
from textwrap import fill
from matplotlib.ticker import FuncFormatter

from .schemes import PASS_RATINGS, pass_input_flows, pass_outflow, spillway_outflows, terminal_fraction


COLORS = ['#246b9c', '#008779', '#b76327', '#73558e']
STATE_LABELS = {0: 'normal', 1: 'rising', 1.5: 'extended crest', 2: 'falling', 3: 'low water'}


def _formula(rating, p):
    a, b = getattr(p, rating.a_parameter), getattr(p, rating.b_parameter)
    return f'{a:,.6g} ln(max(Q, 1)) − {b:,.6g}' if rating.logarithmic else f'{a:,.6g} Q − {b:,.6g}'


def rating_group(choice):
    return {'terminal': 'Terminal passes', 'controlled': 'Lower diversions',
            'spillways': 'Floodway & spillways', 'birds': 'Floodway & spillways',
            'orcc': 'ORCC operations'}.get(choice, 'Pass rating curves')


def rating_input(result, choice):
    f = result.flows
    if choice in {r.column for r in PASS_RATINGS}:
        return pass_input_flows(f)[choice]
    return f.HeadOfPasses if choice == 'terminal' else f.Thebes+f.Ohio if choice == 'birds' else (
        f.TarbertLanding if choice == 'spillways' else f.forcing_flow)


def rating_range(result, choice):
    p = result.parameters
    if choice == 'all_passes':
        upper = max(v.max() for v in pass_input_flows(result.flows).values())
    else:
        upper = rating_input(result, choice).max()
    threshold = {'terminal': p.swp_threshold, 'controlled': p.diversion_trigger,
                 'spillways': p.spill_threshold+(p.bc_limit if p.spill_style == 'threshold' else p.bc_switch),
                 'birds': p.bp_threshold}.get(choice, 0)
    return max(100000., upper*1.1, threshold*1.1)


def rating_notes(result, choice, index=0):
    p, row = result.parameters, result.flows.iloc[index]
    matching = next((r for r in PASS_RATINGS if r.column == choice), None)
    if matching:
        order = [r.column for r in PASS_RATINGS].index(choice)
        upstream = 'spillways and controlled diversions' if order == 0 else PASS_RATINGS[order-1].label
        a, b = getattr(p, matching.a_parameter), getattr(p, matching.b_parameter)
        onset = (np.exp(b/a) if matching.logarithmic and a > 0 and b/a < 700 else
                 b/a if not matching.logarithmic and a > 0 else np.inf)
        onset_text = f'The unbounded relation becomes positive above approximately {onset:,.0f} cfs.' if np.isfinite(onset) else 'There is no finite positive onset within the stated coefficient form.'
        return (f'<b>{matching.label}: local discharge-to-discharge relation</b><br>'
            f'Raw extraction = <b>{_formula(matching, p)}</b>. Applied extraction is bounded to [0, Q]. '
            f'Q is the mainstem flow remaining after {upstream}; it is not the original gauge flow. '
            'The next pass is evaluated using Q minus this applied extraction.<br><br>'
            + ('The logarithm uses the numerical flow in cfs. A scales the response to a logarithmic change in flow; '
               'B sets the offset. The max(Q,1) guard avoids log(0), and does not add water. ' if matching.logarithmic else
               'A is the slope of extracted discharge against local mainstem discharge; B shifts the onset. '
               'A alone is not the extracted fraction at finite Q because of the intercept. ')
            + onset_text+'<br><br>The grey band marks flows encountered at this location in the loaded run; '
            'it is not a verified calibration range. The supplied files do not document coefficient calibration limits.')
    if choice == 'all_passes':
        return ('<b>Seven sequential pass ratings</b><br>Mardi Gras and Point à la Hache use logarithmic relations; '
            'the five following relations are linear. Each panel has its own local remaining-flow input. '
            'Solid curves apply the same zero/available-water bounds as the engine; enable Show raw formulas to inspect unbounded curves. '
            'Dots identify the selected day and shaded bands show the local flow span in this run.<br><br>'
            'These spans describe the loaded scenario. The original code provides coefficients but no documented calibration limits.')
    if choice == 'terminal':
        low = p.swp_quad*p.swp_threshold**2+p.swp_low_slope*p.swp_threshold+p.swp_low_offset
        high = p.swp_high_slope*p.swp_threshold+p.swp_high_offset
        return (f'<b>Head of Passes: fraction first, discharge second</b><br>'
            f'Below {p.swp_threshold:,.0f} cfs, Southwest Pass fraction = {p.swp_quad:.6g} Q² + '
            f'{p.swp_low_slope:.6g} Q + {p.swp_low_offset:.6g}. At or above the switch, fraction = '
            f'{p.swp_high_slope:.6g} Q + {p.swp_high_offset:.6g}. The fraction is bounded to [0,1].<br><br>'
            'Southwest Pass outflow = fraction × Head of Passes flow. South Pass and Pass a Loutre each receive '
            'half the remainder. Their fractions sum to 100% when flow is positive. The plotted pieces are separated at the switch; '
            f'the unbounded Southwest fraction changes by {(high-low)*100:+.4g} percentage points there. '
            'The equal split of the remaining two passes is a retained assumption, not an independent rating for each pass.')
    if choice == 'controlled':
        return (f'<b>Binary diversion demands</b><br>The trigger is the selected input-gauge forcing, '
            f'not local downstream flow. Below {p.diversion_trigger:,.0f} cfs the demands are zero; '
            f'at or above it, Davis Pond requests {p.davis:,.0f}, Caernarvon {p.caernarvon:,.0f}, '
            f'and siphons {p.siphons:,.0f} cfs.<br><br>They are applied in that order after the spillways and each is limited by '
            'the mainstem water still available. Lines show requested amounts; selected-day dots show applied amounts. '
            'This is an on/off scenario rule, not a stage-dependent structure rating.')
    if choice == 'spillways':
        rule = (f'Bonnet Carré takes min(excess, {p.bc_limit:,.0f} cfs); Morganza takes the remainder. '
                'The ratio-switch parameter is inactive in this mode.' if p.spill_style == 'threshold' else
                f'Bonnet Carré takes {100*p.bc_low_share:g}% of excess below {p.bc_switch:,.0f} cfs excess and '
                f'{100*p.bc_high_share:g}% at or above it; Morganza takes the remainder. '
                'The Bonnet Carré ceiling parameter is inactive in this mode.')
        return (f'<b>Allocate excess mainstem flow</b><br>Excess = max(Tarbert Landing − {p.spill_threshold:,.0f}, 0). '
            +rule+'<br><br>The input is modeled Tarbert flow after ORCC adjustments. This preserves the original lower-river '
            'discharge proxy; it does not predict Carrollton stage or route travel time to the spillways. '
            'The total line is excess, not an additional third diversion.')
    if choice == 'birds':
        return (f'<b>Threshold diversion plus delayed return</b><br>Birds Point diversion = max(MMR + Ohio − '
            f'{p.bp_threshold:,.0f}, 0). The trigger uses the combined headwater boundary flows.<br><br>'
            f'For a diversion on one day, the return starts after {p.bp_lag} days; the bars give the return on each lag day '
            f'as a fraction of that diversion. The returned fraction is {100*p.bp_efficiency:g}%; '
            f'{100*(1-p.bp_efficiency):g}% is accounted for as modeled loss. New Madrid adds overlapping returns from preceding '
            'diversions, so today’s return is not a rating of today’s discharge. Returns beyond the run end remain in the tail ledger.')
    if choice == 'orcc':
        reference = 'Union Point' if p.input_reference == 'union_point' else 'Tarbert-reference input'
        formula = '(1 − r)(Q + Red River) − Red River' if p.input_reference == 'union_point' else 'Q(1/r − 1) − Red River'
        mode = ('<b>The loaded run uses prescribed ORCC totals: these ratio lines are inactive explanatory alternatives.</b> '
                if p.orcc_mode == 'prescribed' else 'The selected hydrograph state chooses the ratio target. ')
        return (f'<b>Latitude-flow target at fixed Red River discharge</b><br>r is the Mississippi fraction of '
            f'combined latitude flow, not the fraction of Union Point left after diversion. Requested ORCC = <b>{formula}</b>. '
            f'This plot holds Red River at the selected-day value, {row.Red_River:,.0f} cfs, and varies {reference}.<br><br>'
            +mode+'The dot is the final applied total. E-flow targets, optional override, minimum/maximum requests, available '
            'water, and structure capacity may change it. Horizontal lines are total operating limits, not an applied rating. '
            'Structure allocation also depends on Tarbert flow and hydrograph state; it is not a single curve of Q alone.')
    raise ValueError(f'Unknown rating choice: {choice}')


def draw_rating_curves(figure, result, index=0, choice='all_passes', max_flow=None, show_raw=False):
    figure.clear()
    # Recompute spacing on every draw, including Qt resizes after changing view.
    figure.set_layout_engine('constrained', rect=(0, .13, 1, .78), h_pad=.06, w_pad=.07)
    p, row = result.parameters, result.flows.iloc[index]
    maximum = rating_range(result, choice) if max_flow is None else float(max_flow)
    if not np.isfinite(maximum) or maximum <= 0:
        raise ValueError('Rating plot maximum flow must be positive and finite')
    # Include exact switches and points on either side so jumps are not smoothed.
    switches = [p.swp_threshold, p.diversion_trigger, p.spill_threshold,
                p.spill_threshold+p.bc_switch, p.spill_threshold+p.bc_limit, p.bp_threshold]
    extra = [v for t in switches for v in [np.nextafter(t, 0), t, np.nextafter(t, np.inf)] if 0 <= v <= maximum]
    q = np.unique(np.r_[np.linspace(0, maximum, 700), extra])
    overview = choice == 'all_passes'
    axes = figure.subplots(4, 2).ravel() if overview else np.atleast_1d(figure.subplots(1, 2 if choice in {r.column for r in PASS_RATINGS} | {'terminal', 'birds'} else 1))
    figure.suptitle('Outflow ratings and operating relations' if overview else dict(
        terminal='Terminal pass fractions and outflows', controlled='Controlled diversion requests',
        spillways='Spillway excess-flow allocation', birds='Birds Point diversion and New Madrid return',
        orcc='ORCC latitude-flow target').get(choice, next((r.label for r in PASS_RATINGS if r.column == choice), choice)),
        fontsize=13, fontweight='bold', y=.99)
    inputs = pass_input_flows(result.flows)

    def style(ax, xlabel='Local remaining mainstem flow (1,000 cfs)', ylabel='Outflow (1,000 cfs)', percent_axis=False):
        ax.set_xlabel(xlabel, fontsize=9)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v/1000:,.3f}'.rstrip('0').rstrip('.')))
        if not percent_axis:
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f'{v/1000:,.3f}'.rstrip('0').rstrip('.')))
        ax.set_xlim(0, maximum)
        ax.grid(alpha=.2)
        ax.tick_params(labelsize=8)

    def band(ax, values):
        if values.max() > values.min():
            ax.axvspan(values.min(), values.max(), color='#e3e9ed', alpha=.6, zorder=0)

    def pieces(ax, values, switch, **kwargs):
        ax.plot(q[q < switch], np.asarray(values)[q < switch], **kwargs)
        ax.plot(q[q >= switch], np.asarray(values)[q >= switch], **dict(kwargs, label=None))

    if overview or choice in inputs:
        ratings = PASS_RATINGS if overview else [next(r for r in PASS_RATINGS if r.column == choice)]
        for ax, rating in zip(axes, ratings):
            raw, applied = pass_outflow(q, rating, p)
            band(ax, inputs[rating.column])
            if show_raw:
                ax.plot(q, raw, '--', color='#7b858b', lw=1, label='Raw formula')
            ax.plot(q, applied, color=COLORS[0], lw=2, label='Applied after bounds')
            ax.scatter([inputs[rating.column].iloc[index]], [-row[rating.column]], color=COLORS[2], zorder=4, label='Selected day')
            ax.set_title(rating.label+'\nRaw: '+_formula(rating, p), fontsize=9, loc='left')
            style(ax)
            if not show_raw:
                ax.set_ylim(0, max(1, applied.max()*1.08))
        if overview:
            axes[-1].axis('off')
            raw_note = 'Dashed grey: unbounded formula' if show_raw else 'Raw formulas are named in the titles.\nOnly applied outflows are drawn.'
            axes[-1].text(0, .9, 'Each panel uses its own local flow.\n\n'+raw_note+'\nBlue: applied, bounded to [0, Q]\nOrange dot: selected day\nGrey band: local input span in this run\n\nCalibration limits are not supplied.',
                           va='top', fontsize=10, linespacing=1.7, transform=axes[-1].transAxes)
        else:
            ax = axes[1]
            shares = np.divide(applied*100, q, out=np.full_like(q, np.nan), where=q > 0)
            band(ax, inputs[choice])
            ax.plot(q, shares, color=COLORS[0], lw=2)
            current = inputs[choice].iloc[index]
            if current > 0:
                ax.scatter([current], [-row[choice]/current*100], color=COLORS[2], zorder=4)
            style(ax, ylabel='Applied share of local flow (%)', percent_axis=True)
            ax.set_ylim(0, min(105, max(5, float(np.nanmax(shares))*1.1)))
            ax.set_title('Extraction as a percentage of local inflow', fontsize=10)
            axes[0].legend(fontsize=8)
    elif choice == 'terminal':
        raw, fraction = terminal_fraction(q, p)
        parts = [fraction, (1-fraction)/2, (1-fraction)/2]
        for i, (name, share) in enumerate(zip(['Southwest Pass', 'South Pass', 'Pass a Loutre'], parts)):
            linestyle = ':' if i == 2 else '-'
            for ax, values in [(axes[0], np.where(q > 0, share*100, np.nan)), (axes[1], share*q)]:
                band(ax, result.flows.HeadOfPasses) if i == 0 else None
                pieces(ax, values, p.swp_threshold, color=COLORS[i], lw=2, linestyle=linestyle, label=name)
            column = ['SWP_Flow', 'SouthPass', 'PassALoutre'][i]
            if row.HeadOfPasses > 0:
                axes[0].scatter([row.HeadOfPasses], [-row[column]/row.HeadOfPasses*100], color=COLORS[i], zorder=4)
            axes[1].scatter([row.HeadOfPasses], [-row[column]], color=COLORS[i], zorder=4)
        if show_raw:
            pieces(axes[0], raw*100, p.swp_threshold, color='#7b858b', linestyle='--', label='SW raw fraction')
        for ax in axes:
            ax.axvline(p.swp_threshold, color='#7b858b', ls=':', lw=1)
            ax.legend(fontsize=8)
        style(axes[0], 'Head of Passes flow (1,000 cfs)', 'Share of Head of Passes flow (%)', True)
        style(axes[1], 'Head of Passes flow (1,000 cfs)')
    elif choice == 'controlled':
        ax = axes[0]
        for i, (name, amount) in enumerate([('Davis Pond', p.davis), ('Caernarvon', p.caernarvon), ('Siphons', p.siphons)]):
            ax.step(q, np.where(q >= p.diversion_trigger, amount, 0), where='post', color=COLORS[i], label=name+' request')
            ax.scatter([row.forcing_flow], [-row[['Davis_Pond', 'Caernarvon', 'Siphons'][i]]], color=COLORS[i], zorder=4)
        band(ax, result.flows.forcing_flow)
        ax.axvline(p.diversion_trigger, color='#7b858b', ls=':', label='Activation threshold')
        style(ax, 'Input-gauge forcing (1,000 cfs)', 'Requested / applied extraction (1,000 cfs)')
        ax.legend(fontsize=9)
    elif choice == 'spillways':
        ax = axes[0]
        morg, bc = spillway_outflows(q, p)
        for i, (name, values) in enumerate([('Morganza', morg), ('Bonnet Carré', bc), ('Total excess', morg+bc)]):
            if p.spill_style == 'ratio':
                pieces(ax, values, p.spill_threshold+p.bc_switch, color=COLORS[i], label=name)
            else:
                ax.plot(q, values, color=COLORS[i], label=name)
        for i, column in enumerate(['Morganza', 'BonnetCarre']):
            ax.scatter([row.TarbertLanding], [-row[column]], color=COLORS[i], zorder=4)
        band(ax, result.flows.TarbertLanding)
        ax.axvline(p.spill_threshold, color='#7b858b', ls=':', label='Excess begins')
        style(ax, 'Modeled Tarbert Landing flow (1,000 cfs)')
        ax.legend(fontsize=9)
    elif choice == 'birds':
        ax = axes[0]
        ax.plot(q, np.maximum(q-p.bp_threshold, 0), color=COLORS[0], lw=2, label='Birds Point diversion')
        ax.scatter([row.Thebes+row.Ohio], [-row.BirdsPoint], color=COLORS[2], zorder=4)
        band(ax, result.flows.Thebes+result.flows.Ohio)
        ax.axvline(p.bp_threshold, color='#7b858b', ls=':', label='Diversion begins')
        style(ax, 'Combined MMR + Ohio flow (1,000 cfs)')
        ax.legend(fontsize=8)
        axes[1].bar(p.bp_lag+np.arange(len(p.bp_return_weights)), np.asarray(p.bp_return_weights)*p.bp_efficiency*100, color=COLORS[1])
        axes[1].set_xlabel('Days after one diversion day')
        axes[1].set_ylabel('Return on that lag day (% of diversion)')
        axes[1].set_title('New Madrid return kernel', fontsize=10)
        axes[1].set_ylim(0, max(1, max(p.bp_return_weights)*p.bp_efficiency*115))
        axes[1].grid(axis='y', alpha=.2)
    elif choice == 'orcc':
        ax = axes[0]
        for i, (label, ratio) in enumerate([('Normal', p.orcc_ratio), ('Rising / crest', p.rising_ratio),
                                           ('Falling', p.falling_ratio), ('Low water', p.low_ratio)]):
            target = (q+row.Red_River)*(1-ratio)-row.Red_River if p.input_reference == 'union_point' else q*(1/ratio-1)-row.Red_River
            ax.plot(q, target, color=COLORS[i], label=f'{label}: r={ratio:g}', linestyle=['-', '--', ':', '-.'][i])
        if p.consider_head:
            target = (q+row.Red_River)*(1-p.head_ratio)-row.Red_River if p.input_reference == 'union_point' else q*(1/p.head_ratio-1)-row.Red_River
            ax.plot(q, target, color='#926c39', ls='--', label=f'Head proxy: r={p.head_ratio:g}')
        ax.axhline(p.orcc_max, color='#7b858b', ls=':', label='Total ceiling')
        ax.axhline(p.hp_min, color='#7b858b', ls='-.', label='Minimum target')
        ax.scatter([row.forcing_flow], [row.ORCC_total], color='black', zorder=5, label='Selected-day applied total')
        band(ax, result.flows.forcing_flow)
        style(ax, 'Selected input-reference flow (1,000 cfs)', 'Requested diversion / applied dot (1,000 cfs)')
        ax.legend(fontsize=9, ncol=2)
    else:
        raise ValueError(f'Unknown rating choice: {choice}')
    footer = f'Selected day: {row.date:%d %b %Y}. ' + (
        'Positive magnitudes shown; exported lateral extractions are negative. '
        'Shading = encountered input span, not calibration limits.')
    figure.text(.03, .023, fill(footer, max(45, int(figure.bbox.width/(figure.dpi*.06)))), fontsize=8, color='#394f5d')
    return figure
