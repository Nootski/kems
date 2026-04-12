"""
Revenue calculator implementing the 6 revenue models from the Excel,
now fully parametric based on battery size, inverter, and user inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class RevenueInputs:
    pv_kwh_year: float = 0
    self_consumption_pct_no_battery: float = 0.30
    purchase_price_kwh: float = 0.21
    feedin_price_kwh: float = 0.10
    contract_type: str = "dynamic"

    battery_kwh: float = 0
    usable_kwh: float = 0
    inverter_kw: float = 0
    battery_efficiency: float = 0.91

    arbitrage_spread: float = 0.115
    arbitrage_days_per_year: int = 220

    current_connection: str = "3x35A"
    target_connection: str = "3x25A"
    grid_cost_current: float = 1923
    grid_cost_target: float = 474
    peak_kw_without_battery: float = 27
    capacity_tariff_per_kw: float = 40

    fcr_kw_available: float = 0
    fcr_price_per_kw_year: float = 50

    ev_battery_kwh: float = 0
    ev_soc_window: float = 0.30
    ev_availability: float = 0.66
    ev_cycles_year: int = 180
    ev_efficiency: float = 0.90
    ev_extra_pv_shift_kwh: float = 800
    ev_pv_shift_efficiency: float = 0.85
    has_v2h: bool = False

    goal: str = "balanced"


@dataclass
class RevenueResult:
    name: str
    description: str
    annual_eur: float
    formula: str
    enabled: bool = True
    details: dict = field(default_factory=dict)


def _estimate_self_consumption_target(
    usable_kwh: float, pv_kwh_year: float, base_sc: float
) -> float:
    """
    Estimate achievable self-consumption with a battery.
    Larger batteries increase self-consumption but with diminishing returns.
    Based on empirical data: each kWh of usable storage adds ~0.5-1% SC
    for a typical Dutch PV system, tapering off.
    """
    if pv_kwh_year <= 0:
        return base_sc

    daily_surplus_kwh = pv_kwh_year * (1 - base_sc) / 365
    capturable_fraction = min(1.0, usable_kwh / max(daily_surplus_kwh, 0.1))
    max_improvement = 1.0 - base_sc
    improvement = max_improvement * capturable_fraction * 0.75
    return min(0.95, base_sc + improvement)


def _estimate_peak_kw(annual_kwh: float, large_consumers: list[dict] | None = None) -> float:
    """Estimate peak demand based on annual consumption and large consumers."""
    base_peak = annual_kwh / 8760 * 4
    extra = 0
    if large_consumers:
        for lc in large_consumers:
            extra += lc.get("peak_kw", 0)
    return max(base_peak, 3.0) + extra


def calc_pv_shift(inp: RevenueInputs) -> RevenueResult:
    """Model 1: PV self-consumption shift."""
    if inp.pv_kwh_year <= 0:
        return RevenueResult(
            name="PV-shift",
            description="Geen PV-installatie opgegeven",
            annual_eur=0, formula="N/A", enabled=False,
        )

    target_sc = _estimate_self_consumption_target(
        inp.usable_kwh, inp.pv_kwh_year, inp.self_consumption_pct_no_battery
    )
    extra_kwh = (target_sc - inp.self_consumption_pct_no_battery) * inp.pv_kwh_year
    shifted_kwh = extra_kwh / inp.battery_efficiency
    value_per_kwh = inp.battery_efficiency * inp.purchase_price_kwh - inp.feedin_price_kwh
    annual = shifted_kwh * value_per_kwh

    return RevenueResult(
        name="PV-shift",
        description="Eigenverbruik verhogen door PV-surplus op te slaan",
        annual_eur=round(max(annual, 0), 2),
        formula=f"({target_sc:.0%} - {inp.self_consumption_pct_no_battery:.0%}) × {inp.pv_kwh_year:.0f} kWh / η × (η×inkoop - teruglever)",
        details={
            "target_self_consumption": round(target_sc, 3),
            "extra_kwh_shifted": round(extra_kwh, 1),
            "value_per_kwh": round(value_per_kwh, 4),
        },
    )


def calc_arbitrage(inp: RevenueInputs) -> RevenueResult:
    """Model 2: Dynamic tariff arbitrage (buy low, sell high)."""
    if inp.contract_type != "dynamic":
        return RevenueResult(
            name="Arbitrage (dynamisch)",
            description="Alleen relevant bij dynamisch contract",
            annual_eur=0, formula="N/A", enabled=False,
        )

    kwh_per_cycle = min(inp.usable_kwh * 0.5, inp.usable_kwh)
    pv_shift_days = 180 if inp.pv_kwh_year > 5000 else 90
    available_days = inp.arbitrage_days_per_year
    effective_cycles = max(0, available_days)
    annual = effective_cycles * kwh_per_cycle * inp.arbitrage_spread * inp.battery_efficiency

    return RevenueResult(
        name="Arbitrage (dynamisch)",
        description="Laden in goedkope uren, ontladen in dure uren",
        annual_eur=round(annual, 2),
        formula=f"{effective_cycles} cycli × {kwh_per_cycle:.1f} kWh × €{inp.arbitrage_spread:.3f} × {inp.battery_efficiency:.0%}",
        details={
            "effective_cycles": effective_cycles,
            "kwh_per_cycle": round(kwh_per_cycle, 1),
        },
    )


def calc_peak_shaving(inp: RevenueInputs) -> RevenueResult:
    """Model 3: Connection downgrade by shaving peaks with battery."""
    if inp.grid_cost_current <= inp.grid_cost_target:
        return RevenueResult(
            name="Peak shaving (nu)",
            description="Geen downgrade mogelijk",
            annual_eur=0, formula="N/A", enabled=False,
        )

    can_shave_kw = min(inp.inverter_kw, inp.peak_kw_without_battery * 0.5)
    connection_hierarchy = ["1x25A", "3x25A", "3x35A", "3x40A", "3x50A", "3x63A", "3x80A"]
    current_idx = (
        connection_hierarchy.index(inp.current_connection)
        if inp.current_connection in connection_hierarchy else -1
    )
    target_idx = (
        connection_hierarchy.index(inp.target_connection)
        if inp.target_connection in connection_hierarchy else -1
    )

    if current_idx <= target_idx or current_idx < 0:
        return RevenueResult(
            name="Peak shaving (nu)",
            description="Downgrade niet haalbaar met deze configuratie",
            annual_eur=0, formula="N/A", enabled=False,
        )

    saving = inp.grid_cost_current - inp.grid_cost_target

    return RevenueResult(
        name="Peak shaving (nu)",
        description=f"Downgrade van {inp.current_connection} naar {inp.target_connection}",
        annual_eur=round(saving, 2),
        formula=f"€{inp.grid_cost_current:.0f} - €{inp.grid_cost_target:.0f}",
        details={
            "can_shave_kw": round(can_shave_kw, 1),
            "current_connection": inp.current_connection,
            "target_connection": inp.target_connection,
        },
    )


def calc_capacity_tariff(inp: RevenueInputs) -> RevenueResult:
    """Model 4: Future capacity tariff savings."""
    saved_kw = min(inp.inverter_kw, max(0, inp.peak_kw_without_battery - 5))
    annual = saved_kw * inp.capacity_tariff_per_kw

    return RevenueResult(
        name="Capaciteitstarief (toekomstig)",
        description="Besparing op kwartierpiek-tarief (verwacht vanaf 2027+)",
        annual_eur=round(annual, 2),
        formula=f"{saved_kw:.0f} kW × €{inp.capacity_tariff_per_kw:.0f}/kW/jaar",
        details={"saved_kw": round(saved_kw, 1)},
    )


def calc_fcr(inp: RevenueInputs) -> RevenueResult:
    """Model 5: FCR / imbalance market revenue via aggregator."""
    available_kw = min(inp.inverter_kw * 0.3, inp.usable_kwh * 0.2)
    annual = available_kw * inp.fcr_price_per_kw_year

    return RevenueResult(
        name="Onbalansmarkt (FCR)",
        description="Deelname via aggregator, conservatieve schatting",
        annual_eur=round(annual, 2),
        formula=f"{available_kw:.1f} kW × €{inp.fcr_price_per_kw_year:.0f}/kW/jaar",
        details={"available_kw": round(available_kw, 1)},
    )


def calc_ev_integration(inp: RevenueInputs) -> RevenueResult:
    """Model 6: EV V2H/V2G integration."""
    if not inp.has_v2h or inp.ev_battery_kwh <= 0:
        return RevenueResult(
            name="EV-integratie (V2H/V2G)",
            description="Geen V2H/V2G of geen EV opgegeven",
            annual_eur=0, formula="N/A", enabled=False,
        )

    usable_ev_kwh = inp.ev_battery_kwh * inp.ev_soc_window
    arb_revenue = (
        inp.ev_cycles_year * usable_ev_kwh * inp.ev_availability
        * inp.arbitrage_spread * inp.ev_efficiency
    )
    pv_shift_value = inp.ev_extra_pv_shift_kwh * (
        inp.ev_pv_shift_efficiency * inp.purchase_price_kwh - inp.feedin_price_kwh
    )
    annual = arb_revenue + max(pv_shift_value, 0)

    return RevenueResult(
        name="EV-integratie (V2H/V2G)",
        description="Extra opbrengst via EV-accu (V2H/V2G arbitrage + PV-shift)",
        annual_eur=round(annual, 2),
        formula="EV_cycli × EV_kWh × SOC × beschikb × spread × η + PV_shift",
        details={
            "usable_ev_kwh": round(usable_ev_kwh, 1),
            "arb_revenue": round(arb_revenue, 2),
            "pv_shift_value": round(max(pv_shift_value, 0), 2),
        },
    )


def calculate_all(inp: RevenueInputs) -> list[RevenueResult]:
    """Run all 6 revenue models and return results."""
    return [
        calc_pv_shift(inp),
        calc_arbitrage(inp),
        calc_peak_shaving(inp),
        calc_capacity_tariff(inp),
        calc_fcr(inp),
        calc_ev_integration(inp),
    ]


def total_annual_revenue(results: list[RevenueResult], include_disabled: bool = False) -> float:
    """Sum up annual revenue from all (enabled) models."""
    return sum(
        r.annual_eur for r in results
        if r.enabled or include_disabled
    )
