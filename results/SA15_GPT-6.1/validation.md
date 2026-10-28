# Validation de SA15_GPT-6.1

- Suite globale hors réseau : 3514 tests réussis, 19 exclus, un échec dans le test qui recense les exports de stratégies. Ce test ne connaissait pas encore SA15.
- Après ajout de SA15 au recensement : 61 tests ciblés passent (exports, étude, robustesse), dont les tests du correctif de dates et du mode de rendu sans backtest.
- Les tests de stratégie et catalogue avaient également passé ; les nouveaux comportements financiers, le garde-fou contre les données futures et l'architecture ont été vérifiés.
- Ruff check et format --check : les 12 fichiers Python concernés passent.
- 10 configurations, chacune en développement et sélection, puis 20 vrais rejouages aux frais doubles ; 4 vrais redémarrages depuis cash ; 5 livres sur l'historique continu.
- Contrôle final de la configuration figée et son stress de frais exécutés une seule fois chacun. Une erreur de type d'index à l'export a été corrigée ensuite ; le mode --render-only a produit les graphiques et statistiques relatives à partir des courbes sauvegardées, sans rejouer les transactions.
- Courbes de l'historique complet et du contrôle final inspectées visuellement.
- Le code et les métadonnées originaux sont conservés dans source/. Le correctif du rendu, ses tests et ses empreintes sont dans postprocessing/. Aucun prix, ordre, poids, coût ou rendement financier déjà calculé n'a été remplacé.

Le statut de l'hypothèse économique contre World est NOT_SUPPORTED. Le meilleur essai réduit le risque et surpasse SA1, mais ne dépasse pas World en rendement absolu. Le panier équipondéré fait également mieux sur la période finale.
