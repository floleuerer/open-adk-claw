from datetime import datetime, timezone


def get_current_datetime() -> dict:
    """Get the current date and time in UTC."""
    now = datetime.now(timezone.utc)
    return {
        "datetime": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
        "timezone": "UTC",
    }
