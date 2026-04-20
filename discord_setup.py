"""
🎮 8-BIT TANKS — Discord Server Setup v3
Запусти ОДИН РАЗ — усе налаштується автоматично.
Ролі: повна ієрархія EN + мовні флаги + категорії
"""

import discord
from discord.ext import commands
import asyncio, os
from dotenv import load_dotenv

load_dotenv()
TOKEN    = os.getenv("DISCORD_TOKEN", "YOUR_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!!", intents=intents)

# ══════════════════════════════════════════════════════════════════════════════
#  РОЛІ  (порядок: вищі спочатку — Discord показує згори донизу)
# ══════════════════════════════════════════════════════════════════════════════
# (назва, hex-color, is_admin, hoisted, mentionable)
ROLES = [
    # ── Команда ───────────────────────────────────────────────────────────────
    ("👑 Owner",           0xFF0000, True,  True,  True),
    ("🎮 Developer",       0xFF6B35, True,  True,  True),
    ("🎨 Artist",          0xFF69B4, False, True,  True),
    ("📹 Content Creator", 0xE040FB, False, True,  True),

    # ── Модерація ────────────────────────────────────────────────────────────
    ("👑 Admin",           0xFFD700, True,  True,  True),
    ("🛡️ Moderator",      0x5865F2, False, True,  True),

    # ── Тестери ──────────────────────────────────────────────────────────────
    ("🧪 Alpha Tester",    0xFF4500, False, True,  True),
    ("🔬 Beta Tester",     0xFFA500, False, True,  True),

    # ── Гравці ───────────────────────────────────────────────────────────────
    ("💎 Booster",         0xFF73FA, False, True,  True),   # хто бустить сервер
    ("🌟 VIP Player",      0xFFD700, False, True,  True),
    ("🏆 Champion",        0xFF4444, False, True,  True),
    ("🎖️ Veteran",        0xAAAAAA, False, False, True),
    ("🎯 Player",          0x57F287, False, False, True),   # базова, авто-видача

    # ── Мовні флаги (авто-видача при виборі мови) ────────────────────────────
    ("🇺🇦 Ukrainian",      0x005BBB, False, False, False),
    ("🇬🇧 English",        0x012169, False, False, False),
    ("🇩🇪 Deutsch",        0x000000, False, False, False),
    ("🇵🇱 Polski",         0xDC143C, False, False, False),
    ("🇫🇷 Français",       0x0055A4, False, False, False),

    # ── Внутрішні категорії (для доступу до каналів) ──────────────────────────
    ("lang-uk",            0x005BBB, False, False, False),
    ("lang-en",            0x012169, False, False, False),
    ("lang-de",            0x333333, False, False, False),
    ("lang-pl",            0xDC143C, False, False, False),
    ("lang-fr",            0x0055A4, False, False, False),
]

