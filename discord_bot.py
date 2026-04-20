"""
🎮 8-BIT TANKS — Discord Moderation Bot v1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Повна ієрархія покарань: warn → mute → kick → tempban → permban
✅ Авто-escalation за кількістю warn (1→mute1h, 3→mute24h, 5→tempban3d, 6→ban)
✅ Temp-ban з авто-unban (кожні 60с)
✅ Anti-spam: 5 повідомлень/5с → mute 5хв
✅ Forbidden words авто-warn + видалення
✅ Report система з кнопками та модалами
✅ Quick punish модали для модераторів
✅ Повний лог у #mod-log
✅ JSON БД: warns/reports/tempbans
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, asyncio
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import re

# ─── НАЛАШТУВАННЯ ──────────────────────────────────────────────────────────────
MODLOG_NAME = "mod-log"
WARN_FILE = "warns.json"
REPORT_FILE = "reports.json"
TEMPBAN_FILE = "tempbans.json"

# ESCALATION: {warn_count: (action, duration_seconds)}
ESCALATION = {
    1: ("mute", 3600),      # 1h
    3: ("mute", 86400),     # 24h  
    4: ("kick", 0),
    5: ("tempban", 259200), # 3d
    6: ("ban", 0)           # permanent
}

SPAM_LIMIT = 5
SPAM_WINDOW = 5  # seconds
BANNED_WORDS = ["cheat", "hack", "aimbot", "wallhack", "exploit", "cheater"]

# ─── БАЗА ДАНИХ ───────────────────────────────────────────────────────────────
def load_file(filename):
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            return json.load(f)
    return {}

def save_file(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_warns(uid: str) -> list:
    return load_file(WARN_FILE).get(str(uid), [])

def add_warn(uid: str, reason: str, mod_id: int) -> int:
    db = load_file(WARN_FILE)
    uid = str(uid)
    if uid not in db:
        db[uid] = []
    db[uid].append({
        "reason": reason,
        "mod_id": mod_id,
        "time": datetime.now().isoformat()
    })
    save_file(WARN_FILE, db)
    return len(db[uid])

def clear_warns(uid: str):
    db = load_file(WARN_FILE)
    db.pop(str(uid), None)
    save_file(WARN_FILE, db)

def add_report(target_id: int, reporter_id: int, reason: str, proof: str = "") -> str:
    db = load_file(REPORT_FILE)
    rid = f"R{len(db):04d}"
    db[rid] = {
        "target_id": str(target_id),
        "reporter_id": str(reporter_id),
        "reason": reason,
        "proof": proof,
        "status": "open",
        "time": datetime.now().isoformat()
    }
    save_file(REPORT_FILE, db)
    return rid

def close_report(rid: str):
    db = load_file(REPORT_FILE)
    if rid in db:
        db[rid]["status"] = "closed"
        save_file(REPORT_FILE, db)

def add_tempban(guild_id: int, uid: str, unban_at: float, reason: str):
    db = load_file(TEMPBAN_FILE)
    key = f"{guild_id}:{uid}"
    db[key] = {
        "uid": uid,
        "guild_id": guild_id,
        "unban_at": unban_at,
        "reason": reason
    }
    save_file(TEMPBAN_FILE, db)

def remove_tempban(guild_id: int, uid: str):
    db = load_file(TEMPBAN_FILE)
    key = f"{guild_id}:{uid}"
    db.pop(key, None)
    save_file(TEMPBAN_FILE, db)

def get_active_tempbans():
    return list(load_file(TEMPBAN_FILE).values())

# ─── УТИЛІТИ ──────────────────────────────────────────────────────────────────
def fmt_duration(seconds: int) -> str:
    if seconds == 0:
        return "permanent"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    return " ".join(parts) or "1m"

def parse_duration(text: str) -> int:
    multipliers = {'s':1, 'm':60, 'h':3600, 'd':86400, 'w':604800}
    total = 0
    buf = ''
    text = text.strip().lower()
    for ch in text + 's':  # default seconds
        if ch.isdigit():
            buf += ch
        elif ch in multipliers and buf:
            total += int(buf) * multipliers[ch]
            buf = ''
    return total if total > 0 else -1

# ─── АВТО-ESCLATION ───────────────────────────────────────────────────────────
async def apply_escalation(member: discord.Member, warn_count: int, reason: str, guild: discord.Guild):
    action, duration = ESCALATION.get(min(warn_count, max(ESCALATION.keys())), ("ban", 0))
    
    msgs = {
        "warn": f"⚠️ Warning #{warn_count} on **{guild.name}**\n**Reason:** {reason}",
        "mute": f"🔇 **Muted** on **{guild.name}** for `{fmt_duration(duration)}`\n**Reason:** {reason} (warn #{warn_count})",
        "kick": f"👢 **Kicked** from **{guild.name}**\n**Reason:** {reason} (warn #{warn_count})",
        "tempban": f"⏳ **Temp-banned** from **{guild.name}** for `{fmt_duration(duration)}`\n**Reason:** {reason} (warn #{warn_count})",
        "ban": f"🔨 **Permanently banned** from **{guild.name}**\n**Reason:** {reason} (warn #{warn_count})"
    }
    
    try:
        await member.send(msgs.get(action, msgs["warn"]))
    except Exception:
        pass
    
    if action == "mute" and duration > 0:
        until = discord.utils.utcnow() + timedelta(seconds=duration)
        try:
            await member.timeout(until=until, reason=f"Auto-escalation (warn #{warn_count})")
        except Exception:
            pass
    elif action == "kick":
        try:
            await member.kick(reason=f"Auto-escalation (warn #{warn_count})")
        except Exception:
            pass
    elif action == "tempban":
        unban_at = datetime.now(timezone.utc).timestamp() + duration
        add_tempban(guild.id, str(member.id), unban_at, reason)
        try:
            await guild.ban(member, reason=f"Temp-ban `{fmt_duration(duration)}` (warn #{warn_count})", delete_message_days=0)
        except Exception:
            pass
    elif action == "ban":
        try:
            await guild.ban(member, reason=f"Permanent ban (warn #{warn_count})", delete_message_days=1)
        except Exception:
            pass

# ─── REPORT VIEW ──────────────────────────────────────────────────────────────
class ModActionView(discord.ui.View):
    def __init__(self, target_id: int, report_id: str):
        super().__init__(timeout=None)
        self.target_id = target_id
        self.report_id = report_id

    def is_mod(self, i: discord.Interaction) -> bool:
        return any(r.permissions.moderate_members or r.permissions.administrator 
                  for r in i.user.roles)

    @discord.ui.button(label="⚠️ Warn", style=discord.ButtonStyle.secondary, row=0)
    async def btn_warn(self, i: discord.Interaction, _):
        if not self.is_mod(i):
            return await i.response.send_message("❌ No permission!", ephemeral=True)
        await i.response.send_modal(QuickPunishModal("warn", self.target_id, self.report_id))

    @discord.ui.button(label="🔇 Mute 1h", style=discord.ButtonStyle.primary, row=0)
    async def btn_mute1(self, i: discord.Interaction, _):
        if not self.is_mod(i):
            return await i.response.send_message("❌ No permission!", ephemeral=True)
        await self.do_mute(i, 3600)

    @discord.ui.button(label="🔇 Mute 24h", style=discord.ButtonStyle.primary, row=0)
    async def btn_mute24(self, i: discord.Interaction, _):
        if not self.is_mod(i):
            return await i.response.send_message("❌ No permission!", ephemeral=True)
        await self.do_mute(i, 86400)

    @discord.ui.button(label="⏳ Temp-ban", style=discord.ButtonStyle.danger, row=1)
    async def btn_tempban(self, i: discord.Interaction, _):
        if not self.is_mod(i):
            return await i.response.send_message("❌ No permission!", ephemeral=True)
        await i.response.send_modal(QuickPunishModal("tempban", self.target_id, self.report_id))

    @discord.ui.button(label="🔨 Perm-ban", style=discord.ButtonStyle.danger, row=1)
    async def btn_ban(self, i: discord.Interaction, _):
        if not self.is_mod(i):
            return await i.response.send_message("❌ No permission!", ephemeral=True)
        await i.response.send_modal(QuickPunishModal("ban", self.target_id, self.report_id))

    @discord.ui.button(label="✅ Dismiss", style=discord.ButtonStyle.secondary, row=1)
    async def btn_dismiss(self, i: discord.Interaction, _):
        if not self.is_mod(i):
            return await i.response.send_message("❌ No permission!", ephemeral=True)
        close_report(self.report_id)
        await i.response.send_message(f"✅ Report `{self.report_id}` dismissed by {i.user.mention}")
        self.disable()
        await i.message.edit(view=self)

    def disable(self):
        for item in self.children:
            item.disabled = True

    async def do_mute(self, i: discord.Interaction, secs: int):
        member = i.guild.get_member(self.target_id)
        if not member:
            return await i.response.send_message("❌ Member not found!", ephemeral=True)
        until = discord.utils.utcnow() + timedelta(seconds=secs)
        await member.timeout(until=until, reason=f"Muted by {i.user.display_name}")
        try:
            await member.send(f"🔇 **Muted** on **{i.guild.name}** for `{fmt_duration(secs)}`.")
        except:
            pass
        await i.response.send_message(f"{member.display_name} muted `{fmt_duration(secs)}`.")
        close_report(self.report_id)
        self.disable()
        await i.message.edit(view=self)

class QuickPunishModal(discord.ui.Modal):
    reason_inp = discord.ui.TextInput(
        label="Reason", 
        max_length=200, 
        placeholder="Describe the violation..."
    )
    duration_inp = discord.ui.TextInput(
        label="Duration (tempban only): 1d, 12h, 30m", 
        placeholder="3d", 
        required=False, 
        max_length=10
    )

    def __init__(self, action: str, target_id: int, report_id: str):
        titles = {"warn": "⚠️ Warn Player", "tempban": "⏳ Temp-ban Player", "ban": "🔨 Ban Player"}
        super().__init__(title=titles.get(action, "Punish"))
        self.action = action
        self.target_id = target_id
        self.report_id = report_id

    async def on_submit(self, i: discord.Interaction):
        reason = self.reason_inp.value
        member = i.guild.get_member(self.target_id)
        if not member:
            return await i.response.send_message("❌ Member not found (may have left).", ephemeral=True)

        if self.action == "warn":
            count = add_warn(str(self.target_id), reason, i.user.id)
            await apply_escalation(member, count, reason, i.guild)
            await i.response.send_message(f"{member.display_name} warned ({count} total).")
        
        elif self.action == "tempban":
            raw = (self.duration_inp.value.strip() or "3d")
            secs = parse_duration(raw)
            if secs == -1:
                secs = 259200  # 3d default
            unban_at = datetime.now(timezone.utc).timestamp() + secs
            add_tempban(i.guild.id, str(member.id), unban_at, reason)
            try:
                await member.send(f"⏳ **Temp-banned** from **{i.guild.name}** for `{fmt_duration(secs)}`.\n**Reason:** {reason}\n**Auto-unban:** <t:{int(unban_at)}:F>")
            except:
                pass
            await i.guild.ban(member, reason=f"Temp-ban `{fmt_duration(secs)}`: {reason}", delete_message_days=0)
            await i.response.send_message(f"{member.display_name} temp-banned for `{fmt_duration(secs)}`.\n**Auto-unban:** <t:{int(unban_at)}:F>")
        
        elif self.action == "ban":
            try:
                await member.send(f"🔨 **Permanently banned** from **{i.guild.name}**.\n**Reason:** {reason}")
            except:
                pass
            await i.guild.ban(member, reason=reason, delete_message_days=1)
            await i.response.send_message(f"{member.display_name} permanently banned.")

        close_report(self.report_id)
        # Disable view buttons
        for item in self.view.children:
            item.disabled = True  # type: ignore
        await i.message.edit(view=self.view)  # type: ignore

# ─── КОМАНДИ ──────────────────────────────────────────────────────────────────
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# REPORT GROUP
report_grp = app_commands.Group(name="report", description="Report a player")

@report_grp.command(name="player", description="Report a player")
@app_commands.describe(player="Player to report", reason="Reason for report")
async def report_player(i: discord.Interaction, player: discord.Member, reason: str):
    if player.bot:
        return await i.response.send_message("❌ Can't report bots!", ephemeral=True)
    
    ml = discord.utils.get(i.guild.text_channels, name=MODLOG_NAME)
    if not ml:
        return await i.response.send_message("❌ Mod-log channel not found!", ephemeral=True)
    
    rid = add_report(player.id, i.user.id, reason)
    warns = get_warns(str(player.id))
    
    embed = discord.Embed(title=f"📋 Report `{rid}`", color=0xFF4444, timestamp=datetime.now(timezone.utc))
    embed.set_thumbnail(url=player.display_avatar.url)
    embed.add_field(name="Reported", value=player.mention, inline=True)
    embed.add_field(name="Reporter", value=i.user.mention, inline=True)
    embed.add_field(name="Warns", value=f"{len(warns)}/{max(ESCALATION.keys())}", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text="Use buttons below to take action")
    
    await ml.send(content="🔔 **New report!** 🔔", embed=embed, view=ModActionView(player.id, rid))
    await i.response.send_message(f"✅ Report `{rid}` submitted. Moderators notified! 🔔", ephemeral=True)

tree.add_command(report_grp)

# MOD COMMANDS
@tree.command(name="warn", description="⚠️ MOD: Warn a player")
@app_commands.describe(player="Player", reason="Reason")
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_warn(i: discord.Interaction, player: discord.Member, reason: str):
    count = add_warn(str(player.id), reason, i.user.id)
    action = ESCALATION.get(min(count, max(ESCALATION.keys())), ("ban", 0))[0]
    action_labels = {"warn": "Warned", "mute": "Muted", "kick": "Kicked", "tempban": "Temp-banned", "ban": "Banned"}
    
    embed = discord.Embed(title="🔨 Moderation Action", color=0xFF6B35, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Player", value=player.mention, inline=True)
    embed.add_field(name="Warns", value=f"{count}/{max(ESCALATION.keys())}", inline=True)
    embed.add_field(name="Action", value=action_labels.get(action, "Warned"), inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Mod", value=i.user.mention, inline=True)
    
    await i.response.send_message(embed=embed)
    
    ml = discord.utils.get(i.guild.text_channels, name=MODLOG_NAME)
    if ml:
        await ml.send(embed=embed)
    
    await apply_escalation(player, count, reason, i.guild)

@tree.command(name="mute", description="🔇 MOD: Mute a player")
@app_commands.describe(player="Player", duration="Duration (1h, 30m, 2d)", reason="Reason")
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_mute(i: discord.Interaction, player: discord.Member, duration: str = "1h", reason: str = "No reason"):
    secs = parse_duration(duration)
    if secs == -1:
        return await i.response.send_message("❌ Invalid duration. Use: `30m`, `2h`, `1d`", ephemeral=True)
    
    until = discord.utils.utcnow() + timedelta(seconds=secs)
    await player.timeout(until=until, reason=reason)
    try:
        await player.send(f"🔇 **Muted** on **{i.guild.name}** for `{fmt_duration(secs)}`.\n**Reason:** {reason}")
    except:
        pass
    
    await i.response.send_message(f"{player.display_name} muted for `{fmt_duration(secs)}`.\n**Unmutes:** <t:{int(until.timestamp())}:R>")

@tree.command(name="unmute", description="🔊 MOD: Remove mute")
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_unmute(i: discord.Interaction, player: discord.Member):
    await player.timeout(None)
    await i.response.send_message(f"{player.display_name} unmuted.")

@tree.command(name="kick", description="👢 MOD: Kick a player")
@app_commands.describe(player="Player", reason="Reason")
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_kick(i: discord.Interaction, player: discord.Member, reason: str = "No reason"):
    try:
        await player.send(f"👢 **Kicked** from **{i.guild.name}**.\n**Reason:** {reason}")
    except:
        pass
    await player.kick(reason=reason)
    await i.response.send_message(f"{player.display_name} kicked.")

@tree.command(name="tempban", description="⏳ MOD: Temp-ban with auto-unban timer")
@app_commands.describe(player="Player", duration="Duration", reason="Reason")
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_tempban(i: discord.Interaction, player: discord.Member, duration: str, reason: str = "No reason"):
    secs = parse_duration(duration)
    if secs == -1:
        return await i.response.send_message("❌ Invalid duration. Use: `1d`, `12h`, `30m`", ephemeral=True)
    
    unban_at = datetime.now(timezone.utc).timestamp() + secs
    add_tempban(i.guild.id, str(player.id), unban_at, reason)
    
    try:
        await player.send(f"⏳ **Temp-banned** from **{i.guild.name}** for `{fmt_duration(secs)}`.\n**Reason:** {reason}\n**Auto-unban:** <t:{int(unban_at)}:F>")
    except:
        pass
    
    await i.guild.ban(player, reason=f"Temp-ban `{fmt_duration(secs)}`: {reason}", delete_message_days=0)
    
    embed = discord.Embed(title="⏳ Temp-ban Applied", color=0xFF6B35, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="Player", value=player.mention, inline=True)
    embed.add_field(name="Duration", value=fmt_duration(secs), inline=True)
    embed.add_field(name="Unban at", value=f"<t:{int(unban_at)}:F>", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Mod", value=i.user.mention, inline=True)
    
    await i.response.send_message(embed=embed)
    
    ml = discord.utils.get(i.guild.text_channels, name=MODLOG_NAME)
    if ml:
        await ml.send(embed=embed)

@tree.command(name="ban", description="🔨 MOD: Permanently ban a player")
@app_commands.describe(player="Player", reason="Reason")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_ban(i: discord.Interaction, player: discord.Member, reason: str = "No reason"):
    try:
        await player.send(f"🔨 **Permanently banned** from **{i.guild.name}**.\n**Reason:** {reason}")
    except:
        pass
    await i.guild.ban(player, reason=reason, delete_message_days=1)
    await i.response.send_message(f"{player.display_name} permanently banned.")

@tree.command(name="unban", description="🔓 MOD: Unban a user by ID")
@app_commands.describe(userid="User ID (number)")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_unban(i: discord.Interaction, userid: str):
    try:
        user = await bot.fetch_user(int(userid))
        await i.guild.unban(user, reason=f"Unbanned by {i.user.display_name}")
        remove_tempban(i.guild.id, userid)
        await i.response.send_message(f"{user.name} unbanned.")
    except Exception as e:
        await i.response.send_message(f"❌ Error: {e}", ephemeral=True)

@tree.command(name="warns", description="📋 MOD: View player warns")
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_warns(i: discord.Interaction, player: discord.Member):
    warns = get_warns(str(player.id))
    embed = discord.Embed(title=f"📋 Warns: {player.display_name}", color=0xFF6B35 if warns else 0x57F287)
    
    if not warns:
        embed.description = "✅ No warnings on record."
    else:
        for idx, w in enumerate(warns, 1):
            next_action = ESCALATION.get(idx, ("ban", 0))[0].upper()
            embed.add_field(
                name=f"#{idx} {w['time'][:10]}",
                value=f"**Reason:** {w['reason']}\n**Mod:** <@{w['mod_id']}>",
                inline=False
            )
        embed.set_footer(text=f"Next escalation: {ESCALATION.get(len(warns), ('ban', 0))[0].upper()}")
    
    await i.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="clearwarns", description="🗑️ MOD: Clear all warns")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_clearwarns(i: discord.Interaction, player: discord.Member):
    clear_warns(str(player.id))
    await i.response.send_message(f"🗑️ All warns cleared for {player.display_name}.")

@tree.command(name="tempbans", description="⏳ MOD: List active temp-bans")
@app_commands.checks.has_permissions(moderate_members=True)
async def cmd_tempbans(i: discord.Interaction):
    bans = [b for b in get_active_tempbans() if b["guild_id"] == i.guild.id]
    embed = discord.Embed(title="⏳ Active Temp-bans", color=0xFF6B35)
    
    if not bans:
        embed.description = "✅ No active temp-bans."
    else:
        for b in bans:
            ts = int(b["unban_at"])
            embed.add_field(
                name=f"<@{b['uid']}>",
                value=f"**Unban:** <t:{ts}:F> (<t:{ts}:R>)\n**Reason:** {b['reason']}",
                inline=False
            )
    
    await i.response.send_message(embed=embed, ephemeral=True)

# ─── AUTO-MOD ─────────────────────────────────────────────────────────────────
spam_tracker = defaultdict(list)

@bot.listen()
async def automod(message: discord.Message):
    if message.author.bot:
        return
    if any(r.permissions.moderate_members for r in message.author.roles):
        return
    
    uid = message.author.id
    now = datetime.now(timezone.utc).timestamp()
    
    # Anti-spam
    spam_tracker[uid] = [t for t in spam_tracker[uid] if now - t < SPAM_WINDOW]
    spam_tracker[uid].append(now)
    if len(spam_tracker[uid]) >= SPAM_LIMIT:
        spam_tracker[uid].clear()
        try:
            await message.author.timeout(discord.utils.utcnow() + timedelta(minutes=5), reason="Auto-mod: spam")
        except:
            pass
        await message.channel.send(f"{message.author.mention} auto-muted 5 min for spam.", delete_after=8)
        return
    
    # Forbidden words
    if any(w in message.content.lower() for w in BANNED_WORDS):
        try:
            await message.delete()
        except:
            pass
        count = add_warn(str(uid), "Auto-mod: forbidden word", 0)
        await apply_escalation(message.author, count, "Forbidden word", message.guild)
        await message.channel.send(f"{message.author.mention} message removed. Forbidden content. ⚠️({count}/{max(ESCALATION.keys())})", delete_after=8)

# ─── AUTO-UNBAN TASK ──────────────────────────────────────────────────────────
@tasks.loop(seconds=60)
async def unban_loop():
    now = datetime.now(timezone.utc).timestamp()
    bans = get_active_tempbans()
    
    for entry in bans:
        if entry["unban_at"] <= now:
            gid = entry["guild_id"]
            uid = int(entry["uid"])
            guild = bot.get_guild(gid)
            if guild:
                try:
                    user = await bot.fetch_user(uid)
                    await guild.unban(user, reason="Temp-ban expired")
                    remove_tempban(gid, str(uid))
                    
                    # Log
                    ml = discord.utils.get(guild.text_channels, name=MODLOG_NAME)
                    if ml:
                        embed = discord.Embed(title="⏳ Temp-ban Expired", 
                                            description=f"<@{uid}> has been automatically unbanned.", 
                                            color=0x57F287, timestamp=datetime.now(timezone.utc))
                        await ml.send(embed=embed)
                    
                    try:
                        await user.send(f"✅ Your temp-ban on **{guild.name}** has expired. You can rejoin!")
                    except:
                        pass
                    
                    print(f"Auto-unbanned {uid} from {guild.name}")
                except Exception as e:
                    print(f"Unban error {uid}: {e}")

@bot.event
async def on_ready():
    await tree.sync()
    unban_loop.start()
    print(f"✅ 8-BIT TANKS Moderation Bot online: {bot.user}")

# ─── ЗАПУСК ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
