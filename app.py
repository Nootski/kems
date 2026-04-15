import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, request, jsonify

from engine.optimizer import get_top_configs
from engine.sizing import estimate_pv_yield

app = Flask(__name__)

try:
    __version__ = (Path(__file__).parent / "VERSION").read_text().strip()
except OSError:
    __version__ = "0.0.0"


@app.context_processor
def _inject_version():
    return {"app_version": __version__}

DATA_DIR = Path(os.environ.get(
    "KEMS_DATA_DIR",
    Path(__file__).parent / "data",
))
FEEDBACK_FILE = DATA_DIR / "feedback.json"
CALC_LOG_FILE = DATA_DIR / "calculations.jsonl"
_fb_lock = threading.Lock()
_log_lock = threading.Lock()


def _read_feedback() -> list[dict]:
    try:
        return json.loads(FEEDBACK_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write_feedback(msgs: list[dict]):
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_FILE.write_text(json.dumps(msgs, ensure_ascii=False, indent=2))


def _log_calculation(inputs: dict, top_result: dict | None, source: str):
    """Append a calculation to the log file (one JSON object per line)."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "inputs": {k: v for k, v in inputs.items() if k != "space"},
        "top_result": {
            "brand": top_result["brand"],
            "capacity_kwh": top_result["capacity_kwh"],
            "inverter_kw": top_result["inverter_kw"],
            "price_eur": top_result["price_eur"],
            "annual_revenue": top_result["annual_revenue"],
            "payback_years": top_result["payback_years"],
        } if top_result else None,
    }
    with _log_lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(CALC_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

GOAL_LABELS = {
    "balanced": "Beste balans (rendement + autarkie)",
    "max_rendement": "Maximaal financieel rendement",
    "max_autarkie": "Maximale zelfvoorzienendheid",
    "peak_shaving": "Primair peak shaving",
}


def _parse_inputs(data: dict) -> dict:
    """Parse raw form/JSON data into optimizer inputs."""

    def _float(key, default=0.0):
        try:
            return float(data.get(key, default))
        except (TypeError, ValueError):
            return default

    def _int(key, default=0):
        try:
            return int(data.get(key, default))
        except (TypeError, ValueError):
            return default

    def _bool(key):
        v = data.get(key)
        if isinstance(v, bool):
            return v
        return v in ("on", "true", "1", True)

    has_pv = _bool("has_pv")
    pv_kwp = _float("pv_kwp")
    pv_orientation = data.get("pv_orientation", "east_west")
    pv_tilt = _float("pv_tilt", 35)
    pv_kwh_year = _float("pv_kwh_year")

    if has_pv and pv_kwh_year <= 0 and pv_kwp > 0:
        pv_kwh_year = estimate_pv_yield(pv_kwp, pv_orientation, pv_tilt)
    if not has_pv:
        pv_kwh_year = 0

    sc = _float("self_consumption_pct", 30)
    if sc > 1:
        sc /= 100.0

    space = None
    sw = _float("space_width")
    sd = _float("space_depth")
    sh = _float("space_height")
    if sw > 0 or sd > 0 or sh > 0:
        space = {
            "width": sw if sw > 0 else 9999,
            "depth": sd if sd > 0 else 9999,
            "height": sh if sh > 0 else 9999,
        }

    inputs = {
        "phases": _int("phases", 3),
        "current_connection": data.get("current_connection", "3x35A"),
        "netbeheerder": data.get("netbeheerder", "stedin"),
        "contract_type": data.get("contract_type", "dynamic"),
        "purchase_price_kwh": _float("purchase_price_kwh", 0.21),
        "feedin_price_kwh": _float("feedin_price_kwh", 0.10),
        "has_pv": has_pv,
        "pv_kwp": pv_kwp,
        "pv_orientation": pv_orientation,
        "pv_tilt": pv_tilt,
        "pv_kwh_year": pv_kwh_year,
        "annual_consumption_kwh": _float("annual_consumption_kwh", 4000),
        "peak_kw": _float("peak_kw") or None,
        "self_consumption_pct": sc,
        "has_heat_pump": _bool("has_heat_pump"),
        "heat_pump_kw": _float("heat_pump_kw", 3.5),
        "has_ev": _bool("has_ev"),
        "ev_charger_kw": _float("ev_charger_kw", 11),
        "ev_battery_kwh": _float("ev_battery_kwh", 0),
        "has_v2h": _bool("has_v2h"),
        "has_induction": _bool("has_induction"),
        "extra_peak_kw": 0,
        "budget": _float("budget", 25000),
        "goal": data.get("goal", "balanced"),
        "space": space,
        "placement": data.get("placement") or None,
        "coupling_preference": data.get("coupling_preference", "any"),
        "notstrom": _bool("notstrom"),
        "future_ev": _bool("future_ev"),
        "future_heat_pump": _bool("future_heat_pump"),
        "future_pv": _bool("future_pv"),
        "future_v2h": _bool("future_v2h"),
    }

    if inputs["future_ev"] and not inputs["has_ev"]:
        inputs["has_ev"] = True
        inputs["ev_charger_kw"] = inputs["ev_charger_kw"] or 11
        inputs["extra_peak_kw"] += 7.4
    if inputs["future_heat_pump"] and not inputs["has_heat_pump"]:
        inputs["has_heat_pump"] = True
        inputs["heat_pump_kw"] = inputs["heat_pump_kw"] or 3.5
    if inputs["future_pv"] and inputs["pv_kwh_year"] > 0:
        inputs["pv_kwh_year"] *= 1.3

    return inputs


def _configs_to_dicts(configs):
    return [
        {
            "product": c.product,
            "brand": c.brand,
            "capacity_kwh": c.capacity_kwh,
            "usable_kwh": c.usable_kwh,
            "inverter_kw": c.inverter_kw,
            "efficiency": c.efficiency,
            "price_eur": c.price_eur,
            "annual_revenue": c.annual_revenue,
            "payback_years": c.payback_years,
            "revenue_breakdown": c.revenue_breakdown,
            "coupling": c.coupling,
            "dims_cm": c.dims_cm,
            "weight_kg": c.weight_kg,
            "notstrom": c.notstrom,
            "three_phase": c.three_phase,
            "warranty_years": c.warranty_years,
            "cycle_life": c.cycle_life,
            "expandable": c.expandable,
            "ems": c.ems,
            "ems_features": c.ems_features,
            "integration_protocols": c.integration_protocols,
            "integration_platforms": c.integration_platforms,
            "integration_score": c.integration_score,
            "modularity_score": c.modularity_score,
            "score": c.score,
            "within_recommendation": c.within_recommendation,
            "details": c.details,
        }
        for c in configs
    ]


@app.route("/")
def index():
    return render_template("intake.html")


@app.route("/calculate", methods=["POST"])
def calculate():
    inputs = _parse_inputs(request.form)
    configs = get_top_configs(inputs, n=10)
    config_dicts = _configs_to_dicts(configs)
    _log_calculation(inputs, config_dicts[0] if config_dicts else None, "form")

    return render_template(
        "results.html",
        configs=config_dicts,
        inputs=inputs,
        goal_label=GOAL_LABELS.get(inputs["goal"], inputs["goal"]),
    )


@app.route("/api/calculate", methods=["POST"])
def api_calculate():
    data = request.get_json(force=True)
    inputs = _parse_inputs(data)
    configs = get_top_configs(inputs, n=10)
    config_dicts = _configs_to_dicts(configs)
    _log_calculation(inputs, config_dicts[0] if config_dicts else None, "api")
    return jsonify({
        "configs": config_dicts,
        "goal_label": GOAL_LABELS.get(inputs["goal"], inputs["goal"]),
        "inputs": {
            "pv_kwh_year": inputs["pv_kwh_year"],
            "budget": inputs["budget"],
            "goal": inputs["goal"],
        },
    })


@app.route("/api/calculations", methods=["GET"])
def get_calculations():
    """Return recent calculation log entries."""
    limit = request.args.get("limit", 50, type=int)
    try:
        lines = CALC_LOG_FILE.read_text().strip().split("\n")
        entries = [json.loads(line) for line in lines[-limit:]]
        return jsonify({"calculations": entries})
    except (FileNotFoundError, json.JSONDecodeError):
        return jsonify({"calculations": []})


@app.route("/api/feedback", methods=["GET"])
def get_feedback():
    since_id = request.args.get("since_id", 0, type=int)
    msgs = _read_feedback()
    new_msgs = [m for m in msgs if m["id"] > since_id]
    return jsonify({"messages": new_msgs})


@app.route("/api/feedback", methods=["POST"])
def post_feedback():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    author = (data.get("author") or "Gebruiker").strip()
    page = (data.get("page") or "").strip()
    if not text:
        return jsonify({"error": "Lege feedback"}), 400
    with _fb_lock:
        msgs = _read_feedback()
        msg = {
            "id": (msgs[-1]["id"] if msgs else 0) + 1,
            "author": author,
            "text": text,
            "page": page,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        msgs.append(msg)
        _write_feedback(msgs)
    return jsonify(msg), 201


@app.route("/api/feedback/reply", methods=["POST"])
def reply_feedback():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Lege reply"}), 400
    with _fb_lock:
        msgs = _read_feedback()
        msg = {
            "id": (msgs[-1]["id"] if msgs else 0) + 1,
            "author": "Ontwikkelaar",
            "text": text,
            "page": "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        msgs.append(msg)
        _write_feedback(msgs)
    return jsonify(msg), 201


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, port=5050)  # nosec B201
