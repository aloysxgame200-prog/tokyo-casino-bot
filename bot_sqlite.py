import discord
from discord.ext import commands, tasks
import sqlite3
import os
import random
import asyncio
import pytz
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# ==========================================
#   TOKYO FR CASINO - Bot Principal
# ==========================================

TOKEN = os.environ.get("TOKEN")

SALON_AUTORISE = 1495152917890732172
OWNER_ID = 1022218025539223695
TIMEZONE = pytz.timezone("Europe/Paris")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
#   BASE DE DONNÉES SQLite
# ==========================================

# Sur Koyeb : monte un volume persistant et pointe DB_PATH dessus,
# ex: DB_PATH = "/data/casino.db"  (avec le volume monté sur /data)
DB_PATH = os.environ.get("DB_PATH", "casino.db")

def get_conn() -> sqlite3.Connection:
    """Retourne une connexion SQLite avec row_factory dict-like."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # écriture concurrente plus sûre
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """Crée la table si elle n'existe pas encore."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id             TEXT PRIMARY KEY,
                coins               INTEGER NOT NULL DEFAULT 500,
                tirages             INTEGER NOT NULL DEFAULT 3,
                tirages_stock       INTEGER NOT NULL DEFAULT 0,
                pillages            INTEGER NOT NULL DEFAULT 0,
                sabotages           INTEGER NOT NULL DEFAULT 0,
                contre_sabotages    INTEGER NOT NULL DEFAULT 0,
                pillages_total      INTEGER NOT NULL DEFAULT 0,
                sabotages_total     INTEGER NOT NULL DEFAULT 0,
                sabote_jusqu        TEXT,
                dernier_reset       TEXT,
                duels_gagnes        INTEGER NOT NULL DEFAULT 0,
                duels_perdus        INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()

def _row_to_dict(row) -> dict:
    return dict(row) if row else None

def get_user(user_id: str) -> dict:
    uid = str(user_id)
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
        if row is None:
            conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
        return _row_to_dict(row)

def save_user(user_id: str, data: dict):
    uid = str(user_id)
    # On construit le UPDATE dynamiquement à partir des clés du dict
    fields = {k: v for k, v in data.items() if k != "user_id"}
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [uid]
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {set_clause} WHERE user_id = ?", values)
        conn.commit()