# ══════════════════════════════════════════════════════════════════════════════
#  СТРУКТУРА КАНАЛІВ
# ══════════════════════════════════════════════════════════════════════════════
# lang_only: тільки гравці з цією мовною роллю бачать категорію
CATEGORIES = [
    # ── Інформація ────────────────────────────────────────────────────────────
    {
        "name": "📢 INFORMATION",
        "public": True,
        "channels": [
            {"name": "📌│rules",         "type": "text", "topic": "Server rules / Правила — Read before playing!"},
            {"name": "📣│announcements", "type": "text", "topic": "Game updates & news"},
            {"name": "🗓️│events",       "type": "text", "topic": "Tournaments & events"},
            {"name": "🔔│changelog",     "type": "text", "topic": "Game version updates"},
            {"name": "🤝│partnerships",  "type": "text", "topic": "Partner servers & links"},
        ]
    },

    # ── Вхід ─────────────────────────────────────────────────────────────────
    {
        "name": "👋 START HERE",
        "public": True,
        "channels": [
            {"name": "👋│welcome",         "type": "text", "topic": "New here? Start here!"},
            {"name": "🌐│choose-language", "type": "text", "topic": "Pick your language & get roles"},
            {"name": "📋│register",        "type": "text", "topic": "Use /register to join the game"},
            {"name": "🤖│bot-commands",    "type": "text", "topic": "All bot commands: /help"},
        ]
    },

    # ── 🇺🇦 Українська ──────────────────────────────────────────────────────
    {
        "name": "🇺🇦 УКРАЇНСЬКА",
        "public": True,
        "channels": [
            {"name": "🇺🇦│загальний",   "type": "text", "topic": "Загальне спілкування • Автопереклад активний"},
            {"name": "🎮│ігровий-чат",  "type": "text", "topic": "Обговорення ігрового процесу"},
            {"name": "💡│пропозиції",   "type": "text", "topic": "Ідеї та побажання до гри"},
            {"name": "🏆│результати",   "type": "text", "topic": "Результати матчів"},
            {"name": "🎨│творчість",    "type": "text", "topic": "Арт, відео та фан-контент"},
        ]
    },

    # ── 🇬🇧 English ──────────────────────────────────────────────────────────
    {
        "name": "🇬🇧 ENGLISH",
        "public": True,
        "channels": [
            {"name": "🇬🇧│general",    "type": "text", "topic": "General chat • Auto-translate active"},
            {"name": "🎮│game-chat",   "type": "text", "topic": "Game discussion"},
            {"name": "💡│suggestions", "type": "text", "topic": "Ideas & feedback for the game"},
            {"name": "🏆│results",     "type": "text", "topic": "Match results"},
            {"name": "🎨│creative",    "type": "text", "topic": "Art, videos & fan content"},
        ]
    },

    # ── 🇩🇪 Deutsch ──────────────────────────────────────────────────────────
    {
        "name": "🇩🇪 DEUTSCH",
        "public": True,
        "channels": [
            {"name": "🇩🇪│allgemein",  "type": "text", "topic": "Allgemeiner Chat • Auto-Übersetzung aktiv"},
            {"name": "🎮│spiel-chat",  "type": "text", "topic": "Spiel-Diskussion"},
            {"name": "💡│vorschläge",  "type": "text", "topic": "Ideen für das Spiel"},
            {"name": "🏆│ergebnisse",  "type": "text", "topic": "Spielergebnisse"},
        ]
    },

    # ── 🇵🇱 Polski ───────────────────────────────────────────────────────────
    {
        "name": "🇵🇱 POLSKI",
        "public": True,
        "channels": [
            {"name": "🇵🇱│ogólny",   "type": "text", "topic": "Ogólny czat • Automatyczne tłumaczenie aktywne"},
            {"name": "🎮│czat-gry",  "type": "text", "topic": "Dyskusja o grze"},
            {"name": "💡│sugestie",  "type": "text", "topic": "Pomysły do gry"},
            {"name": "🏆│wyniki",    "type": "text", "topic": "Wyniki meczów"},
        ]
    },

    # ── 🇫🇷 Français ─────────────────────────────────────────────────────────
    {
        "name": "🇫🇷 FRANÇAIS",
        "public": True,
        "channels": [
            {"name": "🇫🇷│général",    "type": "text", "topic": "Chat général • Traduction automatique active"},
            {"name": "🎮│chat-jeu",    "type": "text", "topic": "Discussion de jeu"},
            {"name": "💡│suggestions", "type": "text", "topic": "Idées pour le jeu"},
            {"name": "🏆│résultats",   "type": "text", "topic": "Résultats des matchs"},
        ]
    },

    # ── Ігровий хаб ──────────────────────────────────────────────────────────
    {
        "name": "🎮 GAME HUB",
        "public": True,
        "channels": [
            {"name": "🎯│matchmaking",   "type": "text",  "topic": "Find opponents for battle"},
            {"name": "📊│leaderboard",   "type": "text",  "topic": "Top players • /top"},
            {"name": "🗺️│maps-tactics", "type": "text",  "topic": "Maps, tips & strategies"},
            {"name": "🐛│bug-reports",   "type": "text",  "topic": "Report bugs here"},
            {"name": "📸│screenshots",   "type": "text",  "topic": "Share your epic moments"},
            {"name": "🔊 Lobby",         "type": "voice"},
            {"name": "⚔️ Battle 1",     "type": "voice"},
            {"name": "⚔️ Battle 2",     "type": "voice"},
            {"name": "⚔️ Battle 3",     "type": "voice"},
            {"name": "🏆 Champions",    "type": "voice"},
        ]
    },

    # ── Приватні кімнати (авто-створюються ботом) ─────────────────────────────
    {
        "name": "🏠 PRIVATE ROOMS",
        "public": True,
        "channels": [
            {"name": "📖│room-guide", "type": "text",
             "topic": "How to create your own room: /room create"},
        ]
    },

    # ── Команда розробників ───────────────────────────────────────────────────
    {
        "name": "🛠️ DEV TEAM",
        "public": False,
        "channels": [
            {"name": "💬│dev-chat",      "type": "text", "topic": "Developer discussion"},
            {"name": "🎨│art-studio",    "type": "text", "topic": "Artist workspace & assets"},
            {"name": "📹│content-lab",   "type": "text", "topic": "Content creators workspace"},
            {"name": "📋│tasks",         "type": "text", "topic": "Dev tasks & issues"},
            {"name": "🔊 Dev Voice",     "type": "voice"},
        ]
    },

    # ── Адмін ────────────────────────────────────────────────────────────────
    {
        "name": "🔧 STAFF",
        "public": False,
        "channels": [
            {"name": "🔧│admin-chat",  "type": "text", "topic": "Admin/Mod discussion"},
            {"name": "📝│mod-log",     "type": "text", "topic": "Moderation log"},
            {"name": "🧪│test-zone",   "type": "text", "topic": "Bot & feature testing"},
            {"name": "🔊 Staff Voice", "type": "voice"},
        ]
    },
]

