import discord
from discord.ext import commands
import json
import os
import random
from datetime import datetime, timedelta

# ==========================================
#   TOKYO FR CASINO - Bot Principal
#   Restriction : salon unique uniquement
# ==========================================

TOKEN = os.environ.get("TOKEN")

SALON_AUTORISE = 1495152917890732172  # Seul salon autorisé

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

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
#   ICÔNES À COLLECTIONNER
# ==========================================

ICONES = {
    "🌸 Sakura":        ("commun",     15.00),
    "⭐ Étoile":        ("commun",     12.00),
    "🌙 Lune":          ("commun",     10.00),
    "🔥 Flamme":        ("commun",      8.00),
    "💫 Étincelle":     ("commun",      8.00),
    "🐉 Dragon":        ("peu_commun",  4.00),
    "⚡ Foudre":        ("peu_commun",  3.00),
    "🌊 Vague":         ("peu_commun",  3.00),
    "🗡️ Katana":       ("peu_commun",  2.50),
    "🦊 Renard":        ("peu_commun",  2.00),
    "💎 Diamant":       ("rare",        1.00),
    "🌺 Fleur de Cerisier": ("rare",    0.80),
    "🦋 Papillon Noir": ("rare",        0.60),
    "⚜️ Fleur de Lys":  ("rare",        0.50),
    "🔮 Orbe":          ("rare",        0.40),
    "👁️ Œil du Démon":  ("epique",     0.20),
    "🌑 Éclipse":       ("epique",     0.15),
    "💀 Crâne Maudit":  ("epique",     0.10),
    "🧿 Œil Bleu":      ("epique",     0.08),
    "👑 Couronne":      ("legendaire",  0.05),
    "🌟 Étoile d'Or":   ("legendaire",  0.03),
    "⚫ Trou Noir":     ("legendaire",  0.02),
    "🔱 Trident":       ("legendaire",  0.01),
}

RARETE_AFFICHAGE = {
    "commun":     "⬜ Commun",
    "peu_commun": "🟦 Peu commun",
    "rare":       "🟣 Rare",
    "epique":     "🟡 Épique",
    "legendaire": "🔴 Légendaire",
}

# ==========================================
#   BASE DE DONNÉES
# ==========================================

DB_FILE = "data.json"

def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user(user_id: str):
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
            "xp_boosts": 0,
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
#   PROBABILITÉS DE TIRAGE
# ==========================================

TIRAGES_TABLE = (
    [(nom, prob, "icone") for nom, (rarete, prob) in ICONES.items()]
    + [
        ("Tokyo Coins",  20.00, "coins"),
        ("Rien",         15.00, "rien"),
        ("Pillage",       5.00, "pillage"),
        ("Tirages x5",    4.00, "tirages"),
        ("Sabotage",      2.00, "sabotage"),
        ("XP x50",        5.00, "xp"),
    ]
)

def faire_tirage():
    total = sum(prob for _, prob, _ in TIRAGES_TABLE)
    r = random.uniform(0, total)
    cumul = 0
    for nom, prob, categorie in TIRAGES_TABLE:
        cumul += prob
        if r <= cumul:
            return categorie, nom
    return "rien", "Rien"

