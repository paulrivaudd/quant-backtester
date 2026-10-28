# Controle causal en lecture seule - M10 et M16

Controle effectivement execute sur les donnees gelees et les journaux reels, sans moteur de backtest complet, sans ordre ni modification financiere. Les valeurs de prix chargees sont bornees au 31 decembre 2024 ; aucun resultat 2025-2026 nouveau n'est utilise.

## Methode independante

Les sept soirees choisies par strategie couvrent le choc de 2020, sa reprise, le rebond de juillet 2022 et un autre regime en novembre 2023. Chaque calcul ne conserve que les observations dont close_available_at_utc est anterieur ou egal a la decision de 23 h Paris. Les dates exactes proviennent des calendriers du magasin gele, jamais d'un simple calendrier de jours ouvres.

- Momentum : P[t-S]/P[t-L]-1 aux deux sessions exactes du calendrier du fonds, sans remplacer une date manquante par une observation disponible.
- MA : P[t]/moyenne des N derniers prix sur N sessions consecutives, dernier prix inclus.
- Volatilite : ecart-type echantillonnal des N log-rendements sur N+1 prix consecutifs, ddof=1, multiplie par racine(252).
- Drawdown du signal : P[t]/max des 63 derniers prix consecutifs-1 ; distinct du drawdown de portefeuille.
- Canaris : momentum126 des fonds Monde et Emergents selon leurs propres calendriers et disponibilites.
- Les prix de cloture contestes sont exclus champ par champ. La table des actions d'entreprise est vide dans ce magasin : l'ajustement interne ne change aucun prix pour ce controle.

Les formules ont ete recalculees independamment, puis confrontees au journal. Les vraies classes de signaux ont aussi ete executees ponctuellement, dans des lecteurs isoles servant des copies en memoire : historique connu jusqu'a 2024 ; prefixe strict a la decision ; prefixe plus une barre future aux prix multiplies par un million ; historique avec toutes les barres futures multipliees par un million. Le code financier et les fichiers ne sont jamais modifies par ces variations.

Les etapes de poids ont ete reconstruites independamment : votes de tendance, reprise, confirmation, risque conditionnel, defense, puis hold_defense et bande sur les positions deja detenues a la cloture. Aucun rendement ulterieur n'intervient.

## Resultats executes

- 147 rapprochements de signaux independants contre journaux ; 588 calculs ponctuels avec les classes reelles, sous quatre vues des donnees.
- 588 comparaisons independantes sous quatre vues, dont 441 avec suppression, ajout ou empoisonnement du futur. Suppression, ajout et empoisonnement des observations futures n'ont change aucun resultat des vrais signaux, meme bit pour bit.
- 98 etapes de poids et 14 cibles avant/apres bande confrontees au journal.
- Ecart maximal des signaux : 0 ; ecart maximal des etapes : 8.33e-17 (tolerance de comparaison 1e-12).
- Chaque observation effectivement consommee etait deja disponible selon les horodatages et le calendrier du magasin ; marge minimale de 5.5 heures entre derniere publication et decision.
- Les 112 sources et 41 fichiers de donnees/metadonnees restent identiques au gel.

