# Market data — les exercices d'implémentation

**Tous terminés.** Le module a été construit en remplissant des corps de
fonction qui levaient `NotImplementedError("Exercice N.x")`, chacun décrit par
la section `Notes` de sa docstring — indications, pièges, test associé. Ces
notes sont restées en place : elles disent pourquoi le code est ce qu'il est, et
c'est la seule documentation de conception au niveau de la fonction.

Ce fichier garde l'ordre dans lequel le module a été écrit, les trois tests qui
comptent et les trois invariants. Rien ici n'est un reste : c'est ce qu'il faut
relire avant de toucher à la couche.

## L'ordre suivi

Il n'était pas arbitraire : chaque étape est testable hors ligne avant que la
suivante ne s'appuie dessus.

| # | Module | Contenu | Difficulté |
|---|---|---|---|
| 1 | `instruments.py` | registre, règles de publication, dates de cotation | facile |
| 2 | `calendars.py` | sessions, ouverture et clôture réelles en UTC | **moyen — à faire en premier** |
| 3 | `repository.py` | écriture atomique, raw immuable, clean | facile |
| 4 | `sources/` | adaptateurs fournisseurs | moyen |
| 5 | `normalizer.py` | frames fournisseur → schémas canoniques | moyen |
| 6 | `validator.py` | règles typées par instrument | moyen |
| 7 | `revisions.py` | détection ≠ décision | moyen |
| 8 | `reader.py` | lecture point-in-time, masquage par champ | **difficile** |
| 9 | `updater.py` | pipeline d'ingestion, rebuild | difficile |

`calendars.py` d'abord, malgré l'envie de commencer par Yahoo : c'est lui qui produit `open_available_at_utc` et `close_available_at_utc`. Tant qu'il est faux, tout ce qui est écrit en aval doit être réécrit — et il se teste entièrement hors ligne, sur une poignée de dates choisies.

## Les trois tests qui comptent

Ils sont dans `tests/`, et ce sont eux qu'il faut relancer en premier après un
changement de la couche.

1. **Masquage par champ** — `tests/data/test_reader.py::test_field_masking_follows_the_session`
   À 23:00 Paris le jour *t*, le reader expose le close de *t* et refuse l'open
   de *t+1* ; à 09:01 le jour *t+1*, l'inverse.

2. **Garde anti-look-ahead** — `test_future_data_does_not_change_the_past`
   Ajoute des barres **et un split** postérieurs à la date de décision, rappelle
   le même reader : résultat identique octet pour octet.

3. **Idempotence du rebuild** — `tests/data/test_updater.py::test_rebuild_is_idempotent`
   Deux `rebuild_clean()` consécutifs produisent des fichiers identiques. C'est
   celui qui prouve qu'il n'y a aucun état caché dans la chaîne.

## Vérifications avant chaque commit

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest && uv run pyright
```

Aucun test n'est marqué `skip` et il ne reste aucun `NotImplementedError` : un
exercice n'était terminé que lorsque son test passait.

## Les trois invariants à ne pas perdre de vue

Si une implémentation t'oblige à en violer un, c'est l'implémentation qui est
fausse, pas l'invariant.

1. **La disponibilité est portée par le champ, pas par la ligne.** L'open est
   connu à l'ouverture, le close à la clôture. Un seul horodatage par ligne
   cacherait le prix d'exécution au moteur ou fuiterait le close à la stratégie.

2. **Rien de restaté n'est stocké.** Pas d'`adj_close`. Prix bruts plus table
   d'actions, ajustement calculé à la lecture avec les seules actions connues à
   la date de décision.

3. **Le clean est dérivé.** `raw` + `instruments.toml` + `accepted_revisions.toml`
   + calendriers + version du normalizer détermine entièrement `clean/`. Il doit
   pouvoir être supprimé et reconstruit à l'identique.
