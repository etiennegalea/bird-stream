
from pathlib import Path
import yaml


def load_api_key(key: str) -> str:
    try:
        # Get the directory of the current file
        current_dir = Path(__file__).parent.parent
        # Path to the secrets file
        secrets_path = current_dir / '.secrets.yaml'
        
        with open(secrets_path, 'r') as file:
            secrets = yaml.safe_load(file)
            return secrets.get(key)
    except Exception as e:
        print(f"Error loading API key: {e}")