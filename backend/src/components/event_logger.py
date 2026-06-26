import os
import re
import logging
from logging.handlers import TimedRotatingFileHandler

# Path to the log file in the backend root directory
LOG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "camera_events.log"
)

# Setup dedicated logger
logger = logging.getLogger("camera_events_file")
logger.setLevel(logging.INFO)
logger.propagate = False  # Keep separate from general FastAPI app logs

# Prevent adding handlers multiple times (e.g. during FastAPI hot reload)
if not logger.handlers:
    # Rotate every 7 days, keep 4 backup files
    handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="D",
        interval=7,
        backupCount=4,
        encoding="utf-8"
    )
    
    # Custom format: YYYY-MM-DD HH:MM:SS [INFO] - MESSAGE
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def log_event(event_type: str, details: str = ""):
    """Logs a structured camera event to the rotating log file."""
    # Format message as "EVENT_TYPE | Details"
    logger.info(f"{event_type.upper()} | {details}")

def read_events(limit: int = 100):
    """Parses the camera_events.log file and returns a list of events (newest first)."""
    events = []
    if not os.path.exists(LOG_FILE):
        return events

    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Parse lines in reverse order (most recent first)
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue

            # Match standard log format: YYYY-MM-DD HH:MM:SS [INFO] - EVENT_TYPE | Details
            match = re.match(
                r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[INFO\] - ([A-Z_]+) \| (.*)$",
                line
            )
            if match:
                events.append({
                    "timestamp": match.group(1),
                    "event_type": match.group(2),
                    "details": match.group(3)
                })
                if len(events) >= limit:
                    break
    except Exception as e:
        # Fallback console log for backend debugging
        print(f"Error reading or parsing camera_events.log: {e}")

    return events
