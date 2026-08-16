# XYNTRIXREDEEMER

A small Discord + Render licensing system.

## What it does

- `/whitelist @user` creates a random XYN key and DMs it.
- `/unwhitelist @user` revokes active keys for that user.
- `/key @user` shows their active key to an admin.
- `/revoke KEY` revokes a key.
- `/reset-hwid KEY` clears the HWID field.
- `/panelsetup` posts the XYNTRIXREDEEMER Discord panel.
- `/stats` shows basic license statistics.
- The Flask API validates keys and protects `script.lua`.

## 1. Create the Discord bot

Create an application/bot in the Discord Developer Portal.

Enable the bot and invite it to your server with the permissions it needs, including:
- Send Messages
- Embed Links
- Use Application Commands
- Manage Roles (only if you want the Get Role feature)

The bot's role must be above the whitelist role.

## 2. Configure environment variables

Set these in Render:

- `DISCORD_TOKEN` = your bot token
- `WEB_URL` = your Render web URL, e.g. `https://xyntrixscripts.onrender.com`
- `ADMIN_ROLE_ID` = role allowed to manage licenses
- `WHITELIST_ROLE_ID` = role granted to licensed users

Never publish the bot token.

## 3. Deploy

Push this folder to a GitHub repository.

In Render, create the services from `render.yaml`, or create:
- a Python Web Service running `gunicorn server:app`
- a Python Background Worker running `python bot.py`

Set the environment variables above.

## 4. Put your authorized code in script.lua

Replace the example contents of `script.lua` with the code for software/experience you control.

The protected endpoint is:

`/api/script?key=YOUR_KEY`

Example client request:

```lua
local key = "YOUR_KEY"
local source = game:HttpGet("https://xyntrixscripts.onrender.com/api/script?key=" .. key)
local fn = loadstring(source)
if fn then fn() end
```

Only use that loader with code and a game/application you are authorized to operate.

## 5. Database note

This template uses SQLite on a Render persistent disk. For a larger service, move the license table to PostgreSQL.

## 6. Security improvements for production

For a public commercial system, add:
- rate limiting
- HTTPS-only deployment
- Discord OAuth login
- short-lived download tokens instead of putting keys in URLs
- audit logs
- PostgreSQL
- encrypted/separately managed secrets
- stronger device binding if your software needs it
