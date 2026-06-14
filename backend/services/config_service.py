from pathlib import Path

import yaml


def get_secrets_path() -> Path:
    return Path(__file__).parent.parent / ".secrets.yaml"


def load_api_key(key: str) -> str | None:
    try:
        with open(get_secrets_path()) as file:
            secrets = yaml.safe_load(file)
            return secrets.get(key)
    except Exception as e:
        print(f"Error loading API key: {e}")
        return None


def load_turn_credentials() -> tuple[str | None, str | None]:
    try:
        with open(get_secrets_path()) as file:
            secrets = yaml.safe_load(file)
            return (
                secrets.get("OPENRELAY_TURN_USERNAME"),
                secrets.get("OPENRELAY_TURN_CREDENTIAL"),
            )
    except Exception as e:
        print(f"Error loading TURN credentials: {e}")
        return None, None
