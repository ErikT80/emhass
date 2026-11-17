# Changelog

## v0.18.10-ems1

- Update the isolated test app to upstream EMHASS 0.18.10.
- Retain the opt-in minimum on-time for heat-topology sources.
- Add optional battery fleet direction exclusivity. The default is `false`.
- Support bearer-token authentication on host port 5001 and use the upstream dedicated Supervisor ingress listener on internal port 8099.
- Start Gunicorn with the dependencies already installed in the image, including on networks without access to PyPI.
