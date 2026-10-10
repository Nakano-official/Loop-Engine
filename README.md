# Loop Engine

AI に実装を任せるループを、テストの自己申告や権限逸脱に頼らず運用するための実験的な実行基盤です。

> [!IMPORTANT]
> **作り直しの途中です（2026-10-09〜）。** 設計の本体は [DESIGN.md](docs/DESIGN.md) です。
> 要求から、definer・designer が定義と設計を書き、本物のローカル 9B が実装し、**開けば動くアプリ（1つの HTML）が出る**
> ところまで通っています（2D と 3D）。ダッシュボードは `host\loop-dashboard.cmd`。
> 次にやることは [PROGRESS.md](docs/PROGRESS.md) にあります。

## 考え方

**定義と設計を部分的に、深く書く。そうすれば実装は狭い仕事になり、弱いモデルでも担える。**

- 要件を分析し、定義し、モジュール単位まで設計する。設計は関数の契約と**具体的な入出力の例**まで持つ
- **テストは機械が設計の例から生成する。** 期待値は誰も書かない ── テストは書き写しにすぎない
- 実装はローカルの 9B モデルが行う
- テストが落ちたら、**落ちた場所で、どの段が悪かったかが決まる**（実装・テスト・設計・定義）。判定は機械が行う
- 判断するもの（LLM と生成コードの実行）はサンドボックスの中、判断しないもの（流れ・判定・台帳）はホストに置く
- **役は uid です。** 何を見られるかはプロンプトの約束ではなくファイルシステムが決める
- 言語に依存しない。言語ごとの差は**アダプタ**に閉じ込める（Python・TypeScript・Go・Rust・Java・Ruby・PHP・Perl・C/C++）

```
要件分析 → 要件定義 → モジュール設計 → テスト生成 → 実装 → デバッグ
   ▲           ▲             ▲              ▲          ▲        │
   └───────────┴─────────────┴──────────────┴──────────┴────────┘
                  落ちた場所が、戻り先の段を指す
```

## 役

| 役 | 担い手 | 書けるもの | 要点 |
|---|---|---|---|
| definer / designer | Claude | 自分の `out/` | 定義と設計。**別の uid** ── 同じ主体が両方書くと突き合わせが形だけになる |
| tester | Claude | 自分の `out/` | 支援モジュール（偽物・ヘルパ）だけ。テストは機械が生成する |
| solver | ローカルの 9B | 自分の `out/` | 実装。通信は loopback の 8080（llama-server）だけ |
| exec | ── | 記録だけ | テストと生成コードの実行。作業場を**読むだけ**。通信なし |
| critic | Claude | 自分の `out/` | 欠陥の指摘。**読めないことが役の価値** |
| runner | ── | 作業場 | 窓口。SSH の鍵では `loop-window` しか開かない |

どの役も作業場には書きません。役は自分の `out/` に書き、窓口が検査して作業場へ写します。
全部の役を全部の場所で試す検査（920 項目）が、プロビジョンの一部として毎回走ります。
詳細は [provision/README.md](provision/README.md)。

## 今の状態

| | |
|---|---|
| **できた** | 設計（[DESIGN.md](docs/DESIGN.md)・[SYSTEM.md](docs/SYSTEM.md)・[FORMATS.md](docs/FORMATS.md)）/ サンドボックスのプロビジョン（役の表から生成・総当たりの検査・通信制限・窓口）/ 9言語のツールチェーン / Python と TypeScript のアダプタ / 出口の関門・diagnose・pipeline（`engine/`）/ **要求から definer・designer・9B を通して1つの HTML を出力**（2D の放置ゲーム、3D の迷路）/ 複数アプリの置き場とダッシュボード（`host/dashboard`） |
| **次** | 外側の輪: 要求分析と概念ファイル → 評価 → 続きから → 改良の輪（[DESIGN.md](docs/DESIGN.md) §4〜§6、[PROGRESS.md](docs/PROGRESS.md)） |

## これまでの実績（旧い形で得たもの）

作り直しの前、旧い形（プランナー・ランナー・ソルバー・クリティック）で、題材のアイドルゲームを
**要件6行から11ステップ、人間の介在ゼロで**通し切っています。

