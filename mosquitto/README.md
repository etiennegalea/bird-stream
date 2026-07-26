# Mosquitto (MQTT broker)

Runs on the Proxmox box via docker-compose. Anonymous access is disabled and
the broker will not start until `config/passwd` exists. Create the backend user
and one unique user per Pi before starting the stack:

```bash
./scripts/mosquitto-user.sh backend
./scripts/mosquitto-user.sh pi-01
docker compose up -d mosquitto
```

The helper runs a one-off container, prompts for the password, creates or
updates the ignored password database, assigns it to the `mosquitto` user, and
sets mode `0700`. This works even while the broker is stopped and avoids
putting passwords in shell history.

Put the backend credentials in `.env` (`MQTT_USERNAME`/`MQTT_PASSWORD`). Put
each device's credentials in its `pi-agent/config.yaml` (`mqtt.username` and
`mqtt.password`).

Before exposing port 1883 beyond the LAN, enable the TLS listener in
`config/mosquitto.conf` (certs go in `certs/`) and switch the Pis to port 8883
with `mqtt.tls.enabled: true`.