def load_all_users() -> dict:
    """Retourne tous les utilisateurs sous forme {user_id: dict}."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users").fetchall()
        return {row["user_id"]: _row_to_dict(row) for row in rows}

def now_local() -> datetime:
    return datetime.now(TIMEZONE)

def est_sabote(user_data: dict) -> bool:
    ts = user_data.get("sabote_jusqu")
    if not ts:
        return False
    return now_local() < datetime.fromisoformat(ts)

def temps_restant_sabotage(user_data: dict) -> str:
    delta = datetime.fromisoformat(user_data["sabote_jusqu"]) - now_local()
    h = int(delta.total_seconds() // 3600)
    m = int((delta.total_seconds() % 3600) // 60)
    return f"{h}h{m:02d}min"

# ==========================================
#   VÉRIFICATION SALON
# ==========================================

async def check_salon(interaction: discord.Interaction) -> bool:
    if interaction.channel_id != SALON_AUTORISE:
        await interaction.response.send_message(
            f"❌ Ce bot fonctionne uniquement dans <#{SALON_AUTORISE}> !",
            ephemeral=True
        )
        return False
    return True

# ==========================================
#   RESET AUTOMATIQUE À MINUIT (Paris)
# ==========================================

@tasks.loop(hours=24)
async def reset_tirages_minuit():
    today = now_local().strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute("UPDATE users SET tirages = 3, dernier_reset = ?", (today,))
        conn.commit()
    print(f"✅ Tirages remis à 3 pour tous les joueurs ({today})")

@reset_tirages_minuit.before_loop
async def before_reset():
    await bot.wait_until_ready()
    now = now_local()
    minuit = TIMEZONE.localize(
        now.replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    )
    attente = (minuit - now).total_seconds()
    print(f"⏳ Prochain reset dans {int(attente // 3600)}h{int((attente % 3600) // 60)}min")
    await discord.utils.sleep_until(minuit)

# ==========================================
#   PROBABILITÉS DE TIRAGE
# ==========================================

TIRAGES_TABLE: list[tuple[str, float, str]] = [
    ("coins_tier1",  20.00, "coins"),
    ("coins_tier2",  15.00, "coins"),
    ("coins_tier3",  10.00, "coins"),
    ("coins_tier4",   5.00, "coins"),
    ("Rien",         18.00, "rien"),
    ("Pillage",       7.00, "pillage"),
    ("Tirages x5",    5.00, "tirages"),
    ("Sabotage",      3.00, "sabotage"),
]

COINS_PALIERS = {
    "coins_tier1": (0,    500),
    "coins_tier2": (501,  1000),
    "coins_tier3": (1001, 2000),
    "coins_tier4": (2001, 2500),
}

TOTAL_PROB: float = sum(prob for _, prob, _ in TIRAGES_TABLE)
_CUMUL: list[float] = []
_acc = 0.0
for _nom, _prob, _cat in TIRAGES_TABLE:
    _acc += _prob
    _CUMUL.append(_acc)

def faire_tirage() -> tuple[str, str]:
    r = random.uniform(0, TOTAL_PROB)
    for i, cumul in enumerate(_CUMUL):
        if r <= cumul:
            nom, _, cat = TIRAGES_TABLE[i]
            return cat, nom
    return "rien", "Rien"

def faire_tirage_duel() -> tuple[str, int]:
    cat, nom = faire_tirage()
    if cat == "coins":
        lo, hi = COINS_PALIERS[nom]
        montant = random.randint(lo, hi)
        return f"💰 {montant:,} coins", montant
    elif cat == "rien":
        return "😔 Rien", 0
    elif cat == "pillage":
        return "🗡️ Pillage (→ 0 coins)", 0
    elif cat == "tirages":
        return "🎲 Tirages bonus (→ 0 coins)", 0
    elif cat == "sabotage":
        return "🔥 Sabotage (→ 0 coins)", 0
    return "😔 Rien", 0

def appliquer_gain(user_data: dict, categorie: str, nom: str) -> tuple[dict, str, int]:
    if categorie == "coins":
        lo, hi = COINS_PALIERS.get(nom, (100, 500))
        montant = random.randint(lo, hi)
        user_data["coins"] = user_data.get("coins", 0) + montant
        msg = f"💰 **{montant:,} Tokyo Coins** tombent dans ta poche !"
        return user_data, msg, montant

    elif categorie == "rien":
        msg = "😔 **Rien** cette fois... La chance te sourira au prochain tirage !"
        return user_data, msg, 0

    elif categorie == "pillage":
        user_data["pillages"] = user_data.get("pillages", 0) + 1
        msg = (
            "🗡️ **Pillage** obtenu !\n"
            "└ Utilise `/tokyo_piller @quelquun` pour lui voler **tous ses tirages**."
        )
        return user_data, msg, 0

    elif categorie == "tirages":
        user_data["tirages_stock"] = user_data.get("tirages_stock", 0) + 5
        msg = "🎲 **5 tirages bonus** ajoutés à ton compteur !"
        return user_data, msg, 0

    elif categorie == "sabotage":
        user_data["sabotages"] = user_data.get("sabotages", 0) + 1
        msg = (
            "🔥 **Sabotage** obtenu !\n"
            "└ Utilise `/tokyo_saboter @quelquun` pour bloquer tous ses tirages pendant **24 heures**."
        )
        return user_data, msg, 0

    return user_data, "❓ Résultat inconnu.", 0

# ==========================================
#   ÉVÉNEMENTS
# ==========================================

@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    if not reset_tirages_minuit.is_running():
        reset_tirages_minuit.start()
    print(f"✅ {bot.user} est en ligne ! Tokyo FR Casino prêt.")
    await bot.change_presence(activity=discord.Game(name="🎰 /tokyo — Tokyo FR Casino"))

# ==========================================
#   /tokyo — MENU PRINCIPAL
# ==========================================

@bot.tree.command(name="tokyo", description="🎰 Ouvre le menu du Tokyo FR Casino")
async def tokyo(interaction: discord.Interaction):
    if not await check_salon(interaction):
        return

    user = get_user(str(interaction.user.id))
    tirages_dispo = user.get("tirages", 3) + user.get("tirages_stock", 0)

    embed = discord.Embed(title="🎰 Tokyo FR Casino", color=0xFF4444)
    embed.description = (
        f"Bienvenue au **Tokyo FR Casino** !\n"
        f"💰 **{user['coins']:,} coins**  •  🎲 **{tirages_dispo} tirages**\n\n"
        "**💰 Profil** — Tes stats\n"
        "**🎲 Tirage** — Tente ta chance !\n"
        "**🏪 Shop** — Dépense tes coins\n"
        "**⚔️ Duel** — Défie un membre\n"
        "**🏆 Classement** — Top 10 coins"
    )
    embed.set_footer(text="3 tirages gratuits par jour • Remis à zéro à minuit (heure de Paris)")
    await interaction.response.send_message(embed=embed, view=MenuPrincipal(), ephemeral=True)

# ==========================================
#   /tokyo_piller
# ==========================================

@bot.tree.command(name="tokyo_piller", description="🗡️ Vole tous les tirages d'un membre (nécessite un Pillage)")
async def piller(interaction: discord.Interaction, cible: discord.Member):
    if not await check_salon(interaction):
        return
    if cible.id == interaction.user.id:
        await interaction.response.send_message("❌ Tu ne peux pas te piller toi-même !", ephemeral=True)
        return
    if cible.bot:
        await interaction.response.send_message("❌ Tu ne peux pas piller un bot !", ephemeral=True)
        return

    voleur = get_user(str(interaction.user.id))
    victime = get_user(str(cible.id))

    if voleur.get("pillages", 0) <= 0:
        await interaction.response.send_message(
            "❌ Tu n'as pas de **Pillage** disponible !\n"
            "└ Gagne-en au tirage ou achète-en dans le Shop.",
            ephemeral=True
        )
        return

    tirages_voles = victime.get("tirages", 0) + victime.get("tirages_stock", 0)

    if tirages_voles <= 0:
        await interaction.response.send_message(
            f"❌ **{cible.display_name}** n'a aucun tirage à voler !", ephemeral=True
        )
        return

    victime["tirages"] = 0
    victime["tirages_stock"] = 0
    voleur["tirages_stock"] = voleur.get("tirages_stock", 0) + tirages_voles
    voleur["pillages"] -= 1
    voleur["pillages_total"] = voleur.get("pillages_total", 0) + 1

    save_user(str(interaction.user.id), voleur)
    save_user(str(cible.id), victime)

    embed = discord.Embed(title="🗡️ Pillage réussi !", color=0xE74C3C)
    embed.description = (
        f"Tu as volé **{tirages_voles} tirage(s)** à **{cible.display_name}** !\n\n"
        f"🎲 Tes tirages : **{voleur.get('tirages', 0) + voleur.get('tirages_stock', 0)}**\n"
        f"🗡️ Pillages restants : **{voleur['pillages']}**"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

    try:
        await cible.send(
            f"🗡️ **{interaction.user.display_name}** t'a pillé sur **Tokyo FR** !\n"
            f"Il t'a volé **{tirages_voles} tirage(s)**. Prépare ta revanche..."
        )
    except Exception:
        pass

# ==========================================
#   /tokyo_saboter
# ==========================================

@bot.tree.command(name="tokyo_saboter", description="🔥 Bloque les tirages d'un membre 24h (nécessite un Sabotage)")
async def saboter(interaction: discord.Interaction, cible: discord.Member):
    if not await check_salon(interaction):
        return
    if cible.id == interaction.user.id:
        await interaction.response.send_message("❌ Tu ne peux pas te saboter toi-même !", ephemeral=True)
        return
    if cible.bot:
        await interaction.response.send_message("❌ Tu ne peux pas saboter un bot !", ephemeral=True)
        return

    saboteur = get_user(str(interaction.user.id))
    victime = get_user(str(cible.id))

    if saboteur.get("sabotages", 0) <= 0:
        await interaction.response.send_message(
            "❌ Tu n'as pas de **Sabotage** disponible !\n"
            "└ Gagne-en au tirage ou achète-en dans le Shop.",
            ephemeral=True
        )
        return

    if est_sabote(victime):
        await interaction.response.send_message(
            f"❌ **{cible.display_name}** est déjà saboté ({temps_restant_sabotage(victime)} restants).",
            ephemeral=True
        )
        return

    victime["sabote_jusqu"] = (now_local() + timedelta(hours=24)).isoformat()
    saboteur["sabotages"] -= 1
    saboteur["sabotages_total"] = saboteur.get("sabotages_total", 0) + 1

    save_user(str(interaction.user.id), saboteur)
    save_user(str(cible.id), victime)

    embed = discord.Embed(title="🔥 Sabotage posé !", color=0xFF6B35)
    embed.description = (
        f"**{cible.display_name}** ne peut plus faire de tirage pendant **24 heures** !\n\n"
        f"🔥 Sabotages restants : **{saboteur['sabotages']}**"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

    try:
        await cible.send(
            f"🔥 **{interaction.user.display_name}** t'a saboté sur **Tokyo FR** !\n"
            f"Tes tirages sont bloqués pendant **24 heures**. Prépare ta revanche..."
        )
    except Exception:
        pass

# ==========================================
#   /tokyo_contresaboter
# ==========================================

@bot.tree.command(name="tokyo_contresaboter", description="🛡️ Annule ton sabotage actif (nécessite un Contre-Sabotage)")
async def contresaboter(interaction: discord.Interaction):
    if not await check_salon(interaction):
        return

    user_data = get_user(str(interaction.user.id))

    if user_data.get("contre_sabotages", 0) <= 0:
        await interaction.response.send_message(
            "❌ Tu n'as pas de **Contre-Sabotage** disponible !\n"
            "└ Achète-en dans le Shop.",
            ephemeral=True
        )
        return

    if not est_sabote(user_data):
        await interaction.response.send_message(
            "✅ Tu n'es pas saboté en ce moment, rien à annuler !", ephemeral=True
        )
        return

    user_data["sabote_jusqu"] = None
    user_data["contre_sabotages"] -= 1
    save_user(str(interaction.user.id), user_data)

    embed = discord.Embed(title="🛡️ Sabotage annulé !", color=0x2ECC71)
    embed.description = (
        "Ton sabotage a été **annulé** ! Tu peux à nouveau faire des tirages.\n\n"
        f"🛡️ Contre-Sabotages restants : **{user_data['contre_sabotages']}**"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
#   DUELS EN ATTENTE
# ==========================================

duel_en_attente: dict[int, dict] = {}

@bot.tree.command(name="tokyo_duel", description="⚔️ Défie un membre — mise 3 tirages chacun, le gagnant prend tout")
async def duel_cmd(interaction: discord.Interaction, cible: discord.Member):
    if not await check_salon(interaction):
        return
    if cible.id == interaction.user.id:
        await interaction.response.send_message("❌ Tu ne peux pas te défier toi-même !", ephemeral=True)
        return
    if cible.bot:
        await interaction.response.send_message("❌ Tu ne peux pas défier un bot !", ephemeral=True)
        return

    challenger = get_user(str(interaction.user.id))
    tirages_c = challenger.get("tirages", 0) + challenger.get("tirages_stock", 0)
    if tirages_c < 3:
        await interaction.response.send_message(
            f"❌ Tu n'as que **{tirages_c}** tirage(s), il t'en faut **3** pour un duel !",
            ephemeral=True
        )
        return

    try:
        dm_embed = discord.Embed(title="⚔️ Défi de Duel !", color=0xFF4444)
        dm_embed.description = (
            f"**{interaction.user.display_name}** te défie en duel sur **Tokyo FR Casino** !\n\n"
            f"🎲 Mise : **3 tirages** chacun\n"
            f"🏆 Le gagnant remporte les **6 tirages** au total\n\n"
            f"Va dans <#{SALON_AUTORISE}> et utilise `/tokyo_accepter_duel` pour accepter !"
        )
        await cible.send(embed=dm_embed)
    except Exception:
        pass

    duel_en_attente[interaction.user.id] = {
        "cible_id": cible.id,
        "expire": (now_local() + timedelta(minutes=5)).isoformat(),
    }

    embed = discord.Embed(title="⚔️ Défi envoyé !", color=0xFF8C00)
    embed.description = (
        f"Tu as défié **{cible.display_name}** !\n\n"
        f"🎲 Mise : **3 tirages** chacun\n"
        f"Il a **5 minutes** pour accepter avec `/tokyo_accepter_duel`."
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
#   /tokyo_accepter_duel
# ==========================================

@bot.tree.command(name="tokyo_accepter_duel", description="⚔️ Accepte le duel en attente contre toi")
async def accepter_duel(interaction: discord.Interaction):
    if not await check_salon(interaction):
        return

    challenger_id = None
    for cid, info in list(duel_en_attente.items()):
        if info["cible_id"] == interaction.user.id:
            if now_local() > datetime.fromisoformat(info["expire"]):
                del duel_en_attente[cid]
                await interaction.response.send_message(
                    "❌ Le défi a expiré (5 minutes dépassées).", ephemeral=True
                )
                return
            challenger_id = cid
            break

    if challenger_id is None:
        await interaction.response.send_message(
            "❌ Aucun défi en attente pour toi en ce moment.", ephemeral=True
        )
        return

    del duel_en_attente[challenger_id]

    cible_id = interaction.user.id
    challenger_data = get_user(str(challenger_id))
    cible_data = get_user(str(cible_id))

    tirages_c = challenger_data.get("tirages", 0) + challenger_data.get("tirages_stock", 0)
    tirages_ci = cible_data.get("tirages", 0) + cible_data.get("tirages_stock", 0)

    if tirages_c < 3:
        await interaction.response.send_message(
            "❌ Le challenger n'a plus assez de tirages pour le duel (il lui faut 3).", ephemeral=True
        )
        return
    if tirages_ci < 3:
        await interaction.response.send_message(
            f"❌ Tu n'as que **{tirages_ci}** tirage(s), il t'en faut **3** pour accepter !", ephemeral=True
        )
        return

    def deduire_tirages(data: dict, nb: int):
        stock = data.get("tirages_stock", 0)
        daily = data.get("tirages", 0)
        used_stock = min(nb, stock)
        used_daily = nb - used_stock
        data["tirages_stock"] = stock - used_stock
        data["tirages"] = max(0, daily - used_daily)
        return data

    challenger_data = deduire_tirages(challenger_data, 3)
    cible_data = deduire_tirages(cible_data, 3)
    save_user(str(challenger_id), challenger_data)
    save_user(str(cible_id), cible_data)

    await interaction.response.send_message(
        "⚔️ **Duel en cours...** Les tirages se déroulent, résultats dans quelques secondes !",
        ephemeral=True
    )

    async def effectuer_3_tirages():
        resultats_c, resultats_ci = [], []
        score_c = score_ci = 0
        for _ in range(3):
            label_c, val_c = faire_tirage_duel()
            label_ci, val_ci = faire_tirage_duel()
            resultats_c.append((label_c, val_c))
            resultats_ci.append((label_ci, val_ci))
            score_c += val_c
            score_ci += val_ci
            await asyncio.sleep(1.2)
        return resultats_c, resultats_ci, score_c, score_ci

    resultats_c, resultats_ci, score_c, score_ci = await effectuer_3_tirages()

    if score_c > score_ci:
        gagnant_id, perdant_id = challenger_id, cible_id
    elif score_ci > score_c:
        gagnant_id, perdant_id = cible_id, challenger_id
    else:
        gagnant_id = None

    if gagnant_id:
        gagnant_data = get_user(str(gagnant_id))
        perdant_data = get_user(str(perdant_id))
        gagnant_data["tirages_stock"] = gagnant_data.get("tirages_stock", 0) + 6
        gagnant_data["duels_gagnes"] = gagnant_data.get("duels_gagnes", 0) + 1
        perdant_data["duels_perdus"] = perdant_data.get("duels_perdus", 0) + 1
        save_user(str(gagnant_id), gagnant_data)
        save_user(str(perdant_id), perdant_data)
    else:
        # Égalité : remboursement
        for uid in (str(challenger_id), str(cible_id)):
            d = get_user(uid)
            d["tirages_stock"] = d.get("tirages_stock", 0) + 3
            save_user(uid, d)

    try:
        challenger_user = await bot.fetch_user(challenger_id)
        nom_c = challenger_user.display_name
    except Exception:
        nom_c = "Challenger"

    nom_ci = interaction.user.display_name

    lignes_c = "\n".join(f"Tirage {i+1} — `{l}`" for i, (l, v) in enumerate(resultats_c))
    lignes_ci = "\n".join(f"Tirage {i+1} — `{l}`" for i, (l, v) in enumerate(resultats_ci))

    if gagnant_id == challenger_id:
        conclusion = f"🏆 **{nom_c}** remporte le duel et gagne **6 tirages** !"
    elif gagnant_id == cible_id:
        conclusion = f"🏆 **{nom_ci}** remporte le duel et gagne **6 tirages** !"
    else:
        conclusion = "🤝 **Égalité !** Les mises sont remboursées (3 tirages chacun)."

    embed = discord.Embed(title="⚔️ Résultats du Duel", color=0xF1C40F)
    embed.add_field(
        name=f"🗡️ {nom_c}",
        value=f"{lignes_c}\n\n💰 **Total : {score_c:,} coins**",
        inline=True
    )
    embed.add_field(
        name=f"🛡️ {nom_ci}",
        value=f"{lignes_ci}\n\n💰 **Total : {score_ci:,} coins**",
        inline=True
    )
    embed.add_field(name="─" * 30, value=conclusion, inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)

    try:
        challenger_user = await bot.fetch_user(challenger_id)
        await challenger_user.send(embed=embed)
    except Exception:
        pass

# ==========================================
#   VUES
# ==========================================

class MenuPrincipal(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Profil", style=discord.ButtonStyle.secondary, emoji="💰")
    async def profil(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(str(interaction.user.id))
        tirages_dispo = user.get("tirages", 3) + user.get("tirages_stock", 0)

        embed = discord.Embed(title=f"💰 Profil de {interaction.user.display_name}", color=0x5865F2)
        embed.add_field(name="Tokyo Coins", value=f"**{user['coins']:,}** 💰", inline=True)
        embed.add_field(name="Tirages dispo", value=f"**{tirages_dispo}** 🎲", inline=True)
        embed.add_field(name="Pillages", value=f"**{user.get('pillages', 0)}** 🗡️", inline=True)
        embed.add_field(name="Sabotages", value=f"**{user.get('sabotages', 0)}** 🔥", inline=True)
        embed.add_field(name="Contre-Sabotages", value=f"**{user.get('contre_sabotages', 0)}** 🛡️", inline=True)
        embed.add_field(name="Duels", value=f"**{user.get('duels_gagnes', 0)}W / {user.get('duels_perdus', 0)}L** ⚔️", inline=True)

        if est_sabote(user):
            embed.add_field(
                name="⚠️ TU ES SABOTÉ",
                value=f"Tirages bloqués encore **{temps_restant_sabotage(user)}**.\n"
                      "Utilise `/tokyo_contresaboter` si tu as un Contre-Sabotage !",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Tirage", style=discord.ButtonStyle.primary, emoji="🎲")
    async def tirage(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(str(interaction.user.id))
        tirages_dispo = user.get("tirages", 3) + user.get("tirages_stock", 0)
        embed = discord.Embed(title="🎲 Tirages", color=0xFF8C00)
        embed.description = (
            "**Comment ça marche ?**\n"
            "Chaque tirage donne un résultat aléatoire :\n\n"
            "💰 **Coins** — 4 paliers possibles :\n"
            "└ Tier 1 : 0 – 500 coins\n"
            "└ Tier 2 : 501 – 1 000 coins\n"
            "└ Tier 3 : 1 001 – 2 000 coins\n"
            "└ Tier 4 : 2 001 – 2 500 coins\n\n"
            "😔 **Rien** — Pas de chance cette fois\n"
            "🗡️ **Pillage** — Vole tous les tirages d'un membre\n"
            "🎲 **Tirages x5** — Bonus de tirages\n"
            "🔥 **Sabotage** — Bloque quelqu'un 24h\n\n"
            f"Tu as **{tirages_dispo} tirage(s)** disponible(s).\n"
            "_(3 tirages gratuits par jour, remis à zéro à minuit)_"
        )
        await interaction.response.send_message(embed=embed, view=VueTirage(), ephemeral=True)

    @discord.ui.button(label="Shop", style=discord.ButtonStyle.success, emoji="🏪")
    async def shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(str(interaction.user.id))
        embed = discord.Embed(title="🏪 Boutique du Casino", color=0x2ECC71)
        embed.description = (
            f"Tu as **{user['coins']:,} Tokyo Coins** 💰\n\n"
            "🎲 **Tirages x10** — 30 000 coins\n"
            "└ Ajoute 10 tirages à ton stock\n\n"
            "🗡️ **Pillage x3** — 30 000 coins\n"
            "└ Vole **tous les tirages** d'un membre avec `/tokyo_piller`\n\n"
            "🔥 **Sabotage x1** — 15 000 coins\n"
            "└ Bloque les tirages de quelqu'un 24h avec `/tokyo_saboter`\n\n"
            "🛡️ **Contre-Sabotage x1** — 15 000 coins\n"
            "└ Annule immédiatement ton sabotage actif avec `/tokyo_contresaboter`\n\n"
            "💎 **Discord Nitro** — 2 000 000 coins\n"
            "└ Un vrai Discord Nitro offert par l'admin ! 🎉"
        )
        await interaction.response.send_message(embed=embed, view=VueShop(), ephemeral=True)

    @discord.ui.button(label="Duel", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def duel_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚔️ Duel", color=0xFF4444)
        embed.description = (
            "**Comment ça marche ?**\n\n"
            "1️⃣ Utilise `/tokyo_duel @membre` pour défier quelqu'un\n"
            "2️⃣ Il reçoit un DM et a **5 minutes** pour accepter avec `/tokyo_accepter_duel`\n"
            "3️⃣ Chacun fait **3 tirages** (coins uniquement comptabilisés)\n"
            "4️⃣ Celui avec le **plus de coins** gagne les **6 tirages** misés\n\n"
            "🎲 Mise : **3 tirages** par joueur\n"
            "🏆 Gain : **6 tirages** pour le vainqueur\n"
            "🤝 Égalité : remboursement des mises\n\n"
            "_Tu as besoin d'au moins 3 tirages pour défier !_"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Classement", style=discord.ButtonStyle.secondary, emoji="🏆")
    async def classement_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = load_all_users()
        if not db:
            await interaction.response.send_message("Aucun joueur enregistré.", ephemeral=True)
            return

        tri = sorted(db.items(), key=lambda x: x[1].get("coins", 0), reverse=True)[:10]
        embed = discord.Embed(title="🏆 Classement — Tokyo Coins", color=0xF1C40F)

        for idx, (uid, data) in enumerate(tri):
            user_obj = bot.get_user(int(uid))
            if user_obj is None:
                try:
                    user_obj = await bot.fetch_user(int(uid))
                    nom = user_obj.display_name
                except Exception:
                    nom = "Joueur inconnu"
            else:
                nom = user_obj.display_name

            medaille = ["🥇", "🥈", "🥉"][idx] if idx < 3 else f"**#{idx+1}**"
            tirages = data.get("tirages", 0) + data.get("tirages_stock", 0)
            embed.add_field(
                name=f"{medaille} {nom}",
                value=f"{data.get('coins', 0):,} coins • {tirages} tirages",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


class VueTirage(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    async def effectuer_tirages(self, interaction: discord.Interaction, nb: int):
        user_data = get_user(str(interaction.user.id))

        if est_sabote(user_data):
            await interaction.response.send_message(
                f"🔥 **Tu es saboté !** Tes tirages sont bloqués encore **{temps_restant_sabotage(user_data)}**.\n"
                "Utilise `/tokyo_contresaboter` si tu as un Contre-Sabotage !",
                ephemeral=True
            )
            return

        tirages_dispo = user_data.get("tirages", 3) + user_data.get("tirages_stock", 0)
        if tirages_dispo < nb:
            await interaction.response.send_message(
                f"❌ Tu n'as que **{tirages_dispo}** tirage(s) disponible(s) !\n"
                "└ Attends demain pour les tirages gratuits, ou achète-en dans le Shop.",
                ephemeral=True
            )
            return

        stock = user_data.get("tirages_stock", 0)
        daily = user_data.get("tirages", 3)
        used_stock = min(nb, stock)
        used_daily = nb - used_stock
        user_data["tirages_stock"] = stock - used_stock
        user_data["tirages"] = max(0, daily - used_daily)

        resultats = []
        for i in range(nb):
            categorie, nom = faire_tirage()
            user_data, msg, _ = appliquer_gain(user_data, categorie, nom)
            resultats.append(f"**Tirage {i+1}** — {msg}")

        save_user(str(interaction.user.id), user_data)

        tirages_restants = user_data.get("tirages", 0) + user_data.get("tirages_stock", 0)
        embed = discord.Embed(title=f"🎲 Résultats — {nb} tirage(s)", color=0xFF8C00)
        embed.description = "\n\n".join(resultats)
        embed.set_footer(text=f"Tirages restants : {tirages_restants} • Solde : {user_data['coins']:,} coins")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Tirage x1", style=discord.ButtonStyle.primary)
    async def t1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.effectuer_tirages(interaction, 1)

    @discord.ui.button(label="Tirage x5", style=discord.ButtonStyle.primary)
    async def t5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.effectuer_tirages(interaction, 5)

    @discord.ui.button(label="Tirage x10", style=discord.ButtonStyle.danger)
    async def t10(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.effectuer_tirages(interaction, 10)


class VueShop(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    async def acheter(self, interaction: discord.Interaction, prix: int, item: str, description: str):
        if prix < 0:
            await interaction.response.send_message("❌ Prix invalide.", ephemeral=True)
            return
        user_data = get_user(str(interaction.user.id))
        if user_data["coins"] < prix:
            manque = prix - user_data["coins"]
            await interaction.response.send_message(
                f"❌ Pas assez de coins ! Il te manque **{manque:,}** coins.\n"
                f"Ton solde : **{user_data['coins']:,}** / **{prix:,}** requis.",
                ephemeral=True
            )
            return
        user_data["coins"] -= prix
        if item == "tirages_x10":
            user_data["tirages_stock"] = user_data.get("tirages_stock", 0) + 10
        elif item == "pillage_x3":
            user_data["pillages"] = user_data.get("pillages", 0) + 3
        elif item == "sabotage_x1":
            user_data["sabotages"] = user_data.get("sabotages", 0) + 1
        elif item == "contresabotage_x1":
            user_data["contre_sabotages"] = user_data.get("contre_sabotages", 0) + 1
        elif item == "nitro":
            try:
                owner = await bot.fetch_user(OWNER_ID)
                await owner.send(
                    f"💎 **ACHAT NITRO !**\n"
                    f"**{interaction.user.display_name}** (`{interaction.user.id}`) vient d'acheter un **Discord Nitro** avec 2 000 000 coins !\n"
                    f"Envoie-lui son Nitro dès que possible. 🎉"
                )
            except Exception as e:
                print(f"Erreur MP owner : {e}")
        save_user(str(interaction.user.id), user_data)
        await interaction.response.send_message(
            f"✅ Achat réussi !\n{description}\n\n💰 Solde restant : **{user_data['coins']:,} coins**",
            ephemeral=True
        )

    @discord.ui.button(label="Tirages x10 — 30 000", style=discord.ButtonStyle.primary, emoji="🎲")
    async def buy_tirages(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.acheter(interaction, 30000, "tirages_x10", "🎲 **10 tirages** ajoutés à ton stock !")

    @discord.ui.button(label="Pillage x3 — 30 000", style=discord.ButtonStyle.danger, emoji="🗡️")
    async def buy_pillage(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.acheter(interaction, 30000, "pillage_x3", "🗡️ **3 Pillages** obtenus ! Utilise `/tokyo_piller @quelquun`.")

    @discord.ui.button(label="Sabotage x1 — 15 000", style=discord.ButtonStyle.secondary, emoji="🔥")
    async def buy_sabo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.acheter(interaction, 15000, "sabotage_x1", "🔥 **Sabotage** obtenu ! Utilise `/tokyo_saboter @quelquun`.")

    @discord.ui.button(label="Contre-Sabotage x1 — 15 000", style=discord.ButtonStyle.secondary, emoji="🛡️")
    async def buy_contresabo(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.acheter(interaction, 15000, "contresabotage_x1", "🛡️ **Contre-Sabotage** obtenu ! Utilise `/tokyo_contresaboter` si tu es saboté.")

    @discord.ui.button(label="Discord Nitro — 2 000 000", style=discord.ButtonStyle.danger, emoji="💎")
    async def buy_nitro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.acheter(interaction, 2000000, "nitro", "💎 **Discord Nitro** acheté ! L'admin va te l'envoyer très bientôt. 🎉")


# ==========================================
#   COMMANDES ADMIN
# ==========================================

@bot.tree.command(name="tokyo_admin_coins", description="[ADMIN] Donner des Tokyo Coins à un membre")
@discord.app_commands.checks.has_permissions(administrator=True)
async def admin_coins(interaction: discord.Interaction, membre: discord.Member, montant: int):
    if montant <= 0:
        await interaction.response.send_message("❌ Le montant doit être positif.", ephemeral=True)
        return
    user_data = get_user(str(membre.id))
    user_data["coins"] += montant
    save_user(str(membre.id), user_data)
    await interaction.response.send_message(
        f"✅ **{montant:,} coins** donnés à {membre.display_name}. Solde : **{user_data['coins']:,}**",
        ephemeral=True
    )

@bot.tree.command(name="tokyo_admin_tirages", description="[ADMIN] Donner des tirages à un membre")
@discord.app_commands.checks.has_permissions(administrator=True)
async def admin_tirages(interaction: discord.Interaction, membre: discord.Member, nb: int):
    if nb <= 0:
        await interaction.response.send_message("❌ Le nombre doit être positif.", ephemeral=True)
        return
    user_data = get_user(str(membre.id))
    user_data["tirages_stock"] = user_data.get("tirages_stock", 0) + nb
    save_user(str(membre.id), user_data)
    await interaction.response.send_message(
        f"✅ **{nb} tirages** donnés à {membre.display_name} !",
        ephemeral=True
    )

@bot.tree.command(name="tokyo_admin_reset_tirages", description="[ADMIN] Remet les tirages gratuits à 3 pour tout le monde")
@discord.app_commands.checks.has_permissions(administrator=True)
async def admin_reset(interaction: discord.Interaction):
    today = now_local().strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute("UPDATE users SET tirages = 3, dernier_reset = ?", (today,))
        conn.commit()
    await interaction.response.send_message("✅ Tirages gratuits remis à 3 pour tout le monde !", ephemeral=True)

@bot.tree.command(name="tokyo_classement", description="🏆 Voir le top 10 des Tokyo Coins (public)")
async def classement(interaction: discord.Interaction):
    db = load_all_users()
    if not db:
        await interaction.response.send_message("Aucun joueur enregistré.", ephemeral=True)
        return

    tri = sorted(db.items(), key=lambda x: x[1].get("coins", 0), reverse=True)[:10]
    embed = discord.Embed(title="🏆 Classement — Tokyo Coins", color=0xF1C40F)

    for idx, (uid, data) in enumerate(tri):
        user_obj = bot.get_user(int(uid))
        if user_obj is None:
            try:
                user_obj = await bot.fetch_user(int(uid))
                nom = user_obj.display_name
            except Exception:
                nom = "Joueur inconnu"
        else:
            nom = user_obj.display_name

        medaille = ["🥇", "🥈", "🥉"][idx] if idx < 3 else f"**#{idx+1}**"
        tirages = data.get("tirages", 0) + data.get("tirages_stock", 0)
        embed.add_field(
            name=f"{medaille} {nom}",
            value=f"{data.get('coins', 0):,} coins • {tirages} tirages",
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ==========================================
#   SERVEUR WEB POUR KOYEB / UPTIMEROBOT
# ==========================================

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot en ligne !")
    def log_message(self, format, *args):
        pass  # Silence les logs HTTP

def run_web():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

threading.Thread(target=run_web, daemon=True).start()

bot.run(TOKEN)
