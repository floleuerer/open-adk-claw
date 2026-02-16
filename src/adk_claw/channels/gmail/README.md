# Gmail Integration

ADK-Claw supports Gmail as a bidirectional channel — it can receive emails, process them through the agent, and reply. It also provides email and calendar tools so the agent can proactively send emails, search the inbox, and manage Google Calendar events.

## Prerequisites

- A Google account
- A Google Cloud project with the **Gmail API** and **Google Calendar API** enabled
- OAuth 2.0 credentials (Desktop application type)

## Setup

### 1. Create a Google Cloud Project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select an existing one)
3. Navigate to **APIs & Services > Library**
4. Search for and enable:
   - **Gmail API**
   - **Google Calendar API**

### 2. Configure the OAuth Consent Screen

1. Go to **APIs & Services > OAuth consent screen**
2. Select **External** user type (or Internal if using Google Workspace)
3. Fill in the required fields (app name, user support email)
4. Add the following scopes:
   - `https://www.googleapis.com/auth/gmail.modify`
   - `https://www.googleapis.com/auth/calendar`
5. Under **Test users**, add your Google email address
6. Save

> **Note**: While the app is in "Testing" status, only listed test users can authorize. This is fine for personal use. Publishing the app requires Google's review.

### 3. Create OAuth Credentials

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. Select **Desktop app** ("Desktop-App") as the application type — this is required because the code uses `InstalledAppFlow`, which runs a one-time local browser consent flow. Do **not** select "Web application".
4. Name it (e.g. "ADK-Claw")
5. Click **Create**
6. Download the JSON file and save it as `credentials.json` in your project root (or wherever you prefer)

### 4. Configure ADK-Claw

Add these to your `.env` file:

```
GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_POLL_INTERVAL=30.0
GMAIL_LABEL_FILTER=
```

| Variable | Default | Description |
|----------|---------|-------------|
| `GMAIL_CREDENTIALS_FILE` | *(empty — Gmail disabled)* | Path to your OAuth `credentials.json` file. Setting this enables the email/calendar tools and sub-agent. |
| `GMAIL_TOKEN_FILE` | `/secrets/gmail_token.json` | Path where the OAuth refresh token is stored. Kept outside `workspace/` so the agent's file tools can't access it. |
| `GMAIL_CHANNEL_ENABLED` | `true` | Set to `false` to disable inbox polling while keeping the email/calendar tools available. Useful if you only want the agent to send emails and manage calendar on demand (e.g. via Telegram), without processing incoming mail. |
| `GMAIL_POLL_INTERVAL` | `30.0` | Seconds between checks for new unread emails |
| `GMAIL_LABEL_FILTER` | *(empty)* | Optional Gmail label to filter incoming emails (e.g. `AI-Agent`). Only emails with this label are processed. |

### 5. Authorize and Obtain the Token

The OAuth flow requires a browser, so you'll generate the token **locally** before deploying to Docker:

```bash
# Run locally (not in Docker) to trigger the OAuth flow
mkdir -p secrets
GMAIL_TOKEN_FILE=./secrets/gmail_token.json uv run python -c "
from adk_claw.channels.gmail.auth import get_gmail_service
from pathlib import Path
get_gmail_service('./secrets/credentials.json', Path('./secrets/gmail_token.json'))
print('Token saved to ./secrets/gmail_token.json')
"
```

This opens your browser for Google OAuth consent. After granting permissions, the refresh token is saved to `./secrets/gmail_token.json`.

The `secrets/` directory is mounted into the Docker container at `/secrets` (configured in `docker-compose.yml`), so the containerized app can read and refresh the token automatically.

> **Important**: The token file is stored outside `workspace/` intentionally — the agent's file read/write tools operate inside `workspace/`, so the token is not accessible to the LLM.

### 6. Start in Docker

```bash
docker compose up --build
```

The app reads the token from `/secrets/gmail_token.json` inside the container. Token refreshes are written back to the same file, persisted to the host via the volume mount.