**run 5 と run 6 ── 同じ計画で、ソルバーだけを入れ替えた統制実験**

| | run 5（Codex） | run 6（ローカル Qwen3.5-9B） |
|---|---|---|
| 無介入の緑 | 11/11 | **11/11** |
| ステップあたりの試行 | ほぼ1 | **1** |
| エスカレーション | 1回 | **0** |
| 実行時間 | 19分37秒 | **15分12秒** |
| 人間の介在 | ゼロ | ゼロ |

弱いソルバーでも結果が落ちなかったことが、「合格基準を外に置けば、満たす側の質は結果を支配しない」
という主張の検証になりました。一方 run 8 では、範囲が広すぎると弱いモデルが落ちること、
そして**未解決の失敗3件がどれもテスト側の誤りだった**ことが分かり、それが今回の作り直しの出発点です
（[DESIGN.md](docs/DESIGN.md) §3・§5）。旧設計の文書は消しました（git の履歴（`6a03828` 以前）に残る）。

## ドキュメント

1. [docs/DESIGN.md](docs/DESIGN.md) — 何を作っているか（設計の本体）
2. [docs/SYSTEM.md](docs/SYSTEM.md) — どこに置き、どう守るか
3. [docs/DECISIONS.md](docs/DECISIONS.md) — 決まったことと、決まっていないこと
4. [docs/PROGRESS.md](docs/PROGRESS.md) — 進み具合と、次にやること
5. [docs/FORMATS.md](docs/FORMATS.md) — 定義・設計・概念ファイル・記録の形
6. [provision/README.md](provision/README.md) — WSL2 サンドボックスの構築・検証手順と落とし穴
7. [host/README.md](host/README.md) — Windows 側の起動、keepalive、SSH 設定
8. [docs/LOCAL_SOLVER.md](docs/LOCAL_SOLVER.md) — ローカルモデルを solver に据える手順と失敗表

## リポジトリ構成

```text
.
├── README.md
├── docs/
│   ├── DESIGN.md          # 設計の本体
│   ├── SYSTEM.md          # 置き場と守り方
│   ├── DECISIONS.md       # 決まったこと・決まっていないこと
│   ├── PROGRESS.md        # 進み具合・次にやること
│   ├── FORMATS.md         # 定義・設計・概念ファイル・記録の形
│   ├── formats/examples/  # 放置ゲームとコイン集めを今の形で書いた見本
│   └── LOCAL_SOLVER.md    # ローカルモデルの手順
├── engine/                # ホストの流れ（pipeline.py）と部品: 関門・判定・ブリーフ・窓口・アプリの置き場
├── adapters/
│   ├── design.py          # 言語に依らない中核
│   ├── python/            # Python のアダプタ（比較関数・生成器）と適合テスト
│   ├── typescript/        # TypeScript のアダプタと適合テスト（放置ゲーム・コイン集め）
│   └── platforms/         # browser-dom・browser-3d: 汎用シェル・ページ・起動確認
├── provision/
│   ├── roles.json         # 役の表 ── 正本
│   ├── roles.py           # 表から生成し、総当たりで検査する
│   ├── provision.sh       # 入口（05 → 10 → 15 → 25 → 30/35/36 → 45 → 40 → 50）
│   └── bin/               # 起動スクリプト、loop-window、ローカルソルバー
└── host/                  # Windows 側：起動、keepalive、ミラー（loop-pull.cmd）
    └── dashboard/         # アプリ・通し・出力・承認のダッシュボード
```

## 環境構築について

対象環境は Windows 上の WSL2 `Ubuntu-24.04` です。構築作業はホストや WSL の設定、SSH 鍵、ユーザー権限、ネットワーク制御を変更します。コマンドを抜粋して実行せず、先に [provision/README.md](provision/README.md) の前提、手順、既知の落とし穴を通して確認してください。

WSL2 は既定のままでは隔離環境ではありません。この構成では Windows ドライブの自動マウント、Windows 実行ファイルとの相互運用、WSLg を明示的に無効化し、プロビジョニング後に状態を検証します。
