# CRT Bot — Candle Range Trading (Forex + Indices synthétiques)

Bot Python qui applique la méthodologie **Candle Range Trading (CRT)** :

1. Range de référence = haut/bas de la dernière bougie **D1** et **H4** clôturée.
2. Détection d'un **sweep de liquidité** (fausse cassure) de ce range, en parallèle sur
   **deux timeframes de confirmation** : M5 (⚡ rapide, plus de bruit) et M15 (🐢 filtré,
   signal généralement plus fiable) — chacun génère ses propres alertes, étiquetées
   séparément dans le message Telegram.
3. Confirmation avancée : **cassure de structure** + **Fair Value Gap** et/ou **Order Block**
   (FVG **et** OB exigés ensemble sur M5, pour filtrer davantage le bruit — voir
   `STRICT_CONFIRMATION_TIMEFRAMES` dans `config.py`).
4. Envoi d'une alerte **Telegram** dès qu'un setup confirmé est détecté.

Le bot tourne gratuitement via **GitHub Actions** (cron toutes les 5 minutes — le minimum
fiable sur GitHub Actions ; en dessous, les exécutions peuvent être retardées voire
ignorées par GitHub en cas de forte charge), sans serveur à héberger.

> ⚠️ Ceci est un outil d'aide à la décision basé sur une implémentation simplifiée
> des concepts ICT / Smart Money Concepts. Ce n'est pas un conseil financier et la
> logique doit être backtestée/affinée avant tout usage en argent réel.

## 1. Créer le bot Telegram

1. Sur Telegram, parle à **@BotFather** → `/newbot` → suis les instructions.
2. Récupère le **token** fourni (ex : `123456:ABC-DEF...`).
3. Envoie un message à ton bot, puis va sur :
   `https://api.telegram.org/bot<TON_TOKEN>/getUpdates`
   pour récupérer ton **chat_id** dans la réponse JSON.

## 2. Obtenir un app_id Deriv (optionnel)

L'app_id par défaut (`1089`, test public) fonctionne pour démarrer.
Pour un usage sérieux, crée ta propre app sur https://api.deriv.com pour obtenir ton propre `app_id`.

## 3. Déployer sur GitHub

1. Crée un nouveau repo GitHub (public ou privé).
2. Pousse le contenu de ce dossier dedans :
   ```bash
   git init
   git remote add origin https://github.com/<ton-user>/<ton-repo>.git
   git add .
   git commit -m "Initial commit: CRT bot"
   git branch -M main
   git push -u origin main
   ```
3. Dans **Settings → Secrets and variables → Actions**, ajoute ces secrets :
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `DERIV_APP_ID` (optionnel, sinon `1089` par défaut)
4. Le workflow `.github/workflows/crt-scan.yml` se lance automatiquement toutes les 15 minutes.
   Tu peux aussi le lancer manuellement depuis l'onglet **Actions** (`workflow_dispatch`).

## 4. Personnaliser

- **Symboles** : liste `SYMBOLS` dans `config.py` — actuellement forex majeurs, or (`frxXAUUSD`),
  cryptos (`cryBTCUSD`, `cryETHUSD`, `cryLTCUSD`, `cryXRPUSD`), Volatility Index classiques
  (`R_10`...`R_100`) et 1 seconde (`1HZ10V`...`1HZ100V`), Step Index (`stpRNG`), Boom/Crash 500/1000.
- **Fréquence de scan** : modifier le `cron` dans le workflow.
- **Timeframes de confirmation** : liste `CONFIRMATION_TIMEFRAMES` dans `config.py`
  (actuellement `["M5", "M15"]`, chacun tourne indépendamment) — ajouter ou retirer
  des TF ici pour changer les pistes actives.
- **Sensibilité de la confirmation** : ajuster `left`/`right` (détection des swing points)
  et `window` (FVG/Order Block) dans `strategy.py`.
- **Une seule alerte par range et par piste** : le premier setup confirmé (haussier ou
  baissier) sur un range D1/H4 donné verrouille ce range **pour ce timeframe de
  confirmation** — pas de nouvelle alerte tant qu'une nouvelle bougie D1/H4 ne s'est
  pas formée. Les pistes M5 et M15 restent indépendantes l'une de l'autre.

## 5. Tester en local

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python main.py
```

## Structure du projet

```
crt-bot/
├── main.py              # Orchestration (récupération groupée → analyse → notification)
├── config.py             # Symboles, timeframes, secrets (via variables d'environnement)
├── deriv_client.py        # Récupération des bougies via l'API Deriv (1 seule connexion WebSocket réutilisée)
├── strategy.py            # Logique CRT (range, sweep, structure, FVG, order block)
├── notifier.py             # Envoi des messages Telegram
├── state_manager.py         # Anti-doublons entre chaque exécution
├── state.json                # État persistant (committé automatiquement par le workflow)
└── .github/workflows/crt-scan.yml  # Planification GitHub Actions
```
