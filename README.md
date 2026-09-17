# CRT Bot — Candle Range Trading (Forex + Indices synthétiques)

Bot Python qui applique la méthodologie **Candle Range Trading (CRT)** :

1. Range de référence = haut/bas de la dernière période **W1** (semaine complète,
   dérivée des bougies D1), **D1** et **H4** clôturée.
2. Détection d'un **sweep de liquidité** (fausse cassure) de ce range, sur un
   timeframe de confirmation **proportionnel à la référence** (voir tableau
   ci-dessous) — chaque paire référence/confirmation génère ses propres
   alertes, étiquetées séparément dans le message Telegram.

   | Référence | Confirmation |
   |---|---|
   | W1 | H4 |
   | D1 | H1 |
   | H4 | M15 |

   Cette répartition (`REFERENCE_CONFIRMATION_MAP` dans `config.py`) évite de
   confirmer un range large sur un timeframe disproportionnellement fin (bruyant).
3. Confirmation avancée : **cassure de structure** + **Fair Value Gap** et/ou **Order Block**.
4. Calcul de niveaux de trade indicatifs :
   - **Entrée** :
     - Marchés réels (forex, or, cryptos) : bord de l'Order Block le plus
       proche du prix (ou milieu du FVG si pas d'OB) — ordre en attente
       (Limit/Stop) qui suppose un retracement.
     - **Indices synthétiques** : entrée immédiate à la clôture de la bougie de
       cassure de structure (quasi ordre au marché) — ces actifs, générés par
       algorithme, enchaînent souvent des mouvements directs sans jamais
       revenir sur la zone OB/FVG, où un ordre en attente resterait non rempli.
   - **Stop loss** : au-delà de l'extrême de la bougie de sweep, avec une marge de
     sécurité (`STOP_LOSS_BUFFER_PCT` dans `config.py`, 0.05% par défaut)
   - **Deux cibles** : TP1 à mi-range (souvent visé en premier) et TP2 à
     l'extrémité opposée du range — étendue pour les indices synthétiques
     (`SYNTHETIC_TP_EXTENSION_PCT`, +50% de la taille du range par défaut), qui
     offrent généralement un ratio risque/récompense plus favorable
   - Ratio risque/récompense approximatif (calculé sur TP2) — **seuls les
     setups avec un R:R ≥ 1:3 déclenchent une alerte** (`MIN_RISK_REWARD`)
   - **Type d'ordre** (Buy/Sell/Buy Limit/Sell Limit/Buy Stop/Sell Stop), déterminé
     en comparant l'entrée au prix actuel — comme sur une app de trading
     (`ORDER_TYPE_TOLERANCE_PCT` dans `config.py` pour ajuster la tolérance
     "prix déjà sur zone" = ordre au marché).
5. Confirmation Fibonacci OTE (Optimal Trade Entry, retracement 61.8%-79% du
   mouvement impulsif après le sweep) — indiquée dans le message quand l'entrée
   tombe dans cette zone (`REQUIRE_FIB_OTE = True` dans `config.py` pour en faire
   un filtre obligatoire plutôt qu'une simple indication).
6. Détection de la **tendance de fond** en D1, en combinant 3 critères :
   fenêtre de swing élargie (`TREND_SWING_WINDOW`, 4 par défaut), 3 swing highs
   **et** 3 swing lows consécutifs tous croissants/décroissants
   (`TREND_SWING_COUNT`), confirmés par la position du prix par rapport à une
   moyenne mobile (`TREND_SMA_PERIOD`, 50 bougies D1 par défaut). Un setup à
   contre-tendance n'est **jamais bloqué**, juste signalé par un tag
   `⚠️ Contre-tendance` dans le message.
7. **Killzone** (Londres 3h-6h / New York 8h30-11h30, heure de New York),
   uniquement sur les marchés réels (forex, or, cryptos) — les indices
   synthétiques Deriv tournent 24/7 par algorithme sans session de liquidité
   réelle, donc le concept ne leur est jamais appliqué. Informatif par défaut
   (tag `⏰ Hors killzone` si le sweep a eu lieu en dehors de ces fenêtres) ;
   `REQUIRE_KILLZONE_FOR_REAL_MARKETS = True` dans `config.py` pour en faire un
   filtre bloquant.
8. **Suivi automatique des trades** : chaque alerte envoyée est enregistrée
   (`trade_stats.json`). Pour un ordre en attente (Buy/Sell Limit/Stop), le bot
   vérifie d'abord que le prix a réellement atteint la zone d'entrée avant de
   commencer à chercher le SL/TP — un ordre jamais rempli après 7 jours
   (`PENDING_MAX_AGE_DAYS`) expire et s'archive avec le résultat `EXPIRE`
   (jamais compté comme gagnant/perdant, mais donne un vrai taux de remplissage,
   utile notamment sur les indices synthétiques qui reviennent rarement sur leur
   zone d'entrée). Un ordre au marché (Buy/Sell) est considéré rempli dès
   l'alerte. Une fois rempli, le bot vérifie si le SL ou le TP a été touché en
   premier (si les deux sont touchés dans la même bougie, hypothèse prudente :
   le SL a cédé). Un résumé (taux de réussite global, contre-tendance vs
   aligné, taux de remplissage) s'affiche dans les logs GitHub Actions.
9. **Filtre de gap de weekend** (forex/or uniquement, jamais cryptos/synthétiques
   qui tournent 24/7) : une bougie qui suit un écart temporel anormal (fermeture
   de marché le weekend) n'est jamais comptée comme un sweep de liquidité —
   évite les faux signaux causés par un simple gap d'ouverture plutôt qu'une
   vraie manipulation intrabar (`WEEKEND_GAP_MULTIPLIER` dans `config.py`).
10. **Nettoyage automatique** : les verrous de range et clés anti-doublon de
    `state.json` plus vieux que 30 jours (`STATE_MAX_AGE_DAYS`), et l'historique
    de `trade_stats.json` plus vieux que 180 jours (`TRADE_HISTORY_MAX_AGE_DAYS`),
    sont purgés automatiquement à chaque scan — les fichiers restent légers
    indéfiniment, sans intervention manuelle.
11. Envoi d'une alerte **Telegram** dès qu'un setup confirmé est détecté.

> ⚠️ Le suivi ne voit que les bougies encore présentes dans l'historique récupéré
> (150 bougies, `CANDLE_COUNT`) — un trade qui met plus de temps que ça à atteindre
> son SL/TP peut ne jamais être résolu et rester indéfiniment "en attente".

Le bot tourne gratuitement via **GitHub Actions**, déclenché toutes les 5 minutes par un
**cronjob externe sur [cron-job.org](https://cron-job.org)** — le `schedule:` interne de
GitHub Actions s'est avéré peu fiable en pratique (délais de plusieurs heures, best-effort
non garanti), donc le déclenchement se fait désormais via l'API GitHub
(`workflow_dispatch`) plutôt que via le cron intégré.

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
4. Le workflow `.github/workflows/crt-scan.yml` est déclenché toutes les 5 minutes par
   un cronjob externe configuré sur cron-job.org (voir section ci-dessous), qui appelle
   l'API GitHub (`POST /repos/<user>/<repo>/actions/workflows/crt-scan.yml/dispatches`
   avec un token GitHub en en-tête `Authorization: Bearer <token>` et le corps
   `{"ref":"main"}`). Tu peux aussi le lancer manuellement depuis l'onglet **Actions**.

## 4. Personnaliser

- **Symboles** : liste `SYMBOLS` dans `config.py` — actuellement forex majeurs et
  mineurs (paires croisées sans USD), or (`frxXAUUSD`), cryptos (`cryBTCUSD`,
  `cryETHUSD`, `cryLTCUSD`, `cryXRPUSD`), Volatility Index classiques (`R_10`,
  `R_25`, `R_50`, `R_75`, `R_100`) et toutes les variantes 1 seconde disponibles
  chez Deriv (`1HZ10V` à `1HZ300V`), Step Index (`stpRNG`) — 50 actifs au total.
- **Fréquence de scan** : modifier l'intervalle du cronjob sur cron-job.org (le
  `schedule:` du fichier `.yml` n'est plus utilisé).
- **Répartition référence/confirmation** : `REFERENCE_CONFIRMATION_MAP` dans
  `config.py` — modifier quels TF de confirmation sont associés à W1/D1/H4.
- **Sensibilité de la confirmation** : `STRUCTURE_SWING_WINDOW` dans `config.py`
  permet d'ajuster, par timeframe de confirmation, la fenêtre de détection des
  swing points lors de la cassure de structure (actuellement réduite à 1 pour
  M15, pour une confirmation plus réactive sans changer de timeframe — 2 par
  défaut ailleurs). Le paramètre `window` dans `detect_fvg`/`detect_order_block`
  (dans `strategy.py`) reste ajustable de la même façon si besoin.
- **Une seule alerte par range et par piste** : le premier setup confirmé (haussier ou
  baissier) sur un range D1/H4 donné verrouille ce range **pour ce timeframe de
  confirmation** — pas de nouvelle alerte tant qu'une nouvelle bougie D1/H4 ne s'est
  pas formée.

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
├── trade_tracker.py          # Suivi des trades (résolution SL/TP, statistiques)
├── state.json                # État persistant (committé automatiquement par le workflow)
├── trade_stats.json           # Historique des trades résolus (committé automatiquement)
└── .github/workflows/crt-scan.yml  # Planification GitHub Actions
```
