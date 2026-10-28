# SA15_GPT-6.1 — protocole fixé avant les essais

Le 15 octobre 2026. Maximum 10 configurations. Long-only sans levier, 100000 EUR, parts entières. Décisions après clôtures (horaire du moteur), exécution ouverture suivante. Commission5pb minimum1EUR, demi-spread3pb, slippage2pb par ordre. Allocation initiale hebdomadaire, bande5points. Données isolées dans runs/sa15_gpt61_store.

Développement : 2019-06-03 au 2022-12-30. Validation pour sélection : 2023-01-02 au 2024-12-31. Contrôle final réservé à la configuration choisie : 2025-01-02 au 2026-10-09. La période finale a déjà été vue dans les travaux SA1–SA14 : elle n'est pas vierge au niveau du projet. Univers choisi rétrospectivement.

Score de sélection = moyenne(CAGR développement, CAGR validation) - 0.25*moyenne(drawdowns absolus) - 0.10*abs(CAGR développement-CAGR validation). Égalité : premier essai. Aucun choix après lecture du contrôle final. Répétition frais doubles = diagnostic, pas nouvel essai.

Comparer World buy&hold, SA1 MA20, S&P500 buy&hold, panier équipondéré aux mêmes dates et coûts. Publier tous les essais, net/brut, CAGR, volatilité, Sharpe à taux nul, drawdown, Calmar, rotation, coûts, rejets, exposition et années. Pas de garantie d'enrichissement ; dire si la cible de surperformance échoue.

Sources étudiées avant essai1 :
- Moskowitz/Ooi/Pedersen2012 : https://fairmodel.econ.yale.edu/ec439/mosk.pdf (tendances futures multi-actifs, pas réplication directe en ETF long-only).
- Keller/Keuning2023 HAA : https://ssrn.com/abstract=4346906 (momentum1/3/6/12 mois ; allocation et filtres adaptés ici).
- Moreira/Muir : https://conference.nber.org/confer/2016/LTAMs16/Moreira_Muir.pdf (inverse variance ; notre plafond inverse écart-type est une adaptation).
- Forum Bogleheads : https://www.bogleheads.org/forum/viewtopic.php?start=100&t=158297 (faux signaux, frais, sous-performance prolongée ; opinions, pas preuve).

Limites : source unique, possibles révisions, choix rétrospectif de titres, historique court, ruptures d'indices, sélection parmi plusieurs essais. L'or 4GLD est un ETC et non un ETF UCITS. Nasdaq/émergents cotés EUR gardent leurs risques de devises. XDBC change d'indice le21/05/2021.