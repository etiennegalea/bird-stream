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

## Replace passwords with mutual TLS

The tracked password listener remains the default so an existing deployment is
not cut off before its certificates are installed. The configurator's
**MQTT mutual TLS** page prepares the command and per-device settings.

From the repository root, generate the broker, backend, and Pi identities:

```bash
./scripts/mosquitto-mtls.sh \
  --broker-host mqtt.home.arpa \
  --broker-ip 192.168.1.100 \
  --device backend \
  --device pi-01 \
  --device pi-02
```

Generated private material is written under the ignored `mosquitto/pki/`
directory. Existing keys are never overwritten; rerun the command with an
additional `--device` to enroll another transmitter. The broker certificate
always includes the Docker service name `mosquitto`, allowing the backend to
verify the same broker certificate inside Compose.

Deploy each `clients/<device>/` bundle only to its owner. Keep
`pki/ca/ca.key` offline after enrollment. On a Pi:

```yaml
mqtt:
  port: 8883
  username: null
  password: null
  tls:
    enabled: true
    ca_cert: /etc/birdstream/mqtt/ca.crt
    client_cert: /etc/birdstream/mqtt/client.crt
    client_key: /etc/birdstream/mqtt/client.key
```

In `.env`, use:

```dotenv
MQTT_PORT="8883"
MQTT_USERNAME=""
MQTT_PASSWORD=""
MQTT_TLS_ENABLED="true"
MQTT_TLS_CA_CERT="/run/secrets/mqtt/ca.crt"
MQTT_TLS_CLIENT_CERT="/run/secrets/mqtt/client.crt"
MQTT_TLS_CLIENT_KEY="/run/secrets/mqtt/client.key"
```

Start the mTLS-only broker configuration and backend mounts with:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.mtls.yml \
  up -d
```

The overlay mounts `config/mosquitto-mtls.conf.example` in place of
`config/mosquitto.conf`, exposes the generated broker identity, and gives the
backend only its own client bundle. `config/acl-mtls` uses the certificate CN
as the Mosquitto username. Each Pi can publish only
`camera/<its-CN>/status` and read only `camera/<its-CN>/control`.

After all clients reconnect successfully, verify nothing is listening on 1883
and firewall that port. Do not use TLS `insecure` options to work around a
hostname mismatch; regenerate the server identity with the correct DNS/IP SAN.
