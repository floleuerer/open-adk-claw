# Actions

Actions are plain Python functions registered as tools with the ADK agent.

## Adding a new action

1. Create a new file in this directory (e.g., `email_tools.py`)
2. Define functions with type hints and docstrings:

```python
def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email to the specified recipient.

    Args:
        to: Email address of the recipient.
        subject: Email subject line.
        body: Email body text.
    """
    # your implementation
    return {"status": "sent", "to": to}
```

3. Register in `agent.py` by adding to the `tools` list in `create_agent()`

ADK auto-wraps plain functions as `FunctionTool`. No base class needed.
