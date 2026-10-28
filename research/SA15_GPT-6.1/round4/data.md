# Données R4 — 16 octobre 2026

Le magasin runs/sa15_gpt61_r4_store copie le magasin SA15 initial, puis ajoute trois classes capitalisantes cotées en EUR sur Xetra. Les22fichiers de prix/niveaux antérieurs sont identiques bit à bit (origin_prices_verified.json). Le registre et le journal administratif des nouvelles collectes diffèrent volontairement dans le nouveau magasin ; R1/R2/R3 et market_data ne sont pas modifiés.

| ID | Symbole | Exposition | Lancement de classe / source émetteur | Archive retenue |
| --- | --- | --- | --- | --- |
| ETF_US_TECH | QDVE.DE | S&P500 technologieUS, fonds capitalisant | Classe/listing2015, iShares | 2017-01-02/2026-10-09 |
| ETF_WORLD_HEALTH | XDWH.DE | Santé mondiale, classe1C capitalisante | 2016-03-04, DWS | 2017-01-02/2026-10-09 |
| ETF_WORLD_UTILITIES | XDWU.DE | Utilities mondiales, classe1C capitalisante | 2016-03-16, DWS | 2017-01-02/2026-10-09 |

Les pages officielles et limites sont liées dans literature.md et instruments.toml. La première séance du registre est le début d'archive choisi, pas une date de lancement. Aucun historique de fonds prédécesseur n'est concaténé. EUR est la devise de cotation et du portefeuille, sans supprimer l'exposition aux devises étrangères. La technologie reste concentrée : elle n'est pas un substitut diversifié au Nasdaq. Aucun ETF à levier n'est utilisé.

Le script scripts/SA15_download_gpt61_round4.py appelle le data-layer updater existant, ses normaliseurs et validateurs. Données brutes conservées ; clean écrit uniquement après validation. Bilan des trois nouvelles lignes : zéro erreur de validation, aucun corporate action enregistré ;2478/2478/2475barres nettoyées respectivement. Les historiques Yahoo sont restatés au téléchargement, pas des millésimes point-in-time et pas une vérification indépendante multi-sources.

Les séances hors calendrier fournisseur sont retirées par la règle normale du projet. Deux barres manquent pour les trois fonds :24/10/2025 et06/03/2026. Les utilities manquent aussi03/07/2017,05/07/2017,02/08/2017, avant toutes fenêtres utilisées en2019. Les trois fonds présentent des barres plates sans volume04–06/12/2023 ; les utilities en ont aussi103en2017,7en2018 et1en2019. Le validateur les signale comme avertissements, sans fabriquer un prix ou supposer une transaction. Ces observations restent identifiables dans les archives.

Momentum : endpoints exacts et dernier close propre attendu, sans imputation. MA/volatilités : fenêtres de séances consécutives strictes ; un trou peut donc rendre une ligne inutilisable pour plusieurs décisions et influer sur l'allocation. Cette limite devra être publiée si la variante retenue y est exposée. Le rapport distingue refus de signal et rejets d'exécution. Les courbes de choix s'arrêtent en2024 ; les nouveaux trous communs2025/2026 n'y interviennent pas.

Toutes les comparaisons utilisent le même calendrier, capital, frais et règles d'exécution. La date finale09/10/2026 est conservée pour rester comparable aux trois séries antérieures ; aucune promesse de prix actuels ou de performance future.