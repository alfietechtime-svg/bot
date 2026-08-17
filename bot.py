import os
import secrets
import string
import sqlite3
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands

# ========== CONFIG ==========
DB_PATH = os.getenv("DB_PATH", "xyntrix.db")
WEB_URL = os.getenv("WEB_URL", "http://localhost:10000").rstrip("/")
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", "0") or 0)
WHITELIST_ROLE_ID = int(os.getenv("WHITELIST_ROLE_ID", "0") or 0)
HWID_COOLDOWN_HOURS = 24

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
            uses INTEGER NOT NULL DEFAULT 0,
            last_hwid_reset TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS riddles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            prize INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            winner_id TEXT,
            winner_name TEXT,
            won_at TEXT
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
        
        self.add_item(discord.ui.Button(
            label="🔑 Redeem Key",
            style=discord.ButtonStyle.primary,
            custom_id="redeem_key"
        ))
        
        self.add_item(discord.ui.Button(
            label="📜 Get Script",
            style=discord.ButtonStyle.primary,
            custom_id="get_script"
        ))
        
        self.add_item(discord.ui.Button(
            label="👤 Get Role",
            style=discord.ButtonStyle.secondary,
            custom_id="get_role"
        ))
        
        self.add_item(discord.ui.Button(
            label="⚙️ Reset HWID",
            style=discord.ButtonStyle.danger,
            custom_id="reset_hwid"
        ))
        
        self.add_item(discord.ui.Button(
            label="📊 Stats",
            style=discord.ButtonStyle.secondary,
            custom_id="show_stats"
        ))

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
        
        if row["discord_id"] != str(interaction.user.id) and row["discord_id"] != "UNASSIGNED":
            return await interaction.response.send_message("❌ This key doesn't belong to you.", ephemeral=True)
        
        # If key is unassigned, assign it to this user
        if row["discord_id"] == "UNASSIGNED":
            conn = db()
            conn.execute(
                "UPDATE licenses SET discord_id=?, username=? WHERE key=?",
                (str(interaction.user.id), str(interaction.user), key)
            )
            conn.commit()
            conn.close()
        
        # Always grant role if configured (no extra check)
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

# ========== BOT ==========
class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(PanelView())
        await self.tree.sync()

