#!/usr/bin/env bash
#
# Create a private CA, one Mosquitto server certificate, and any number of
# scoped client identities. Existing keys are never overwritten, so rerunning
# the command with more --device arguments safely grows the fleet.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

broker_host=""
output_dir="$REPO_ROOT/mosquitto/pki"
valid_days=365
declare -a broker_ips=()
declare -a devices=()

usage() {
  sed -n '2,8p' "$0"
  printf '\nUsage:\n'
  printf '  %s --broker-host NAME [--broker-ip IP] --device ID [--device ID ...]\n' "$0"
  printf '\nOptions:\n'
  printf '  --broker-host NAME  DNS name clients use, included in the server SAN\n'
  printf '  --broker-ip IP      Optional server IP SAN; may be repeated\n'
  printf '  --device ID         Client certificate CN; may be repeated\n'
  printf '  --output-dir PATH   PKI directory (default: mosquitto/pki)\n'
  printf '  --days NUMBER       Client validity in days (default: 365)\n'
  printf '  -h, --help          Show this help\n'
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

need_value() {
  [[ $# -ge 2 && -n "$2" ]] || die "$1 requires a value"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --broker-host)
      need_value "$@"
      broker_host="$2"
      shift 2
      ;;
    --broker-ip)
      need_value "$@"
      broker_ips+=("$2")
      shift 2
      ;;
    --device)
      need_value "$@"
      devices+=("$2")
      shift 2
      ;;
    --output-dir)
      need_value "$@"
      output_dir="$2"
      shift 2
      ;;
    --days)
      need_value "$@"
      valid_days="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

command -v openssl >/dev/null 2>&1 || die "openssl is required"
[[ -n "$broker_host" ]] || die "--broker-host is required"
[[ "$broker_host" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] \
  || die "invalid broker DNS name: $broker_host"
[[ "$valid_days" =~ ^[0-9]+$ && "$valid_days" -ge 1 ]] \
  || die "--days must be a positive integer"
[[ ${#devices[@]} -gt 0 ]] || die "provide at least one --device"

for ip in "${broker_ips[@]}"; do
  [[ "$ip" =~ ^[0-9A-Fa-f:.]+$ ]] || die "invalid broker IP address: $ip"
done
for device in "${devices[@]}"; do
  [[ "$device" =~ ^[A-Za-z0-9_-]{1,64}$ ]] \
    || die "invalid device ID '$device' (use 1-64 letters, digits, _ or -)"
done

umask 077
mkdir -p "$output_dir/ca" "$output_dir/broker" "$output_dir/clients"

ca_key="$output_dir/ca/ca.key"
ca_cert="$output_dir/ca/ca.crt"
if [[ -e "$ca_key" || -e "$ca_cert" ]]; then
  [[ -f "$ca_key" && -f "$ca_cert" ]] \
    || die "incomplete CA in $output_dir/ca; restore both ca.key and ca.crt"
  printf 'Reusing CA: %s\n' "$ca_cert"
else
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$ca_key"
  openssl req -x509 -new -sha256 -days 3650 \
    -key "$ca_key" \
    -out "$ca_cert" \
    -subj "/CN=Birdstream MQTT CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign"
  printf 'Created CA: %s\n' "$ca_cert"
fi

server_key="$output_dir/broker/server.key"
server_csr="$output_dir/broker/server.csr"
server_cert="$output_dir/broker/server.crt"
if [[ -e "$server_key" || -e "$server_cert" ]]; then
  [[ -f "$server_key" && -f "$server_cert" ]] \
    || die "incomplete server identity in $output_dir/broker"
  openssl x509 -in "$server_cert" -noout -checkhost "$broker_host" \
    >/dev/null 2>&1 \
    || die "existing server certificate does not contain DNS name $broker_host"
  for ip in "${broker_ips[@]}"; do
    openssl x509 -in "$server_cert" -noout -checkip "$ip" >/dev/null 2>&1 \
      || die "existing server certificate does not contain IP address $ip"
  done
  printf 'Reusing server identity: %s\n' "$server_cert"
else
  server_ext="$(mktemp)"
  trap 'rm -f "$server_ext"' EXIT
  san="DNS:$broker_host,DNS:mosquitto"
  for ip in "${broker_ips[@]}"; do
    san+=",IP:$ip"
  done
  {
    printf 'basicConstraints=critical,CA:FALSE\n'
    printf 'keyUsage=critical,digitalSignature,keyEncipherment\n'
    printf 'extendedKeyUsage=serverAuth\n'
    printf 'subjectAltName=%s\n' "$san"
  } > "$server_ext"

  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$server_key"
  openssl req -new -key "$server_key" -out "$server_csr" \
    -subj "/CN=$broker_host"
  openssl x509 -req -sha256 -days 825 \
    -in "$server_csr" \
    -CA "$ca_cert" \
    -CAkey "$ca_key" \
    -CAcreateserial \
    -out "$server_cert" \
    -extfile "$server_ext"
  rm -f "$server_csr" "$server_ext"
  trap - EXIT
  printf 'Created server identity: %s\n' "$server_cert"
fi

for device in "${devices[@]}"; do
  client_dir="$output_dir/clients/$device"
  client_key="$client_dir/client.key"
  client_csr="$client_dir/client.csr"
  client_cert="$client_dir/client.crt"
  mkdir -p "$client_dir"
  if [[ -e "$client_key" || -e "$client_cert" ]]; then
    [[ -f "$client_key" && -f "$client_cert" ]] \
      || die "incomplete client identity in $client_dir"
    printf 'Reusing client identity: %s\n' "$device"
    continue
  fi

  client_ext="$(mktemp)"
  trap 'rm -f "$client_ext"' EXIT
  {
    printf 'basicConstraints=critical,CA:FALSE\n'
    printf 'keyUsage=critical,digitalSignature\n'
    printf 'extendedKeyUsage=clientAuth\n'
  } > "$client_ext"

  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$client_key"
  openssl req -new -key "$client_key" -out "$client_csr" \
    -subj "/CN=$device"
  openssl x509 -req -sha256 -days "$valid_days" \
    -in "$client_csr" \
    -CA "$ca_cert" \
    -CAkey "$ca_key" \
    -CAserial "$output_dir/ca/ca.srl" \
    -out "$client_cert" \
    -extfile "$client_ext"
  cp "$ca_cert" "$client_dir/ca.crt"
  rm -f "$client_csr" "$client_ext"
  trap - EXIT
  printf 'Created client identity: %s\n' "$device"
done

cp "$ca_cert" "$output_dir/broker/ca.crt"
chmod 600 "$ca_key" "$server_key"
find "$output_dir/clients" -type f -name '*.key' -exec chmod 600 {} +
find "$output_dir" -type f -name '*.crt' -exec chmod 644 {} +

openssl verify -CAfile "$ca_cert" "$server_cert" >/dev/null
for device in "${devices[@]}"; do
  openssl verify -CAfile "$ca_cert" \
    "$output_dir/clients/$device/client.crt" >/dev/null
done

printf '\nPKI ready in %s\n' "$output_dir"
printf 'Broker files: %s/broker/{ca.crt,server.crt,server.key}\n' "$output_dir"
printf 'Client bundles: %s/clients/<device>/{ca.crt,client.crt,client.key}\n' "$output_dir"
printf '\nKeep %s offline and private. Copy each client bundle only to its owner.\n' "$ca_key"
printf 'Next: enable mosquitto/config/mosquitto-mtls.conf.example and port 8883.\n'
