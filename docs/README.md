# ドキュメント

Loop Engine の設計・運用ドキュメントです。

## 今の設計

1. [REDESIGN.md](REDESIGN.md) — **何を作っているか。** 定義と設計を深くして、実装を弱いモデルに任せる。
   落ちた場所で悪い段が分かるデバッグ、言語のアダプタ、役と窓口、プロビジョン。
   §10 に決まったことと、**再開点**がある
2. [FORMATS.md](FORMATS.md) — 定義と設計の形、記録の形。例は [formats/examples/](formats/examples/)
3. [LOCAL_SOLVER.md](LOCAL_SOLVER.md) — ローカルモデルをソルバーに据える手順と失敗表

環境別の手順は [provision/README.md](../provision/README.md)（サンドボックス）と
[host/README.md](../host/README.md)（Windows ホスト）。

## 旧設計の記録

2026-10-09 に設計を作り直した。それまでの形（プランナー・ランナー・ソルバー・クリティック、
`tasks.json`、`runner/loop.py`）の文書（ARCHITECTURE・BOOTSTRAP・RUNNER_SPEC・HANDOFF）は
2026-10-10 に消した。git の履歴（`6a03828` 以前）に残る。取り出すときは `git show 6a03828:docs/archive/HANDOFF.md` のように。
