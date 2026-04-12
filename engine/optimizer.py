"""
Configuration optimizer: iterates over product configurations,
applies constraints, calculates business case, and ranks results.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.products import get_all_configs, get_grid_cost
from engine.revenue import RevenueInputs, calculate_all, total_annual_revenue
from engine.sizing import (
    recommended_capacity_range,
    recommended_inverter_range,
    target_connection_with_battery,
    estimate_peak_demand,
)


@dataclass
class OptimizedConfig:
    product: str
    brand: str
    capacity_kwh: float
    usable_kwh: float
    inverter_kw: float
    efficiency: float
    price_eur: int
    annual_revenue: float
    payback_years: float
    revenue_breakdown: list
    coupling: str
    dims_cm: dict
    weight_kg: float
    notstrom: bool
    three_phase: bool
    warranty_years: int
    cycle_life: int = 6000
    expandable: bool = True
    ems: str = ""
    ems_features: list = field(default_factory=list)
    integration_protocols: list = field(default_factory=list)
    integration_platforms: list = field(default_factory=list)
    integration_score: int = 1
    modularity_score: int = 1
    score: float = 0
    within_recommendation: bool = True
    details: dict = field(default_factory=dict)


def _fits_space(config: dict, space: dict | None) -> bool:
    if not space or not any(space.values()):
        return True
    cw = space.get("width", 9999)
    cd = space.get("depth", 9999)
    ch = space.get("height", 9999)
    return (
        config["dims_cm"]["w"] <= cw
        and config["dims_cm"]["d"] <= cd
        and config["dims_cm"]["h"] <= ch
    )


def _fits_placement(config: dict, placement: str | None) -> bool:
    if not placement:
        return True
    if placement == "outdoor" and config["indoor_outdoor"] == "indoor":
        return False
    return True


def optimize(inputs: dict) -> list[OptimizedConfig]:
    """
    Main optimization entry point.
    inputs: dict from the intake form with all user-provided data.
    Returns sorted list of OptimizedConfig (best first).
    """
    pv_kwh = inputs.get("pv_kwh_year", 0)
    annual_kwh = inputs.get("annual_consumption_kwh", 4000)
    sc_pct = inputs.get("self_consumption_pct", 0.30)
    budget = inputs.get("budget", 999999)
    space = inputs.get("space")
    placement = inputs.get("placement")
    goal = inputs.get("goal", "balanced")
    phases = inputs.get("phases", 3)
    current_conn = inputs.get("current_connection", "3x25A")
    netbeheerder = inputs.get("netbeheerder", "stedin")
    contract_type = inputs.get("contract_type", "dynamic")
    purchase_price = inputs.get("purchase_price_kwh", 0.21)
    feedin_price = inputs.get("feedin_price_kwh", 0.10)
    coupling_pref = inputs.get("coupling_preference")
    notstrom_required = inputs.get("notstrom", False)
    three_phase_required = phases == 3

    has_heat_pump = inputs.get("has_heat_pump", False)
    heat_pump_kw = inputs.get("heat_pump_kw", 0)
    has_ev = inputs.get("has_ev", False)
    ev_charger_kw = inputs.get("ev_charger_kw", 0)
    has_induction = inputs.get("has_induction", False)
    extra_peak_kw = inputs.get("extra_peak_kw", 0)

    ev_battery_kwh = inputs.get("ev_battery_kwh", 0)
    has_v2h = inputs.get("has_v2h", False)
    ev_soc_window = inputs.get("ev_soc_window", 0.30)
    ev_availability = inputs.get("ev_availability", 0.66)

    peak_kw = inputs.get("peak_kw") or estimate_peak_demand(
        annual_kwh, has_heat_pump, heat_pump_kw,
        has_ev, ev_charger_kw, has_induction, extra_peak_kw,
    )

    rec = recommended_capacity_range(pv_kwh, annual_kwh, sc_pct, peak_kw, goal)

    pv_kwp = inputs.get("pv_kwp", 0)
    inv_rec = recommended_inverter_range(
        peak_kw, rec["optimal_kwh"], pv_kwp, annual_kwh, goal,
    )

    grid_current = get_grid_cost(netbeheerder, current_conn) or 1923
    all_configs = get_all_configs()

    results = []
    for cfg in all_configs:
        if cfg["price_eur"] > budget:
            continue
        if not _fits_space(cfg, space):
            continue
        if not _fits_placement(cfg, placement):
            continue
        if coupling_pref and coupling_pref != "any" and cfg["coupling"].lower() != coupling_pref.lower():
            continue
        if notstrom_required and not cfg["notstrom"]:
            continue
        if three_phase_required and not cfg["three_phase"]:
            continue

        tgt_conn = target_connection_with_battery(peak_kw, cfg["inverter_kw"], phases)
        grid_target = get_grid_cost(netbeheerder, tgt_conn) or grid_current

        rev_inputs = RevenueInputs(
            pv_kwh_year=pv_kwh,
            self_consumption_pct_no_battery=sc_pct,
            purchase_price_kwh=purchase_price,
            feedin_price_kwh=feedin_price,
            contract_type=contract_type,
            battery_kwh=cfg["capacity_kwh"],
            usable_kwh=cfg["usable_kwh"],
            inverter_kw=cfg["inverter_kw"],
            battery_efficiency=cfg["efficiency"],
            arbitrage_spread=0.115,
            arbitrage_days_per_year=220,
            current_connection=current_conn,
            target_connection=tgt_conn,
            grid_cost_current=grid_current,
            grid_cost_target=grid_target,
            peak_kw_without_battery=peak_kw,
            capacity_tariff_per_kw=40,
            fcr_kw_available=cfg["inverter_kw"] * 0.3,
            fcr_price_per_kw_year=50,
            ev_battery_kwh=ev_battery_kwh,
            ev_soc_window=ev_soc_window,
            ev_availability=ev_availability,
            ev_cycles_year=180,
            ev_efficiency=0.90,
            ev_extra_pv_shift_kwh=800 if has_v2h else 0,
            ev_pv_shift_efficiency=0.85,
            has_v2h=has_v2h,
            goal=goal,
        )

        rev_results = calculate_all(rev_inputs)
        annual_rev = total_annual_revenue(rev_results)
        payback = cfg["price_eur"] / annual_rev if annual_rev > 0 else 999

        within_rec = rec["min_kwh"] <= cfg["capacity_kwh"] <= rec["max_kwh"]
        inverter_in_range = inv_rec["min_kw"] <= cfg["inverter_kw"] <= inv_rec["max_kw"]

        score = _calc_score(cfg, annual_rev, payback, rec, inv_rec, goal, within_rec, inverter_in_range)

        results.append(OptimizedConfig(
            product=cfg["product"],
            brand=cfg["brand"],
            capacity_kwh=cfg["capacity_kwh"],
            usable_kwh=cfg["usable_kwh"],
            inverter_kw=cfg["inverter_kw"],
            efficiency=cfg["efficiency"],
            price_eur=cfg["price_eur"],
            annual_revenue=round(annual_rev, 2),
            payback_years=round(payback, 1),
            revenue_breakdown=[
                {"name": r.name, "annual_eur": r.annual_eur,
                 "enabled": r.enabled, "description": r.description}
                for r in rev_results
            ],
            coupling=cfg["coupling"],
            dims_cm=cfg["dims_cm"],
            weight_kg=cfg["weight_kg"],
            notstrom=cfg["notstrom"],
            three_phase=cfg["three_phase"],
            warranty_years=cfg["warranty_years"],
            cycle_life=cfg.get("cycle_life", 6000),
            expandable=cfg.get("expandable", False),
            ems=cfg.get("ems", ""),
            ems_features=cfg.get("ems_features", []),
            integration_protocols=cfg.get("integration_protocols", []),
            integration_platforms=cfg.get("integration_platforms", []),
            integration_score=cfg.get("integration_score", 1),
            modularity_score=cfg.get("modularity_score", 1),
            score=round(score, 2),
            within_recommendation=within_rec,
            details={
                "recommended_range": rec,
                "recommended_inverter": inv_rec,
                "target_connection": tgt_conn,
                "peak_kw": round(peak_kw, 1),
            },
        ))

    results.sort(key=lambda x: x.score, reverse=True)
    return results


def _calc_score(
    cfg: dict, annual_rev: float, payback: float,
    rec: dict, inv_rec: dict, goal: str,
    within_rec: bool, inverter_in_range: bool,
) -> float:
    """
    Compute a weighted score to rank configurations.
    Higher = better. Incorporates all 10 kernvariabelen plus
    inverter right-sizing (too big = expensive, too small = limited revenue).
    """
    if payback >= 999:
        return -1000

    payback_score = max(0, 20 - payback) * 5
    revenue_score = annual_rev / 100
    rec_bonus = 15 if within_rec else 0
    efficiency_score = cfg["efficiency"] * 20
    cycle_life_score = min(cfg.get("cycle_life", 6000) / 1000, 8) * 2
    integration_score = cfg.get("integration_score", 1) * 3
    modularity_score = cfg.get("modularity_score", 1) * 2

    inv_kw = cfg["inverter_kw"]
    inv_opt = inv_rec["optimal_kw"]
    inv_min = inv_rec["min_kw"]
    if inv_kw < inv_min:
        inverter_score = -15
    elif inverter_in_range:
        closeness = 1 - abs(inv_kw - inv_opt) / max(inv_opt, 1)
        inverter_score = 10 * max(0, closeness)
    else:
        overshoot = (inv_kw - inv_rec["max_kw"]) / max(inv_opt, 1)
        inverter_score = -5 * min(overshoot, 2)

    if goal == "max_rendement":
        payback_score *= 2
        revenue_score *= 0.8
    elif goal == "max_autarkie":
        capacity_bonus = min(cfg["capacity_kwh"] / rec["max_kwh"], 1.0) * 30
        revenue_score += capacity_bonus
        payback_score *= 0.5
    elif goal == "peak_shaving":
        peak_inv_bonus = min(inv_kw / inv_opt, 1.5) * 15
        revenue_score += peak_inv_bonus

    return (
        payback_score + revenue_score + rec_bonus + efficiency_score
        + cycle_life_score + integration_score + modularity_score
        + inverter_score
    )


def get_top_configs(inputs: dict, n: int = 3) -> list[OptimizedConfig]:
    """Return the top-n recommended configurations."""
    all_results = optimize(inputs)
    if not all_results:
        return []

    top = []
    seen_brands = set()
    for r in all_results:
        key = (r.brand, r.capacity_kwh, r.inverter_kw)
        if key not in seen_brands:
            top.append(r)
            seen_brands.add(key)
        if len(top) >= n:
            break

    return top