| Regle | Soiree | Tendance | Apres reprise | Apres confirmation | Echelle risque | Nasdaq avant bande | Maintien positions |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| M10 | 2020-02-28 | 0.666667 | 0.666667 | 0.666667 | 0.641419 | 0.427613 | False |
| M10 | 2020-03-31 | 0.333333 | 0.333333 | 0.333333 | 0.357221 | 0.119074 | False |
| M10 | 2020-04-30 | 0.666667 | 0.666667 | 0.666667 | 1.000000 | 0.666667 | False |
| M10 | 2022-06-30 | 0.000000 | 0.000000 | 0.000000 | 0.689894 | 0.000000 | True |
| M10 | 2022-07-29 | 0.333333 | 0.333333 | 0.333333 | 0.710301 | 0.236767 | False |
| M10 | 2022-08-31 | 0.333333 | 0.333333 | 0.333333 | 0.804700 | 0.268233 | True |
| M10 | 2023-11-30 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | False |
| M16 | 2020-02-28 | 0.666667 | 0.666667 | 0.000000 | 0.641419 | 0.000000 | False |
| M16 | 2020-03-31 | 0.333333 | 0.333333 | 0.000000 | 0.357221 | 0.000000 | True |
| M16 | 2020-04-30 | 0.666667 | 0.666667 | 0.000000 | 1.000000 | 0.000000 | True |
| M16 | 2022-06-30 | 0.000000 | 0.000000 | 0.000000 | 0.689894 | 0.000000 | True |
| M16 | 2022-07-29 | 0.333333 | 1.000000 | 0.000000 | 0.710301 | 0.000000 | True |
| M16 | 2022-08-31 | 0.333333 | 0.333333 | 0.000000 | 0.804700 | 0.000000 | True |
| M16 | 2023-11-30 | 1.000000 | 1.000000 | 0.000000 | 1.000000 | 0.000000 | True |

Le 29 juillet 2022, le drawdown63 vaut zero : la reprise breakout de M16 restaure la direction. Les deux canaris restent negatifs et bloquent ensuite cette reprise. Ce resultat suit les seules donnees deja connues ; aucune date de reprise gagnante n'est injectee. Le 30 avril 2020, le risque conditionnel autorise une echelle de un grace a MA200 et momentum21 positifs, mais M10 ne vise encore que deux tiers de Nasdaq a cause du vote de tendance.

Un maintien de positions peut conserver une defense differente du nouveau plan, comme prevu par hold_defense ; il ne constitue pas un poids choisi avec la suite des rendements. Les poids effectivement detenus sont lus dans le livre a la meme cloture.

Ce controle teste la causalite informatique sur quatorze decisions ; il ne prouve ni l'absence de surajustement des mecanismes, ni la performance future. Les prix de fournisseur peuvent etre retrospectivement revises : leurs horodatages de disponibilite sont ceux du calendrier dans le magasin, pas une preuve que la valeur numerique exacte etait distribuee identiquement a l'epoque.

## Details reproductibles des fenetres consommees

Chaque ligne ci-dessous indique les bornes exactes, le nombre de prix et la derniere disponibilite des observations utilisees.

