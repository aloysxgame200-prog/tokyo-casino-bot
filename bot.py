# Tokyo FR Casino — Version Optimisée

## Optimisations ajoutées

### ✅ Reset automatique à 00h00

* Les tirages gratuits reviennent automatiquement tous les jours.
* Plus besoin de commande admin.
* Fonctionne proprement sur Render.

### ✅ Serveur HTTP Render

* Garde le bot actif sur Render.
* Évite l’extinction automatique.

### ✅ Optimisation des probabilités

* Les probabilités sont calculées une seule fois.
* Réduction du CPU.

### ✅ Fonction `verifier_succes()`

* Code plus propre.
* Plus facile à modifier.

### ✅ Sauvegarde JSON sécurisée

* Évite la corruption de `data.json`.
* Utilise un fichier temporaire avant remplacement.

### ✅ Anti-spam boutons

* Empêche les doubles clics rapides.
* Évite les abus.

### ✅ Optimisation du classement

* Utilise `bot.get_user()` avant `fetch_user()`.
* Réduction des appels API Discord.

---

```python
import discord
from discord.ext import commands, tasks
import json
import os
import random
from datetime import datetime, timedelta
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# ==========================================
#   SERVEUR HTTP — Render Keep Alive
# ==========================================

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

    def log_message(self, format, *args):
        pass


def run_http():
    HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


Thread(target=run_http, daemon=True).start()

# ==========================================
#   CONFIG
# ==========================================

TOKEN = os.environ.get("TOKEN")
SALON_AUTORISE = 1495152917890732172
OWNER_ID = 1022218025539223695
DB_FILE = "data.json"

# ==========================================
#   INTENTS
# ==========================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
#   ICÔNES
# ==========================================

ICONES = {
    "🌸 Sakura": ("commun", 15.00),
    "⭐ Étoile": ("commun", 12.00),
    "🌙 Lune": ("commun", 10.00),
    "🔥 Flamme": ("commun", 8.00),
    "💫 Étincelle": ("commun", 8.00),
    "🐉 Dragon": ("peu_commun", 4.00),
    "⚡ Foudre": ("peu_commun", 3.00),
    "🌊 Vague": ("peu_commun", 3.00),
    "🗡️ Katana": ("peu_commun", 2.50),
    "🦊 Renard": ("peu_commun", 2.00),
    "💎 Diamant": ("rare", 1.00),
    "🌺 Fleur de Cerisier": ("rare", 0.80),
    "🦋 Papillon Noir": ("rare", 0.60),
    "⚜️ Fleur de Lys": ("rare", 0.50),
    "🔮 Orbe": ("rare", 0.40),
    "👁️ Œil du Démon": ("epique", 0.20),
    "🌑 Éclipse": ("epique", 0.15),
    "💀 Crâne Maudit": ("epique", 0.10),
    "🧿 Œil Bleu": ("epique", 0.08),
    "👑 Couronne": ("legendaire", 0.05),
    "🌟 Étoile d'Or": ("legendaire", 0.03),
    "⚫ Trou Noir": ("legendaire", 0.02),
    "🔱 Trident": ("legendaire", 0.01),
}

RARETE_AFFICHAGE = {
    "commun": "⬜ Commun",
    "peu_commun": "🟦 Peu commun",
    "rare": "🟣 Rare",
    "epique": "🟡 Épique",
    "legendaire": "🔴 Légendaire",
}

# ==========================================
#   BASE DE DONNÉES
# ==========================================


def load_db() -> dict:
    if not os.path.exists(DB_FILE):
        return {}

    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)



def save_db(data: dict):
    temp_file = DB_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    os.replace(temp_file, DB_FILE)



def get_user(user_id: str) -> dict:
    db = load_db()
    uid = str(user_id)

    if uid not in db:
        db[uid] = {
            "coins": 500,
            "tirages": 3,
            "tirages_stock": 0,
            "icones": [],
            "succes": ["Bienvenue"],
            "pillages": 0,
            "sabotages": 0,
            "pillages_total": 0,
            "sabotages_total": 0,
            "sabote_jusqu": None,
        }

        save_db(db)

    return db[uid]



def save_user(user_id: str, data: dict):
    db = load_db()
    db[str(user_id)] = data
    save_db(db)

# ==========================================
#   SABOTAGE
# ==========================================


def est_sabote(user_data: dict) -> bool:
    if not user_data.get("sabote_jusqu"):
        return False

    return datetime.now() < datetime.fromisoformat(user_data["sabote_jusqu"])



def temps_restant_sabotage(user_data: dict) -> str:
    delta = datetime.fromisoformat(user_data["sabote_jusqu"]) - datetime.now()

    h = int(delta.total_seconds() // 3600)
    m = int((delta.total_seconds() % 3600) // 60)

    return f"{h}h{m:02d}min"

# ==========================================
#   TIRAGES
# ==========================================

TIRAGES_TABLE = (
    [(nom, prob, "icone") for nom, (rarete, prob) in ICONES.items()]
    + [
        ("Tokyo Coins", 20.00, "coins"),
        ("Rien", 15.00, "rien"),
        ("Pillage", 5.00, "pillage"),
        ("Tirages x5", 4.00, "tirages"),
        ("Sabotage", 2.00, "sabotage"),
    ]
)

TOTAL_PROB = sum(prob for _, prob, _ in TIRAGES_TABLE)



def faire_tirage():
    r = random.uniform(0, TOTAL_PROB)
    cumul = 0

    for nom, prob, categorie in TIRAGES_TABLE:
        cumul += prob

        if r <= cumul:
            return categorie, nom

    return "rien", "Rien"

# ==========================================
#   SUCCÈS
# ==========================================


def verifier_succes(user_data: dict):
    succes = user_data["succes"]
    coins = user_data["coins"]
    icones = user_data["icones"]

    if "Premier Tirage" not in succes:
        succes.append("Premier Tirage")

    if coins >= 10000 and "Riche" not in succes:
        succes.append("Riche")

    if coins >= 100000 and "Légende" not in succes:
        succes.append("Légende")

    if len(icones) >= 10 and "Collectionneur" not in succes:
        succes.append("Collectionneur")

    communes = [n for n, (r, _) in ICONES.items() if r == "commun"]

    if all(c in icones for c in communes):
        if "Grand Collectionneur" not in succes:
            succes.append("Grand Collectionneur")

    raretes_hautes = {"rare", "epique", "legendaire"}

    if any(ICONES[i][0] in raretes_hautes for i in icones if i in ICONES):
        if "Chanceux" not in succes:
            succes.append("Chanceux")

    if any(ICONES[i][0] == "legendaire" for i in icones if i in ICONES):
        if "Béni des Dieux" not in succes:
            succes.append("Béni des Dieux")

# ==========================================
#   RESET AUTO MINUIT
# ==========================================

@tasks.loop(hours=24)
async def reset_tirages_minuit():
    db = load_db()

    for uid in db:
        db[uid]["tirages"] = 3

    save_db(db)

    print("✅ Tirages remis à 3 pour tous les joueurs")


@reset_tirages_minuit.before_loop
async def before_reset():
    now = datetime.now()

    cible = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if now >= cible:
        cible += timedelta(days=1)

    await discord.utils.sleep_until(cible)

# ==========================================
#   CHECK SALON
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
#   ÉVÉNEMENTS
# ==========================================

@bot.event
async def on_ready():
    await bot.tree.sync()

    if not reset_tirages_minuit.is_running():
        reset_tirages_minuit.start()

    print(f"✅ {bot.user} est en ligne !")

    await bot.change_presence(
        activity=discord.Game(name="🎰 /tokyo — Tokyo FR Casino")
    )

# ==========================================
#   ANTI-SPAM VIEW
# ==========================================

class AntiSpamView(discord.ui.View):
    def __init__(self, timeout=120):
        super().__init__(timeout=timeout)
        self.utilisateurs = set()

    async def interaction_check(self, interaction: discord.Interaction):
        uid = interaction.user.id

        if uid in self.utilisateurs:
            await interaction.response.send_message(
                "⏳ Attends un peu avant de recliquer.",
                ephemeral=True
            )
            return False

        self.utilisateurs.add(uid)
        return True

# ==========================================
#   LE RESTE DU SCRIPT
# ==========================================

# Tu gardes ensuite :
# - toutes tes commandes
# - MenuPrincipal
# - VueTirage
# - VueShop
# - classement
# - pillage
# - sabotage
# etc.

# MAIS :
#
# Remplace :
# class MenuPrincipal(discord.ui.View)
#
# par :
# class MenuPrincipal(AntiSpamView)
#
# Pareil pour :
# - VueTirage
# - VueShop
#
# Ensuite dans effectuer_tirages() :
# ajoute :
# verifier_succes(user_data)
#
# avant :
# save_user(...)
#
# Enfin dans classement :
#
# Remplace :
# user = await bot.fetch_user(int(uid))
#
# par :
# user = bot.get_user(int(uid))
# if not user:
#     user = await bot.fetch_user(int(uid))

# ==========================================
#   LANCEMENT
# ==========================================

bot.run(TOKEN)
```
