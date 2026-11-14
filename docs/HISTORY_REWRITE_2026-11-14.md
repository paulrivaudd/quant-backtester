# The history rewrite of 2026-11-14

On 2026-11-14, 32 commits made between 2026-11-07 and 2026-11-14 whose message
carried a `Co-Authored-By: Claude` line were rewritten without that line. A
commit contains the hash of its parent, so the 11 commits that followed or
merged them changed hash as well. 43 commits out of 301 are concerned, from
`b0951d5` onwards (now `165eb22`).

## Why it happened again

`.githooks/commit-msg` refuses such a line, but a clone has to enable it:
`git config core.hooksPath .githooks`. The repository was cloned afresh under
WSL on 2026-11-07 and the hook was not enabled there, so nothing refused the
commits made from that clone. It is enabled in it now. The attribution is also
switched off in the settings of the tool that added it.

## What changed, and what did not

- **Changed**: the hash of those 43 commits, and the line removed from 32
  messages. Five of the 43 were merge commits GitHub had signed; a rewritten
  commit cannot keep a signature made over its old content, so those five no
  longer show as verified.
- **Unchanged**, checked commit by commit: the tree (the code and the files),
  the parents once translated, the author, the committer, both dates, and the
  rest of each message. The tree of `main` is identical before and after.
- The branches `main`, `sa16-long-history`, `sa17-study`, `sa17-admission`,
  `sa17-mechanism` and `sa17-review-fixes` were rewritten together and
  force-pushed. No tag was concerned: `results-archive-2026-10-31` points to
  a commit before the first one rewritten.
- The descriptions of pull requests #6 to #10 lost their "Generated with
  Claude Code" line. Their pages still list the commits under their old hashes.

## What still cites an old hash

These files were not modified: a report says which commit produced it, and a
frozen design which commit froze it. The table below translates them.

- `CHANGELOG.md`: `15e67dc` became `099cf9d`, `3556e4d` became `6802d94`, `c372612` became `8ac0c2b`.
- `research/SA17/README.md`: `235b0bf` became `1b28777`, `98da1ef` became `b7fdade`.
- `research/SA17/admission.md`: `17d963e` became `522f768`, `2de9ed5` became `5d8cebe`.
- `results/SA17/mechanism/study.md` and `verdict.json`: `98da1ef` became `b7fdade`.
- `results/SA16/long_history/study.md` and `verdict.json`: `3556e4d` became `6802d94`.
- `results/SA16/levered_long_history/study.md` and `verdict.json`:
  `c372612` became `8ac0c2b`.

The code and the files of each pair are the same, so a run on the new commit
gives the same figures. A `run_id` that includes the commit differs. SA17's
executable runs are identified by the content of their producing files, not by
the commit, and are not affected.

The repository as it stood before the rewrite is kept outside it, in
`~/quant-snapshots/pre-rewrite-2026-11-14.bundle`.

## Mapping table

