# EMHASS Thermal Test — minimum ON time
This is an **isolated test app**, based on official EMHASS v0.18.9 plus
the `feature/heat-topology-minimum-on-time` implementation.

- Docker image: `ghcr.io/erikt80/emhass:v0.18.9-thermal1`.
- Separate Supervisor app slug: `emhass-thermal-test`.
- Dedicated app config mounted at `/config`, independent `/data` volume.
- Host API port: **5001**; the production EMHASS port **5000** is untouched.
- Startup is manual. The shared `/share` volume is intentionally not mounted.
- No live EMS REST commands, dispatchers, or HA scripts are modified.

## Install
1. Check that the [Docker publish workflow](https://github.com/ErikT80/emhass/actions/workflows/publish_emhass_thermal_test.yml)
   succeeded and `ghcr.io/erikt80/emhass:v0.18.9-thermal1` is **publicly readable**.
   GitHub Container Registry packages may need their visibility changed to Public
   under the package settings before Home Assistant can pull them.
2. Home Assistant → Settings → Apps → Install app → three-dot menu → Repositories.
3. Add repository `https://github.com/ErikT80/emhass#release/thermal-min-on-v0.18.9`.
   The `#branch` suffix is supported by Home Assistant Supervisor.
4. Install **EMHASS Thermal Test**. Do not delete the original EMHASS app.
5. Start the test app and inspect logs. Use the separate web interface on host
   port 5001 or its distinct sidebar ingress.
6. Configure the test instance independently. Its app config is `/config/config.json`
   and data path is `/data`; do not point either at your production EMHASS files.

## Validation
Run **dry-run** optimization requests against port 5001, without `publish-data`
and without redirecting the existing Home Assistant `rest_command` endpoints.

Validate `minimum_on_timesteps: 4` against a 15-minute heat-topology test
including OFF→ON, an active run crossing an MPC replan boundary, and a near-horizon
start. A valid duration requires the physical current-state and elapsed-ON
runtime parameters; do not assume the solver knows that from forecasts.

A successful image build is not proof the minimum-runtime feature works
end-to-end. Keep production EMHASS and all actuators unchanged during tests.
