#!/usr/bin/env bash
set -euo pipefail

image=${1:?Specify the test image}
temp=$(mktemp -d)
container=
cleanup() {
    if [[ -n "$container" ]]; then
        docker rm -f "$container" >/dev/null
    fi
    rm -rf "$temp"
}
trap cleanup EXIT

token=$(openssl rand -hex 32)
printf '{"emhass_api_token":"%s","data_path":"/data","config_path":"/config/config.json"}\n' "$token" > "$temp/options.json"
mkdir "$temp/config"
existing_config='{"optimization_time_step":15}'
printf '%s\n' "$existing_config" > "$temp/config/config.json"
container=$(docker run --detach --network none \
    --env SUPERVISOR_TOKEN=isolated-test-supervisor \
    --mount "type=bind,source=$temp/options.json,target=/data/options.json,readonly" \
    --mount "type=bind,source=$temp/config,target=/config" \
    "$image")

if ! docker exec -i "$container" python - <<'PY'
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

with open("/data/options.json") as stream:
    token = json.load(stream)["emhass_api_token"]


def request(port, token=None, path="/get-config/defaults"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urlopen(req, timeout=2) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, None


for _ in range(60):
    try:
        response = request(5000)
        break
    except (URLError, TimeoutError):
        time.sleep(1)
else:
    raise SystemExit("EMHASS API listener did not start")

assert response[0] == 401, response[0]
assert request(5000, "wrong-token")[0] == 401
status, defaults = request(5000, token)
assert status == 200, status
assert defaults["set_battery_fleet_exclusive_direction"] is False
status, config = request(5000, token, "/get-config")
assert status == 200, status
assert config["optimization_time_step"] == 15
assert request(8099, token)[0] == 403  # a non-Supervisor TCP peer
print("Verified bearer authentication, fleet default, existing config and ingress peer enforcement")
PY
then
    docker logs "$container"
    exit 1
fi
test "$(cat "$temp/config/config.json")" = "$existing_config"
