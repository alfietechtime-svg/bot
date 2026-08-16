import os
import secrets
import string
import sqlite3
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

# ========== CONFIG ==========
DB_PATH = os.getenv("DB_PATH", "xyntrix.db")
WEB_URL = os.getenv("WEB_URL", "http://localhost:10000").rstrip("/")
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0") or 0)
WHITELIST_ROLE_ID = int(os.getenv("WHITELIST_ROLE_ID", "0") or 0)

# ========== DATABASE ==========
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

def is_admin(interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    return ADMIN_ROLE_ID != 0 and any(r.id == ADMIN_ROLE_ID for r in interaction.user.roles)

# ========== DISCORD PANEL VIEW ==========
class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
        # Redeem Key - OPENS POPUP IN DISCORD
        self.add_item(discord.ui.Button(
            label="🔑 Redeem Key",
            style=discord.ButtonStyle.primary,
            custom_id="redeem_key"
        ))
        
        # Get Script - GOES TO WEBSITE
        self.add_item(discord.ui.Button(
            label="📜 Get Script",
            style=discord.ButtonStyle.link,
            url=f"{WEB_URL}/script"
        ))
        
        # Get Role - AUTO GRANTS ROLE
        self.add_item(discord.ui.Button(
            label="👤 Get Role",
            style=discord.ButtonStyle.secondary,
            custom_id="get_role"
        ))
        
        # Reset HWID - GOES TO WEBSITE
        self.add_item(discord.ui.Button(
            label="⚙️ Reset HWID",
            style=discord.ButtonStyle.link,
            url=f"{WEB_URL}/reset"
        ))
        
        # Stats - GOES TO WEBSITE
        self.add_item(discord.ui.Button(
            label="📊 Stats",
            style=discord.ButtonStyle.link,
            url=f"{WEB_URL}/stats"
        ))

# ========== BOT ==========
class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(PanelView())
        await self.tree.sync()

bot = Bot()

# ========== MODAL FOR REDEEM ==========
class RedeemModal(discord.ui.Modal, title="🔑 Redeem Your Key"):
    key_input = discord.ui.TextInput(
        label="Enter your license key",
        placeholder="XYN-XXXXX-XXXXX-XXXXX",
        style=discord.TextStyle.short,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        key = self.key_input.value.strip().upper()
        
        conn = db()
        row = conn.execute("SELECT * FROM licenses WHERE key=?", (key,)).fetchone()
        conn.close()
        
        if not row:
            return await interaction.response.send_message("❌ Invalid key.", ephemeral=True)
        
        if row["active"] == 0:
            return await interaction.response.send_message("❌ This key has been revoked.", ephemeral=True)
        
        if row["discord_id"] != str(interaction.user.id):
            return await interaction.response.send_message("❌ This key doesn't belong to you.", ephemeral=True)
        
        # Grant role if configured
        if WHITELIST_ROLE_ID:
            role = interaction.guild.get_role(WHITELIST_ROLE_ID)
            if role:
                try:
                    await interaction.user.add_roles(role, reason="Redeemed license key")
                    await interaction.response.send_message(f"✅ Key `{key}` redeemed! You now have the whitelist role.", ephemeral=True)
                    return
                except discord.Forbidden:
                    await interaction.response.send_message(f"✅ Key `{key}` is valid, but I couldn't add the role. Contact an admin.", ephemeral=True)
                    return
        
        await interaction.response.send_message(f"✅ Key `{key}` is valid!", ephemeral=True)

# ========== EVENTS ==========
@bot.event
async def on_ready():
    init_db()
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")

@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    
    custom_id = interaction.data.get("custom_id") if interaction.data else None
    
    # Handle Redeem Key button
    if custom_id == "redeem_key":
        await interaction.response.send_modal(RedeemModal())
        return
    
    # Handle Get Role button
    if custom_id == "get_role":
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use this inside the server.", ephemeral=True)
        
        conn = db()
        row = conn.execute(
            "SELECT key FROM licenses WHERE discord_id=? AND active=1 LIMIT 1",
            (str(interaction.user.id),)
        ).fetchone()
        conn.close()
        
        if not row:
            return await interaction.response.send_message("❌ You need an active license first.", ephemeral=True)
        
        if not WHITELIST_ROLE_ID:
            return await interaction.response.send_message("❌ Whitelist role not configured.", ephemeral=True)
        
        role = interaction.guild.get_role(WHITELIST_ROLE_ID)
        if not role:
            return await interaction.response.send_message("❌ Whitelist role not found.", ephemeral=True)
        
        try:
            await interaction.user.add_roles(role, reason="Active license")
            await interaction.response.send_message("✅ Whitelist role granted!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I can't manage that role. Put my role above the whitelist role.", ephemeral=True)
        return

# ========== SLASH COMMANDS ==========
@bot.tree.command(name="whitelist", description="Whitelist a user and DM them a key")
@app_commands.describe(user="The user to whitelist")
async def whitelist(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    key = make_key()
    conn = db()
    conn.execute(
        "INSERT INTO licenses(key, discord_id, username, created_at) VALUES (?, ?, ?, ?)",
        (key, str(user.id), str(user), datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()
    
    try:
        embed = discord.Embed(
            title="🔑 Your License Key",
            description=f"**Key:** `{key}`\n\nRedeem it by clicking the **'Redeem Key'** button in the panel!",
            color=discord.Color.gold()
        )
        await user.send(embed=embed)
        msg = f"✅ Whitelisted {user.mention}. Key sent via DM."
    except:
        msg = f"✅ Whitelisted {user.mention}. Key: `{key}` (DMs closed)"
    
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="unwhitelist", description="Revoke all keys for a user")
@app_commands.describe(user="The user")
async def unwhitelist(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    conn = db()
    cur = conn.execute("UPDATE licenses SET active=0 WHERE discord_id=? AND active=1", (str(user.id),))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Revoked {cur.rowcount} key(s) for {user.mention}.", ephemeral=True)

@bot.tree.command(name="key", description="Show a user's active key")
@app_commands.describe(user="The user")
async def key_command(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    conn = db()
    row = conn.execute(
        "SELECT key FROM licenses WHERE discord_id=? AND active=1 ORDER BY created_at DESC LIMIT 1",
        (str(user.id),)
    ).fetchone()
    conn.close()
    
    await interaction.response.send_message(f"Active key: `{row['key']}`" if row else "No active key found.", ephemeral=True)

@bot.tree.command(name="revoke", description="Revoke a specific key")
@app_commands.describe(key="The key to revoke")
async def revoke(interaction: discord.Interaction, key: str):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    conn = db()
    cur = conn.execute("UPDATE licenses SET active=0 WHERE key=?", (key.strip().upper(),))
    conn.commit()
    conn.close()
    await interaction.response.send_message("✅ Key revoked." if cur.rowcount else "❌ Key not found.", ephemeral=True)

@bot.tree.command(name="panelsetup", description="Post the control panel")
async def panelsetup(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    embed = discord.Embed(
        title="XYNTRIXREDEEMER",
        description="🔑 Click **'Redeem Key'** to enter your license key.\n\nUse the other buttons to get your script, manage HWID, or view stats.",
        color=discord.Color.gold()
    )
    embed.set_footer(text="XYNTRIXSCRIPTS")
    await interaction.channel.send(embed=embed, view=PanelView())
    await interaction.response.send_message("✅ Panel sent!", ephemeral=True)

# ========== MAIN ==========
def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_TOKEN is missing.")
    init_db()
    bot.run(token)

if __name__ == "__main__":
    main()self.add_item(discord.ui.Button(  
    label="?? Get Script",  
    style=discord.ButtonStyle.primary,  
    custom_id="get_script"  
))  
if custom_id == "get_script":  
    conn = db()  
    row = conn.execute(  
        "SELECT key FROM licenses WHERE discord_id=? AND active=1 LIMIT 1",  
        (str(interaction.user.id),)  
    ).fetchone()  
    conn.close()  
    if not row:  
        return await interaction.response.send_message("? You need an active license first!", ephemeral=True)  
    loadstring = f'script_key = "{row["key"]}"\nloadstring(game:HttpGet("https://xyntrix-auth.onrender.com/api/script?key=" .. script_key))()'  
    embed = discord.Embed(  
        title="?? Your Script Loadstring",  
        description=f"```lua\n{loadstring}\n```",  
        color=discord.Color.gold()  
    )  
    embed.set_footer(text="Copy this into your executor")  
    await interaction.response.send_message(embed=embed, ephemeral=True)  
    return  

