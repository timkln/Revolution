# ⚡ Revolution — Notificateur IA

Une application web qui surveille vos sources d'information et vous **alerte sur ce qui est important** grâce à l'intelligence artificielle (OpenAI).

---

## Fonctionnalités

- 🤖 **Analyse IA** — chaque article/page est analysé par GPT pour évaluer son importance (score 1–10)
- 🔔 **Notifications en temps réel** — via WebSockets (Socket.IO), les alertes apparaissent instantanément
- 📡 **Sources multiples** — flux RSS et pages web
- 🏷️ **Mots-clés** — orientez l'IA vers vos sujets préférés
- ⏱️ **Vérification automatique** — intervalle configurable (15 min → 1 jour)
- 🌙 **Interface sombre moderne** — dashboard avec filtres, stats, badges non-lu

---

## Installation

### Prérequis

- Python 3.11+
- Une clé API OpenAI ([platform.openai.com](https://platform.openai.com/api-keys))

### Étapes

```bash
# 1. Cloner le dépôt
git clone https://github.com/timkln/Revolution.git
cd Revolution

# 2. Créer un environnement virtuel
python -m venv .venv
source .venv/bin/activate   # Windows : .venv\Scripts\activate

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer l'environnement
cp .env.example .env
# Éditez .env et renseignez votre OPENAI_API_KEY

# 5. Lancer l'application
python app.py
```

L'application est disponible sur **http://localhost:5000**

---

## Configuration

Copiez `.env.example` en `.env` et modifiez les valeurs :

| Variable | Description | Défaut |
|---|---|---|
| `OPENAI_API_KEY` | Clé API OpenAI (**obligatoire**) | — |
| `OPENAI_MODEL` | Modèle GPT à utiliser | `gpt-4o-mini` |
| `CHECK_INTERVAL_MINUTES` | Fréquence de vérification (minutes) | `30` |
| `SECRET_KEY` | Clé secrète Flask | `change-me-in-production` |

Vous pouvez aussi configurer la clé API directement depuis l'interface web (page **Paramètres**).

---

## Utilisation

1. **Ouvrez** http://localhost:5000
2. **Allez dans Paramètres** → entrez votre clé API OpenAI
3. **Ajoutez des sources** : un flux RSS (ex: `https://www.lemonde.fr/rss/une.xml`) ou une URL de page web
4. **Optionnel** : ajoutez des mots-clés pour orienter l'analyse
5. **Cliquez sur « Analyser maintenant »** ou attendez la vérification automatique
6. Les éléments importants apparaissent dans le **tableau de bord** avec leur score et un résumé IA

---

## Architecture

```
Revolution/
├── app.py              # Backend Flask + SocketIO + scheduler
├── requirements.txt    # Dépendances Python
├── .env.example        # Template de configuration
├── data.json           # Base de données locale (auto-créée)
├── templates/
│   ├── base.html       # Layout commun
│   ├── index.html      # Dashboard notifications
│   └── settings.html   # Paramètres & sources
└── static/
    ├── css/style.css   # Interface sombre moderne
    └── js/app.js       # Logique front-end (WebSocket, API)
```

## Licence

MIT
