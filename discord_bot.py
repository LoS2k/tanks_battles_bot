"""
🎮 8-BIT TANKS — Discord Bot v3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Ролі: повна ієрархія (EN назви)
✅ Авто-видача ролі Player + флаг країни після реєстрації
✅ Голосові кімнати: створення, налаштування, закриття, +15хв після виходу
✅ Автопереклад у мовних каналах
✅ Реєстрація гравців

pip install discord.py aiohttp python-dotenv
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, asyncio, aiohttp
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TOKEN    = os.getenv("DISCORD_TOKEN", "YOUR_TOKEN_HERE")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

# ─── МОВИ ──────────────────────────────────────────────────────────────────────
LANGS = {
    "uk": {"flag": "🇺🇦", "name": "Українська", "code": "uk-UA", "role": "🇺🇦 Ukrainian"},
    "en": {"flag": "🇬🇧", "name": "English",    "code": "en-GB", "role": "🇬🇧 English"},
    "de": {"flag": "🇩🇪", "name": "Deutsch",    "code": "de-DE", "role": "🇩🇪 Deutsch"},
    "pl": {"flag": "🇵🇱", "name": "Polski",     "code": "pl-PL", "role": "🇵🇱 Polski"},
    "fr": {"flag": "🇫🇷", "name": "Français",   "code": "fr-FR", "role": "🇫🇷 Français"},
}

# Канали де активний автопереклад
TRANSLATE_CHANNELS = [
    "загальний","general","allgemein","ogólny","général",
    "ігровий-чат","game-chat","spiel-chat","czat-gry","chat-jeu",
]

TRANSLATE_API = "https://api.mymemory.translated.net/get"

# ─── БД ────────────────────────────────────────────────────────────────────────
DB_FILE    = "players.json"
ROOMS_FILE = "rooms.json"

def load_db() -> dict:
    if not os.path.exists(DB_FILE): return {}
    with open(DB_FILE) as f: return json.load(f)

def save_db(d: dict):
    with open(DB_FILE, "w") as f: json.dump(d, f, indent=2, ensure_ascii=False)

def get_player(uid) -> dict | None:
    return load_db().get(str(uid))

def set_player(uid, data: dict):
    db = load_db(); db[str(uid)] = data; save_db(db)

def load_rooms() -> dict:
    if not os.path.exists(ROOMS_FILE): return {}
    with open(ROOMS_FILE) as f: return json.load(f)

def save_rooms(d: dict):
    with open(ROOMS_FILE, "w") as f: json.dump(d, f, indent=2, ensure_ascii=False)

def get_lang(user) -> str:
    p = get_player(str(user.id))
    return p.get("lang", "en") if p else "en"

# ─── ПЕРЕКЛАД ──────────────────────────────────────────────────────────────────
async def translate_text(text: str, target: str, source: str = "en") -> str | None:
    if len(text) > 400: text = text[:400] + "…"
    src = LANGS.get(source, {}).get("code", "en-GB")
    tgt = LANGS.get(target, {}).get("code", "en-GB")
    if src == tgt: return None
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(TRANSLATE_API,
                             params={"q": text, "langpair": f"{src}|{tgt}"},
                             timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status == 200:
                    d = await r.json()
                    if d.get("responseStatus") == 200:
                        t = d["responseData"]["translatedText"]
                        if t and t.lower() != text.lower():
                            return t
    except Exception:
        pass
    return None

# ─── БОТ ───────────────────────────────────────────────────────────────────────
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ─── ЗАДАЧА: ПРИБИРАННЯ КІМНАТ ─────────────────────────────────────────────────
@tasks.loop(seconds=30)
async def room_cleanup_task():
    """Кожні 30с перевіряє чи минуло 15хв після того як кімната спорожніла."""
    rooms = load_rooms()
    now   = datetime.now(timezone.utc).timestamp()
    to_delete = []

    for ch_id, info in rooms.items():
        empty_since = info.get("empty_since")
        if empty_since and (now - empty_since) >= 900:   # 15 хвилин
            to_delete.append(ch_id)

    for ch_id in to_delete:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            ch = guild.get_channel(int(ch_id))
            if ch:
                try:
                    await ch.delete(reason="Room empty for 15 minutes")
                    print(f"🗑️  Deleted empty room: {ch.name}")
                except Exception:
                    pass
        rooms.pop(ch_id, None)

    if to_delete:
        save_rooms(rooms)

@bot.event
async def on_ready():
    await tree.sync()
    room_cleanup_task.start()
    print(f"✅ 8-BIT TANKS Bot v3 online: {bot.user}")
    await bot.change_presence(activity=discord.Game("🎮 8-BIT TANKS | /register"))

# ─── ГОЛОСОВІ ПОДІЇ: відстеження порожніх кімнат ────────────────────────────────
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    rooms = load_rooms()

    # Якщо вийшов з кімнати
    if before.channel and str(before.channel.id) in rooms:
        ch = before.channel
        if len(ch.members) == 0:
            rooms[str(ch.id)]["empty_since"] = datetime.now(timezone.utc).timestamp()
            save_rooms(rooms)
            # Повідомлення в текстовий канал кімнати якщо є
            txt_id = rooms[str(ch.id)].get("text_channel_id")
            if txt_id:
                txt = member.guild.get_channel(int(txt_id))
                if txt:
                    await txt.send("⏳ Room is empty. It will be **deleted in 15 minutes** unless someone joins.")

    # Якщо хтось зайшов — скасувати таймер видалення
    if after.channel and str(after.channel.id) in rooms:
        if rooms[str(after.channel.id)].get("empty_since"):
            rooms[str(after.channel.id)]["empty_since"] = None
            save_rooms(rooms)

# ─── ВИБІР МОВИ ────────────────────────────────────────────────────────────────
class LangView(discord.ui.View):
    def __init__(self, member: discord.Member):
        super().__init__(timeout=300)
        self.member = member

    async def _set(self, interaction: discord.Interaction, lang: str):
        uid  = str(self.member.id)
        info = LANGS[lang]

        # Зберегти гравця
        player = get_player(uid) or {
            "wins": 0, "losses": 0, "kills": 0, "deaths": 0,
            "registered": datetime.now().isoformat()
        }
        player.update({"name": self.member.display_name, "lang": lang})
        set_player(uid, player)

        guild = interaction.guild

        # ── Зняти старі мовні ролі та флаги ──────────────────────────────────
        lang_role_names = [v["role"] for v in LANGS.values()]
        to_remove = [r for r in self.member.roles if r.name in lang_role_names]
        if to_remove:
            await self.member.remove_roles(*to_remove)

        # ── Дати нові ролі ────────────────────────────────────────────────────
        roles_to_add = []

        # 1. Флаг мови
        flag_role = discord.utils.get(guild.roles, name=info["role"])
        if flag_role:
            roles_to_add.append(flag_role)

        # 2. Роль Player (базова для всіх)
        player_role = discord.utils.get(guild.roles, name="🎯 Player")
        if player_role:
            roles_to_add.append(player_role)

        # 3. Мовна категорія lang-XX
        lang_cat_role = discord.utils.get(guild.roles, name=f"lang-{lang}")
        if lang_cat_role:
            roles_to_add.append(lang_cat_role)

        if roles_to_add:
            await self.member.add_roles(*roles_to_add, reason="Language selected")

        embed = discord.Embed(
            title="✅ Registered!",
            description=(
                f"**{info['flag']} {info['name']}** selected!\n\n"
                f"🟨 Basic Tank • Level 1\n"
                f"📌 Use `/stats` to see your profile\n"
                f"🏠 Use `/room create` to make a private room"
            ),
            color=0x00FF41
        )
        embed.set_footer(text="8-BIT TANKS • Welcome to the battlefield!")
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="🇺🇦 Українська", style=discord.ButtonStyle.primary,  row=0)
    async def btn_uk(self, i, _): await self._set(i, "uk")
    @discord.ui.button(label="🇬🇧 English",    style=discord.ButtonStyle.primary,  row=0)
    async def btn_en(self, i, _): await self._set(i, "en")
    @discord.ui.button(label="🇩🇪 Deutsch",    style=discord.ButtonStyle.secondary, row=1)
    async def btn_de(self, i, _): await self._set(i, "de")
    @discord.ui.button(label="🇵🇱 Polski",     style=discord.ButtonStyle.secondary, row=1)
    async def btn_pl(self, i, _): await self._set(i, "pl")
    @discord.ui.button(label="🇫🇷 Français",   style=discord.ButtonStyle.secondary, row=1)
    async def btn_fr(self, i, _): await self._set(i, "fr")

@bot.event
async def on_member_join(member: discord.Member):
    ch = discord.utils.get(member.guild.text_channels, name="👋│welcome")
    if not ch: return
    embed = discord.Embed(
        title="🎮 8-BIT TANKS",
        description=f"**{member.mention}** — choose your language to register!\nОберіть мову для реєстрації!",
        color=0xFFD700
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await ch.send(embed=embed, view=LangView(member))

# ─── КОМАНДА /register ─────────────────────────────────────────────────────────
@tree.command(name="register", description="Register / Зареєструватись")
async def cmd_register(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if get_player(uid):
        await interaction.response.send_message("⚠️ Already registered! Use `/lang` to change language.", ephemeral=True)
        return
    embed = discord.Embed(title="🎮 8-BIT TANKS — Choose Language", color=0xFFD700)
    await interaction.response.send_message(embed=embed, view=LangView(interaction.member), ephemeral=True)

# ─── КОМАНДА /lang ─────────────────────────────────────────────────────────────
@tree.command(name="lang", description="Change language / Змінити мову")
async def cmd_lang(interaction: discord.Interaction):
    embed = discord.Embed(title="🌐 Choose Language", color=0x5865F2)
    await interaction.response.send_message(embed=embed, view=LangView(interaction.member), ephemeral=True)

# ─── КОМАНДА /stats ────────────────────────────────────────────────────────────
@tree.command(name="stats", description="Player statistics / Статистика")
async def cmd_stats(interaction: discord.Interaction, player: discord.Member = None):
    target = player or interaction.user
    data   = get_player(str(target.id))
    if not data:
        await interaction.response.send_message("❌ Player not registered!", ephemeral=True)
        return
    w  = data.get("wins", 0); l = data.get("losses", 0)
    k  = data.get("kills", 0); d = data.get("deaths", 0)
    kd = round(k / max(d, 1), 2)
    wr = round(w / max(w+l, 1) * 100, 1)
    lang = data.get("lang", "en")
    flag = LANGS.get(lang, {}).get("flag", "🌐")

    embed = discord.Embed(title=f"📊 {target.display_name}", color=0xFFD700)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="🏆 Wins",    value=str(w),       inline=True)
    embed.add_field(name="💀 Losses",  value=str(l),       inline=True)
    embed.add_field(name="📊 Win%",    value=f"{wr}%",     inline=True)
    embed.add_field(name="🎯 Kills",   value=str(k),       inline=True)
    embed.add_field(name="☠️ Deaths",  value=str(d),       inline=True)
    embed.add_field(name="📈 K/D",     value=str(kd),      inline=True)
    embed.add_field(name="🌐 Lang",    value=f"{flag} {LANGS.get(lang,{}).get('name',lang)}", inline=True)
    embed.set_footer(text=f"Registered: {data.get('registered','')[:10]}")
    await interaction.response.send_message(embed=embed)

# ─── КОМАНДА /top ──────────────────────────────────────────────────────────────
@tree.command(name="top", description="Leaderboard / Таблиця лідерів")
async def cmd_top(interaction: discord.Interaction):
    db  = load_db()
    top = sorted(db.items(), key=lambda x: x[1].get("wins", 0), reverse=True)[:10]
    embed = discord.Embed(title="🏆 8-BIT TANKS — TOP 10", color=0xFFD700)
    medals = ["🥇","🥈","🥉"] + ["🎖️"]*7
    for i, (uid, d) in enumerate(top):
        kd   = round(d.get("kills",0)/max(d.get("deaths",1),1), 2)
        flag = LANGS.get(d.get("lang","en"), {}).get("flag", "🌐")
        embed.add_field(
            name=f"{medals[i]} #{i+1} {flag} {d.get('name','?')}",
            value=f"🏆 {d.get('wins',0)} wins  •  K/D {kd}",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# ─── КОМАНДА /win /loss (ADMIN) ────────────────────────────────────────────────
@tree.command(name="win", description="[ADMIN] Add win")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_win(interaction: discord.Interaction, player: discord.Member, kills: int = 1):
    d = get_player(str(player.id))
    if not d:
        await interaction.response.send_message("❌ Not registered!", ephemeral=True); return
    d["wins"]  = d.get("wins",0)  + 1
    d["kills"] = d.get("kills",0) + kills
    set_player(str(player.id), d)
    await interaction.response.send_message(f"✅ +1 Win, +{kills} Kills → **{player.display_name}** 🏆")

@tree.command(name="loss", description="[ADMIN] Add loss")
@app_commands.checks.has_permissions(administrator=True)
async def cmd_loss(interaction: discord.Interaction, player: discord.Member, deaths: int = 1):
    d = get_player(str(player.id))
    if not d:
        await interaction.response.send_message("❌ Not registered!", ephemeral=True); return
    d["losses"]  = d.get("losses",0)  + 1
    d["deaths"]  = d.get("deaths",0) + deaths
    set_player(str(player.id), d)
    await interaction.response.send_message(f"📝 +1 Loss, +{deaths} Deaths → **{player.display_name}**")

# ─── АВТОПЕРЕКЛАД ──────────────────────────────────────────────────────────────
def ch_lang(name: str) -> str | None:
    n = name.split("│")[-1].strip() if "│" in name else name
    for lang, channels in {
        "uk": ["загальний","ігровий-чат","результати","пропозиції"],
        "en": ["general","game-chat","results","suggestions"],
        "de": ["allgemein","spiel-chat","ergebnisse","vorschläge"],
        "pl": ["ogólny","czat-gry","wyniki","sugestie"],
        "fr": ["général","chat-jeu","résultats","suggestions"],
    }.items():
        if any(c in n for c in channels):
            return lang
    return None

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.content or message.content.startswith("/"): 
        await bot.process_commands(message); return

    target_lang = ch_lang(message.channel.name)
    if not target_lang:
        await bot.process_commands(message); return

    author_lang = get_lang(message.author)
    if author_lang == target_lang:
        await bot.process_commands(message); return

    translated = await translate_text(message.content, target_lang, author_lang)
    if translated:
        af = LANGS.get(author_lang, {}).get("flag", "🌐")
        tf = LANGS[target_lang]["flag"]
        embed = discord.Embed(description=f"**{translated}**", color=0x5865F2)
        embed.set_author(
            name=f"{af} {message.author.display_name} → {tf} Auto-translate",
            icon_url=message.author.display_avatar.url
        )
        embed.set_footer(text="MyMemory • /translate for manual translation")
        await message.channel.send(embed=embed)

    await bot.process_commands(message)

# ══════════════════════════════════════════════════════════════════════════════
#  СИСТЕМА ПРИВАТНИХ КІМНАТ
# ══════════════════════════════════════════════════════════════════════════════

room_group = app_commands.Group(name="room", description="Private room management / Управління кімнатою")

class RoomSettingsView(discord.ui.View):
    """Панель управління кімнатою — пишеться у текстовий канал кімнати."""
    def __init__(self, owner_id: int, voice_ch_id: int, text_ch_id: int):
        super().__init__(timeout=None)   # постійна
        self.owner_id   = owner_id
        self.voice_ch_id = voice_ch_id
        self.text_ch_id  = text_ch_id

    def _is_owner(self, i: discord.Interaction) -> bool:
        return i.user.id == self.owner_id

    # ── Перейменувати ───────────────────────────────────────────────────────
    @discord.ui.button(label="✏️ Rename", style=discord.ButtonStyle.secondary, row=0)
    async def btn_rename(self, interaction: discord.Interaction, _):
        if not self._is_owner(interaction):
            await interaction.response.send_message("❌ Only room owner can do this!", ephemeral=True); return
        await interaction.response.send_modal(RenameModal(self.voice_ch_id, self.text_ch_id))

    # ── Закрити / відкрити ──────────────────────────────────────────────────
    @discord.ui.button(label="🔒 Lock / Unlock", style=discord.ButtonStyle.secondary, row=0)
    async def btn_lock(self, interaction: discord.Interaction, _):
        if not self._is_owner(interaction):
            await interaction.response.send_message("❌ Only room owner can do this!", ephemeral=True); return
        ch = interaction.guild.get_channel(self.voice_ch_id)
        if not ch:
            await interaction.response.send_message("❌ Voice channel not found!", ephemeral=True); return
        ow = ch.overwrites_for(interaction.guild.default_role)
        currently_locked = ow.connect is False
        if currently_locked:
            ow.connect = None   # відкрити
            await ch.set_permissions(interaction.guild.default_role, overwrite=ow)
            await interaction.response.send_message("🔓 Room **unlocked** — anyone can join!", ephemeral=False)
        else:
            ow.connect = False  # закрити
            await ch.set_permissions(interaction.guild.default_role, overwrite=ow)
            await interaction.response.send_message("🔒 Room **locked** — only invited players can join!", ephemeral=False)

    # ── Обмежити кількість ──────────────────────────────────────────────────
    @discord.ui.button(label="👥 Set Limit", style=discord.ButtonStyle.secondary, row=0)
    async def btn_limit(self, interaction: discord.Interaction, _):
        if not self._is_owner(interaction):
            await interaction.response.send_message("❌ Only room owner!", ephemeral=True); return
        await interaction.response.send_modal(LimitModal(self.voice_ch_id))

    # ── Запросити гравця ────────────────────────────────────────────────────
    @discord.ui.button(label="➕ Invite Player", style=discord.ButtonStyle.success, row=1)
    async def btn_invite(self, interaction: discord.Interaction, _):
        if not self._is_owner(interaction):
            await interaction.response.send_message("❌ Only room owner!", ephemeral=True); return
        await interaction.response.send_message(
            "Mention the player you want to invite (e.g. `@PlayerName`).\nI'll wait 30 seconds.",
            ephemeral=True
        )

        def check(m):
            return (m.author.id == interaction.user.id
                    and m.channel.id == self.text_ch_id
                    and m.mentions)

        try:
            msg = await bot.wait_for("message", check=check, timeout=30)
            ch  = interaction.guild.get_channel(self.voice_ch_id)
            for target in msg.mentions:
                await ch.set_permissions(target, connect=True, view_channel=True)
            names = ", ".join(m.mention for m in msg.mentions)
            await msg.channel.send(f"✅ Invited: {names}")
        except asyncio.TimeoutError:
            pass

    # ── Видалити гравця ─────────────────────────────────────────────────────
    @discord.ui.button(label="➖ Kick from Room", style=discord.ButtonStyle.danger, row=1)
    async def btn_kick(self, interaction: discord.Interaction, _):
        if not self._is_owner(interaction):
            await interaction.response.send_message("❌ Only room owner!", ephemeral=True); return
        ch = interaction.guild.get_channel(self.voice_ch_id)
        if not ch or not ch.members:
            await interaction.response.send_message("❌ Nobody in voice!", ephemeral=True); return

        options = [
            discord.SelectOption(label=m.display_name, value=str(m.id))
            for m in ch.members if m.id != interaction.user.id
        ]
        if not options:
            await interaction.response.send_message("No other players in voice.", ephemeral=True); return

        view = KickSelectView(ch, options, interaction.user.id)
        await interaction.response.send_message("Select player to kick:", view=view, ephemeral=True)

    # ── Закрити кімнату ─────────────────────────────────────────────────────
    @discord.ui.button(label="🗑️ Delete Room", style=discord.ButtonStyle.danger, row=1)
    async def btn_delete(self, interaction: discord.Interaction, _):
        if not self._is_owner(interaction):
            await interaction.response.send_message("❌ Only room owner!", ephemeral=True); return

        rooms = load_rooms()
        vc = interaction.guild.get_channel(self.voice_ch_id)
        tc = interaction.guild.get_channel(self.text_ch_id)
        rooms.pop(str(self.voice_ch_id), None)
        save_rooms(rooms)
        await interaction.response.send_message("🗑️ Deleting room...")
        await asyncio.sleep(1)
        if vc: await vc.delete(reason="Owner deleted room")
        if tc: await tc.delete(reason="Owner deleted room")


class KickSelectView(discord.ui.View):
    def __init__(self, voice_ch, options, owner_id):
        super().__init__(timeout=30)
        self.voice_ch = voice_ch
        self.owner_id = owner_id
        sel = discord.ui.Select(placeholder="Choose player...", options=options)
        sel.callback = self.kick_callback
        self.add_item(sel)

    async def kick_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ Not your room!", ephemeral=True); return
        uid    = int(interaction.data["values"][0])
        member = interaction.guild.get_member(uid)
        if member and member.voice and member.voice.channel == self.voice_ch:
            await member.move_to(None)
        await self.voice_ch.set_permissions(member, overwrite=None)
        await interaction.response.send_message(f"✅ {member.mention} kicked from room.", ephemeral=False)


class RenameModal(discord.ui.Modal, title="Rename Room"):
    name = discord.ui.TextInput(label="New room name", max_length=40, placeholder="My Epic Tank Room")

    def __init__(self, voice_id, text_id):
        super().__init__()
        self.voice_id = voice_id
        self.text_id  = text_id

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.name.value.strip()
        vc = interaction.guild.get_channel(self.voice_id)
        tc = interaction.guild.get_channel(self.text_id)
        if vc: await vc.edit(name=f"🎮 {new_name}")
        if tc: await tc.edit(name=new_name.lower().replace(" ", "-"))
        await interaction.response.send_message(f"✅ Room renamed to **{new_name}**")


class LimitModal(discord.ui.Modal, title="Set Player Limit"):
    limit = discord.ui.TextInput(label="Max players (0 = unlimited)", max_length=2, placeholder="4")

    def __init__(self, voice_id):
        super().__init__()
        self.voice_id = voice_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n  = int(self.limit.value)
            vc = interaction.guild.get_channel(self.voice_id)
            if vc: await vc.edit(user_limit=n)
            txt = f"**{n}** players" if n > 0 else "**unlimited**"
            await interaction.response.send_message(f"✅ Limit set to {txt}")
        except ValueError:
            await interaction.response.send_message("❌ Enter a number!", ephemeral=True)


# ── /room create ───────────────────────────────────────────────────────────────
@room_group.command(name="create", description="Create a private room / Створити кімнату")
@app_commands.describe(name="Room name", private="Lock room (invite only)")
async def room_create(interaction: discord.Interaction, name: str = None, private: bool = False):
    await interaction.response.defer(ephemeral=True)

    guild   = interaction.guild
    member  = interaction.user
    room_name = name or f"{member.display_name}'s Room"

    # Знайти категорію для кімнат
    category = discord.utils.get(guild.categories, name="🏠 PRIVATE ROOMS")
    if not category:
        category = await guild.create_category("🏠 PRIVATE ROOMS")

    # Права
    ow = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=not private,
            connect=not private
        ),
        member: discord.PermissionOverwrite(
            view_channel=True, connect=True,
            manage_channels=True, move_members=True
        ),
    }
    # Модери/адміни завжди бачать
    for r in guild.roles:
        if r.permissions.administrator or r.name in ("🛡️ Moderator", "👑 Admin"):
            ow[r] = discord.PermissionOverwrite(view_channel=True, connect=True)

    # Голосовий канал
    vc = await guild.create_voice_channel(
        f"🎮 {room_name}",
        category=category,
        overwrites=ow,
        reason=f"Room created by {member.display_name}"
    )

    # Текстовий канал кімнати
    tc = await guild.create_text_channel(
        room_name.lower().replace(" ", "-"),
        category=category,
        overwrites=ow,
        topic=f"Room by {member.display_name} | Use buttons to manage",
        reason=f"Room text by {member.display_name}"
    )

    # Зберегти
    rooms = load_rooms()
    rooms[str(vc.id)] = {
        "owner_id":       member.id,
        "name":           room_name,
        "voice_id":       vc.id,
        "text_id":        tc.id,
        "private":        private,
        "empty_since":    None,
        "created":        datetime.now().isoformat(),
    }
    save_rooms(rooms)

    # ── Інструкція + кнопки управління ──────────────────────────────────────
    lock_icon = "🔒 Private" if private else "🔓 Public"
    embed = discord.Embed(
        title=f"🏠 Room: {room_name}",
        description=(
            f"**Owner:** {member.mention}\n"
            f"**Status:** {lock_icon}\n"
            f"**Voice:** {vc.mention}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "**📖 HOW TO USE YOUR ROOM:**\n\n"
            "✏️ **Rename** — change room name\n"
            "🔒 **Lock/Unlock** — toggle private mode\n"
            "👥 **Set Limit** — max players (e.g. 4)\n"
            "➕ **Invite** — allow a specific player\n"
            "➖ **Kick** — remove player from room\n"
            "🗑️ **Delete** — close room immediately\n\n"
            "⏳ Room auto-deletes **15 min** after everyone leaves.\n"
            "━━━━━━━━━━━━━━━━━━━━"
        ),
        color=0x5865F2
    )
    embed.set_footer(text="Only room owner can use the buttons below")

    view = RoomSettingsView(member.id, vc.id, tc.id)
    await tc.send(embed=embed, view=view)

    await interaction.followup.send(
        f"✅ Room **{room_name}** created!\n"
        f"🔊 Voice: {vc.mention}\n"
        f"💬 Text: {tc.mention}",
        ephemeral=True
    )

# ── /room list ─────────────────────────────────────────────────────────────────
@room_group.command(name="list", description="Show active rooms / Список кімнат")
async def room_list(interaction: discord.Interaction):
    rooms = load_rooms()
    if not rooms:
        await interaction.response.send_message("📭 No active rooms right now.", ephemeral=True); return
    embed = discord.Embed(title="🏠 Active Rooms", color=0x5865F2)
    for ch_id, info in rooms.items():
        vc = interaction.guild.get_channel(int(ch_id))
        if not vc: continue
        members = len(vc.members)
        lock    = "🔒" if info.get("private") else "🔓"
        embed.add_field(
            name=f"{lock} {info['name']}",
            value=f"👥 {members} online | Owner: <@{info['owner_id']}>",
            inline=False
        )
    await interaction.response.send_message(embed=embed)

# ── /room close ────────────────────────────────────────────────────────────────
@room_group.command(name="close", description="Delete your room / Видалити свою кімнату")
async def room_close(interaction: discord.Interaction):
    rooms = load_rooms()
    uid   = interaction.user.id
    found = None
    for ch_id, info in rooms.items():
        if info["owner_id"] == uid:
            found = (ch_id, info); break

    if not found:
        await interaction.response.send_message("❌ You don't have an active room.", ephemeral=True); return

    ch_id, info = found
    vc = interaction.guild.get_channel(int(ch_id))
    tc = interaction.guild.get_channel(int(info.get("text_id", 0)))

    rooms.pop(ch_id, None)
    save_rooms(rooms)
    await interaction.response.send_message("🗑️ Closing your room...", ephemeral=True)
    if vc: await vc.delete(reason="Owner closed room")
    if tc: await tc.delete(reason="Owner closed room")

tree.add_command(room_group)

# ─── ЗАПУСК ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 8-BIT TANKS Bot v3 starting...")
    bot.run(TOKEN)