```json
[
  {
    "strategy": "M10",
    "day": "2020-02-28",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-02-27",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-02-28",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-30",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-02-28",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-08-28",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-02-28",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-05-16",
    "last_session": "2020-02-28",
    "observations": 200,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-02-28",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-11-26",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-02-28",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-31",
    "last_session": "2020-02-28",
    "observations": 21,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-02-28",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-11-29",
    "last_session": "2020-02-28",
    "observations": 61,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-02-28",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2020-01-30",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-02-28",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2019-11-26",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-03-31",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-03-30",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-03-31",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-03-02",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-03-31",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-09-27",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-03-31",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-06-18",
    "last_session": "2020-03-31",
    "observations": 200,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-03-31",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-02",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-03-31",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-03-03",
    "last_session": "2020-03-31",
    "observations": 21,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-03-31",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-07",
    "last_session": "2020-03-31",
    "observations": 61,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-03-31",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2020-03-02",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-03-31",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2020-01-02",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-04-30",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-04-29",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-04-30",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-03-30",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-04-30",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-10-28",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-04-30",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-07-16",
    "last_session": "2020-04-30",
    "observations": 200,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-04-30",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-30",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-04-30",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-03-31",
    "last_session": "2020-04-30",
    "observations": 21,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-04-30",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-02-04",
    "last_session": "2020-04-30",
    "observations": 61,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-04-30",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2020-03-30",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2020-04-30",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2020-01-30",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-06-30",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-29",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-06-30",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-01",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-06-30",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-01-03",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-06-30",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2021-09-20",
    "last_session": "2022-06-30",
    "observations": 200,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-06-30",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-03-31",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-06-30",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-02",
    "last_session": "2022-06-30",
    "observations": 21,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-06-30",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-04-05",
    "last_session": "2022-06-30",
    "observations": 61,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-06-30",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2022-06-01",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-06-30",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2022-03-31",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-07-29",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-07-28",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-07-29",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-30",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-07-29",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-02-01",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-07-29",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2021-10-19",
    "last_session": "2022-07-29",
    "observations": 200,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-07-29",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-05-03",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-07-29",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-07-01",
    "last_session": "2022-07-29",
    "observations": 21,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-07-29",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-05-06",
    "last_session": "2022-07-29",
    "observations": 61,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-07-29",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2022-06-30",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-07-29",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2022-05-03",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-08-31",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-08-30",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-08-31",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-08-02",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-08-31",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-03-04",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-08-31",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2021-11-19",
    "last_session": "2022-08-31",
    "observations": 200,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-08-31",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-03",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-08-31",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-08-03",
    "last_session": "2022-08-31",
    "observations": 21,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-08-31",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-08",
    "last_session": "2022-08-31",
    "observations": 61,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-08-31",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2022-08-02",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2022-08-31",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2022-06-03",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2023-11-30",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-11-29",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2023-11-30",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-11-01",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2023-11-30",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-06-07",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2023-11-30",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-02-21",
    "last_session": "2023-11-30",
    "observations": 200,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2023-11-30",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-09-04",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2023-11-30",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-11-02",
    "last_session": "2023-11-30",
    "observations": 21,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2023-11-30",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-09-07",
    "last_session": "2023-11-30",
    "observations": 61,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2023-11-30",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2023-11-01",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M10",
    "day": "2023-11-30",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2023-09-04",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-02-27",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-30",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-08-28",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "canary:ETF_EMERGING",
    "instrument": "ETF_EMERGING",
    "first_session": "2019-08-28",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "canary:ETF_WORLD",
    "instrument": "ETF_WORLD",
    "first_session": "2019-09-02",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "drawdown",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-11-27",
    "last_session": "2020-02-28",
    "observations": 63,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-05-16",
    "last_session": "2020-02-28",
    "observations": 200,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-11-26",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-31",
    "last_session": "2020-02-28",
    "observations": 21,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-11-29",
    "last_session": "2020-02-28",
    "observations": 61,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2020-01-30",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-02-28",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2019-11-26",
    "last_session": "2020-02-28",
    "observations": 2,
    "latest_available_at": "2020-02-28T16:30:00+00:00",
    "decision_at": "2020-02-28T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-03-30",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-03-02",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-09-27",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "canary:ETF_EMERGING",
    "instrument": "ETF_EMERGING",
    "first_session": "2019-09-27",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "canary:ETF_WORLD",
    "instrument": "ETF_WORLD",
    "first_session": "2019-10-02",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "drawdown",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-03",
    "last_session": "2020-03-31",
    "observations": 63,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-06-18",
    "last_session": "2020-03-31",
    "observations": 200,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-02",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-03-03",
    "last_session": "2020-03-31",
    "observations": 21,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-07",
    "last_session": "2020-03-31",
    "observations": 61,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2020-03-02",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-03-31",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2020-01-02",
    "last_session": "2020-03-31",
    "observations": 2,
    "latest_available_at": "2020-03-31T15:30:00+00:00",
    "decision_at": "2020-03-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-04-29",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-03-30",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-10-28",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "canary:ETF_EMERGING",
    "instrument": "ETF_EMERGING",
    "first_session": "2019-10-28",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "canary:ETF_WORLD",
    "instrument": "ETF_WORLD",
    "first_session": "2019-10-30",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "drawdown",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-31",
    "last_session": "2020-04-30",
    "observations": 63,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2019-07-16",
    "last_session": "2020-04-30",
    "observations": 200,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-01-30",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-03-31",
    "last_session": "2020-04-30",
    "observations": 21,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2020-02-04",
    "last_session": "2020-04-30",
    "observations": 61,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2020-03-30",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2020-04-30",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2020-01-30",
    "last_session": "2020-04-30",
    "observations": 2,
    "latest_available_at": "2020-04-30T15:30:00+00:00",
    "decision_at": "2020-04-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-29",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-01",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-01-03",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "canary:ETF_EMERGING",
    "instrument": "ETF_EMERGING",
    "first_session": "2022-01-03",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "canary:ETF_WORLD",
    "instrument": "ETF_WORLD",
    "first_session": "2022-01-03",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "drawdown",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-04-01",
    "last_session": "2022-06-30",
    "observations": 63,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2021-09-20",
    "last_session": "2022-06-30",
    "observations": 200,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-03-31",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-02",
    "last_session": "2022-06-30",
    "observations": 21,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-04-05",
    "last_session": "2022-06-30",
    "observations": 61,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2022-06-01",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-06-30",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2022-03-31",
    "last_session": "2022-06-30",
    "observations": 2,
    "latest_available_at": "2022-06-30T15:30:00+00:00",
    "decision_at": "2022-06-30T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-07-28",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-30",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-02-01",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "canary:ETF_EMERGING",
    "instrument": "ETF_EMERGING",
    "first_session": "2022-02-01",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "canary:ETF_WORLD",
    "instrument": "ETF_WORLD",
    "first_session": "2022-02-01",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "drawdown",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-05-04",
    "last_session": "2022-07-29",
    "observations": 63,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2021-10-19",
    "last_session": "2022-07-29",
    "observations": 200,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-05-03",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-07-01",
    "last_session": "2022-07-29",
    "observations": 21,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-05-06",
    "last_session": "2022-07-29",
    "observations": 61,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2022-06-30",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-07-29",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2022-05-03",
    "last_session": "2022-07-29",
    "observations": 2,
    "latest_available_at": "2022-07-29T15:30:00+00:00",
    "decision_at": "2022-07-29T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-08-30",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-08-02",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-03-04",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "canary:ETF_EMERGING",
    "instrument": "ETF_EMERGING",
    "first_session": "2022-03-04",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "canary:ETF_WORLD",
    "instrument": "ETF_WORLD",
    "first_session": "2022-03-04",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "drawdown",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-06",
    "last_session": "2022-08-31",
    "observations": 63,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2021-11-19",
    "last_session": "2022-08-31",
    "observations": 200,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-03",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-08-03",
    "last_session": "2022-08-31",
    "observations": 21,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2022-06-08",
    "last_session": "2022-08-31",
    "observations": 61,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2022-08-02",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2022-08-31",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2022-06-03",
    "last_session": "2022-08-31",
    "observations": 2,
    "latest_available_at": "2022-08-31T15:30:00+00:00",
    "decision_at": "2022-08-31T21:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "fresh",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-11-29",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "mom_21",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-11-01",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "mom_126",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-06-07",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "canary:ETF_EMERGING",
    "instrument": "ETF_EMERGING",
    "first_session": "2023-06-07",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "canary:ETF_WORLD",
    "instrument": "ETF_WORLD",
    "first_session": "2023-06-07",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "drawdown",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-09-05",
    "last_session": "2023-11-30",
    "observations": 63,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "ma_200",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-02-21",
    "last_session": "2023-11-30",
    "observations": 200,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "mom_63",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-09-04",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "vol_20",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-11-02",
    "last_session": "2023-11-30",
    "observations": 21,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "vol_60",
    "instrument": "ETF_NASDAQ",
    "first_session": "2023-09-07",
    "last_session": "2023-11-30",
    "observations": 61,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "ETF_MONETARY_EUR:carry",
    "instrument": "ETF_MONETARY_EUR",
    "first_session": "2023-11-01",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  },
  {
    "strategy": "M16",
    "day": "2023-11-30",
    "label": "ETF_GOLD:defense",
    "instrument": "ETF_GOLD",
    "first_session": "2023-09-04",
    "last_session": "2023-11-30",
    "observations": 2,
    "latest_available_at": "2023-11-30T16:30:00+00:00",
    "decision_at": "2023-11-30T22:00:00+00:00"
  }
]
```
