# ドキュメント

Loop Engine の設計・運用ドキュメントをまとめています。

初めて読む場合は、次の順番を推奨します。

1. [ARCHITECTURE.md](ARCHITECTURE.md) — **この機械は何でできているか**（役、位相、輪、繰り返す失敗の形）
2. [BOOTSTRAP.md](BOOTSTRAP.md) — 設計思想とプランナー向けの開始手順
3. [RUNNER_SPEC.md](RUNNER_SPEC.md) — ランナーの仕様
4. [LOCAL_SOLVER.md](LOCAL_SOLVER.md) — ローカルソルバーの導入と運用
5. [HANDOFF.md](HANDOFF.md) — 現在地、未完了項目、再開時の注意

作り直しの設計（未実装）:

- [REDESIGN.md](REDESIGN.md) — 定義と設計を深くして、実装を弱いモデルに任せる。これから何を変えるか
- [FORMATS.md](FORMATS.md) — 定義と設計の形（たたき台）。例は [formats/examples/](formats/examples/)

環境別の手順は、それぞれ [provision/README.md](../provision/README.md) と [host/README.md](../host/README.md) を参照してください。
