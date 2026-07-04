# Mosquitto (MQTT broker)

Runs on the Proxmox box via docker-compose. Anonymous access is disabled;
create users before the Pis can connect:

```bash
# one user per device + one for the backend
docker exec mosquitto mosquitto_passwd -b /mosquitto/config/passwd pi-01 <password>
docker exec mosquitto mosquitto_passwd -b /mosquitto/config/passwd backend <password>
docker restart mosquitto
```

Put the same credentials in each Pi's `pi-agent/config.yaml` (`mqtt.username`/
`mqtt.password`) and in the backend env (`MQTT_USERNAME`/`MQTT_PASSWORD`).

Before exposing port 1883 beyond the LAN, enable the TLS listener in
`config/mosquitto.conf` (certs go in `certs/`) and switch the Pis to port 8883
with `mqtt.tls.enabled: true`.
