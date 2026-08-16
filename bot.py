import os
import secrets
import string
import sqlite3
import asyncio
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

DB_PATH = os.getenv("DB_PATH", "xyntrix.db")
WEB_URL = os.getenv("WEB_URL", "http://localhost:10000").rstrip("/")
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0") or 0)
WHITELIST_ROLE_ID = int(os.getenv("WHITELIST_ROLE_ID", "0") or 0)

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            key TEXT PRIMARY KEY,
            discord_id TEXT NOT NULL,
            username TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            hwid TEXT,
            created_at TEXT NOT NULL,
            last_used TEXT,
            uses INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def make_key():
    alphabet = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(alphabet) for _ in range(5)) for _ in range(4)]
    return "XYN-" + "-".join(parts)

def is_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    return ADMIN_ROLE_ID != 0 and any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles)

async def dm_key(user: discord.User, key: str):
    embed = discord.Embed(
        title="🔑 XYNTRIXREDEEMER",
        description=(
            "You have been whitelisted.\n\n"
            f"**Your key:** `{key}`\n\n"
            f"Redeem it here: {WEB_URL}"
        ),
        color=discord.Color.gold()
    )
    await user.send(embed=embed)

class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="🔑 Redeem Key", style=discord.ButtonStyle.link,
            url=WEB_URL
        ))
        self.add_item(discord.ui.Button(
            label="📜 Get Script", style=discord.ButtonStyle.link,
            url=f"{WEB_URL}/script"
        ))
        self.add_item(discord.ui.Button(
            label="👤 Get Role", style=discord.ButtonStyle.secondary,
            custom_id="xyntrix_get_role"
        ))
        self.add_item(discord.ui.Button(
            label="⚙️ Reset HWID", style=discord.ButtonStyle.secondary,
            url=f"{WEB_URL}/reset"
        ))
        self.add_item(discord.ui.Button(
            label="📊 Get Stats", style=discord.ButtonStyle.secondary,
            url=f"{WEB_URL}/stats"
        ))

class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(PanelView())
        await self.tree.sync()

bot = Bot()

@bot.event
async def on_ready():
    init_db()
    print(f"Logged in as {bot.user} ({bot.user.id})")

