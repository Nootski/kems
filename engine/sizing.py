"""
Sizing engine: determines optimal battery capacity and inverter power
based on PV production, consumption profile, constraints, and goals.
"""

from __future__ import annotations



def estimate_pv_yield(kwp: float, orientation: str, tilt: float = 35) -> float:
    """
    Estimate annual PV yield in kWh for a Dutch location.
    orientation: 'south', 'east', 'west', 'east_west', 'southeast', 'southwest', 'north'
    """
    base_yield_per_kwp = 950  # kWh/kWp/year for south-facing, ~35° tilt in NL
    orientation_factors = {
        "south": 1.00,
        "southeast": 0.96,
        "southwest": 0.96,
        "east": 0.85,
        "west": 0.85,
        "east_west": 0.88,
        "north": 0.60,
    }
    tilt_factor = 1.0
    if tilt < 10:
        tilt_factor = 0.90
    elif tilt > 50:
        tilt_factor = 0.92

    factor = orientation_factors.get(orientation, 0.88) * tilt_factor
    return round(kwp * base_yield_per_kwp * factor)


def estimate_peak_demand(
    annual_kwh: float,
    has_heat_pump: bool = False,
    heat_pump_kw: float = 0,
    has_ev_charger: bool = False,
    ev_charger_kw: float = 0,
    has_induction: bool = False,
    extra_peak_kw: float = 0,
) -> float:
    """Estimate household peak demand in kW."""
    base_peak = max(annual_kwh / 2500, 2.5)
    peak = base_peak
    if has_heat_pump:
        peak += heat_pump_kw if heat_pump_kw > 0 else 3.5
    if has_ev_charger:
        peak += ev_charger_kw if ev_charger_kw > 0 else 7.4
    if has_induction:
        peak += 3.5
    peak += extra_peak_kw
    return round(peak, 1)


def connection_for_peak(peak_kw: float, phases: int = 3) -> str:
    """Determine minimum connection size for a given peak."""
    if phases == 1:
        return "1x25A" if peak_kw <= 5.75 else "1x35A"
    amps_needed = peak_kw * 1000 / (phases * 230)
    thresholds = [(25, "3x25A"), (35, "3x35A"), (40, "3x40A"),
                  (50, "3x50A"), (63, "3x63A"), (80, "3x80A")]
    for amps, label in thresholds:
        if amps_needed <= amps:
            return label
    return "3x80A"


def target_connection_with_battery(
    peak_kw: float, inverter_kw: float, phases: int = 3
) -> str:
    """Determine achievable connection after peak shaving with battery."""
    shaved_peak = max(peak_kw - inverter_kw * 0.7, 2.0)
    return connection_for_peak(shaved_peak, phases)


def daily_surplus_profile(pv_kwh_year: float, self_consumption_pct: float) -> float:
    """Average daily surplus available for storage (kWh)."""
    annual_surplus = pv_kwh_year * (1 - self_consumption_pct)
    return annual_surplus / 365


def _peak_day_surplus(pv_kwh_year: float, self_consumption_pct: float) -> float:
    """
    Estimate surplus on a peak production day (sunny spring/summer).
    In NL, peak days produce ~2.2x the annual daily average.
    Direct self-consumption on peak days is lower (as % of production)
    because production far exceeds momentary demand.
    """
    avg_daily = pv_kwh_year / 365
    peak_daily = avg_daily * 2.2
    sc_on_peak_day = self_consumption_pct * 0.4
    return peak_daily * (1 - sc_on_peak_day)


