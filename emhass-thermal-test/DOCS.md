# EMHASS Thermal Test

`v0.18.10-ems1` combines upstream EMHASS 0.18.10 with heat-topology minimum on-time and optional battery fleet direction exclusivity. The existing `emhass-thermal-test` app uses `ghcr.io/erikt80/emhass:v0.18.10-ems1`, maps the API to host port **5001**, and keeps its own `/config` and `/data` mounts. Ingress uses the separate internal port **8099** for EMHASS 0.18.10 authentication.

## Update the installed app

1. Refresh the Home Assistant app store under **Settings → Apps → Install app**. The existing custom repository is `https://github.com/ErikT80/emhass#release/thermal-min-on-v0.18.9`. Keep that repository and the installed **EMHASS Thermal Test** app.
2. Open the installed app and choose **Update** to `v0.18.10-ems1`. Both Linux architectures are built by the [test image workflow](https://github.com/ErikT80/emhass/actions/workflows/publish_emhass_thermal_test.yml). Supervisor pulls from the public GHCR package. The previous tag `v0.18.9-thermal1` remains available for rollback.
3. On the app's **Configuration** tab, set `emhass_api_token` to a separate random token of at least 16 characters. For example, generate one with `openssl rand -hex 32`. Save and restart or start the test app. This token authenticates calls **to EMHASS**. The existing `long_lived_token` option is for calls **to Home Assistant**.
4. If you leave `emhass_api_token` blank, the test app generates a token and keeps it in `/data/emhass_api_token`. A Home Assistant administrator can view it via the **API token** key icon in the test app's ingress panel. See the [API authentication guide](../docs/api_authentication.md).

For calls to port 5001, send `Authorization: Bearer <test-token>`. This request reads the effective configuration.

```bash
curl -fsS -H "Authorization: Bearer $EMHASS_TEST_TOKEN" \
  "http://$HA_HOST:5001/get-config"
```

## Enable the features on the test app

Updating retains the existing `/config/config.json`. Open **Configuration** in the EMHASS web interface for the test app, or edit that JSON file directly. Set these top-level keys and keep the existing battery sizing, efficiency, SoC and power limits.

```json
{
  "set_use_battery": true,
  "number_of_batteries": 2,
  "set_battery_fleet_exclusive_direction": true,
  "optimization_time_step": 15
}
```

If you edit the file directly, restart the test app so it reloads its configuration. You can also pass `"set_battery_fleet_exclusive_direction": true` on a single optimization request. An explicit JSON `false` restores independent directions for that request. Omitting the flag uses the configured value, which defaults to `false`.

For the heat pump, add `"minimum_on_timesteps": 4` to its existing `heat_topology.sources` entry, or include it in the `heat_topology` sent in the request. At 15-minute intervals four steps equal one hour. A continuously modulating heat pump also needs positive `min_power`, such as `440` W for a 1200 W source. The [heat topology guide](../docs/heat_topology.md#minimum-on-duration) shows the full source, storage and flow setup.

On each MPC call, pass the measured `def_current_state` and the number of completed ON steps as `def_current_on_timesteps`, in the same order as the compiled loads. For a single flow that is ON and has completed two steps, use `[true]` and `[2]`. With an existing EV load followed by the heat pump, put the heat pump at index 1, for example `[false, true]` and `[0, 2]` if the EV is idle. Always derive these from measured state for a real replan.

## Verify with a dry run

Send the prepared MPC payload to the test app at `POST /api/v1/dry-run/naive-mpc-optim`. Include `prediction_horizon`, the PV, load and price forecasts, `outdoor_temperature_forecast`, `soc_init` and `soc_final` for both batteries, the topology if it is not set in the test config, and the current heat-pump state and elapsed steps. This route returns the proposed plan without publishing to Home Assistant or replacing the last plan.

```bash
curl -fsS -H "Authorization: Bearer $EMHASS_TEST_TOKEN" \
  -H 'Content-Type: application/json' --data-binary @mpc-test.json \
  "http://$HA_HOST:5001/api/v1/dry-run/naive-mpc-optim" > dry-run-result.json
jq -e '.dry_run and (.status == "ok") and (.plan | length > 0)' dry-run-result.json
jq -e 'all(.plan[]; ((.P_batt_0 > 0.01 and .P_batt_1 < -0.01) or
  (.P_batt_1 > 0.01 and .P_batt_0 < -0.01)) | not)' dry-run-result.json
jq '.plan[] | {timestamp, optim_status, P_deferrable0, P_batt_0, P_batt_1}' dry-run-result.json
```

`P_batt_0` and `P_batt_1` are positive on discharge and negative on charge. Check that every new ON run in `P_deferrable0` stays at or above the minimum power for four steps. For an already-running heat pump with two completed steps, check the first two steps. Use `P_deferrable1` if the EV precedes the heat pump. Battery exclusivity also applies to `Optimal (Relaxed)` results. For thermal verification, require `Optimal` and check the plan and warnings. A relaxed plan can omit the heat pump's minimum duration and minimum power.

To invoke the same test from Home Assistant, add a dedicated test command. Replace `HA_HOST` with the hostname or address of the instance hosting the test app.

```yaml
# Home Assistant configuration.yaml
rest_command:
  emhass_thermal_test_dry_run:
    url: http://HA_HOST:5001/api/v1/dry-run/naive-mpc-optim
    method: POST
    headers:
      authorization: !secret emhass_thermal_test_bearer
    content_type: application/json
    payload: "{{ runtime | to_json }}"
```

```yaml
# Home Assistant secrets.yaml
emhass_thermal_test_bearer: "Bearer REPLACE_WITH_TEST_TOKEN"
```

Call `rest_command.emhass_thermal_test_dry_run` with the MPC payload as its `runtime` data. The test app's persistent setting requires no change to `ErikT80/ems-appdaemon`. To opt in per request, add the YAML key `set_battery_fleet_exclusive_direction: true` immediately after `number_of_batteries: 2` in `response` under step 17 of `.homeassistant/scripts/emhass_runtime_parameters.yaml` in a test copy, or add the key to a copy of the returned mapping before the test REST command. The EMS thermal configuration already supplies `minimum_on_timesteps: 4` and step 17h supplies the measured current state and elapsed intervals.

If using AppDaemon's optional native shadow HTTP client against port 5001, pass the test token from a secret into `NativeDryRunClient` and add `Authorization: Bearer <test-token>` to the request headers in `assets/thermal/thermal_shadow_client.py`. Do the same for `WeatherCacheRefreshClient` if you explicitly use the test app's weather-cache refresh. Keep production REST commands and dispatch settings on their existing endpoints.