# ── Текст для #room-guide ─────────────────────────────────────────────────────
ROOM_GUIDE = """
# 🏠 Private Room Guide

**Create your room:** `/room create [name] [private]`
**Delete your room:** `/room close`
**View all rooms:**   `/room list`

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 📖 Room Controls (buttons in your room text channel)

| Button | Action |
|--------|--------|
| ✏️ Rename | Change room name |
| 🔒 Lock/Unlock | Toggle private mode |
| 👥 Set Limit | Max players (e.g. 4) |
| ➕ Invite Player | Allow a specific player |
| ➖ Kick from Room | Remove player |
| 🗑️ Delete Room | Close immediately |

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ⏳ Auto-Delete
Room automatically deletes **15 minutes** after everyone leaves.
You'll see a countdown message in your room.

## 🔒 Private Room
When locked — only invited players can join.
Invite with ➕ button or by `/room create private:True`
"""

# ── Правила на 5 мов ──────────────────────────────────────────────────────────
RULES_FIELDS = [
    ("🇺🇦 Українська", "1️⃣ Поважай усіх\n2️⃣ Ніякого читерства\n3️⃣ Спілкуйся у своєму каналі\n4️⃣ Без спаму\n5️⃣ Слухайся модераторів"),
    ("🇬🇧 English",    "1️⃣ Respect everyone\n2️⃣ No cheating\n3️⃣ Use your language channel\n4️⃣ No spam\n5️⃣ Follow moderators"),
    ("🇩🇪 Deutsch",    "1️⃣ Alle respektieren\n2️⃣ Kein Cheaten\n3️⃣ Sprachkanal benutzen\n4️⃣ Kein Spam\n5️⃣ Moderatoren folgen"),
    ("🇵🇱 Polski",     "1️⃣ Szanuj wszystkich\n2️⃣ Zakaz cheaterstwa\n3️⃣ Używaj własnego kanału\n4️⃣ Zakaz spamu\n5️⃣ Słuchaj moderatorów"),
    ("🇫🇷 Français",   "1️⃣ Respectez tous\n2️⃣ Pas de triche\n3️⃣ Canal de langue requis\n4️⃣ Pas de spam\n5️⃣ Suivez les modérateurs"),
]

