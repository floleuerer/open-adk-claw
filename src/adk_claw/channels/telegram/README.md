# Telegram Integration

ADK-Claw uses Telegram as its communication channel. This guide covers how to set up and use the Telegram bot.

## Creating a Bot

1. Open Telegram and start a conversation with [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Choose a display name (e.g. "Claw")
4. Choose a username (must end in `bot`, e.g. `my_claw_bot`)
5. BotFather will reply with your **bot token** — a string like `123456789:ABCdefGhIjKlMnOpQrStUvWxYz`
6. Copy the token into your `.env` file:

```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIjKlMnOpQrStUvWxYz
```

## Finding Your Chat ID

The `ADMIN_CHAT_ID` setting is needed for heartbeat messages (scheduled autonomous tasks). To find your chat ID:

1. Start a conversation with your bot (send any message)
2. Open this URL in your browser, replacing `<TOKEN>` with your bot token:
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Look for `"chat":{"id":123456789}` in the response — that number is your chat ID
4. Add it to `.env`:
   ```
   ADMIN_CHAT_ID=123456789
   ```

Alternatively, send a message to the bot after it's running and check the logs — the chat ID is logged with each incoming message.

## Using the Bot

### Starting a Conversation

Open your bot in Telegram and send any text message. The bot processes plain text messages only — commands (messages starting with `/`) are ignored.

### How Messages Are Processed

When you send a message:

1. The bot receives it via long-polling
2. Your message is placed in a **debounce queue** (default 2 seconds)
3. If you send more messages within that window, they're batched together
4. The combined batch is sent to the Gemini agent
5. The agent processes your message, optionally calling tools (memory search, web browsing, code execution)
6. The response is sent back to your Telegram chat

This means there's a small delay (the debounce period) before the bot starts responding. You can adjust this with `DEBOUNCE_SECONDS` in `.env`.

### Multi-Message Batching

If you send several messages quickly:

```
You: Hey
You: Can you look up the weather in Berlin
You: And also check my notes about the trip
```

These are combined into a single prompt for the agent rather than triggering three separate LLM calls. Each message is prefixed with your Telegram display name.

### Response Splitting

Telegram has a 4096-character limit per message. If the agent's response exceeds this, it's automatically split into multiple messages.

### Group Chats

The bot works in group chats too. It listens to all text messages (not commands) in the group. Messages from different users are attributed by name when batched. Each group chat gets its own session and memory context, identified by the chat ID.

To add the bot to a group:
1. Open the group settings
2. Add the bot by its username
3. The bot will respond to all text messages in the group

> **Note**: If the bot should only respond when mentioned, you'd need to modify the message handler in `src/adk_claw/channels/telegram.py`. By default it processes all non-command text messages.

## What the Bot Can Do

The agent behind the bot has access to these capabilities:

- **Remember things** — It searches and saves to persistent memory. Ask it to remember something and it will be there next session.
- **Browse the web** — Give it a URL and it can fetch the page content or take a screenshot.
- **Run Python code** — It can execute Python in a sandboxed environment for calculations, data processing, etc.
- **Scheduled tasks** — If `ADMIN_CHAT_ID` is set, the bot sends heartbeat messages based on schedules defined in `workspace/HEARTBEAT.md`.

### Example Conversations

**Memory:**
```
You: Remember that my server IP is 10.0.1.42
Bot: Saved to memory. I'll remember your server IP is 10.0.1.42.

You: What's my server IP?
Bot: Your server IP is 10.0.1.42.
```

**Code execution:**
```
You: Calculate the compound interest on $10,000 at 5% over 10 years
Bot: [runs Python code]
     After 10 years at 5% annual compound interest:
     Final amount: $16,288.95
     Interest earned: $6,288.95
```

**Web browsing:**
```
You: What's on the front page of news.ycombinator.com?
Bot: [fetches the page]
     Here are the top stories on Hacker News: ...
```

## Configuration Reference

| Variable | Default | Effect on Telegram behavior |
|----------|---------|----------------------------|
| `TELEGRAM_BOT_TOKEN` | *(required)* | Authenticates the bot with Telegram's API |
| `ADMIN_CHAT_ID` | *(empty)* | Chat where heartbeat/scheduled messages are sent |
| `DEBOUNCE_SECONDS` | `2.0` | How long to wait for additional messages before processing |
| `SESSION_IDLE_TIMEOUT` | `1800` | Seconds of inactivity before session is rotated (curated, flushed, reset) |

## Troubleshooting

**Bot doesn't respond:**
- Check that `TELEGRAM_BOT_TOKEN` is correct in `.env`
- Verify the agent container is running: `docker compose logs agent`
- Make sure you're sending plain text, not commands (`/start`, etc.)

**"Sorry, I encountered an error":**
- Check agent logs: `docker compose logs agent`
- Verify `GOOGLE_API_KEY` is valid and has Gemini access
- Ensure the browser and sandbox services are healthy: `docker compose ps`

**Slow responses:**
- The debounce timer adds a `DEBOUNCE_SECONDS` delay before processing starts
- Complex queries involving tool calls (browsing, code) take longer
- Consider using a faster model by changing `MODEL_NAME`

**Bot not receiving messages in groups:**
- Talk to [@BotFather](https://t.me/BotFather) and send `/setprivacy`
- Select your bot and set privacy to **Disabled** so it can see all group messages
