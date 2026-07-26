#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <mqtt-username>" >&2
    echo "The password is requested interactively and is not stored in shell history." >&2
    exit 2
fi

username=$1
case "$username" in
    *[!A-Za-z0-9_-]*|'')
        echo "Username must contain only letters, numbers, underscores, or dashes." >&2
        exit 2
        ;;
esac

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_dir=$(dirname -- "$script_dir")
password_file="$project_dir/mosquitto/config/passwd"

cd "$project_dir"
mkdir -p mosquitto/config mosquitto/data mosquitto/log

if [ -s "$password_file" ]; then
    create_flag=""
else
    create_flag="-c"
fi

echo "Creating/updating MQTT user '$username'..."
docker compose run --rm --no-deps --entrypoint sh mosquitto -c '
    set -eu
    create_flag=$1
    username=$2
    if [ -n "$create_flag" ]; then
        mosquitto_passwd "$create_flag" /mosquitto/config/passwd "$username"
    else
        mosquitto_passwd /mosquitto/config/passwd "$username"
    fi
    chown mosquitto:mosquitto /mosquitto/config/passwd
    chmod 0700 /mosquitto/config/passwd
' sh "$create_flag" "$username"

echo "MQTT user '$username' is configured."
echo "Start/restart the broker with: docker compose up -d mosquitto"