def appliquer_gain(user_data: dict, categorie: str, nom: str):
    coins_gagnes = random.randint(100, 940)

    if categorie == "icone":
        rarete, _ = ICONES[nom]
        rarete_texte = RARETE_AFFICHAGE[rarete]
        if nom not in user_data["icones"]:
            user_data["icones"].append(nom)
            msg = (
                f"{nom} obtenu ! ✨\n"
                f"└ Rareté : **{rarete_texte}**\n"
                f"└ Nouvelle icône ajoutée à ta collection !"
            )
        else:
            msg = (
                f"{nom} — déjà dans ta collection !\n"
                f"└ Rareté : **{rarete_texte}**\n"
                f"└ Tu gagnes quand même des coins en bonus."
            )
    elif categorie == "coins":
        montant = random.randint(300, 1200)
        user_data["coins"] += montant
        coins_gagnes = 0
        msg = f"💰 **{montant} Tokyo Coins** tombent dans ta poche !"
    elif categorie == "rien":
        msg = "😔 **Rien** cette fois... La chance te sourira au prochain tirage !"
    elif categorie == "pillage":
        user_data["pillages"] = user_data.get("pillages", 0) + 1
        msg = (
            "🗡️ **Pillage** obtenu !\n"
            "└ Utilise `/tokyo_piller @quelquun` pour lui voler des Tokyo Coins.\n"
            "└ Tu voles entre 10% et 30% de ses coins."
        )
    elif categorie == "tirages":
        user_data["tirages_stock"] = user_data.get("tirages_stock", 0) + 5
        coins_gagnes = 0
        msg = "🎲 **5 tirages bonus** ajoutés à ton compteur !"
    elif categorie == "sabotage":
        user_data["sabotages"] = user_data.get("sabotages", 0) + 1
        msg = (
            "🔥 **Sabotage** obtenu !\n"
            "└ Utilise `/tokyo_saboter @quelquun` pour bloquer tous ses tirages pendant **24 heures**."
        )
    elif categorie == "xp":
        user_data["xp_boosts"] = user_data.get("xp_boosts", 0) + 1
        msg = "✨ **XP x50** obtenu !\n└ Gardé dans ton inventaire."
    else:
        msg = "❓ Résultat inconnu."

    if coins_gagnes > 0:
        user_data["coins"] = user_data.get("coins", 0) + coins_gagnes

    return user_data, msg, coins_gagnes

# ==========================================
#   ÉVÉNEMENTS
# ==========================================

@bot.event
async def on_ready():
    await bot.tree.sync()
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
    nb_icones = len(user.get("icones", []))

    embed = discord.Embed(title="🎰 Tokyo FR Casino", color=0xFF4444)
    embed.description = (
        f"Bienvenue au **Tokyo FR Casino** !\n"
        f"💰 **{user['coins']:,} coins**  •  🎲 **{tirages_dispo} tirages**  •  🖼️ **{nb_icones} icônes**\n\n"
        "**💰 Profil** — Tes stats et icônes\n"
        "**🎲 Tirage** — Tente ta chance !\n"
        "**🏪 Shop** — Dépense tes coins\n"
        "**🖼️ Collection** — Toutes tes icônes\n"
        "**🏆 Succès** — Tes objectifs"
    )
    embed.set_footer(text="3 tirages gratuits par jour • Remis à zéro à minuit")
    await interaction.response.send_message(embed=embed, view=MenuPrincipal(), ephemeral=False)

# ==========================================
#   /tokyo_piller
# ==========================================