@bot.tree.command(name="whitelist", description="Whitelist a Discord user and DM them a key.")
@app_commands.describe(user="The Discord user to whitelist")
async def whitelist(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("You do not have permission.", ephemeral=True)

    key = make_key()
    conn = db()
    conn.execute(
        "INSERT INTO licenses(key, discord_id, username, created_at) VALUES (?, ?, ?, ?)",
        (key, str(user.id), str(user), datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()

    try:
        await dm_key(user, key)
        msg = f"Whitelisted {user.mention}. Their key was sent by DM."
    except discord.Forbidden:
        msg = f"Whitelisted {user.mention}, but their DMs are closed. Key: `{key}`"

    if WHITELIST_ROLE_ID:
        role = interaction.guild.get_role(WHITELIST_ROLE_ID)
        if role:
            try:
                await user.add_roles(role, reason="XYNTRIX whitelist")
            except discord.Forbidden:
                pass

    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="unwhitelist", description="Revoke all active keys for a Discord user.")
@app_commands.describe(user="The Discord user")
async def unwhitelist(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("You do not have permission.", ephemeral=True)

    conn = db()
    cur = conn.execute(
        "UPDATE licenses SET active=0 WHERE discord_id=? AND active=1",
        (str(user.id),)
    )
    conn.commit()
    conn.close()
    await interaction.response.send_message(
        f"Revoked {cur.rowcount} active license(s) for {user.mention}.", ephemeral=True
    )

@bot.tree.command(name="key", description="Show the current active key for a user.")
@app_commands.describe(user="The Discord user")
async def key_command(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("You do not have permission.", ephemeral=True)

    conn = db()
    row = conn.execute(
        "SELECT key FROM licenses WHERE discord_id=? AND active=1 ORDER BY created_at DESC LIMIT 1",
        (str(user.id),)
    ).fetchone()
    conn.close()

    await interaction.response.send_message(
        f"Active key: `{row['key']}`" if row else "No active key found.",
        ephemeral=True
    )

@bot.tree.command(name="revoke", description="Revoke a license key.")
@app_commands.describe(key="The XYN license key")
async def revoke(interaction: discord.Interaction, key: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("You do not have permission.", ephemeral=True)

    conn = db()
    cur = conn.execute("UPDATE licenses SET active=0 WHERE key=?", (key.strip().upper(),))
    conn.commit()
    conn.close()
    await interaction.response.send_message(
        "Key revoked." if cur.rowcount else "Key not found.", ephemeral=True
    )

@bot.tree.command(name="reset-hwid", description="Clear the HWID attached to a key.")
@app_commands.describe(key="The XYN license key")
async def reset_hwid(interaction: discord.Interaction, key: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("You do not have permission.", ephemeral=True)

    conn = db()
    cur = conn.execute("UPDATE licenses SET hwid=NULL WHERE key=?", (key.strip().upper(),))
    conn.commit()
    conn.close()
    await interaction.response.send_message(
        "HWID reset." if cur.rowcount else "Key not found.", ephemeral=True
    )

@bot.tree.command(name="panelsetup", description="Post the XYNTRIXREDEEMER control panel.")
async def panelsetup(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("You do not have permission.", ephemeral=True)

    embed = discord.Embed(
        title="XYNTRIXREDEEMER",
        description=(
            "This control panel is for the project: **XYNTRIXREDEEMER**\n\n"
            "If you're a buyer, use the buttons below to redeem your key, "
            "get the script, manage your HWID, or view your stats."
        ),
        color=discord.Color.gold()
    )
    embed.set_footer(text="XYNTRIXSCRIPTS")
    await interaction.channel.send(embed=embed, view=PanelView())
    await interaction.response.send_message("Panel sent.", ephemeral=True)

@bot.tree.command(name="stats", description="Show license statistics.")
async def stats(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("You do not have permission.", ephemeral=True)

    conn = db()
    total = conn.execute("SELECT COUNT(*) c FROM licenses").fetchone()["c"]
    active = conn.execute("SELECT COUNT(*) c FROM licenses WHERE active=1").fetchone()["c"]
    uses = conn.execute("SELECT COALESCE(SUM(uses),0) c FROM licenses").fetchone()["c"]
    conn.close()

    embed = discord.Embed(title="📊 XYNTRIX Stats", color=discord.Color.gold())
    embed.add_field(name="Total keys", value=str(total))
    embed.add_field(name="Active keys", value=str(active))
    embed.add_field(name="Script requests", value=str(uses))
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.event
async def on_interaction(interaction: discord.Interaction):
    # The Get Role button is handled here so it survives bot restarts.
    if interaction.type != discord.InteractionType.component:
        return
    if not interaction.data or interaction.data.get("custom_id") != "xyntrix_get_role":
        return

    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return await interaction.response.send_message("Use this inside the server.", ephemeral=True)

    conn = db()
    row = conn.execute(
        "SELECT key FROM licenses WHERE discord_id=? AND active=1 LIMIT 1",
        (str(interaction.user.id),)
    ).fetchone()
    conn.close()

    if not row:
        return await interaction.response.send_message(
            "You need an active XYNTRIX license first.", ephemeral=True
        )

    if not WHITELIST_ROLE_ID:
        return await interaction.response.send_message(
            "The whitelist role is not configured yet.", ephemeral=True
        )

    role = interaction.guild.get_role(WHITELIST_ROLE_ID)
    if not role:
        return await interaction.response.send_message(
            "The configured whitelist role no longer exists.", ephemeral=True
        )

    try:
        await interaction.user.add_roles(role, reason="Valid XYNTRIX license")
        await interaction.response.send_message("✅ Whitelist role granted.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            "I cannot manage that role. Put the bot's role above the whitelist role.",
            ephemeral=True
        )

def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing.")
    init_db()
    bot.run(token)

if __name__ == "__main__":
    main()
