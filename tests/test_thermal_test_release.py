"""End-to-end checks for the isolated Home Assistant test distribution."""

import asyncio
import json
from contextlib import nullcontext
from time import perf_counter
from unittest.mock import patch

import numpy as np
import pytest
import time_machine

from emhass import api_auth, web_server
from emhass.optimization import Optimization

from .api_auth_support import BEARER, TOKEN
from .test_dry_run import _changed, _data_copy, _files, _from_file, _web, _write_params

HORIZON = 48
PATH = "/api/v1/dry-run/naive-mpc-optim"


@pytest.mark.parametrize("mode", ["disabled", "enabled", "relaxed"])
def test_authenticated_15_minute_battery_and_heat_mpc(mode, monkeypatch):
    source = {
        "id": "heat_pump",
        "type": "heatpump",
        "nominal_power": 1200,
        "min_power": 440,
        "treat_as_semi_cont": False,
        "supply_temperature": 30,
        "carnot_efficiency": 0.444,
    }
    if mode != "disabled":
        source["minimum_on_timesteps"] = 4

    body = {
        "prediction_horizon": HORIZON,
        "set_use_battery": True,
        "number_of_batteries": 2,
        "inverter_is_hybrid": False,
        "battery_nominal_energy_capacity": [6400, 10000],
        "battery_charge_power_max": [2000, 3000],
        "battery_discharge_power_max": [2000, 3000],
        "battery_charge_efficiency": [0.92, 0.96],
        "battery_discharge_efficiency": [0.94, 0.91],
        "soc_init": [0.38, 0.65],
        "soc_final": [0.45, 0.55],
        "set_battery_fleet_exclusive_direction": mode != "disabled",
        "heat_topology": {
            "sources": [source],
            "storage": [
                {
                    "id": "house",
                    "thermal_mass": 26.07,
                    "loss_coefficient": 0.1543,
                    "start_temperature": 20.2,
                    "min_temperatures": [19.3],
                    "max_temperatures": [21.0],
                }
            ],
            "flows": [{"from": "heat_pump", "to": "house"}],
        },
        "def_current_state": [True],
        "def_current_on_timesteps": [2],
        "outdoor_temperature_forecast": [6.0 + 0.5 * (i // 6) for i in range(HORIZON)],
        "pv_power_forecast": [max(0, 2200 - 140 * abs(i - 24)) for i in range(HORIZON)],
        "load_power_forecast": [700 + 130 * (i % 7) for i in range(HORIZON)],
        "load_cost_forecast": [0.37] * 12 + [-0.04] * 12 + [0.18] * 12 + [0.42] * 12,
        "prod_price_forecast": [0.05] * HORIZON,
    }

    def configure(params):
        params["retrieve_hass_conf"]["optimization_time_step"] = 15
        params["optim_conf"]["lp_solver_mip_rel_gap"] = 0.001

    monkeypatch.delenv(api_auth.DISABLE_ENV, raising=False)
    monkeypatch.delenv(api_auth.ENV_NAME, raising=False)
    with _data_copy() as data_path:
        _write_params(data_path, configure)
        options = data_path / "options.json"
        options.write_text(json.dumps({"emhass_api_token": TOKEN}), encoding="utf-8")

        async def run(client):
            missing = await client.post(PATH, json=body)
            assert missing.status_code == 401
            wrong = await client.post(PATH, headers={"Authorization": "Bearer wrong"}, json=body)
            assert wrong.status_code == 401
            before = _files(data_path)
            start = perf_counter()
            response = await client.post(PATH, headers=BEARER, json=body)
            assert response.status_code == 200, await response.get_data(as_text=True)
            result = await response.get_json(), perf_counter() - start
            assert _changed(before, _files(data_path)) == []
            return result

        retry = (
            patch.object(Optimization, "_needs_relaxed_retry", return_value=True)
            if mode == "relaxed"
            else nullcontext()
        )
        api_auth.reset()
        try:
            asyncio.run(
                api_auth.configure(None, options, web_server.app.logger, data_dir=data_path)
            )
            with (
                _web(data_path) as client,
                _from_file(),
                time_machine.travel("2026-11-17 06:00:00+00:00", tick=False),
                retry,
            ):
                answer, duration = asyncio.run(run(client))
        finally:
            api_auth.reset()

    assert answer["dry_run"] and answer["status"] == "ok", answer["errors"]
    plan = answer["plan"]
    assert len(plan) == HORIZON
    status = "Optimal (Relaxed)" if mode == "relaxed" else "Optimal"
    assert {row["optim_status"] for row in plan} == {status}
    power = np.array([[row["P_batt_0"], row["P_batt_1"]] for row in plan])
    opposite = (power > 0.01).any(axis=1) & (power < -0.01).any(axis=1)
    assert (power > 0.01).any() and (power < -0.01).any()
    if mode != "disabled":
        assert not opposite.any()

    heat = np.array([row["P_deferrable0"] for row in plan])
    if mode == "enabled":
        on = heat > 0.01
        assert on[:2].all()  # two completed steps plus two scheduled steps
        assert (heat[on] >= 439.99).all()
        for start in np.flatnonzero(on[1:] & ~on[:-1]) + 1:
            assert start + 4 <= HORIZON and on[start : start + 4].all()
    elif mode == "relaxed":
        assert any("does not guarantee heat topology minimum ON" in w for w in answer["warnings"])

    print(
        f"{mode}: API {duration:.3f} s, energy cost {sum(r['cost_profit'] for r in plan):.6f}, "
        f"opposite-direction intervals {opposite.sum()}, heat on intervals {(heat > 0.01).sum()}"
    )