# ══════════════════════════════════════════════════════════════════════════════
#  SETUP
# ══════════════════════════════════════════════════════════════════════════════
async def run_setup(guild: discord.Guild):
    print(f"\n🔧 Setting up: {guild.name}\n{'─'*40}")

    # 1. Видалити поточні канали/категорії
    print("🗑️  Removing existing channels...")
    for ch in guild.channels:
        try:
            await ch.delete(); await asyncio.sleep(0.35)
        except Exception: pass

    # 2. Ролі
    print("\n👥 Creating roles...")
    role_map: dict[str, discord.Role] = {}

    for name, color, is_admin, hoist, mentionable in ROLES:
        perms = discord.Permissions(administrator=True) if is_admin else discord.Permissions()
        r = await guild.create_role(
            name=name,
            color=discord.Color(color),
            permissions=perms,
            hoist=hoist,
            mentionable=mentionable
        )
        role_map[name] = r
        await asyncio.sleep(0.3)
        print(f"   ✅ {name}")

    # Визначити адмін-ролі для overwrites
    admin_roles = [role_map[n] for n in ("👑 Owner","🎮 Developer","👑 Admin","🛡️ Moderator") if n in role_map]
    dev_roles   = [role_map[n] for n in ("👑 Owner","🎮 Developer","🎨 Artist","📹 Content Creator") if n in role_map]

    # 3. Категорії + канали
    print("\n📁 Creating categories...")
    welcome_ch  = None
    room_guide_ch = None

    for cat_data in CATEGORIES:
        is_public = cat_data.get("public", True)
        is_dev    = cat_data["name"].startswith("🛠️")
        is_staff  = cat_data["name"].startswith("🔧")
        is_rooms  = cat_data["name"].startswith("🏠")

        # overwrites категорії
        ow: dict = {
            guild.default_role: discord.PermissionOverwrite(
                read_messages=is_public and not is_dev and not is_staff
            )
        }
        if is_dev or is_staff:
            restricted = dev_roles if is_dev else admin_roles
            for r in restricted:
                ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        for r in admin_roles:   # адміни завжди бачать
            ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        category = await guild.create_category(cat_data["name"], overwrites=ow)
        print(f"\n   📁 {cat_data['name']}")

        for ch in cat_data.get("channels", []):
            if ch["type"] == "voice":
                await guild.create_voice_channel(ch["name"], category=category, overwrites=ow)
            else:
                created = await guild.create_text_channel(
                    ch["name"], category=category,
                    topic=ch.get("topic",""), overwrites=ow
                )
                if "welcome" in ch["name"]:    welcome_ch     = created
                if "room-guide" in ch["name"]: room_guide_ch  = created
            await asyncio.sleep(0.3)
            print(f"      ✅ #{ch['name']}")

    # 4. Правила
    print("\n📜 Posting rules...")
    rules_ch = discord.utils.get(guild.text_channels, name="📌│rules")
    if rules_ch:
        embed = discord.Embed(title="📜 8-BIT TANKS — Rules / Правила", color=0xFFD700)
        for name, value in RULES_FIELDS:
            embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text="Violation = ban • 8-BIT TANKS")
        await rules_ch.send(embed=embed)

    # 5. Room guide
    if room_guide_ch:
        embed = discord.Embed(
            title="🏠 Private Room Guide",
            description=ROOM_GUIDE,
            color=0x5865F2
        )
        await room_guide_ch.send(embed=embed)

    print(f"\n{'─'*40}\n✅ Setup COMPLETE! Server is ready 🎮\n")

@bot.event
async def on_ready():
    print(f"🤖 Setup bot: {bot.user}")
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print(f"❌ Guild {GUILD_ID} not found! Check GUILD_ID in .env")
        await bot.close(); return
    await run_setup(guild)
    await bot.close()

if __name__ == "__main__":
    print("🚀 8-BIT TANKS Server Setup v3")
    bot.run(TOKEN)
