# rakuten-veille

Veille des mentions en ligne autour de la **fermeture de Rakuten France** : collecte quotidienne depuis les réseaux sociaux, puis restitution dans un dashboard web léger.

Le projet se compose de **deux briques** dans une **seule image Docker** :

- un **collecteur** (CronJob Kubernetes / `collect.py`) qui interroge les plateformes sur une liste de mots-clés et stocke les résultats pertinents dans SQLite ;
- un **dashboard** (serveur `http.server` stdlib / `server.py`) qui expose les données collectées sous forme de cartes, histogrammes par plateforme et par période (jour / mois).

> 100 % **bibliothèque standard Python** — aucune dépendance à installer, image minimale et reproductible.

---

## Plateformes couvertes

| Source | Type | Commentaire |
|---|---|---|
| Google News | RSS (gratuit) | via mot-clé |
| Reddit | API publique | filtrage par pertinence |
| Bluesky | API publique | flux public |
| Mastodon | API publique | instances publiques |
| X (Twitter) | Apify (`scrape.badger~twitter-tweets-scraper`) | token requis |
| Instagram | Apify (`apify~instagram-scraper`) | token requis |
| TikTok | Apify (`clockworks~tiktok-scraper`) | token requis |
| Facebook | Apify (`danek~facebook-search-ppr`) | token requis |
| LinkedIn | Apify (`harvestapi~linkedin-post-search`) | token requis |

Les plateformes **Apify** sont optionnelles : elles ne sont activées que si un token (`APIFY_TOKEN`) est fourni. La couverture gratuite (Google News, Reddit, Bluesky, Mastodon) fonctionne sans aucun comptes secrets.

---

## Démarrage rapide (local)

```bash
# 1. Lancer la collecte (écrit dans ./posts.db)
python3 src/collect.py

# 2. Lancer le dashboard
DB_PATH=./posts.db python3 src/server.py
# -> http://localhost:8080
```

Optionnel, pour activer les plateformes Apify payantes :

```bash
export APIFY_TOKEN="votre_token"
```

Mots-clés configurables dans [`src/config.py`](src/config.py).

---

## Déploiement Kubernetes (OVH / on-prem)

Tous les manifests sont dans [`k8s/`](k8s/) :

| Fichier | Rôle |
|---|---|
| `veille-deployment.yaml` | Deployment du dashboard (port 8080) |
| `veille-service.yaml` | Service ClusterIP (`veille-dashboard`) |
| `veille-cronjob.yaml` | CronJob de collecte — tous les **lundis 06:00** (`0 6 * * 1`) |
| `veille-pvc.yaml` | PVC SQLite partagé entre collecteur et dashboard |
| `ingress-staging.yaml` / `ingress-prod.yaml` | Ingress (TLS via conteneur) — accès **public** via `allow_public_unauthenticated_access` |
| `secret.example.yaml` | Template du Secret K8s `APIFY_TOKEN` |

### En un résumé

1. **Tenir à jour uniquement le token Apify** via un Secret K8s :

```bash
kubectl create secret generic veille-secrets \
  --from-literal=APIFY_TOKEN="$(printf '%s' 'VOTRE_TOKEN' | base64)" -n <ns>
```

2. **Appliquer** les manifests :

```bash
kubectl apply -f k8s/
```

Le collecteur et le dashboard partagent le même PVC (`rakuten-veille-data`) : le CronJob écrit `posts.db`, le Deployment le lit pour afficher le tableau de bord.

### Build de l'image

Le workflow Forgejo (`.forgejo/workflows/build.yml`) construit l'image avec **Kaniko**, la tag `build-<run>-<sha>` puis la pousse vers le registre `git.reault.tech`. L'accès au registre passe par les secrets CI `REGISTRY_USER` / `REGISTRY_TOKEN` (jamais commités).

---

## Structure du dépôt

```
.
├── Dockerfile                  # image unique : collecteur ET dashboard
├── src/
│   ├── collect.py              # point d'entrée CronJob (collecte + stockage)
│   ├── server.py               # point d'entrée dashboard (http.server stdlib)
│   ├── store.py                # persistance SQLite + pertinence
│   ├── config.py               # mots-clés surveillés
│   ├── fetch_google_news.py    # sources gratuites
│   ├── fetch_reddit.py
│   ├── fetch_bluesky.py
│   ├── fetch_mastodon.py
│   └── fetch_apify.py          # sources payantes (token via env)
├── k8s/                        # manifests de déploiement
├── tests/                      # tests unitaires / seeds
└── .forgejo/workflows/build.yml
```

---

## Vie privée & sécurité

- **Aucun secret dans le dépôt** : les tokens (Apify, registre) transitent par des Secrets K8s ou des variables d'environnement, jamais par des fichiers versionnés.
- **Données** : tout vit dans la base SQLite locale (PVC), pas d'externalisation vers un service tiers de stockage.
- **Dashboard** : exposé en **HTTPS public** (pas d'authentification). Les données restent des mentions publiques des réseaux sociaux — aucun compte ni donnée personnelle des utilisateurs n'est stocké.

---

## Licence

Voir les fichiers du dépôt. Projet personnel à visée démonstrative (veille), non affilié à Rakuten.