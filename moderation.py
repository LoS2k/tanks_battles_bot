"""
🎮 8-BIT TANKS — moderation.py  (фінальна версія)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
РЕПОРТИ:   /report @гравець причина
ПОКАРАННЯ: warn→mute 1h→mute 24h→kick→tempban→permban (ескалація)
ТИМЧАСОВІ БАНИ: /tempban @user <час> причина  (авто-розбан по таймеру)
АВТО-МОД:  антиспам + фільтр слів
КОНТЕНТ:   setup_content() — повний embed у кожному каналі
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, asyncio
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ══════════════════════════════════════════════════════════════════════════════
#  КОНФІГ
# ══════════════════════════════════════════════════════════════════════════════
MOD_LOG_NAME  = "📝│mod-log"
WARN_FILE     = "warns.json"
REPORT_FILE   = "reports.json"
TEMPBAN_FILE  = "tempbans.json"

# Ескалація: {кількість варнів: (дія, секунди)}
# tempban = тимчасовий бан; 0 секунд = перманентний
ESCALATION = {
    1: ("warn",    0),
    2: ("mute",    3_600),      # 1 год
    3: ("mute",    86_400),     # 24 год
    4: ("kick",    0),
    5: ("tempban", 259_200),    # 3 дні
    6: ("ban",     0),          # перманентний
}

SPAM_LIMIT  = 5   # повідомлень
SPAM_WINDOW = 5   # за секунд

BANNED_WORDS = [
    "cheat","hack","aimbot","wallhack","exploit","cheater",
    "читер","хак","читати",
]

# ══════════════════════════════════════════════════════════════════════════════
#  БД-УТИЛІТИ
# ══════════════════════════════════════════════════════════════════════════════
def _load(f):
    return json.load(open(f)) if os.path.exists(f) else {}

def _save(f, d):
    with open(f, "w") as fp:
        json.dump(d, fp, indent=2, ensure_ascii=False)

# ── Варни ────────────────────────────────────────────────────────────────────
def get_warns(uid: str) -> list:
    return _load(WARN_FILE).get(str(uid), [])

def add_warn(uid: str, reason: str, mod_id: int) -> int:
    db = _load(WARN_FILE)
    uid = str(uid)
    if uid not in db: db[uid] = []
    db[uid].append({"reason": reason, "mod_id": mod_id,
                    "time": datetime.now().isoformat()})
    _save(WARN_FILE, db)
    return len(db[uid])

def clear_warns(uid: str):
    db = _load(WARN_FILE)
    db.pop(str(uid), None)
    _save(WARN_FILE, db)

# ── Репорти ──────────────────────────────────────────────────────────────────
def add_report(target_id, reporter_id, reason, proof="") -> str:
    db  = _load(REPORT_FILE)
    rid = f"R{len(db)+1:04d}"
    db[rid] = {"target_id": str(target_id), "reporter_id": str(reporter_id),
                "reason": reason, "proof": proof, "status": "open",
                "time": datetime.now().isoformat()}
    _save(REPORT_FILE, db)
    return rid

def close_report(rid: str):
    db = _load(REPORT_FILE)
    if rid in db:
        db[rid]["status"] = "closed"
        _save(REPORT_FILE, db)

# ── Тимчасові бани ───────────────────────────────────────────────────────────
def add_tempban(guild_id: int, uid: str, unban_at: float, reason: str):
    db = _load(TEMPBAN_FILE)
    key = f"{guild_id}:{uid}"
    db[key] = {"uid": str(uid), "guild_id": guild_id,
                "unban_at": unban_at, "reason": reason}
    _save(TEMPBAN_FILE, db)

def remove_tempban(guild_id: int, uid: str):
    db  = _load(TEMPBAN_FILE)
    key = f"{guild_id}:{uid}"
    db.pop(key, None)
    _save(TEMPBAN_FILE, db)

def get_active_tempbans() -> list:
    return list(_load(TEMPBAN_FILE).values())

# ══════════════════════════════════════════════════════════════════════════════
#  ХЕЛПЕР — форматування тривалості
# ══════════════════════════════════════════════════════════════════════════════
def fmt_duration(seconds: int) -> str:
    if seconds <= 0: return "permanent"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    return " ".join(parts) or "< 1m"

def parse_duration(text: str) -> int:
    """'1d2h30m' → секунди. Повертає -1 якщо помилка."""
    text = text.strip().lower()
    total = 0
    buf   = ""
    for ch in text:
        if ch.isdigit():
            buf += ch
        elif ch in "dhms" and buf:
            n = int(buf)
            total += n * {"d":86400,"h":3600,"m":60,"s":1}[ch]
            buf = ""
        else:
            return -1
    return total if total > 0 else -1

# ══════════════════════════════════════════════════════════════════════════════
#  ЕСКАЛАЦІЯ
# ══════════════════════════════════════════════════════════════════════════════
async def apply_escalation(member: discord.Member, warn_count: int,
                            reason: str, guild: discord.Guild):
    action, duration = ESCALATION.get(
        min(warn_count, max(ESCALATION.keys())),
        ("ban", 0)
    )

    msgs = {
        "warn":    f"⚠️ **Warning #{warn_count}** on **{guild.name}**\nReason: {reason}",
        "mute":    f"🔇 **Muted** on **{guild.name}** for **{fmt_duration(duration)}**\nReason: {reason}\nWarn #{warn_count}",
        "kick":    f"👢 **Kicked** from **{guild.name}**\nReason: {reason}\nWarn #{warn_count}",
        "tempban": f"⏳ **Temp-banned** from **{guild.name}** for **{fmt_duration(duration)}**\nReason: {reason}\nWarn #{warn_count}",
        "ban":     f"🔨 **Permanently banned** from **{guild.name}**\nReason: {reason}\nWarn #{warn_count}",
    }
    # DM гравцю
    try:
        await member.send(msgs.get(action, msgs["warn"]))
    except Exception:
        pass

    if action == "mute" and duration:
        until = discord.utils.utcnow() + timedelta(seconds=duration)
        try: await member.timeout(until, reason=f"Auto-escalation warn #{warn_count}")
        except Exception: pass

    elif action == "kick":
        try: await member.kick(reason=f"Auto-escalation warn #{warn_count}")
        except Exception: pass

    elif action == "tempban":
        unban_at = datetime.now(timezone.utc).timestamp() + duration
        add_tempban(guild.id, str(member.id), unban_at, reason)
        try: await guild.ban(member, reason=f"Temp-ban {fmt_duration(duration)} | warn #{warn_count}",
                              delete_message_days=0)
        except Exception: pass

    elif action == "ban":
        try: await guild.ban(member, reason=f"Permanent ban | warn #{warn_count}",
                              delete_message_days=1)
        except Exception: pass

# ══════════════════════════════════════════════════════════════════════════════
#  VIEW: кнопки у #mod-log
# ══════════════════════════════════════════════════════════════════════════════
class ModActionView(discord.ui.View):
    def __init__(self, target_id: int, report_id: str):
        super().__init__(timeout=None)
        self.target_id = target_id
        self.report_id = report_id

    def _is_mod(self, i: discord.Interaction) -> bool:
        return any(r.permissions.moderate_members or r.permissions.administrator
                   for r in i.user.roles)

    @discord.ui.button(label="⚠️ Warn",        style=discord.ButtonStyle.secondary, row=0)
    async def b_warn(self, i, _):
        if not self._is_mod(i): await i.response.send_message("❌ No permission!", ephemeral=True); return
        await i.response.send_modal(QuickPunishModal("warn", self.target_id, self.report_id))

    @discord.ui.button(label="🔇 Mute 1h",     style=discord.ButtonStyle.primary,   row=0)
    async def b_mute1(self, i, _):
        if not self._is_mod(i): await i.response.send_message("❌ No permission!", ephemeral=True); return
        await self._do_mute(i, 3600)

    @discord.ui.button(label="🔇 Mute 24h",    style=discord.ButtonStyle.primary,   row=0)
    async def b_mute24(self, i, _):
        if not self._is_mod(i): await i.response.send_message("❌ No permission!", ephemeral=True); return
        await self._do_mute(i, 86400)

    @discord.ui.button(label="⏳ Temp-ban",    style=discord.ButtonStyle.danger,    row=1)
    async def b_tempban(self, i, _):
        if not self._is_mod(i): await i.response.send_message("❌ No permission!", ephemeral=True); return
        await i.response.send_modal(QuickPunishModal("tempban", self.target_id, self.report_id))

    @discord.ui.button(label="🔨 Perm-ban",    style=discord.ButtonStyle.danger,    row=1)
    async def b_ban(self, i, _):
        if not self._is_mod(i): await i.response.send_message("❌ No permission!", ephemeral=True); return
        await i.response.send_modal(QuickPunishModal("ban", self.target_id, self.report_id))

    @discord.ui.button(label="✅ Dismiss",      style=discord.ButtonStyle.secondary, row=1)
    async def b_dismiss(self, i, _):
        if not self._is_mod(i): await i.response.send_message("❌ No permission!", ephemeral=True); return
        close_report(self.report_id)
        await i.response.send_message(f"✅ Report **{self.report_id}** dismissed by {i.user.mention}")
        self._disable(); await i.message.edit(view=self)

    def _disable(self):
        for item in self.children: item.disabled = True

    async def _do_mute(self, i: discord.Interaction, secs: int):
        member = i.guild.get_member(self.target_id)
        if not member:
            await i.response.send_message("❌ Member not found!", ephemeral=True); return
        until = discord.utils.utcnow() + timedelta(seconds=secs)
        await member.timeout(until, reason=f"Muted by {i.user.display_name}")
        try: await member.send(f"🔇 Muted on **{i.guild.name}** for **{fmt_duration(secs)}**.")
        except Exception: pass
        await i.response.send_message(f"🔇 **{member.display_name}** muted {fmt_duration(secs)}.")
        close_report(self.report_id)
        self._disable(); await i.message.edit(view=self)


class QuickPunishModal(discord.ui.Modal):
    reason_inp = discord.ui.TextInput(label="Reason", max_length=200,
                                       placeholder="Describe the violation...")
    duration_inp = discord.ui.TextInput(
        label="Duration (tempban only): 1d / 12h / 30m",
        placeholder="3d", required=False, max_length=10
    )

    def __init__(self, action: str, target_id: int, report_id: str):
        titles = {"warn":"⚠️ Warn Player","tempban":"⏳ Temp-ban Player","ban":"🔨 Ban Player"}
        super().__init__(title=titles.get(action, "Punish"))
        self.action    = action
        self.target_id = target_id
        self.report_id = report_id

    async def on_submit(self, i: discord.Interaction):
        reason = self.reason_inp.value
        member = i.guild.get_member(self.target_id)
        if not member:
            await i.response.send_message("❌ Member not found (may have left).", ephemeral=True); return

        if self.action == "warn":
            count = add_warn(str(self.target_id), reason, i.user.id)
            await apply_escalation(member, count, reason, i.guild)
            await i.response.send_message(
                f"⚠️ **{member.display_name}** warned ({count} total). "
                f"Escalation: **{ESCALATION.get(min(count,max(ESCALATION)),('ban',0))[0].upper()}**"
            )

        elif self.action == "tempban":
            raw = self.duration_inp.value.strip() or "3d"
            secs = parse_duration(raw)
            if secs < 0: secs = 259_200   # дефолт 3 дні
            unban_at = datetime.now(timezone.utc).timestamp() + secs
            add_tempban(i.guild.id, str(member.id), unban_at, reason)
            try: await member.send(f"⏳ **Temp-banned** from **{i.guild.name}** for **{fmt_duration(secs)}**.\nReason: {reason}")
            except Exception: pass
            await i.guild.ban(member, reason=f"Temp-ban {fmt_duration(secs)}: {reason}", delete_message_days=0)
            await i.response.send_message(
                f"⏳ **{member.display_name}** temp-banned for **{fmt_duration(secs)}**. "
                f"Auto-unban at <t:{int(unban_at)}:F>"
            )

        elif self.action == "ban":
            try: await member.send(f"🔨 **Permanently banned** from **{i.guild.name}**.\nReason: {reason}")
            except Exception: pass
            await i.guild.ban(member, reason=reason, delete_message_days=1)
            await i.response.send_message(f"🔨 **{member.display_name}** permanently banned.")

        close_report(self.report_id)
        for item in self.view.children: item.disabled = True  # type: ignore
        await i.message.edit(view=self.view)  # type: ignore


# ══════════════════════════════════════════════════════════════════════════════
#  SETUP_MODERATION  — підключення до бота
# ══════════════════════════════════════════════════════════════════════════════
def setup_moderation(bot: commands.Bot, tree: app_commands.CommandTree, guild_id: int):

    _spam: dict[int, list[float]] = defaultdict(list)

    # ── Таймер авто-розбану ─────────────────────────────────────────────────
    @tasks.loop(seconds=60)
    async def unban_loop():
        now  = datetime.now(timezone.utc).timestamp()
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
                        # Повідомлення у mod-log
                        ml = discord.utils.get(guild.text_channels, name=MOD_LOG_NAME)
                        if ml:
                            embed = discord.Embed(
                                title="⏳ Temp-ban Expired",
                                description=f"<@{uid}> has been automatically unbanned.",
                                color=0x57F287,
                                timestamp=datetime.now(timezone.utc)
                            )
                            await ml.send(embed=embed)
                        # DM гравцю
                        try: await user.send(f"✅ Your temp-ban on **{guild.name}** has expired. You can rejoin!")
                        except Exception: pass
                        print(f"✅ Auto-unbanned {uid} from {guild.name}")
                    except Exception as e:
                        print(f"⚠️ Unban error {uid}: {e}")

    unban_loop.start()

    # ── /report ─────────────────────────────────────────────────────────────
    report_grp = app_commands.Group(name="report", description="Report a player")

    @report_grp.command(name="player", description="Report a player / Поскаржитись на гравця")
    @app_commands.describe(player="Player to report", reason="Reason for report")
    async def report_player(i: discord.Interaction, player: discord.Member, reason: str):
        if player.bot:
            await i.response.send_message("❌ Can't report bots!", ephemeral=True); return
        ml = discord.utils.get(i.guild.text_channels, name=MOD_LOG_NAME)
        if not ml:
            await i.response.send_message("❌ Mod-log channel not found!", ephemeral=True); return

        rid = add_report(str(player.id), str(i.user.id), reason)
        warns = get_warns(str(player.id))

        embed = discord.Embed(title=f"🚩 Report #{rid}", color=0xFF4444,
                              timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=player.display_avatar.url)
        embed.add_field(name="🎯 Reported",  value=player.mention,   inline=True)
        embed.add_field(name="👤 Reporter",  value=i.user.mention,   inline=True)
        embed.add_field(name="⚠️ Warns",     value=f"{len(warns)}/5", inline=True)
        embed.add_field(name="📋 Reason",    value=reason,            inline=False)
        embed.set_footer(text="Use buttons below to take action")

        await ml.send(content="🚩 **New report!** @here", embed=embed,
                      view=ModActionView(player.id, rid))
        await i.response.send_message(
            f"✅ Report **#{rid}** submitted. Moderators notified.\n"
            f"✅ Репорт **#{rid}** надіслано модераторам.", ephemeral=True
        )

    tree.add_command(report_grp)

    # ── /warn ───────────────────────────────────────────────────────────────
    @tree.command(name="warn", description="[MOD] Warn a player")
    @app_commands.describe(player="Player", reason="Reason")
    async def cmd_warn(i: discord.Interaction, player: discord.Member, reason: str):
        if not any(r.permissions.moderate_members or r.permissions.administrator for r in i.user.roles):
            await i.response.send_message("❌ No permission!", ephemeral=True); return
        count  = add_warn(str(player.id), reason, i.user.id)
        action = ESCALATION.get(min(count, max(ESCALATION)), ("ban",0))[0]
        await apply_escalation(player, count, reason, i.guild)

        action_labels = {"warn":"⚠️ Warned","mute":"🔇 Muted","kick":"👢 Kicked",
                         "tempban":"⏳ Temp-banned","ban":"🔨 Banned"}
        embed = discord.Embed(title="🛡️ Moderation Action", color=0xFF6B35,
                              timestamp=datetime.now(timezone.utc))
        embed.add_field(name="👤 Player",  value=player.mention,              inline=True)
        embed.add_field(name="⚠️ Warns",   value=f"{count}/{max(ESCALATION)}", inline=True)
        embed.add_field(name="🔨 Action",  value=action_labels.get(action,"⚠️ Warned"), inline=True)
        embed.add_field(name="📋 Reason",  value=reason,                      inline=False)
        embed.add_field(name="🛡️ Mod",    value=i.user.mention,              inline=True)
        await i.response.send_message(embed=embed)

        ml = discord.utils.get(i.guild.text_channels, name=MOD_LOG_NAME)
        if ml: await ml.send(embed=embed)

    # ── /mute ───────────────────────────────────────────────────────────────
    @tree.command(name="mute", description="[MOD] Mute a player")
    @app_commands.describe(player="Player", duration="Duration: 1h / 30m / 2d", reason="Reason")
    async def cmd_mute(i: discord.Interaction, player: discord.Member,
                       duration: str = "1h", reason: str = "No reason"):
        if not any(r.permissions.moderate_members or r.permissions.administrator for r in i.user.roles):
            await i.response.send_message("❌ No permission!", ephemeral=True); return
        secs = parse_duration(duration)
        if secs < 0:
            await i.response.send_message("❌ Invalid duration. Use: 30m / 2h / 1d", ephemeral=True); return
        until = discord.utils.utcnow() + timedelta(seconds=secs)
        await player.timeout(until, reason=reason)
        try: await player.send(f"🔇 Muted on **{i.guild.name}** for **{fmt_duration(secs)}**.\nReason: {reason}")
        except: pass
        await i.response.send_message(
            f"🔇 **{player.display_name}** muted for **{fmt_duration(secs)}**. "
            f"Unmutes <t:{int(until.timestamp())}:R>"
        )

    # ── /unmute ─────────────────────────────────────────────────────────────
    @tree.command(name="unmute", description="[MOD] Remove mute")
    async def cmd_unmute(i: discord.Interaction, player: discord.Member):
        if not any(r.permissions.moderate_members or r.permissions.administrator for r in i.user.roles):
            await i.response.send_message("❌ No permission!", ephemeral=True); return
        await player.timeout(None)
        await i.response.send_message(f"🔓 **{player.display_name}** unmuted.")

    # ── /kick ───────────────────────────────────────────────────────────────
    @tree.command(name="kick", description="[MOD] Kick a player")
    @app_commands.describe(player="Player", reason="Reason")
    async def cmd_kick(i: discord.Interaction, player: discord.Member, reason: str = "No reason"):
        if not any(r.permissions.moderate_members or r.permissions.administrator for r in i.user.roles):
            await i.response.send_message("❌ No permission!", ephemeral=True); return
        try: await player.send(f"👢 Kicked from **{i.guild.name}**.\nReason: {reason}")
        except: pass
        await player.kick(reason=reason)
        await i.response.send_message(f"👢 **{player.display_name}** kicked.")

    # ── /tempban ─────────────────────────────────────────────────────────────
    @tree.command(name="tempban", description="[MOD] Temp-ban with auto-unban timer")
    @app_commands.describe(player="Player", duration="Duration: 1d / 12h / 7d",
                           reason="Reason")
    async def cmd_tempban(i: discord.Interaction, player: discord.Member,
                          duration: str, reason: str = "No reason"):
        if not any(r.permissions.moderate_members or r.permissions.administrator for r in i.user.roles):
            await i.response.send_message("❌ No permission!", ephemeral=True); return
        secs = parse_duration(duration)
        if secs < 0:
            await i.response.send_message("❌ Invalid duration. Use: 1d / 12h / 30m", ephemeral=True); return

        unban_ts = datetime.now(timezone.utc).timestamp() + secs
        add_tempban(i.guild.id, str(player.id), unban_ts, reason)
        try: await player.send(
            f"⏳ **Temp-banned** from **{i.guild.name}** for **{fmt_duration(secs)}**.\n"
            f"Reason: {reason}\n"
            f"You will be automatically unbanned on <t:{int(unban_ts)}:F>"
        )
        except: pass
        await i.guild.ban(player, reason=f"Temp-ban {fmt_duration(secs)}: {reason}",
                           delete_message_days=0)
        embed = discord.Embed(title="⏳ Temp-ban Applied", color=0xFF6B35,
                              timestamp=datetime.now(timezone.utc))
        embed.add_field(name="👤 Player",    value=player.mention,                      inline=True)
        embed.add_field(name="⏱️ Duration",  value=fmt_duration(secs),                  inline=True)
        embed.add_field(name="📅 Unban at",  value=f"<t:{int(unban_ts)}:F>",           inline=True)
        embed.add_field(name="📋 Reason",    value=reason,                              inline=False)
        embed.add_field(name="🛡️ Mod",      value=i.user.mention,                      inline=True)
        await i.response.send_message(embed=embed)
        ml = discord.utils.get(i.guild.text_channels, name=MOD_LOG_NAME)
        if ml: await ml.send(embed=embed)

    # ── /ban ─────────────────────────────────────────────────────────────────
    @tree.command(name="ban", description="[MOD] Permanently ban a player")
    @app_commands.describe(player="Player", reason="Reason")
    async def cmd_ban(i: discord.Interaction, player: discord.Member, reason: str = "No reason"):
        if not any(r.permissions.administrator for r in i.user.roles):
            await i.response.send_message("❌ Admins only!", ephemeral=True); return
        try: await player.send(f"🔨 **Permanently banned** from **{i.guild.name}**.\nReason: {reason}")
        except: pass
        await i.guild.ban(player, reason=reason, delete_message_days=1)
        await i.response.send_message(f"🔨 **{player.display_name}** permanently banned.")

    # ── /unban ────────────────────────────────────────────────────────────────
    @tree.command(name="unban", description="[MOD] Unban a user by ID")
    @app_commands.describe(user_id="User ID (number)")
    async def cmd_unban(i: discord.Interaction, user_id: str):
        if not any(r.permissions.administrator for r in i.user.roles):
            await i.response.send_message("❌ Admins only!", ephemeral=True); return
        try:
            user = await bot.fetch_user(int(user_id))
            await i.guild.unban(user, reason=f"Unbanned by {i.user.display_name}")
            remove_tempban(i.guild.id, user_id)
            await i.response.send_message(f"✅ **{user.name}** unbanned.")
        except Exception as e:
            await i.response.send_message(f"❌ Error: {e}", ephemeral=True)

    # ── /warns ────────────────────────────────────────────────────────────────
    @tree.command(name="warns", description="[MOD] View player warns")
    async def cmd_warns(i: discord.Interaction, player: discord.Member):
        if not any(r.permissions.moderate_members or r.permissions.administrator for r in i.user.roles):
            await i.response.send_message("❌ No permission!", ephemeral=True); return
        warns = get_warns(str(player.id))
        embed = discord.Embed(title=f"⚠️ Warns — {player.display_name}",
                              color=0xFF6B35 if warns else 0x57F287)
        if not warns:
            embed.description = "✅ No warnings on record."
        else:
            for idx, w in enumerate(warns, 1):
                next_action = ESCALATION.get(idx+1, ("ban",0))[0].upper()
                embed.add_field(
                    name=f"#{idx} • {w['time'][:10]}",
                    value=f"**Reason:** {w['reason']}\n**Mod:** <@{w['mod_id']}>",
                    inline=False
                )
            embed.set_footer(text=f"Next escalation: {ESCALATION.get(len(warns)+1,('ban',0))[0].upper()}")
        await i.response.send_message(embed=embed, ephemeral=True)

    # ── /clearwarns ───────────────────────────────────────────────────────────
    @tree.command(name="clearwarns", description="[MOD] Clear all warns")
    async def cmd_clearwarns(i: discord.Interaction, player: discord.Member):
        if not any(r.permissions.administrator for r in i.user.roles):
            await i.response.send_message("❌ Admins only!", ephemeral=True); return
        clear_warns(str(player.id))
        await i.response.send_message(f"✅ All warns cleared for **{player.display_name}**.")

    # ── /tempbans ─────────────────────────────────────────────────────────────
    @tree.command(name="tempbans", description="[MOD] List active temp-bans")
    async def cmd_tempbans(i: discord.Interaction):
        if not any(r.permissions.moderate_members or r.permissions.administrator for r in i.user.roles):
            await i.response.send_message("❌ No permission!", ephemeral=True); return
        bans = [b for b in get_active_tempbans() if b["guild_id"] == i.guild.id]
        embed = discord.Embed(title="⏳ Active Temp-bans", color=0xFF6B35)
        if not bans:
            embed.description = "✅ No active temp-bans."
        else:
            for b in bans:
                ts = int(b["unban_at"])
                embed.add_field(
                    name=f"<@{b['uid']}>",
                    value=f"Unban: <t:{ts}:F> (<t:{ts}:R>)\nReason: {b['reason']}",
                    inline=False
                )
        await i.response.send_message(embed=embed, ephemeral=True)

    # ── Авто-модерація ────────────────────────────────────────────────────────
    @bot.listen("on_message")
    async def auto_mod(message: discord.Message):
        if message.author.bot: return
        if any(r.permissions.moderate_members for r in message.author.roles): return

        uid = message.author.id
        now = datetime.now(timezone.utc).timestamp()

        # Антиспам
        _spam[uid] = [t for t in _spam[uid] if now - t < SPAM_WINDOW]
        _spam[uid].append(now)
        if len(_spam[uid]) >= SPAM_LIMIT:
            _spam[uid].clear()
            try:
                await message.author.timeout(
                    discord.utils.utcnow() + timedelta(minutes=5),
                    reason="Auto-mod: spam"
                )
            except: pass
            await message.channel.send(
                f"🤖 {message.author.mention} auto-muted **5 min** for spam.",
                delete_after=8
            )
            return

        # Фільтр слів
        if any(w in message.content.lower() for w in BANNED_WORDS):
            try: await message.delete()
            except: pass
            count = add_warn(str(uid), "Auto-mod: forbidden word", 0)
            await apply_escalation(message.author, count, "Forbidden word", message.guild)
            await message.channel.send(
                f"🤖 {message.author.mention} — message removed. Forbidden content. "
                f"(warn **{count}/{max(ESCALATION)}**)",
                delete_after=8
            )


# ══════════════════════════════════════════════════════════════════════════════
#  SETUP_CONTENT — повний контент у кожному каналі
# ══════════════════════════════════════════════════════════════════════════════
async def setup_content(guild: discord.Guild):
    """Викличте один раз після discord_setup.py щоб заповнити канали."""

    async def post(ch_name: str, *embeds: discord.Embed, content: str = ""):
        ch = discord.utils.get(guild.text_channels, name=ch_name)
        if not ch:
            print(f"⚠️  Channel not found: {ch_name}")
            return
        async for m in ch.history(limit=30):
            if m.author == guild.me:
                try: await m.delete()
                except: pass
        await asyncio.sleep(0.4)
        if content:
            await ch.send(content)
        for e in embeds:
            await ch.send(embed=e)
            await asyncio.sleep(0.5)
        print(f"   ✅ #{ch_name}")

    print("\n📢 Posting channel content...\n")

    # ── #📌│rules ──────────────────────────────────────────────────────────
    e = discord.Embed(title="📜  Server Rules — 8-BIT TANKS", color=0xFFD700)
    e.add_field(name="🇺🇦 Українська", inline=False, value=(
        "**1.** Поважай усіх гравців\n"
        "**2.** Заборонено читерство, хаки та експлойти\n"
        "**3.** Спілкуйся у своєму мовному каналі\n"
        "**4.** Без спаму, флуду та рекламних посилань\n"
        "**5.** Слухайся модераторів\n"
        "**6.** 18+ контент, токсичність — бан\n"
        "**7.** Репорти: `/report player @гравець`"
    ))
    e.add_field(name="🇬🇧 English", inline=False, value=(
        "**1.** Respect all players\n"
        "**2.** No cheating, hacks or exploits\n"
        "**3.** Chat in your language channel\n"
        "**4.** No spam, flood or ad links\n"
        "**5.** Follow moderator instructions\n"
        "**6.** 18+ content, toxicity = ban\n"
        "**7.** Reports: `/report player @player`"
    ))
    e.add_field(name="🇩🇪 / 🇵🇱 / 🇫🇷", inline=False, value=(
        "**DE:** Regeln für alle. Kein Cheaten, kein Spam, kein 18+ Inhalt.\n"
        "**PL:** Zasady dla wszystkich. Zakaz cheaterstwa, spamu i treści 18+.\n"
        "**FR:** Règles pour tous. Pas de triche, spam ni contenu 18+."
    ))
    e.add_field(name="⚖️ Punishment Ladder", inline=False, value=(
        "```\n"
        "Warn 1  →  ⚠️  Warning (DM)\n"
        "Warn 2  →  🔇  Mute 1 hour\n"
        "Warn 3  →  🔇  Mute 24 hours\n"
        "Warn 4  →  👢  Kick\n"
        "Warn 5  →  ⏳  Temp-ban 3 days\n"
        "Warn 6  →  🔨  Permanent ban\n"
        "```"
    ))
    e.set_footer(text="8-BIT TANKS • Rules last updated 2025")
    await post("📌│rules", e)

    # ── #📣│announcements ──────────────────────────────────────────────────
    e = discord.Embed(
        title="📣  Welcome to 8-BIT TANKS!",
        description=(
            "🎮 **8-BIT TANKS** is a retro 8-bit tank battle game.\n\n"
            "🇺🇦 Ласкаво просимо! Зареєструйся: `/register`\n"
            "🇬🇧 Welcome! Register: `/register`\n"
            "🇩🇪 Willkommen! Registriere dich: `/register`\n"
            "🇵🇱 Witaj! Zarejestruj się: `/register`\n"
            "🇫🇷 Bienvenue! Inscrivez-vous: `/register`"
        ),
        color=0xFFD700
    )
    e.add_field(name="🔗 Links", inline=False, value=(
        "🌐 Website: *coming soon*\n"
        "🐦 Twitter/X: *coming soon*\n"
        "▶️ YouTube: *coming soon*\n"
        "💬 Support: DM a 🛡️ Moderator"
    ))
    e.set_footer(text="Follow this channel for game updates & events!")
    await post("📣│announcements", e)

    # ── #🗓️│events ─────────────────────────────────────────────────────────
    e = discord.Embed(title="🗓️  Upcoming Events", color=0xFF6B35)
    e.add_field(name="🏆 Weekly Tournament", inline=False, value=(
        "📅 Every Saturday 18:00 UTC\n"
        "🎯 Format: 1v1 Bracket\n"
        "🏅 Prize: 🌟 VIP role for 1 week\n"
        "📋 Sign up: mention a 🛡️ Mod"
    ))
    e.add_field(name="⚔️ Weekend FFA", inline=False, value=(
        "📅 Every Sunday 16:00 UTC\n"
        "🎯 Format: Free-for-all (8 players)\n"
        "🏅 Prize: 🎖️ Veteran role\n"
        "📋 Join voice: ⚔️ Battle rooms"
    ))
    e.add_field(name="🧪 Beta Test Sessions", inline=False, value=(
        "📅 Announced in #announcements\n"
        "🔬 Open for 🔬 Beta Tester role holders\n"
        "📋 Apply: DM a 🎮 Developer"
    ))
    e.set_footer(text="All times in UTC • React 🎮 to get event notifications")
    await post("🗓️│events", e)

    # ── #🔔│changelog ──────────────────────────────────────────────────────
    e = discord.Embed(title="🔔  Game Changelog", color=0x57F287)
    e.add_field(name="🆕 v0.3 — Community Update", inline=False, value=(
        "• Discord & Telegram bots\n"
        "• 5-language auto-translate\n"
        "• Private room system\n"
        "• Report & moderation system\n"
        "• Temp-ban with auto-timer\n"
        "• Player stats & leaderboard"
    ))
    e.add_field(name="🎮 v0.2 — Gameplay", inline=False, value=(
        "• New map: Desert Storm\n"
        "• Tank skin system (3 skins)\n"
        "• Improved bullet physics\n"
        "• Wall collision fix"
    ))
    e.add_field(name="🚀 v0.1 — Alpha", inline=False, value=(
        "• Core gameplay loop\n"
        "• 2-player local multiplayer\n"
        "• 3 tank types\n"
        "• 2 maps"
    ))
    e.set_footer(text="v0.4 in development • Check #announcements")
    await post("🔔│changelog", e)

    # ── #🤖│bot-commands ───────────────────────────────────────────────────
    e = discord.Embed(title="🤖  Bot Commands — 8-BIT TANKS", color=0x5865F2)
    e.add_field(name="👤 Player", inline=False, value=(
        "`/register` — Register your tank\n"
        "`/stats [@player]` — View stats\n"
        "`/top` — Leaderboard top 10\n"
        "`/lang` — Change language\n"
        "`/help` — Full help"
    ))
    e.add_field(name="🏠 Private Rooms", inline=False, value=(
        "`/room create [name] [private]` — Create room\n"
        "`/room list` — Active rooms\n"
        "`/room close` — Delete your room"
    ))
    e.add_field(name="🚩 Reports", inline=False, value=(
        "`/report player @user <reason>` — Report player\n"
        "Right-click message → Apps → **🚩 Report Message**"
    ))
    e.add_field(name="🛡️ Mod Commands", inline=False, value=(
        "`/warn @user <reason>` — Warn\n"
        "`/mute @user <time> <reason>` — Mute (e.g. `1h`, `30m`)\n"
        "`/unmute @user` — Remove mute\n"
        "`/kick @user <reason>` — Kick\n"
        "`/tempban @user <time> <reason>` — Temp-ban (e.g. `3d`)\n"
        "`/ban @user <reason>` — Permanent ban\n"
        "`/unban <userID>` — Unban\n"
        "`/warns @user` — View warns\n"
        "`/clearwarns @user` — Clear warns\n"
        "`/tempbans` — List active temp-bans"
    ))
    e.set_footer(text="Duration format: 30m / 2h / 1d / 1d12h")
    await post("🤖│bot-commands", e)

    # ── #🎯│matchmaking ────────────────────────────────────────────────────
    e = discord.Embed(
        title="🎯  Matchmaking — Find Your Battle",
        description="Looking for opponents? Post here using the template below.",
        color=0xFF6B35
    )
    e.add_field(name="📋 Post Template", inline=False, value=(
        "```\n"
        "Mode:     1v1 / 2v2 / FFA\n"
        "Rank:     Beginner / Regular / Champion\n"
        "Language: UA / EN / DE / PL / FR\n"
        "Time:     Now / In 30min / Tonight\n"
        "Contact:  @YourName\n"
        "```"
    ))
    e.add_field(name="🏆 Game Modes", inline=True, value=(
        "**1v1 Duel** — Ranked\n"
        "**2v2 Team** — Ranked\n"
        "**FFA** — Unranked"
    ))
    e.add_field(name="📊 Quick Links", inline=True, value=(
        "`/stats` — Your profile\n"
        "`/top` — Leaderboard\n"
        "`/room create` — Private room"
    ))
    await post("🎯│matchmaking", e)

    # ── #📊│leaderboard ────────────────────────────────────────────────────
    e = discord.Embed(
        title="📊  Leaderboard",
        description="Use `/top` to see the live top-10!\nUse `/stats @player` to check any player.",
        color=0xFFD700
    )
    e.add_field(name="🏅 Rank Roles", inline=False, value=(
        "🏆 **Champion** — Top 3 all-time\n"
        "🎖️ **Veteran** — 50+ wins\n"
        "🌟 **VIP** — Special recognition\n"
        "🎯 **Player** — Default rank"
    ))
    e.set_footer(text="Leaderboard updates live after each match")
    await post("📊│leaderboard", e)

    # ── #🗺️│maps-tactics ──────────────────────────────────────────────────
    e = discord.Embed(
        title="🗺️  Maps & Tactics",
        description="Share strategies, counters, and map analysis here!",
        color=0x57F287
    )
    e.add_field(name="🏜️ Desert Storm",  inline=True, value="Open. Sniper meta.\n💡 Use rocks for cover")
    e.add_field(name="🌆 City Ruins",    inline=True, value="Close quarters. Ambush.\n💡 Slow tanks shine")
    e.add_field(name="🌲 Forest Maze",   inline=True, value="Narrow paths.\n💡 Fast tanks dominate")
    e.add_field(name="📋 Post Template", inline=False, value=(
        "```\n"
        "Map:      Desert Storm / City Ruins / Forest Maze\n"
        "Mode:     1v1 / 2v2 / FFA\n"
        "Tank:     Heavy / Medium / Light\n"
        "Strategy: [describe your tactic]\n"
        "```"
    ))
    e.set_footer(text="More maps coming in v0.4!")
    await post("🗺️│maps-tactics", e)

    # ── #🐛│bug-reports ────────────────────────────────────────────────────
    e = discord.Embed(
        title="🐛  Bug Reports",
        description="Found a bug? Use the template below. Clear reports = faster fixes!",
        color=0xFF4444
    )
    e.add_field(name="📋 Bug Report Template", inline=False, value=(
        "```\n"
        "Type:        Visual / Gameplay / Crash / Network / Other\n"
        "Severity:    🔴 Critical / 🟡 Major / 🟢 Minor\n"
        "Description: What happened exactly?\n"
        "Steps:       1. ... 2. ... 3. ...\n"
        "Expected:    What should have happened?\n"
        "Platform:    PC / Mobile / Web\n"
        "Version:     v0.3\n"
        "Screenshot:  [attach image if possible]\n"
        "```"
    ))
    e.add_field(name="🏷️ Severity Guide", inline=False, value=(
        "🔴 **Critical** — Game crashes, can't play at all\n"
        "🟡 **Major** — Feature broken, affects gameplay\n"
        "🟢 **Minor** — Visual glitch, cosmetic issue"
    ))
    e.set_footer(text="Bugs with screenshots get fixed 10x faster!")
    await post("🐛│bug-reports", e)

    # ── #📸│screenshots ────────────────────────────────────────────────────
    e = discord.Embed(
        title="📸  Screenshots & Clips",
        description="Share your best moments, epic wins, and funny fails!",
        color=0xE040FB
    )
    e.add_field(name="✅ What to share", inline=True, value=(
        "🏆 Epic victories\n"
        "💥 Cool explosions\n"
        "😂 Funny moments\n"
        "🎨 Fan art"
    ))
    e.add_field(name="❌ What NOT to share", inline=True, value=(
        "🚫 Cheating\n"
        "🚫 Toxic content\n"
        "🚫 Other games\n"
        "🚫 Personal info"
    ))
    e.set_footer(text="Best clips may be featured on our social media!")
    await post("📸│screenshots", e)

    # ── #📖│room-guide ─────────────────────────────────────────────────────
    e = discord.Embed(title="🏠  Private Room Guide", color=0x5865F2)
    e.add_field(name="🚀 Commands", inline=False, value=(
        "`/room create` — Public room\n"
        "`/room create name:My Room private:True` — Private room\n"
        "`/room list` — See all active rooms\n"
        "`/room close` — Delete your room"
    ))
    e.add_field(name="🎛️ Room Panel Buttons", inline=False, value=(
        "✏️ **Rename** — Change room name\n"
        "🔒 **Lock/Unlock** — Toggle private\n"
        "👥 **Set Limit** — Max players (e.g. 4)\n"
        "➕ **Invite Player** — Allow a specific player\n"
        "➖ **Kick from Room** — Remove player\n"
        "🗑️ **Delete Room** — Close immediately"
    ))
    e.add_field(name="⏳ Auto-Delete", inline=False, value=(
        "Room auto-deletes **15 minutes** after everyone leaves.\n"
        "A countdown message appears when room goes empty."
    ))
    e.set_footer(text="Only the room owner can use the control panel buttons")
    await post("📖│room-guide", e)

    # ── Мовні канали: загальний / general / allgemein / ogólny / général ────
    for ch_name, title, desc in [
        ("🇺🇦│загальний",  "🇺🇦 Українська — Загальний чат",
         "Вітаємо! Спілкуйся тут рідною мовою 🎮\nАвтопереклад активний — твої повідомлення побачать гравці інших мов."),
        ("🇬🇧│general",    "🇬🇧 English — General Chat",
         "Welcome! Chat here in English 🎮\nAuto-translate is active — your messages reach players in other languages."),
        ("🇩🇪│allgemein",  "🇩🇪 Deutsch — Allgemeiner Chat",
         "Willkommen! Chatte hier auf Deutsch 🎮\nAuto-Übersetzung aktiv."),
        ("🇵🇱│ogólny",    "🇵🇱 Polski — Ogólny czat",
         "Witaj! Rozmawiaj tutaj po polsku 🎮\nAutomatyczne tłumaczenie aktywne."),
        ("🇫🇷│général",   "🇫🇷 Français — Chat général",
         "Bienvenue! Chattez ici en français 🎮\nTraduction automatique active."),
    ]:
        e = discord.Embed(title=title, description=desc, color=0x57F287)
        e.add_field(name="📌 Useful commands", value="`/stats` • `/top` • `/room create` • `/report player`")
        e.set_footer(text="8-BIT TANKS Community")
        await post(ch_name, e)

    # ── 🧪 TESTING каналів ─────────────────────────────────────────────────

    # #📋│tester-rules
    e = discord.Embed(title="📋  Tester Rules & Guidelines", color=0xFF4500)
    e.add_field(name="🔒 NDA", inline=False, value=(
        "Everything in this category is **confidential**.\n"
        "Do NOT share screenshots, videos or info outside this server.\n"
        "Violation = permanent removal from testing program."
    ))
    e.add_field(name="✅ How to report bugs", inline=False, value=(
        "Use `/bug` command OR post in <#🐛│bugs-private>\n\n"
        "```\n"
        "Title:       Short bug name\n"
        "Type:        Visual / Gameplay / Crash / Network\n"
        "Severity:    🔴 Critical / 🟡 Major / 🟢 Minor\n"
        "Description: What happened?\n"
        "Steps:       1. ... 2. ... 3. ...\n"
        "Expected:    What should happen?\n"
        "Version:     Current test build\n"
        "Screenshot:  [attach if possible]\n"
        "```"
    ))
    e.add_field(name="⭐ How to leave feedback", inline=False, value=(
        "Use `/feedback` command OR post in <#⭐│feedback>\n\n"
        "Be specific — vague feedback is hard to act on.\n"
        "Rate features 1–10 when possible."
    ))
    e.add_field(name="🆕 Feature requests", inline=False, value=(
        "Post in <#🆕│feature-requests>\n"
        "Explain **why** the feature would improve the game."
    ))
    e.set_footer(text="Thank you for helping make 8-BIT TANKS better! 🎮")
    await post("📋│tester-rules", e)

    # #💬│tester-chat
    e = discord.Embed(
        title="💬  Tester Chat",
        description=(
            "Welcome, **Alpha & Beta Testers**! 🧪\n\n"
            "This is your private space to discuss the game, "
            "share findings and coordinate testing sessions.\n\n"
            "🔒 This channel is **not visible** to regular players."
        ),
        color=0xFF4500
    )
    e.add_field(name="📌 Quick links", value=(
        "<#📋│tester-rules> — Rules\n"
        "<#🐛│bugs-private> — Bug reports\n"
        "<#⭐│feedback> — Feedback\n"
        "<#📊│dev-polls> — Dev polls"
    ))
    e.set_footer(text="8-BIT TANKS Alpha/Beta Testing Program")
    await post("💬│tester-chat", e)

    # #🐛│bugs-private
    e = discord.Embed(title="🐛  Private Bug Reports", color=0xFF4500)
    e.add_field(name="📋 Template", inline=False, value=(
        "```\n"
        "Title:       [SHORT BUG NAME]\n"
        "Type:        Visual / Gameplay / Crash / Network / Audio\n"
        "Severity:    🔴 Critical / 🟡 Major / 🟢 Minor\n"
        "Build:       [version number]\n"
        "Description: [what happened]\n"
        "Steps:       1. Open game\n"
        "             2. ...\n"
        "             3. Bug appears\n"
        "Expected:    [what should happen]\n"
        "Platform:    PC / Mobile / Web\n"
        "Screenshot:  [attach image]\n"
        "```"
    ))
    e.add_field(name="🏷️ Severity", inline=False, value=(
        "🔴 **Critical** — Crash / game breaking / data loss\n"
        "🟡 **Major** — Feature broken, affects gameplay\n"
        "🟢 **Minor** — Visual glitch, typo, cosmetic"
    ))
    e.set_footer(text="Use /bug command for quick reports")
    await post("🐛│bugs-private", e)

    # #⭐│feedback
    e = discord.Embed(title="⭐  Feedback Channel", color=0xFFD700)
    e.add_field(name="📋 Template", inline=False, value=(
        "```\n"
        "Feature:    [what you're giving feedback on]\n"
        "Rating:     X/10\n"
        "Pros:       + ...\n"
        "Cons:       - ...\n"
        "Suggestion: [how to improve]\n"
        "```"
    ))
    e.add_field(name="💡 Good feedback examples", inline=False, value=(
        "✅ \"Tank movement feels sluggish on mobile — 5/10. Adding acceleration curve would help.\"\n"
        "✅ \"Bullet speed is perfect for 1v1 but too fast in FFA — 7/10.\"\n"
        "❌ \"The game is bad\" — not helpful\n"
        "❌ \"Fix controls\" — too vague"
    ))
    e.set_footer(text="Use /feedback command for quick submission")
    await post("⭐│feedback", e)

    # #🆕│feature-requests
    e = discord.Embed(title="🆕  Feature Requests", color=0x57F287)
    e.add_field(name="📋 Template", inline=False, value=(
        "```\n"
        "Feature:    [name of the feature]\n"
        "Why:        [why it would improve the game]\n"
        "How:        [how it could work]\n"
        "Priority:   High / Medium / Low\n"
        "```"
    ))
    e.add_field(name="👍 Voting", inline=False, value=(
        "React with **👍** to support a request.\n"
        "Requests with 5+ 👍 go to the dev backlog automatically."
    ))
    await post("🆕│feature-requests", e)

    # #📊│dev-polls
    e = discord.Embed(
        title="📊  Dev Polls",
        description=(
            "Developers will post polls here to get your opinion on upcoming features.\n\n"
            "**Vote honestly** — your feedback shapes the game!\n"
            "React with the emoji shown in each poll."
        ),
        color=0x5865F2
    )
    await post("📊│dev-polls", e)

    # ── 🌍 COMMUNITY каналів ───────────────────────────────────────────────

    # #🐛│bug-reports (публічний)
    e = discord.Embed(title="🐛  Bug Reports", color=0xFF4444)
    e.add_field(name="📋 Template", inline=False, value=(
        "```\n"
        "Type:        Visual / Gameplay / Crash / Network\n"
        "Severity:    🔴 Critical / 🟡 Major / 🟢 Minor\n"
        "Description: What happened?\n"
        "Steps:       1. ... 2. ... 3. ...\n"
        "Expected:    What should happen?\n"
        "Platform:    PC / Mobile / Web\n"
        "Screenshot:  [attach if possible]\n"
        "```"
    ))
    e.add_field(name="🏷️ Severity", inline=False, value=(
        "🔴 **Critical** — Game crashes / can't play\n"
        "🟡 **Major** — Feature broken\n"
        "🟢 **Minor** — Visual glitch"
    ))
    e.add_field(name="💡 Tip", inline=False, value=(
        "Use `/bug` command for a quick form!\n"
        "Screenshots get bugs fixed 10× faster."
    ))
    e.set_footer(text="All bugs are reviewed by the dev team • 8-BIT TANKS")
    await post("🐛│bug-reports", e)

    # #💡│suggestions
    e = discord.Embed(title="💡  Suggestions", color=0xFFD700)
    e.add_field(name="📋 Template", inline=False, value=(
        "```\n"
        "Idea:     [short name]\n"
        "Details:  [full description]\n"
        "Why:      [why it would improve the game]\n"
        "```"
    ))
    e.add_field(name="👍 Voting", inline=False, value=(
        "React **👍** to support or **👎** to oppose.\n"
        "Top suggestions reviewed every week."
    ))
    e.set_footer(text="Use /suggest command for quick submission")
    await post("💡│suggestions", e)

    # #⭐│reviews
    e = discord.Embed(
        title="⭐  Game Reviews",
        description="Share your honest experience with **8-BIT TANKS**!",
        color=0xFFD700
    )
    e.add_field(name="📋 Template", inline=False, value=(
        "```\n"
        "Overall:    ⭐⭐⭐⭐⭐  (X/5)\n"
        "Gameplay:   [your thoughts]\n"
        "Graphics:   [your thoughts]\n"
        "Fun factor: [your thoughts]\n"
        "Would recommend: Yes / No\n"
        "```"
    ))
    e.set_footer(text="Be honest — it helps us improve!")
    await post("⭐│reviews", e)

    # #❓│questions
    e = discord.Embed(
        title="❓  Questions",
        description=(
            "Have a question about 8-BIT TANKS? Ask here!\n\n"
            "🇺🇦 Маєш питання? Питай тут!\n"
            "🇩🇪 Hast du Fragen? Frag hier!\n"
            "🇵🇱 Masz pytania? Pytaj tutaj!"
        ),
        color=0x5865F2
    )
    e.add_field(name="📌 Common questions", inline=False, value=(
        "**Q: How do I register?**\nA: Use `/register`\n\n"
        "**Q: How to create a private room?**\nA: Use `/room create`\n\n"
        "**Q: How to report a cheater?**\nA: Use `/report player @name`\n\n"
        "**Q: How to change language?**\nA: Use `/lang`"
    ))
    await post("❓│questions", e)

    # #🎨│fan-art
    e = discord.Embed(
        title="🎨  Fan Art & Creations",
        description="Share your 8-BIT TANKS fan art, pixel art, videos and more!",
        color=0xE040FB
    )
    e.add_field(name="✅ Allowed", inline=True, value=(
        "🎨 Fan art\n"
        "🖼️ Pixel art\n"
        "🎬 Gameplay clips\n"
        "🎵 Fan music"
    ))
    e.add_field(name="❌ Not allowed", inline=True, value=(
        "🚫 NSFW content\n"
        "🚫 Other game art\n"
        "🚫 AI-generated spam\n"
        "🚫 Stolen art"
    ))
    e.set_footer(text="Best creations may be featured in the game or social media!")
    await post("🎨│fan-art", e)

    print("\n✅ All channel content posted!\n")