def recommended_capacity_range(
    pv_kwh_year: float,
    annual_consumption_kwh: float,
    self_consumption_pct: float,
    peak_kw: float,
    goal: str = "balanced",
) -> dict:
    """
    Calculate recommended battery capacity range.

    Takes into account:
    - Average AND peak-day PV surplus (not just average)
    - Peak shaving capacity needs (sustained discharge at peak_kw)
    - Evening/night consumption patterns
    """
    daily_surplus = daily_surplus_profile(pv_kwh_year, self_consumption_pct)
    peak_surplus = _peak_day_surplus(pv_kwh_year, self_consumption_pct)
    daily_consumption = annual_consumption_kwh / 365
    evening_consumption = daily_consumption * 0.4

    optimal_pv_avg = round(daily_surplus * 1.2)
    optimal_pv_peak = round(peak_surplus * 0.6)
    optimal_pv = max(optimal_pv_avg, optimal_pv_peak)

    optimal_arb = round(evening_consumption * 0.8)

    peak_shave_hours = 2.0
    optimal_peak = round(peak_kw * peak_shave_hours * 0.5)

    if goal == "max_rendement":
        optimal = max(optimal_pv_avg, optimal_arb + 5, optimal_peak)
    elif goal == "max_autarkie":
        optimal = max(optimal_pv, optimal_arb, optimal_peak) + 10
    elif goal == "peak_shaving":
        optimal = max(optimal_peak, round(peak_kw * 2.0))
    else:
        optimal = max(
            round((optimal_pv + optimal_arb) / 2) + 5,
            optimal_peak,
        )

    min_kwh = max(5, round(daily_surplus * 0.7))
    optimal_kwh = max(min_kwh, optimal)
    max_kwh = round(optimal_kwh * 1.4)

    return {
        "min_kwh": min_kwh,
        "optimal_kwh": optimal_kwh,
        "max_kwh": max_kwh,
        "daily_surplus_kwh": round(daily_surplus, 1),
        "peak_day_surplus_kwh": round(peak_surplus, 1),
        "evening_consumption_kwh": round(evening_consumption, 1),
        "reasoning": {
            "pv_based_avg": optimal_pv_avg,
            "pv_based_peak": optimal_pv_peak,
            "consumption_based": optimal_arb,
            "peak_shaving_based": optimal_peak,
        },
    }


def recommended_inverter_range(
    peak_kw: float,
    battery_kwh: float,
    pv_kwp: float = 0,
    annual_consumption_kwh: float = 4000,
    goal: str = "balanced",
) -> dict:
    """
    Recommend inverter power range (min / optimal / max kW).

    Drivers:
    - Peak shaving: need enough kW to cover peaks (at least ~50-60% of peak)
    - Charge rate: battery should charge in 2-4h from PV surplus
    - Arbitrage throughput: faster charge/discharge = more spread captured
    - PV clipping: in DC-coupled, inverter must handle PV peak output
    - Diminishing returns: beyond optimal, extra kW adds cost but little revenue
    """
    min_for_peak = peak_kw * 0.4
    min_for_charge = battery_kwh / 4
    min_kw = max(3.0, min_for_peak, min_for_charge)

    opt_for_peak = peak_kw * 0.6
    opt_for_charge = battery_kwh / 2.5
    opt_for_arb = battery_kwh / 2
    optimal_kw = max(5.0, opt_for_peak, opt_for_charge)

    if goal == "peak_shaving":
        optimal_kw = max(optimal_kw, peak_kw * 0.7)
    elif goal == "max_rendement":
        optimal_kw = max(optimal_kw, opt_for_arb)
    elif goal == "max_autarkie":
        optimal_kw = max(optimal_kw, pv_kwp * 0.5 if pv_kwp > 0 else optimal_kw)

    max_useful = max(optimal_kw, peak_kw * 0.8)
    max_kw = min(max_useful, peak_kw)

    return {
        "min_kw": round(min_kw, 1),
        "optimal_kw": round(optimal_kw, 1),
        "max_kw": round(max_kw, 1),
        "reasoning": {
            "peak_shaving": round(opt_for_peak, 1),
            "charge_rate": round(opt_for_charge, 1),
            "arbitrage": round(opt_for_arb, 1),
        },
    }