If the token becomes invalid (e.g. revoked or expired beyond refresh), delete `secrets/gmail_token.json` and re-run step 5.

## How It Works

### Email Channel (Incoming)

The Gmail channel polls for new unread emails at the configured interval:

1. On startup, it records all existing unread message IDs (so it doesn't process old emails)
2. Every `GMAIL_POLL_INTERVAL` seconds, it checks for new unread emails
3. New emails are parsed (sender, subject, body) and pushed to the message queue
4. The `chat_id` is set to the sender's email address — each sender gets their own agent session
5. Processed emails are marked as read

Replies are threaded using Gmail's `threadId`, so the conversation stays in a single email thread.

### Label Filtering

If `GMAIL_LABEL_FILTER` is set (e.g. `AI-Agent`), only emails with that label are processed. This lets you control which emails reach the agent:

1. In Gmail, create a label (e.g. "AI-Agent")
2. Set up a Gmail filter to auto-label specific emails, or manually label them
3. Set `GMAIL_LABEL_FILTER=AI-Agent` in `.env`

### Email & Calendar Tools (Sub-Agent)

When Gmail is configured, an `email_calendar_manager` sub-agent is registered with these tools:

| Tool | Description |
|------|-------------|
| `send_email(to, subject, body)` | Compose and send an email |
| `search_emails(query, max_results)` | Search inbox using Gmail search syntax |
| `get_email(email_id)` | Read full email content by ID |
| `list_events(days_ahead)` | List upcoming calendar events |
| `create_event(summary, start, end, ...)` | Create a calendar event |
| `update_event(event_id, ...)` | Update an existing event |
| `delete_event(event_id)` | Delete a calendar event |

DateTime values use ISO 8601 format (e.g. `2026-02-14T10:00:00+01:00`).

The sub-agent approach keeps these tools grouped — the main agent transfers to `email_calendar_manager` when it needs email or calendar functionality.

### Multi-Channel Routing

Replies are routed automatically based on the `chat_id` format:
- Contains `@` → sent via Gmail
- Numeric → sent via Telegram

This means you can ask the agent via Telegram to send an email, and it will use the Gmail tools to do so.

## Example Interactions

**Via Telegram:**
```
You: Send an email to alice@example.com about the meeting tomorrow at 3pm
Bot: [transfers to email_calendar_manager]
     I've sent an email to alice@example.com with the subject "Meeting Tomorrow"
     and details about the 3pm meeting.
```

**Via Telegram (calendar):**
```
You: What's on my calendar this week?
Bot: [transfers to email_calendar_manager]
     Here are your upcoming events: ...

You: Create a meeting with bob@example.com tomorrow at 2pm for 1 hour
Bot: Created "Meeting" on 2026-02-15 from 14:00 to 15:00 with bob@example.com
```

**Via Email (incoming):**
```
From: alice@example.com
Subject: Quick question

Hey, what time is our meeting tomorrow?

→ Agent receives this, searches calendar, replies in the same email thread
```

## Troubleshooting

**"Gmail service not configured":**
- Ensure `GMAIL_CREDENTIALS_FILE` points to a valid `credentials.json` file
- Check that the file exists and is readable

**OAuth flow fails:**
- Verify the Gmail API and Calendar API are enabled in your Google Cloud project
- Check that your email is listed as a test user on the OAuth consent screen
- Ensure the OAuth client ID is of type "Desktop app"

**Not receiving emails:**
- Check that `GMAIL_POLL_INTERVAL` is reasonable (default 30s)
- If using `GMAIL_LABEL_FILTER`, verify emails have the correct label
- Check agent logs for polling errors: `docker compose logs agent`

**Token expired / auth errors:**
- Delete `secrets/gmail_token.json` on the host and re-run the local authorization step (step 5)
- If your Google Cloud project's OAuth consent screen is in "Testing" mode, tokens expire after 7 days — you'll need to re-authorize periodically, or publish the app

**Emails not threading:**
- Replies use Gmail's `threadId` for threading. If the original email was processed, replies will be threaded correctly
- The first reply to a new sender may start a new thread
