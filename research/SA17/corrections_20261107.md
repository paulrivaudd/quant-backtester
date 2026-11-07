# SA17 — compte rendu des corrections du 7 novembre 2026

Cette intervention porte sur le code, les sources et le protocole. **Aucun
backtest de performance SA17 ou SA18, aucun fit sur données de marché et
aucune sélection de stratégie n'ont été exécutés.** Les anciens magasins et
résultats sont conservés.

## Réalisé

- Vérification des dix ISIN auprès de State Street ; téléchargement de leurs
  VL officielles USD et des suppléments. Neuf historiques démarrent le
  7 juillet 2015 ; communications le 15 août 2018. Contrôles d'identité,
  devise, schéma, doublons, valeurs invalides et empreintes des fichiers.
- Adaptateur `SSGA_NAV` et normalisation en LEVEL non négociables. Nouveau
  magasin `runs/sa17_nav_store_20261107_v3`, dix séries validées. Une borne
  explicite de disponibilité empêche d'utiliser rétrospectivement les VL
  téléchargées aujourd'hui sans preuve de publication historique.
- Deuxième canal : adaptateur des annonces officielles LSE RNS, horodatage
  de publication, rapprochement par fonds/date/devise, secours si une source
  manque, refus des conflits non revus. L'annonce vérifiée concorde exactement
  avec State Street pour les dix fonds le 5 novembre 2026. Elle est publiée
  le 6 novembre à 10:20:21 UTC. Ce contrôle ne couvre qu'une annonce.
- SA17 exige désormais des VL USD explicites pour le classement, des dates
  communes avec le marché américain et des entrées distinctes pour le risque
  EUR. Conversion USD/EUR testée ; fixing BCE refusé. La date limite commune
  est explicite, par défaut le mois précédent terminé. Aucun cours Xetra
  périmé n'entre implicitement dans le classement ou la covariance.
- Adaptateur Ken French : 10/49 industries mensuelles pondérées par la
  capitalisation, dividendes inclus, et facteur marché `Mkt-RF + RF`.
  1 203 mois acquis de juillet 1926 à septembre 2026. Séries de recherche
  restatées en classification SIC, sans assimilation à des ETF négociables.
- Coûts différenciés par instrument dans le moteur, y compris taille des
  ordres, commissions minimales, contrainte de cash et fills. Hypothèses
  explicites par fonds dans [costs.toml](costs.toml), stress ×2 sur chaque terme.
- [Protocole](protocol.md), hypothèse préalable et calcul de puissance écrits.
  Le seuil d'IR observé à 5 % est ~0,68 sur 8,25 ans ; pour 80 % de puissance,
  l'IR réel requis est ~0,98 sous hypothèses IID. Les scénarios IR 0,3 et 0,5
  n'ont que ~14 % et ~30 % de puissance. Ce ne sont pas des estimations validées
  du rendement de SA17.

## Ce que la vérification corrige dans les hypothèses de départ

1. **Clôture, valorisation et publication diffèrent.** Les dix suppléments
   fixent la valorisation à 22:15 en Irlande, soit 23:15 à Paris. Les fichiers
   n'établissent pas une publication avant 23:00 ; le prospectus décrit une
   diffusion le jour ouvré suivant. Les références EUR de l'émetteur utilisent
   WM 16:00 Londres, pas un change synchrone à la clôture américaine.
2. **VL quotidienne ne signifie pas chaque séance américaine.** Les deux
   trous Yahoo du 24 octobre 2025 et du 6 mars 2026 sont bien couverts pour
   les dix fonds. Mais 26 dates XNYS restent absentes pour neuf fonds, 18 pour
   communications, notamment des jours fériés européens. Il faut le calendrier
   de valorisation officiel, pas une interpolation ni une panne supposée.
3. **Volume nul n'est pas absence de liquidité.** Le texte antérieur est
   corrigé. Les teneurs de marché fournissent des cotations ; leur présence
   ne prouve pas que n'importe quel cours d'ouverture Yahoo était exécutable.
   Les trous de prix d'exécution restent distincts des trous de signal.
4. **Un spread affiché peut être invalide.** La page du fonds technologie
   montre un bid supérieur à l'ask. Cette observation est refusée. Son
   demi-spread de 15 bp dans le protocole est une hypothèse provisoire,
   pas une mesure historique. Les autres hypothèses sont également identifiées.

L'étude exécutable reste donc **non admise** : publication historique complète,
calendriers des fonds, FX synchrone, opérations sur titres et prix d'exécution
doivent encore être validés. Le code ne masque pas ces absences. La demande
de préparation est traitée ; aucune supériorité économique n'est annoncée.

## Reproduction

En environnement POSIX/WSL Python 3.12, depuis la racine :

```bash
# Noms de sortie neufs obligatoires ; ne pas écraser les archives existantes.
uv run python scripts/SA17_acquire_research_inputs.py \
  --archive runs/sa17_nav_new --coverage
uv run python scripts/SA17_acquire_research_inputs.py \
  --archive runs/sa17_french_new --coverage --ken-french
uv run python scripts/SA17_build_nav_store.py \
  --archive runs/sa17_nav_inputs_20261107_v2 --store runs/sa17_nav_replay_new
uv run python scripts/SA17_check_nav_notice.py \
  --archive runs/sa17_rns_replay_new \
  --primary-archive runs/sa17_nav_inputs_20261107_v2 \
  --replay runs/sa17_lse_nav_20261107
uv run pytest
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
```

Une nouvelle acquisition capture une nouvelle version fournisseur. Les
replays ci-dessus utilisent les octets archivés. Les preuves légères sont
versionnables dans `nav_source_evidence.json`, `nav_calendar_coverage.json`,
`ken_french_source_evidence.json`, `lse_nav_validation.json` et `power.json`.

## Validation

Les tests couvrent parsing, horodatages, refus des informations futures,
devises/calendriers, calcul EUR, rapprochement des sources, coûts par fonds,
contraintes de cash, archives non écrasables et calcul de puissance.
Le premier passage complet a révélé trois tests de contrat à adapter et sept
échecs de hook shell dus aux fins de ligne Windows. Ils ont été corrigés ;
`.gitattributes` impose LF aux hooks sans changer leur comportement.
Validation finale : **4 641 tests réussis, 19 désélectionnés** (suite hors
réseau), Ruff lint et formatage conformes, Pyright sans erreur sur les
adaptateurs, scripts et couches modifiées. Les tests s'exécutent sous WSL
avec l'environnement Python 3.12 existant ; aucune dépendance ajoutée.
