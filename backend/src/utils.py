from pathlib import Path
import yaml

def get_secrets_path():
    current_dir = Path(__file__).parent.parent
    secrets_path = current_dir / '.secrets.yaml'

    return secrets_path

def load_api_key(key: str) -> str:
    try:
        with open(get_secrets_path(), 'r') as file:
            secrets = yaml.safe_load(file)
            return secrets.get(key)
    except Exception as e:
        print(f"Error loading API key: {e}")

def load_turn_credentials():
    try:
        with open(get_secrets_path(), 'r') as file:
            secrets = yaml.safe_load(file)
            return secrets.get("OPENRELAY_TURN_USERNAME"), secrets.get("OPENRELAY_TURN_CREDENTIAL")
    except Exception as e:
        print(f"Error loading API key: {e}")