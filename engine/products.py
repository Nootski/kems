"""
Product database for home battery systems.
Prices are indicative installed prices (excl. BTW) for the Dutch market, mid-2025.
"""

PRODUCTS = {
    "sigenstor": {
        "brand": "SigenStor",
        "chemistry": "LFP",
        "coupling": "AC",
        "module_kwh": 5.0,
        "min_modules": 1,
        "max_modules": 20,
        "inverter_options_kw": [10, 15, 20],
        "roundtrip_efficiency": 0.91,
        "cycle_life": 6000,
        "dod": 0.95,
        "module_dims_cm": {"w": 58, "d": 25, "h": 60},
        "module_weight_kg": 52,
        "price_per_kwh_installed": 340,
        "inverter_price": {10: 2800, 15: 3200, 20: 3800},
        "installation_base": 1500,
        "indoor_outdoor": "both",
        "ip_rating": "IP65",
        "warranty_years": 10,
        "notstrom": True,
        "three_phase": True,
    },
    "byd_hvs": {
        "brand": "BYD HVS",
        "chemistry": "LFP",
        "coupling": "DC",
        "module_kwh": 2.56,
        "min_modules": 2,
        "max_modules": 5,
        "inverter_options_kw": [5, 8, 10],
        "roundtrip_efficiency": 0.93,
        "cycle_life": 6000,
        "dod": 0.96,
        "module_dims_cm": {"w": 59, "d": 30, "h": 133},
        "module_weight_kg": 26,
        "price_per_kwh_installed": 380,
        "inverter_price": {5: 2200, 8: 2800, 10: 3200},
        "installation_base": 1200,
        "indoor_outdoor": "indoor",
        "ip_rating": "IP55",
        "warranty_years": 10,
        "notstrom": True,
        "three_phase": True,
    },
    "byd_hvm": {
        "brand": "BYD HVM",
        "chemistry": "LFP",
        "coupling": "DC",
        "module_kwh": 2.76,
        "min_modules": 2,
        "max_modules": 8,
        "inverter_options_kw": [5, 8, 10, 15],
        "roundtrip_efficiency": 0.93,
        "cycle_life": 6000,
        "dod": 0.96,
        "module_dims_cm": {"w": 59, "d": 30, "h": 133},
        "module_weight_kg": 27,
        "price_per_kwh_installed": 370,
        "inverter_price": {5: 2200, 8: 2800, 10: 3200, 15: 3600},
        "installation_base": 1200,
        "indoor_outdoor": "indoor",
        "ip_rating": "IP55",
        "warranty_years": 10,
        "notstrom": True,
        "three_phase": True,
    },
    "huawei_luna2000": {
        "brand": "Huawei LUNA2000",
        "chemistry": "LFP",
        "coupling": "DC",
        "module_kwh": 5.0,
        "min_modules": 1,
        "max_modules": 6,
        "inverter_options_kw": [5, 8, 10],
        "roundtrip_efficiency": 0.92,
        "cycle_life": 6000,
        "dod": 0.95,
        "module_dims_cm": {"w": 67, "d": 15, "h": 60},
        "module_weight_kg": 63,
        "price_per_kwh_installed": 360,
        "inverter_price": {5: 2000, 8: 2600, 10: 3000},
        "installation_base": 1300,
        "indoor_outdoor": "both",
        "ip_rating": "IP66",
        "warranty_years": 10,
        "notstrom": True,
        "three_phase": True,
    },
    "tesla_powerwall3": {
        "brand": "Tesla Powerwall 3",
        "chemistry": "LFP",
        "coupling": "AC",
        "module_kwh": 13.5,
        "min_modules": 1,
        "max_modules": 4,
        "inverter_options_kw": [11.5],
        "roundtrip_efficiency": 0.90,
        "cycle_life": 5000,
        "dod": 1.0,
        "module_dims_cm": {"w": 61, "d": 19, "h": 114},
        "module_weight_kg": 112,
        "price_per_kwh_installed": 420,
        "inverter_price": {11.5: 0},  # integrated
        "installation_base": 2000,
        "indoor_outdoor": "both",
        "ip_rating": "IP67",
        "warranty_years": 10,
        "notstrom": True,
        "three_phase": False,
    },
    "enphase_iq5p": {
        "brand": "Enphase IQ 5P",
        "chemistry": "LFP",
        "coupling": "AC",
        "module_kwh": 5.0,
        "min_modules": 1,
        "max_modules": 8,
        "inverter_options_kw": [3.84],
        "roundtrip_efficiency": 0.90,
        "cycle_life": 6000,
        "dod": 1.0,
        "module_dims_cm": {"w": 43, "d": 19, "h": 114},
        "module_weight_kg": 55,
        "price_per_kwh_installed": 400,
        "inverter_price": {3.84: 0},  # micro-inverters, integrated per module
        "installation_base": 1500,
        "indoor_outdoor": "both",
        "ip_rating": "IP55",
        "warranty_years": 15,
        "notstrom": True,
        "three_phase": True,
    },
}


GRID_COSTS_2025 = {
    "stedin": {
        "1x25A": 290, "3x25A": 474, "3x35A": 1923,
        "3x40A": 2100, "3x50A": 2600, "3x63A": 3200, "3x80A": 4000,
    },
    "liander": {
        "1x25A": 280, "3x25A": 460, "3x35A": 1850,
        "3x40A": 2020, "3x50A": 2500, "3x63A": 3100, "3x80A": 3800,
    },
    "enexis": {
        "1x25A": 285, "3x25A": 465, "3x35A": 1880,
        "3x40A": 2050, "3x50A": 2550, "3x63A": 3150, "3x80A": 3900,
    },
}


def get_product_configs(product_key: str) -> list[dict]:
    """Generate all valid configurations for a product."""
    p = PRODUCTS[product_key]
    configs = []
    for n_modules in range(p["min_modules"], p["max_modules"] + 1):
        capacity = round(n_modules * p["module_kwh"], 2)
        for inv_kw in p["inverter_options_kw"]:
            price = (
                capacity * p["price_per_kwh_installed"]
                + p["inverter_price"].get(inv_kw, 0)
                + p["installation_base"]
            )
            total_h = p["module_dims_cm"]["h"] * n_modules
            configs.append({
                "product": product_key,
                "brand": p["brand"],
                "capacity_kwh": capacity,
                "usable_kwh": round(capacity * p["dod"], 2),
                "inverter_kw": inv_kw,
                "efficiency": p["roundtrip_efficiency"],
                "price_eur": round(price),
                "dims_cm": {
                    "w": p["module_dims_cm"]["w"],
                    "d": p["module_dims_cm"]["d"],
                    "h": total_h,
                },
                "weight_kg": p["module_weight_kg"] * n_modules,
                "coupling": p["coupling"],
                "indoor_outdoor": p["indoor_outdoor"],
                "notstrom": p["notstrom"],
                "three_phase": p["three_phase"],
                "warranty_years": p["warranty_years"],
                "cycle_life": p["cycle_life"],
            })
    return configs


def get_all_configs() -> list[dict]:
    """Return all possible product configurations."""
    all_configs = []
    for key in PRODUCTS:
        all_configs.extend(get_product_configs(key))
    return all_configs


def get_grid_cost(netbeheerder: str, connection: str) -> int | None:
    """Return annual grid cost for a given netbeheerder and connection type."""
    nb = netbeheerder.lower()
    if nb in GRID_COSTS_2025:
        return GRID_COSTS_2025[nb].get(connection)
    return None
