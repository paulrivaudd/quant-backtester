# Glossaire

Les termes de finance et de backtest dans le sens où le projet les emploie. Le
nom anglais est celui du code. Les formules sont dans [FORMULES.md](FORMULES.md).

| Français | Anglais (code) | Sens dans ce projet |
|---|---|---|
| Instrument | instrument | une série décrite dans `instruments.toml` : pas forcément négociable (un indice, un taux) |
| Action | stock, share | une part de propriété d'une entreprise |
| Fonds indiciel coté | ETF | une part de fonds négociée en bourse ; un indice, lui, n'est qu'un calcul et ne s'achète pas |
| Fonds capitalisant / distribuant | accumulating / distributing | réinvestit ses revenus / les verse aux détenteurs (`distribution_policy`) |
| Univers | universe | les instruments qu'une stratégie peut détenir à une date ; membres datés dans `universes.toml` |
| Séance | session | une journée de cotation d'une place, selon son calendrier |
| Barre, OHLCV | bar | ouverture, plus haut, plus bas, clôture, volume d'une séance : un résumé, pas le chemin parcouru |
| Niveau | level | une valeur publiée (taux, change, VIX), sans séance de bourse |
| Fixing | fixing | un niveau fixé selon une procédure à une heure donnée (BCE) ; pas un prix d'exécution |
| Disponibilité | availability | l'instant à partir duquel une valeur pouvait être connue (`available_at_utc`) |
| Version, millésime | vintage | l'état publié d'une série à une date donnée |
| Série restatée | restated | la série telle qu'elle est publiée aujourd'hui, corrections comprises (`RESTATED`) |
| Contrôle croisé | cross-check | comparaison champ par champ de deux sources |
| Trou connu | known gap | une séance absente, expliquée, jamais comblée |
| Opération sur titres (OST) | corporate action | un split, un dividende ou une scission, qui change les titres ou les flux ; voir [OPERATIONS_SUR_TITRES.md](OPERATIONS_SUR_TITRES.md) |
| Date ex | ex-date | premier jour où le titre se négocie sans le droit |
| Prix brut / ajusté | raw / adjusted | la cotation / le prix recalculé en arrière pour neutraliser les OST connues (`PriceBasis`) |
| Rendement avec distributions | total return | performance qui inclut les distributions selon une règle de réinvestissement (`BenchmarkBasis.TOTAL_RETURN`) |
| Signal, indicateur | signal | un nombre et un statut par instrument, calculés sur une fenêtre passée ; jamais un ordre |
| Fenêtre | window | les observations qu'un signal lit, sous un contrat (`WindowSpec`) |
| Momentum | momentum | le rendement passé, lu comme tendance ; ne prouve pas que la tendance continue |
| Retour à la moyenne | mean reversion | ici, l'opposé du rendement ; aucune moyenne d'équilibre n'est estimée |
| Moyenne mobile | moving average | une moyenne recalculée sur une fenêtre qui avance |
| Volatilité | volatility | l'écart-type des rendements, annualisé ; ne distingue pas la hausse de la baisse |
| Z-score | z-score | l'écart à la moyenne de la fenêtre, en écarts-types |
| Stratégie | strategy | la règle qui transforme des signaux en allocation cible |
| Poids cible | target weight | la fraction du capital voulue dans un instrument, avant coûts et lots |
| Allocation cible | `TargetAllocation` | ce que la stratégie demande |
| Cible contrainte | `ConstrainedTarget` | ce que les limites autorisent |
| Position | holding, position | une quantité effectivement détenue (`PortfolioState`) |
| Liquidités | cash | l'argent non investi ; il ne rapporte rien dans le moteur |
| Capital, valeur du livre | equity | le cash plus la valeur des positions |
| Coût moyen | average cost | prix de revient par unité, frais compris ; pas un calcul fiscal |
| Rééquilibrage | rebalancing | ramener les positions vers une cible, ce qui coûte des transactions |
| Acheter et conserver | buy and hold | garder les quantités ; les poids dérivent |
| Rotation | rotation | changer d'instrument selon un classement |
| Ordre | order | une demande au marché |
| Exécution | fill | la partie réellement exécutée d'un ordre, au prix payé |
| Rejet | reject | un ordre non exécuté, avec son motif (`ExecutionRejectReason`) |
| Enchère d'ouverture | opening auction | le prix commun fixé à l'ouverture ; c'est le prix d'exécution du moteur |
| Cours acheteur / vendeur | bid / ask | les prix auxquels on peut vendre / acheter immédiatement |
| Écart, demi-écart | spread, half spread | la différence entre ask et bid ; un achat paie la moitié au-dessus du milieu |
| Glissement | slippage | l'écart supplémentaire défavorable au prix théorique |
| Commission | commission | les frais du courtier, avec un plancher |
| Lot | lot, quantity step | le pas de quantité négociable ; 1 = parts entières |
| Brut / net | gross / net | les mêmes transactions sans / avec les frais |
| Rotation du portefeuille | turnover | le montant échangé rapporté au capital moyen |
| Perte depuis le sommet | drawdown | l'écart relatif au plus haut déjà atteint |
| Ratio de Sharpe | Sharpe ratio | l'excès de rendement sur le taux sans risque, rapporté à sa dispersion |
| Référence | benchmark | ce à quoi on compare le run : une part détenue sans coûts |
| Témoin exécutable | executable control | une stratégie simple (buy and hold) jouée sous les mêmes coûts |
| Bootstrap par blocs | block bootstrap | un rééchantillonnage de blocs de séances consécutives, pour un intervalle |
| Biais d'anticipation | look-ahead bias | utiliser une information qui n'existait pas encore |
| Biais de survivance | survivorship bias | ne garder que les instruments encore cotés aujourd'hui |
| Surapprentissage | overfitting | choisir une règle qui explique le bruit du passé |
| Hypothèse préenregistrée | preregistered hypothesis | une règle et une prédiction écrites avant les essais (`PREREGISTERED`) |
| Hors échantillon | out of sample | des données qui n'ont servi à aucun choix |
| Paper trading | paper trading | suivre une règle figée au fil du temps, sans argent réel |
| Empreinte | fingerprint | le hachage d'une définition ; identifie, ne prouve pas l'absence de bug |
| Provenance | provenance | ce qui identifie le code, les données et les paramètres d'un résultat (`run_id`) |
