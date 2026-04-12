"""
Sizing engine: determines optimal battery capacity and inverter power
based on PV production, consumption profile, constraints, and goals.
"""

from __future__ import annotations

import math


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


def recommended_capacity_range(
    pv_kwh_year: float,
    annual_consumption_kwh: float,
    self_consumption_pct: float,
    peak_kw: float,
    goal: str = "balanced",
) -> dict:
    """
    Calculate recommended battery capacity range.

    Returns dict with min_kwh, optimal_kwh, max_kwh and reasoning.
    """
    daily_surplus = daily_surplus_profile(pv_kwh_year, self_consumption_pct)
    daily_consumption = annual_consumption_kwh / 365
    evening_consumption = daily_consumption * 0.4

    min_useful = max(3, round(daily_surplus * 0.5))
    optimal_pv = round(daily_surplus * 1.2)
    optimal_arb = round(evening_consumption * 0.6)

    if goal == "max_rendement":
        optimal = min(optimal_pv, optimal_arb + 5)
    elif goal == "max_autarkie":
        optimal = max(optimal_pv, optimal_arb) + 10
    elif goal == "peak_shaving":
        optimal = max(10, round(peak_kw * 1.5))
    else:
        optimal = round((optimal_pv + optimal_arb) / 2) + 5

    min_kwh = max(5, min_useful)
    optimal_kwh = max(min_kwh, optimal)
    max_kwh = round(optimal_kwh * 1.8)

    return {
        "min_kwh": min_kwh,
        "optimal_kwh": optimal_kwh,
        "max_kwh": max_kwh,
        "daily_surplus_kwh": round(daily_surplus, 1),
        "evening_consumption_kwh": round(evening_consumption, 1),
        "reasoning": {
            "pv_based": optimal_pv,
            "consumption_based": optimal_arb,
            "peak_based": round(peak_kw * 1.5),
        },
    }


def recommended_inverter_kw(
    peak_kw: float,
    battery_kwh: float,
    pv_kwp: float = 0,
    coupling: str = "AC",
) -> float:
    """
    Recommend inverter power.
    For AC-coupling: must handle peak demand independently.
    For DC-coupling: works alongside existing PV inverter.
    """
    min_for_peak = peak_kw * 0.6
    min_for_charge_rate = battery_kwh / 3
    min_for_pv = pv_kwp * 0.5 if coupling == "DC" else 0

    recommended = max(min_for_peak, min_for_charge_rate, min_for_pv, 3.0)
    standard_sizes = [3, 5, 6, 8, 10, 12, 15, 17, 20, 25, 30]
    for size in standard_sizes:
        if size >= recommended:
            return float(size)
    return float(standard_sizes[-1])