bot = Bot()

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
    
    if custom_id == "redeem_key":
        await interaction.response.send_modal(RedeemModal())
        return
    
    if custom_id == "get_script":
        conn = db()
        row = conn.execute(
            "SELECT key FROM licenses WHERE discord_id=? AND active=1 LIMIT 1",
            (str(interaction.user.id),)
        ).fetchone()
        conn.close()
        
        if not row:
            return await interaction.response.send_message("❌ You need an active license first!", ephemeral=True)
        
        loadstring = f'script_key = "{row["key"]}"\nloadstring(game:HttpGet("https://xyntrix-auth.onrender.com/api/script?key=" .. script_key))()'
        
        embed = discord.Embed(
            title="📜 Your Script Loadstring",
            description=f"```lua\n{loadstring}\n```",
            color=discord.Color.gold()
        )
        embed.set_footer(text="Copy this into your executor")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
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
    
    if custom_id == "reset_hwid":
        conn = db()
        row = conn.execute(
            "SELECT key, hwid, last_hwid_reset FROM licenses WHERE discord_id=? AND active=1 LIMIT 1",
            (str(interaction.user.id),)
        ).fetchone()
        conn.close()
        
        if not row:
            return await interaction.response.send_message("❌ You don't have an active license.", ephemeral=True)
        
        if row["last_hwid_reset"]:
            last_reset = datetime.fromisoformat(row["last_hwid_reset"])
            time_since = datetime.now(timezone.utc) - last_reset
            if time_since < timedelta(hours=HWID_COOLDOWN_HOURS):
                remaining = timedelta(hours=HWID_COOLDOWN_HOURS) - time_since
                hours = int(remaining.total_seconds() // 3600)
                minutes = int((remaining.total_seconds() % 3600) // 60)
                return await interaction.response.send_message(
                    f"⏳ HWID reset on cooldown! Next reset available in **{hours}h {minutes}m**.",
                    ephemeral=True
                )
        
        conn = db()
        conn.execute(
            "UPDATE licenses SET hwid=NULL, last_hwid_reset=? WHERE key=?",
            (datetime.now(timezone.utc).isoformat(), row["key"])
        )
        conn.commit()
        conn.close()
        
        await interaction.response.send_message("✅ HWID has been reset! You can now use your key on a new device.", ephemeral=True)
        return
    
    if custom_id == "show_stats":
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
        await interaction.response.send_message(f"✅ Whitelisted {user.mention}. Key sent via DM.", ephemeral=True)
    except:
        await interaction.response.send_message(
            f"✅ Whitelisted {user.mention} but DMs are closed.\n**Key:** `{key}`\n(Only you can see this)",
            ephemeral=True
        )

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

@bot.tree.command(name="generate", description="Generate random keys for giveaways")
@app_commands.describe(amount="Number of keys to generate (1-10)")
async def generate(interaction: discord.Interaction, amount: int = 1):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    if amount < 1 or amount > 10:
        return await interaction.response.send_message("❌ Please generate between 1-10 keys.", ephemeral=True)
    
    keys = []
    conn = db()
    
    for _ in range(amount):
        key = make_key()
        conn.execute(
            "INSERT INTO licenses(key, discord_id, username, created_at) VALUES (?, ?, ?, ?)",
            (key, "UNASSIGNED", "UNASSIGNED", datetime.now(timezone.utc).isoformat())
        )
        keys.append(key)
    
    conn.commit()
    conn.close()
    
    key_list = "\n".join([f"`{k}`" for k in keys])
    embed = discord.Embed(
        title=f"🔑 Generated {amount} Key(s)",
        description=f"{key_list}\n\nUsers can redeem these by clicking the **'Redeem Key'** button!",
        color=discord.Color.green()
    )
    embed.set_footer(text="These keys are not assigned to anyone yet.")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="panelsetup", description="Post the control panel")
async def panelsetup(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    embed = discord.Embed(
        title="🔐 License Panel",
        description="🔑 Click **'Redeem Key'** to enter your license key.\n\nUse the other buttons to get your script, manage HWID, or view stats.",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Your License System")
    await interaction.channel.send(embed=embed, view=PanelView())
    await interaction.response.send_message("✅ Panel sent!", ephemeral=True)

@bot.tree.command(name="keys", description="Show all users and their active keys")
async def keys(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    conn = db()
    rows = conn.execute(
        "SELECT discord_id, username, key, active, created_at FROM licenses WHERE discord_id != 'UNASSIGNED' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    
    if not rows:
        return await interaction.response.send_message("No keys assigned to users yet.", ephemeral=True)
    
    chunks = []
    current_chunk = []
    for row in rows:
        status = "✅" if row["active"] == 1 else "❌"
        line = f"{status} **{row['username']}** → `{row['key']}`"
        current_chunk.append(line)
        if len(current_chunk) >= 10:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    
    embed = discord.Embed(
        title="🔑 All Users & Keys",
        description=chunks[0],
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Total: {len(rows)} keys assigned")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    for chunk in chunks[1:]:
        await interaction.followup.send(f"```\n{chunk}\n```", ephemeral=True)

# ========== RIDDLE COMMANDS ==========

@bot.tree.command(name="riddle", description="Post a riddle for users to solve")
@app_commands.describe(question="The riddle question", answer="The correct answer", prize="Number of keys or 'lifetime'")
async def riddle(interaction: discord.Interaction, question: str, answer: str, prize: str = "1"):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    if prize.lower() == "lifetime":
        prize_value = 999
        prize_display = "🔑 LIFETIME (999 keys)"
    else:
        try:
            prize_value = int(prize)
            if prize_value < 1 or prize_value > 10:
                return await interaction.response.send_message("❌ Prize must be between 1-10 keys or 'lifetime'.", ephemeral=True)
            prize_display = f"{prize_value} key(s)"
        except ValueError:
            return await interaction.response.send_message("❌ Prize must be a number or 'lifetime'.", ephemeral=True)
    
    conn = db()
    cursor = conn.execute(
        "INSERT INTO riddles (question, answer, prize, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
        (question, answer.lower().strip(), prize_value, str(interaction.user), datetime.now(timezone.utc).isoformat())
    )
    riddle_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    embed = discord.Embed(
        title="🧩 Riddle Time!",
        description=f"**{question}**\n\n💡 Prize: **{prize_display}**\n\nReply with `/guess` to answer!",
        color=discord.Color.purple()
    )
    embed.set_footer(text=f"Riddle #{riddle_id} | Posted by {interaction.user.name}")
    
    await interaction.channel.send(embed=embed)
    await interaction.response.send_message("✅ Riddle posted!", ephemeral=True)

@bot.tree.command(name="guess", description="Guess the answer to the current riddle")
@app_commands.describe(answer="Your guess")
async def guess(interaction: discord.Interaction, answer: str):
    conn = db()
    riddle = conn.execute(
        "SELECT * FROM riddles WHERE active=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    
    if not riddle:
        conn.close()
        return await interaction.response.send_message("❌ No active riddle to guess!", ephemeral=True)
    
    if riddle["winner_id"] == str(interaction.user.id):
        conn.close()
        return await interaction.response.send_message("❌ You already solved this riddle!", ephemeral=True)
    
    if riddle["winner_id"]:
        conn.close()
        return await interaction.response.send_message(f"❌ This riddle has already been solved by {riddle['winner_name']}!", ephemeral=True)
    
    if answer.lower().strip() == riddle["answer"]:
        prize = riddle["prize"]
        keys = []
        for _ in range(prize):
            key = make_key()
            conn.execute(
                "INSERT INTO licenses(key, discord_id, username, created_at) VALUES (?, ?, ?, ?)",
                (key, str(interaction.user.id), str(interaction.user), datetime.now(timezone.utc).isoformat())
            )
            keys.append(key)
        
        conn.execute(
            "UPDATE riddles SET active=0, winner_id=?, winner_name=?, won_at=? WHERE id=?",
            (str(interaction.user.id), str(interaction.user), datetime.now(timezone.utc).isoformat(), riddle["id"])
        )
        conn.commit()
        conn.close()
        
        # Send keys via DM
        key_list = "\n".join([f"`{k}`" for k in keys])
        try:
            embed = discord.Embed(
                title="🎉 You Solved the Riddle!",
                description=f"You won **{prize}** key(s)!\n\n{key_list}\n\nRedeem them using the **'Redeem Key'** button in the panel!",
                color=discord.Color.green()
            )
            await interaction.user.send(embed=embed)
            await interaction.response.send_message(
                f"🎉 Correct! {interaction.user.mention} won **{prize}** key(s)! Check your DMs!",
                ephemeral=False
            )
        except:
            # If DMs closed, send in channel (but this is rare)
            await interaction.response.send_message(
                f"🎉 Correct! {interaction.user.mention} won **{prize}** key(s)!\n{key_list}\n\n(Please open your DMs for future prizes)",
                ephemeral=False
            )
    else:
        conn.close()
        await interaction.response.send_message("❌ Wrong answer! Try again.", ephemeral=True)

@bot.tree.command(name="riddles", description="Show all riddles and their status")
async def riddles(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    
    conn = db()
    riddles_list = conn.execute(
        "SELECT * FROM riddles ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()
    
    if not riddles_list:
        return await interaction.response.send_message("No riddles found.", ephemeral=True)
    
    embed = discord.Embed(title="📋 Recent Riddles", color=discord.Color.blue())
    for r in riddles_list:
        status = "✅ Solved" if r["winner_id"] else "⏳ Active"
        winner = r["winner_name"] if r["winner_name"] else "No winner yet"
        embed.add_field(
            name=f"#{r['id']} - {status}",
            value=f"Q: {r['question'][:50]}...\nPrize: {r['prize']} keys\nWinner: {winner}",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ========== MAIN ==========
def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_TOKEN is missing.")
    init_db()
    bot.run(token)

if __name__ == "__main__":
    main()