@bot.tree.command(name="tokyo_piller", description="🗡️ Vole des coins à un membre (nécessite un Pillage)")
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
            "└ Gagne-en au tirage ou achète-en dans le /tokyo Shop.",
            ephemeral=True
        )
        return

    if victime["coins"] < 50:
        await interaction.response.send_message(
            f"❌ **{cible.display_name}** est trop pauvre, il n'y a rien à voler !",
            ephemeral=True
        )
        return

    pourcentage = random.uniform(0.10, 0.30)
    montant_vole = max(50, int(victime["coins"] * pourcentage))
    montant_vole = min(montant_vole, victime["coins"])

    voleur["coins"] += montant_vole
    voleur["pillages"] -= 1
    voleur["pillages_total"] = voleur.get("pillages_total", 0) + 1
    victime["coins"] -= montant_vole

    if voleur["pillages_total"] >= 3 and "Pillard" not in voleur["succes"]:
        voleur["succes"].append("Pillard")

    save_user(str(interaction.user.id), voleur)
    save_user(str(cible.id), victime)

    embed = discord.Embed(title="🗡️ Pillage réussi !", color=0xE74C3C)
    embed.description = (
        f"Tu as volé **{montant_vole:,} coins** à **{cible.display_name}** !\n\n"
        f"💰 Ton solde : **{voleur['coins']:,}**\n"
        f"🗡️ Pillages restants : **{voleur['pillages']}**"
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

    try:
        await cible.send(
            f"🗡️ **{interaction.user.display_name}** t'a pillé sur **Tokyo FR** !\n"
            f"Il t'a volé **{montant_vole:,} Tokyo Coins**. Prépare ta revanche avec un Pillage..."
        )
    except:
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
            "└ Gagne-en au tirage ou achète-en dans le /tokyo Shop.",
            ephemeral=True
        )
        return

    if est_sabote(victime):
        await interaction.response.send_message(
            f"❌ **{cible.display_name}** est déjà saboté ({temps_restant_sabotage(victime)} restants).",
            ephemeral=True
        )
        return

    victime["sabote_jusqu"] = (datetime.now() + timedelta(hours=24)).isoformat()
    saboteur["sabotages"] -= 1
    saboteur["sabotages_total"] = saboteur.get("sabotages_total", 0) + 1

    if saboteur["sabotages_total"] >= 3 and "Saboteur" not in saboteur["succes"]:
        saboteur["succes"].append("Saboteur")

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
    except:
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
        icones = user.get("icones", [])

        embed = discord.Embed(title=f"💰 Profil de {interaction.user.display_name}", color=0x5865F2)
        embed.add_field(name="Tokyo Coins", value=f"**{user['coins']:,}** 💰", inline=True)
        embed.add_field(name="Tirages dispo", value=f"**{tirages_dispo}** 🎲", inline=True)
        embed.add_field(name="Icônes", value=f"**{len(icones)}** collectionnées 🖼️", inline=True)
        embed.add_field(name="Pillages", value=f"**{user.get('pillages', 0)}** 🗡️", inline=True)
        embed.add_field(name="Sabotages", value=f"**{user.get('sabotages', 0)}** 🔥", inline=True)
        embed.add_field(name="XP Boosts", value=f"**{user.get('xp_boosts', 0)}** ✨", inline=True)

        if icones:
            apercu = "  ".join(icones[-10:])
            embed.add_field(name="🖼️ Dernières icônes", value=apercu, inline=False)

        if est_sabote(user):
            embed.add_field(name="⚠️ TU ES SABOTÉ", value=f"Tirages bloqués encore **{temps_restant_sabotage(user)}**.", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Tirage", style=discord.ButtonStyle.primary, emoji="🎲")
    async def tirage(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(str(interaction.user.id))
        tirages_dispo = user.get("tirages", 3) + user.get("tirages_stock", 0)
        embed = discord.Embed(title="🎲 Tirages", color=0xFF8C00)
        embed.description = (
            "**Comment ça marche ?**\n"
            "Chaque tirage te donne un résultat aléatoire :\n"
            "🖼️ Icônes à collectionner • 💰 Coins\n"
            "🗡️ Pillage • 🔥 Sabotage • 🎲 Tirages bonus • ✨ XP\n\n"
            "**Les icônes ont 5 niveaux de rareté :**\n"
            "⬜ Commun • 🟦 Peu commun • 🟣 Rare • 🟡 Épique • 🔴 Légendaire\n\n"
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
            "└ Ajoute 10 tirages à ton compteur\n\n"
            "🗡️ **Pillage x3** — 30 000 coins\n"
            "└ Pour voler des coins à d'autres membres avec `/tokyo_piller`\n\n"
            "✨ **XP x100** — 20 000 coins\n"
            "└ Donne 100 XP à un membre du serveur\n\n"
            "🔥 **Sabotage x1** — 15 000 coins\n"
            "└ Bloque les tirages de quelqu'un 24h avec `/tokyo_saboter`\n\n"
            "👑 **Souverain des Ombres** — 2 000 000 coins\n"
            "└ Titre légendaire ultra-rare affiché dans ton profil"
        )
        await interaction.response.send_message(embed=embed, view=VueShop(), ephemeral=True)

    @discord.ui.button(label="Collection", style=discord.ButtonStyle.secondary, emoji="🖼️")
    async def collection(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(str(interaction.user.id))
        icones = user.get("icones", [])
        embed = discord.Embed(title="🖼️ Ta Collection d'Icônes", color=0x9B59B6)

        if not icones:
            embed.description = "Tu n'as encore aucune icône !\nFais des tirages pour en collecter."
        else:
            par_rarete = {"legendaire": [], "epique": [], "rare": [], "peu_commun": [], "commun": []}
            for icone in icones:
                if icone in ICONES:
                    rarete, _ = ICONES[icone]
                    par_rarete[rarete].append(icone)
            for rarete, liste in par_rarete.items():
                if liste:
                    rarete_texte = RARETE_AFFICHAGE[rarete]
                    embed.add_field(
                        name=f"{rarete_texte} ({len(liste)})",
                        value="  ".join(liste),
                        inline=False
                    )
            embed.set_footer(text=f"Total : {len(icones)} icône(s) collectionnée(s)")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Succès", style=discord.ButtonStyle.secondary, emoji="🏆")
    async def succes(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = get_user(str(interaction.user.id))
        embed = discord.Embed(title="🏆 Succès", color=0xF1C40F)
        embed.description = "✅ = débloqué  •  🔒 = pas encore obtenu"
        succes_liste = {
            "Bienvenue":            "Rejoindre le Tokyo FR Casino",
            "Premier Tirage":       "Faire ton premier tirage",
            "Riche":                "Accumuler 10 000 Tokyo Coins",
            "Collectionneur":       "Obtenir 10 icônes différentes",
            "Grand Collectionneur": "Obtenir toutes les icônes communes",
            "Chanceux":             "Obtenir une icône Rare ou mieux",
            "Béni des Dieux":       "Obtenir une icône Légendaire",
            "Pillard":              "Piller 3 membres",
            "Saboteur":             "Saboter 3 membres",
            "Légende":              "Atteindre 100 000 Tokyo Coins",
        }
        for nom, desc in succes_liste.items():
            etat = "✅" if nom in user["succes"] else "🔒"
            embed.add_field(name=f"{etat} {nom}", value=desc, inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class VueTirage(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    async def effectuer_tirages(self, interaction: discord.Interaction, nb: int):
        user_data = get_user(str(interaction.user.id))

        if est_sabote(user_data):
            await interaction.response.send_message(
                f"🔥 **Tu es saboté !** Tes tirages sont bloqués encore **{temps_restant_sabotage(user_data)}**.\n"
                "Quelqu'un t'a mis un Sabotage... Prépare ta revanche !",
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
        for _ in range(nb):
            if stock > 0:
                stock -= 1
            else:
                daily -= 1
        user_data["tirages_stock"] = max(0, stock)
        user_data["tirages"] = max(0, daily)

        resultats = []
        coins_total = 0
        for i in range(nb):
            categorie, nom = faire_tirage()
            user_data, msg, coins = appliquer_gain(user_data, categorie, nom)
            coins_total += coins
            resultats.append(f"**Tirage {i+1}** — {msg}")

        icones = user_data.get("icones", [])
        if "Premier Tirage" not in user_data["succes"]:
            user_data["succes"].append("Premier Tirage")
        if user_data["coins"] >= 10000 and "Riche" not in user_data["succes"]:
            user_data["succes"].append("Riche")
        if user_data["coins"] >= 100000 and "Légende" not in user_data["succes"]:
            user_data["succes"].append("Légende")
        if len(icones) >= 10 and "Collectionneur" not in user_data["succes"]:
            user_data["succes"].append("Collectionneur")
        communes = [n for n, (r, _) in ICONES.items() if r == "commun"]
        if all(c in icones for c in communes) and "Grand Collectionneur" not in user_data["succes"]:
            user_data["succes"].append("Grand Collectionneur")
        raretes_hautes = {"rare", "epique", "legendaire"}
        if any(ICONES[i][0] in raretes_hautes for i in icones if i in ICONES) and "Chanceux" not in user_data["succes"]:
            user_data["succes"].append("Chanceux")
        if any(ICONES[i][0] == "legendaire" for i in icones if i in ICONES) and "Béni des Dieux" not in user_data["succes"]:
            user_data["succes"].append("Béni des Dieux")

        save_user(str(interaction.user.id), user_data)

        tirages_restants = user_data.get("tirages", 0) + user_data.get("tirages_stock", 0)
        embed = discord.Embed(title=f"🎲 Résultats — {nb} tirage(s)", color=0xFF8C00)
        embed.description = "\n\n".join(resultats)
        embed.set_footer(text=f"Tirages restants : {tirages_restants} • Solde : {user_data['coins']:,} coins")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Tirage x1", style=discord.ButtonStyle.primary)
    async def t1(self, i, b): await self.effectuer_tirages(i, 1)

    @discord.ui.button(label="Tirage x5", style=discord.ButtonStyle.primary)
    async def t5(self, i, b): await self.effectuer_tirages(i, 5)

    @discord.ui.button(label="Tirage x10", style=discord.ButtonStyle.danger)
    async def t10(self, i, b): await self.effectuer_tirages(i, 10)


class VueShop(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    async def acheter(self, interaction: discord.Interaction, prix: int, item: str, description: str):
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
        elif item == "xp_x100":
            user_data["xp_boosts"] = user_data.get("xp_boosts", 0) + 1
        elif item == "sabotage_x1":
            user_data["sabotages"] = user_data.get("sabotages", 0) + 1
        elif item == "souverain":
            if "Souverain des Ombres" not in user_data["succes"]:
                user_data["succes"].append("Souverain des Ombres")
        save_user(str(interaction.user.id), user_data)
        await interaction.response.send_message(
            f"✅ Achat réussi !\n{description}\n\n💰 Solde restant : **{user_data['coins']:,} coins**",
            ephemeral=True
        )

    @discord.ui.button(label="Tirages x10 — 30 000", style=discord.ButtonStyle.primary, emoji="🎲")
    async def buy_tirages(self, i, b):
        await self.acheter(i, 30000, "tirages_x10", "🎲 **10 tirages** ajoutés à ton compteur !")

    @discord.ui.button(label="Pillage x3 — 30 000", style=discord.ButtonStyle.danger, emoji="🗡️")
    async def buy_pillage(self, i, b):
        await self.acheter(i, 30000, "pillage_x3", "🗡️ **3 Pillages** obtenus ! Utilise `/tokyo_piller @quelquun`.")

    @discord.ui.button(label="XP x100 — 20 000", style=discord.ButtonStyle.success, emoji="✨")
    async def buy_xp(self, i, b):
        await self.acheter(i, 20000, "xp_x100", "✨ **XP x100** obtenu !")

    @discord.ui.button(label="Sabotage x1 — 15 000", style=discord.ButtonStyle.secondary, emoji="🔥")
    async def buy_sabo(self, i, b):
        await self.acheter(i, 15000, "sabotage_x1", "🔥 **Sabotage** obtenu ! Utilise `/tokyo_saboter @quelquun`.")

    @discord.ui.button(label="Souverain des Ombres — 2 000 000", style=discord.ButtonStyle.danger, emoji="👑")
    async def buy_souverain(self, i, b):
        await self.acheter(i, 2000000, "souverain", "👑 **Souverain des Ombres** obtenu ! Titre légendaire !")


# ==========================================
#   COMMANDES ADMIN
# ==========================================

@bot.tree.command(name="tokyo_admin_coins", description="[ADMIN] Donner des Tokyo Coins à un membre")
@discord.app_commands.checks.has_permissions(administrator=True)
async def admin_coins(interaction: discord.Interaction, membre: discord.Member, montant: int):
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
    db = load_db()
    for uid in db:
        db[uid]["tirages"] = 3
    save_db(db)
    await interaction.response.send_message("✅ Tirages gratuits remis à 3 pour tout le monde !", ephemeral=True)

@bot.tree.command(name="tokyo_classement", description="🏆 Voir le top 10 des Tokyo Coins")
async def classement(interaction: discord.Interaction):
    db = load_db()
    if not db:
        await interaction.response.send_message("Aucun joueur enregistré.", ephemeral=True)
        return
    tri = sorted(db.items(), key=lambda x: x[1].get("coins", 0), reverse=True)[:10]
    embed = discord.Embed(title="🏆 Classement — Tokyo Coins", color=0xF1C40F)
    for idx, (uid, data) in enumerate(tri):
        try:
            user = await bot.fetch_user(int(uid))
            nom = user.display_name
        except:
            nom = "Joueur inconnu"
        medaille = ["🥇", "🥈", "🥉"][idx] if idx < 3 else f"**#{idx+1}**"
        icones_nb = len(data.get("icones", []))
        embed.add_field(
            name=f"{medaille} {nom}",
            value=f"{data.get('coins', 0):,} coins • {icones_nb} icônes",
            inline=False
        )
    await interaction.response.send_message(embed=embed)


bot.run(TOKEN)
