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
`tasks.json`、`runner/loop.py`）の文書は [archive/](archive/) にある。手順としては今の箱で
動かないが、規則の一つ一つに run が1本ずつ紐づいており、なぜ今の形になったかはそこにある。

- [archive/ARCHITECTURE.md](archive/ARCHITECTURE.md) — 旧い形の全体像と、繰り返し出てきた失敗の形
- [archive/BOOTSTRAP.md](archive/BOOTSTRAP.md) — 旧い設計思想とプランナー向けの手順
- [archive/RUNNER_SPEC.md](archive/RUNNER_SPEC.md) — 旧いランナーの関門とリンタ規則
- [archive/HANDOFF.md](archive/HANDOFF.md) — run 1〜8 の日誌