| Old hash | New hash |
|---|---|
| `b0951d5a6e477d9821c8b1ba2a90a5287d6d46f1` | `165eb227ff0f2f76216b40b8ec17781506c2e578` |
| `3dad72d8d67b569a53f84b1ed173f6e3ae89cfe3` | `88d0a7054c7d18e54ad21f4c52c5956faca7116c` |
| `79be156b61eca22a7a922d26ece903c6d6fcd420` | `78860e9baf7e4259f4bda9863c6d6d4b1035bc54` |
| `e2c3e394ae35fcdb539eb370e755671c11139eff` | `62316191fa654278e208626c1d9adc65af232bfc` |
| `5e5b767383bdf22939af7dfbc5194079d57e6ba2` | `193b3b1e6f0a617dcc25c0b4e3104a58b2bb1360` |
| `591443e89450aa3698706e65b8d6b7adb1b83212` | `17374502aa7f92921e43821c6c1a6a7583ddc48b` |
| `dac8d8dc1fd767e4c37d7538a81681e8abdef83a` | `15a4a93447d73e679673dbe5e5ac1da0b6918118` |
| `c02090434d12f64a626dc357529a21442b5d526e` | `dc6afae0376b6e453c0c4166798114a50d312d17` |
| `6bc4f7e5d9827166dc458ad69699dc4dd990a56a` | `fa931787e838d0c022232f9436a6cd0309a942a2` |
| `235b0bfae94d22282aebe81e4043163d68e184a9` | `1b287778e82c9053e2555e82a1a07692b52f4f3b` |
| `21dddd39b8c4b3a916b99329467a1c585deffeb7` | `78709a400301b77e888856e58efda73a02b8c3d8` |
| `1bc2fbd746245331682e509c0cf2548fa4ca0fb2` | `d160f6923800c02872346b60071a8eed2b60da06` |
| `98da1efcdedc7fed19ae23fd46cd97cabe17a55b` | `b7fdadeaedc75b0b3da907dd29ccae1a777dd7e6` |
| `d1b42737e649fa53e18c470e49191032ce13575b` | `4048d1e9620a6c9e55e4afd3972c0f9c36f6aeeb` |
| `8437a44dda140e04e49a5889848b3b02f55e3b55` | `4fb5ed5a7ba1fc3e1487d8939debcec466a51ed6` |
| `38b752540ded8206bbf820f247ba5f3ef75109c5` | `935fed99f08665ebbddd6ee573b010bdda120ee4` |
| `a3795dc6cd3f42201548a0ba7fcb91f86d1fb608` | `b2b7c53ec32642df332a0a31c5bc13cdb1ed1344` |
| `364e7e60b3c346fc235f01bee3e6218c0ec9fd95` | `4c3b230df9b3cc6fd887ab0ae3013999953bf81b` |
| `3aa7525ecd882bf12f4cbbadcaee02d2fc503836` | `5617eb6d420e8875d9aabbc8cc9053f92a75533d` |
| `b2cb0b4d012b9120efa773bd0db0dbe0b3ee0334` | `535ccb2c5cbfaac4ba1bf9e0f0cb7edf0a38a2e6` |
| `c4896da762a63df8fec8387fc47174ab78e3c955` | `47c74ee5a8edbbda43e046bc2147fc60500caf12` |
| `e46dd4c22d91482911742217fce21454c7a226b3` | `f1f60fe1804337a062a8fd19be4721e8beea7711` |
| `cb3be90ff93d2d99fc6100bab08796d202849591` | `4e7f070d7ebf944581dbc834d3394e852a3150a1` |
| `15e67dcb91e3e0540c79035f1f82fe21e0a44d03` | `099cf9d7619cec41018b08010dda5015acb34b5c` |
| `ada5edfb96085db0a0fc3e97f630f85a80954bdc` | `fc3e74d7480851fd467e1e2c1a5db5e38eb28574` |
| `03f793cb8bbeb01077a7c38bd69ea972c9463e04` | `a49b919221887ef0f3d2553e2a1dc3b2a3fd29c7` |
| `2de9ed586e2ebec0222ac311bb5314a74dba73a6` | `5d8cebe97603025bd6050242f4c7998f1c598d4f` |
| `ee8c4299161a236a876de1446af4badee066c674` | `e0f73e27103eb6a52f7bb3bfb5719c30b9743879` |
| `17d963e16b142022ab75953bf291d58cc408731e` | `522f768d954336da3402d2a42fd34d075236e57a` |
| `5273ba6bc5dac0104d2a6a2107daedcbdc579aaf` | `4a9ef0ccc8736b82cc59c8f2520d2e5512b632c1` |
| `64f43207a58d8ff5abb6019dc80bcedfb3d0b56d` | `f5f70c4882257b799ebca97dabd3a00e3ac862f2` |
| `725da0bde5b658fb10f210ffd8544967a4fa96f1` | `4cc4edd0aa911e60d2c6437ad039195c221693e9` |
| `6290c3e9c150ae39f20051bd8bea9f66f8c00e88` | `fb1dd9228b991a78c0e7f0d2edfab5687eb52b74` |
| `3556e4d81ff4d4c005d0324cc3e49d942eae1609` | `6802d94a126cca010f198ea7d5b9e17eb8577c10` |
| `fe10686c622d941310afcba516cae8a661bc09dd` | `300622daad6f7565a4cea3ac11feea5934557dd5` |
| `6b79b22eae5f59874dc4049259cacdc4abb9de10` | `86479368ceb7e5fcd8a2b4a85ef3196e88397d75` |
| `f3a6b3742fb7f55d20fb739c786e82b3d259f870` | `6a79e8132f7c52ed7db659d000007b40f6be605a` |
| `ed78eaff294b06f3e0a6a6009c688b34648d8923` | `d11227bc02d12dcce6fbe29ca90dcc9798964d71` |
| `c372612bebdd4a0b140488faade315c62b1136e9` | `8ac0c2bc5fd89db1c83c20e28a26b11daade2184` |
| `afe02fe146704c49cb412c8553354e60b6ed053f` | `87bc820fbc0727463c589c04189db04a6478c43f` |
| `bdb9349cb887dc874908e9e1a8519e2850ccf280` | `8c3ed351320ac8f0524cfd3d53a314e274da3a66` |
| `4467fec50af26340d471821bbe8f851affc8344e` | `c84f18c255559198c7adc4fc880d015de47fccc6` |
| `eacdb9651fee90b2627c9c243af567fa1744a525` | `d53962bb8938c932e17c8f9d7e70ceb9fc4de48d` |
