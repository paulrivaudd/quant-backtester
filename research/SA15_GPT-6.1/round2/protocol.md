# SA15_GPT-6.1 — seconde série : battre le S&P 500 conservé

Demande du propriétaire : dix itérations supplémentaires. Identifiants 11 à 20,
soit vingt configurations cumulées avec la première série. Les références
descriptives ne sont pas des candidats et ne sont jamais sélectionnées.

Objectif principal : croissance nette supérieure à ETF_SP500_PEA acheté une
fois puis conservé, sur mêmes dates, devise EUR, frais et capital. Le S&P 500
conservé demeure la référence même si une autre stratégie antérieure est faible.
Les jours comportant des ordres, le nombre d'ordres, les frais et la rotation
doivent être publiés pour juger si le travail demandé est justifié.

## Hypothèse avant premier essai de cette série

Un cœur permanent S&P 500 et une poche relative peuvent conserver la hausse
du marché tout en capturant les tendances de Nasdaq, or, émergents ou matières
premières. La poche revient au S&P 500 si aucun candidat ne le surpasse.
Score : moyenne pondérée de log(1+R_actif)-log(1+R_SP500), sur63/126/252 séances.
Le filtre absolu porte seulement sur les satellites. Aucun plafond de
volatilité global initial, aucun levier, aucune vente à découvert.

Décisions mensuelles après les clôtures, ouverture suivante, bande de poids
et tampon de classement pour limiter les échanges. Un contrôle de crise
éventuel constitue une variante explicite, jamais une protection ajoutée
après lecture du contrôle final.

## Indicateur et données

Le nouveau momentum utilise exclusivement les deux endpoints EXACTS du
calendrier propre au titre. Un trou intérieur ne rend pas le ratio indéfini.
Un endpoint absent refuse le signal ; aucun prix n'est comblé et aucune
fenêtre en observations n'est présentée comme une fenêtre en séances.
Ce nouveau contrat est testé avant le premier candidat. Les archives de la
première série et son indicateur strict restent inchangés.

Même magasin isolé, huit véhicules enregistrés ; la stratégie peut réellement
tenir S&P 500, Nasdaq, or (ETC), émergents, matières premières et monétaire.
Aucun téléchargement ni modification des prix n'est nécessaire.

## Périodes et choix

Développement : 2019-06-03 au2022-12-30. Sélection : 2023-01-02 au2024-12-31.
Contrôle chronologique : 2025-01-02 au2026-10-09, lu pour le gagnant après gel.
TOUTE cette histoire est déjà connue : ce contrôle est un rejeu rétrospectif,
pas un nouvel échantillon indépendant. Historique continu2019-2026 publié
après sélection, sans substitution du gagnant.

Pour chaque période, e = CAGR_candidat - CAGR_SP500.
Score = moyenne(e_dev,e_selection) -0.25*abs(e_dev-e_selection).
Une configuration qui bat S&P 500 dans LES DEUX périodes de choix est prioritaire
sur toute autre ; ensuite score décroissant, puis premier numéro en cas
d'égalité. Ce critère fait passer la surperformance nette avant le Sharpe.
Une moyenne positive ne doit pas cacher une période en sous-performance.

Qualification économique finale : surperformance nette du S&P 500 conservé
sur historique continu ET contrôle chronologique. Publier les frais doubles,
les redémarrages depuis cash et l'incertitude. Un avantage non confirmé est
déclaré insuffisant, sans onzième modification dans cette série.

## Comparaisons et coûts

100000 EUR, parts entières, commission5pb minimum1EUR, demi-spread3pb,
slippage2pb. Horaires/calendriers/moteur identiques à série1. Références :
S&P 500 conservé, Nasdaq conservé, 50% S&P500/50% Nasdaq conservés après
achat initial, et éventuels livres antérieurs pour contexte. Une prime
Nasdaq n'est pas automatiquement de l'alpha de timing.

Les configurations sont modifiées une à une après analyse, puis conservées
avec justification. Les tests de coûts doublés rejouent les mêmes politiques ;
ils ne sont pas de nouvelles configurations de sélection. Le DSR annonce
les20essais cumulés et leur corrélation ; il ne prouve pas la surperformance.

## Sources consultées avant cette série

- Antonacci : https://ssrn.com/abstract=2042750 (momentum relatif et absolu).
- Gârleanu/Pedersen : https://www.nber.org/papers/w15205 (transactions et coûts).
- MSCI : https://app2.msci.com/webapp/index_ann/DocGet?format=html&lang=en&pub_key=vXBeNkI7Sxg%3D (stabilité de portefeuille, transition graduelle).
- Forum : https://www.reddit.com/r/algotrading/comments/1v0ov4w/turbo_ldm_2x_leveraged_dual_momentum_w_fast/ (objection utile du contrôle Nasdaq simple ; nous n'adoptons pas le levier de la discussion).

Ces sources motivent des composants, pas les performances de notre adaptation.

Précision avant essai11 : première décision dès la première séance du run, puis fins de mois (ou de semaine pour une variante hebdomadaire). Cela permet l'achat initial à l'ouverture suivante comme les références, sans imposer artificiellement un mois initial en cash. Le calendrier propre du moteur reste inchangé.
