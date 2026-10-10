# ドキュメント

Loop Engine の設計・運用ドキュメントです。

## 今の設計

1. [DESIGN.md](DESIGN.md) — **何を作っているか（設計の本体）。** 目的、流れ、要求分析と概念ファイル、
   落ちた場所で悪い段が分かるデバッグ、外側の輪（評価と改良）、言語とプラットフォーム
2. [SYSTEM.md](SYSTEM.md) — **どこに置き、どう守るか。** ホストと箱、役と uid、窓口、正本と台帳、箱の作り方の考え方、ダッシュボード
3. [DECISIONS.md](DECISIONS.md) — 決まったこと（いつ・何を・なぜ）と、決まっていないこと
4. [PROGRESS.md](PROGRESS.md) — 進み具合。済んだこと、通しの結果、**次にやること**
5. [FORMATS.md](FORMATS.md) — 定義・設計・概念ファイル・記録の形。例は [formats/examples/](formats/examples/)
6. [LOCAL_SOLVER.md](LOCAL_SOLVER.md) — ローカルモデルを solver に据える手順と失敗表

どの文書も、それだけで読めるように書く（DESIGN §4）。ほかの文書へのリンクは道案内で、意味をそこに預けない。

環境別の手順は [provision/README.md](../provision/README.md)（サンドボックス）と
[host/README.md](../host/README.md)（Windows ホスト）。

## 旧設計の記録

2026-10-09 に設計を作り直した。それまでの形（プランナー・ランナー・ソルバー・クリティック、
`tasks.json`、`runner/loop.py`）の文書（ARCHITECTURE・BOOTSTRAP・RUNNER_SPEC・HANDOFF）は
2026-10-10 に消した。git の履歴（`6a03828` 以前）に残る。取り出すときは `git show 6a03828:docs/archive/HANDOFF.md` のように。
