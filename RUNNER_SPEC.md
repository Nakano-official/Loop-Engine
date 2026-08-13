# RUNNER_SPEC.md — ループランナー仕様

BOOTSTRAP.md の 1-2 / 1-3 / 1-4 / 1-5 および `files_write` 許可リストを、
**文章ではなく機構として**実装するためのプログラムの仕様。

対象読者は、このランナーを実装する人間（初版は手書きし、捨てる前提）。

---

## 0. 位置づけ

### 0-1. 三者の配置

| 主体 | 実行場所 | 権限 | 見えるもの |
|---|---|---|---|
| プランナー | **ホスト (Windows)** | — | 人間との対話、`plan/` の生成、ESCALATION.md の判定 |
| ランナー | ゲスト VM / `runner` ユーザー | リポジトリ全体の所有、git、sudo なし | tasks.json 全体、台帳、テスト結果 |
| ソルバー | ゲスト VM / `solver` ユーザー | 限定的な書き込みのみ | ランナーが組み立てた1ステップ分のブリーフだけ |

**プランナーは VM に入らない。ソルバーは plan/ を書けない。**
この2つが崩れると以下の全部が意味を失う。

### 0-2. 非目標

- ソルバーの実装（Codex CLI 等をサブプロセスとして呼ぶだけ）
- LLM API の抽象化（1種類決め打ちでよい）
- 並列実行（ステップは全順序で1本ずつ）
- VM の作成・スナップショット操作（ホスト側の別スクリプトの責務。§1-5）

### 0-3. 設計原則

> **検知より剥奪。** ある関門を「違反を検知して止める」で実装できるときと
> 「そもそも実行不能にする」で実装できるときは、後者を選ぶ。
> 検知は二重化のためのトリップワイヤとしてのみ併置する。

BOOTSTRAP.md 1-7 の考え方を、テスト凍結と許可リストにも適用する。

---

## 1. 実行環境

### 1-1. VM

- VirtualBox 7.x / Ubuntu Server 24.04 LTS / GUI なし
- 2 vCPU / 4 GB RAM / 20 GB
- **Guest Additions と共有フォルダは入れない**（理由は 1-4）
- ネットワークアダプタは **NAT 1枚**
  - 外部への egress（LLM API 用）
  - ホストからの SSH / git push/pull は **ポートフォワード `127.0.0.1:2222` → ゲスト `22`**

> 当初はホストオンリーアダプタを併用する構成にしていたが、Windows では
> ホストオンリーアダプタの作成に管理者権限での昇格（ネットワークドライバの
> インストール）が要る。ポートフォワードなら昇格不要で、失われる性質もない
> ── 「ソルバーが git 経路に触れられない」は**鍵を持たせないこと**で担保しており、
> ネットワーク構成には依存していない。

### 1-2. ユーザーとファイル所有

```
runner : uid 1001. リポジトリ全体を所有。sudo なし。SSH 鍵あり。
solver : uid 1002. sudo なし。SSH 鍵なし。他ユーザーの $HOME 参照不可。
```

リポジトリは **`/srv/loop/` に置く。どちらの home にも置かない。**
`/home/runner/project` にすると、solver が project に降りるために `/home/runner` に
通過権限が必要になり、home を 700 にできなくなるため。

```
/srv/loop/
  repo.git/         bare。ホスト（プランナー）が push、runner が pull
  project/          ループが回る作業ツリー
  brief/            runner → solver の唯一の受け渡し口（§5）
```

`/srv/loop/project` 配下の権限（`X` = ステップ位相により変化）:

| パス | 所有 | モード | solver から |
|---|---|---|---|
| `.git/` | runner:runner | 700 | **不可**（読みも不要） |
| `plan/` (tasks.json, CONTEXT.md, ledger.jsonl) | runner:runner | 700 | **不可** |
| `.runner/` (凍結マニフェスト) | runner:runner | 700 | **不可**（何を照合しているか見せない） |
| `tests/` | runner:solverw | `X`: 2775 → **555** | TEST_WRITE 中のみ書、FREEZE 以降 読のみ |
| `src/` | runner:solverw | 2775 | 書（§4-4 の経路チェックあり） |
| `conftest.py`, `pytest.ini`, `pyproject.toml` | runner:runner | 644 | 読のみ（常時） |
| `.venv/` | runner:runner | 755 | 読・実行のみ、**書不可** |
| `/srv/loop/brief/` | runner:solverw | 750 | 読のみ |

CONTEXT.md も含め **solver は `plan/` に一切アクセスしない**。ソルバーが受け取るのは
runner が `brief/` に組み立てたその1ステップ分のブリーフだけ（§5）。
これで「tasks.json を覗く」経路が権限レベルで存在しなくなる。

ソルバーは `solver` グループ経由で `src/` にのみ書き込む。
テスト凍結（1-3）は **FREEZE 位相で `chown runner:runner tests/ && chmod -R a-w tests/`**
によって実装する。ハッシュ照合は二重化のトリップワイヤであって主機構ではない。

### 1-3. sudo を渡さない理由が VM では変わる

VirtualBox の中では、仮に root を取られてもホストへの被害はほぼない。
したがって `solver` を sudo なしにする目的は**安全性ではなく再現性**である。

`apt install` や `pip install` が通ってしまうと、CONTEXT.md に書かれた環境と
実際の環境が乖離し、green が再現不能になる。**環境の変更は必ずエスカレーションとして
表面化させる**（= 詰まったので勝手に入れた、を検出可能にする）ことが目的。

この目的のため、`solver` の egress も塞ぐ:

```
# 既定 DROP、プロキシ経由のみ許可（uid ベース）
iptables -A OUTPUT -m owner --uid-owner solver -o lo -j ACCEPT
iptables -A OUTPUT -m owner --uid-owner solver -d <proxy> -p tcp --dport 3128 -j ACCEPT
iptables -A OUTPUT -m owner --uid-owner solver -j DROP
```

ローカルの許可ドメインのみ通すフォワードプロキシ（tinyproxy 等）を `runner` で動かし、
許可先は **LLM API のドメインのみ**。PyPI も apt も通らない。

> v1 簡易版: プロキシを立てず、`--uid-owner solver` で DNS(53) と API の IP のみ ACCEPT。
> IP 変動で壊れるので、壊れたら上の構成に上げる。

### 1-4. 共有フォルダを使わない理由

vboxsf はパーミッションを正しく持たない。`tests/` を solver から書き込み不可にする
（1-2 の主機構）が成立しなくなる。**リポジトリはゲストのネイティブ ext4 上に置く。**

ホストとの受け渡しは git 経由（§2）。ホストから編集したい場合は
VS Code Remote-SSH でホストオンリーアダプタ越しに繋ぐ。

### 1-5. スナップショットと git の役割分担

| 壊れたもの | 戻し方 |
|---|---|
| コード（green ステップを捨てる = 1-4(c)） | **git**。ステップ単位のコミットとタグ |
| 環境（何かが入った・壊れた） | **VBox スナップショット**。ホスト側から `VBoxManage snapshot` |

ランナーはスナップショットを操作しない。
プロビジョニング直後に `base` スナップショットを取っておくこと。

---

## 2. ホストとの境界

```
ホスト (Windows)                    ゲスト VM
─────────────────                   ─────────────────
プランナー(Claude Code)
  └ plan/ を編集
     ↓
  作業クローン  ──push──▶  /srv/loop/repo.git (bare, runner 所有)
                                    │
                                    │ runner が pull
                                    ▼
                          /srv/loop/project ──── ランナー & ソルバー
                                    │
  作業クローン  ◀──pull──────────────┘  (green コミット、ledger、ESCALATION.md)
```

- bare リポジトリはゲスト上に置き、ホストからは SSH で push/pull（`runner` 鍵）
- **`solver` は SSH 鍵を持たないので、この経路に触れられない**
- プランナーが書き込んでよいのは `SYSTEM_SPEC.md` / `plan/CONTEXT.md` / `plan/tasks.json` のみ。
  ランナーは pull 時にそれ以外の差分を検出したら停止する（プランナー側の暴走検知）

---

## 3. ステップのライフサイクル

1ステップは以下の位相を持つ。位相は `plan/ledger.jsonl` に記録され、中断しても再開できる。

```
 PLAN_LOAD
     │  tasks.json 検証・依存解決・ブリーフ組み立て
     ▼
 TEST_WRITE            ソルバー呼び出し #1（テストのみ書かせる）
     │                 書込許可: files_test のみ
     ▼
 STUB                  ソルバー呼び出し #2（スタブのみ書かせる）
     │                 書込許可: files_write のみ
     │                 指示: 「契約通りのシグネチャで、意図的に誤った値を返す」
     ▼
 RED_GATE ────────────▶ 不合格 → ESCALATE
     │  §4-1
     ▼
 REVIEW_GATE           人間がテストコードだけを1回見る（設定で無効化可）
     │  §4-2
     ▼
 FREEZE                tests/ を読み取り専用化 + マニフェスト採取
     │  §4-3
     ▼
 IMPL ◀───┐            ソルバー呼び出し #3..（実装）
     │     │           書込許可: files_write のみ
     ▼     │
 VERIFY ───┘ 不合格かつ attempt < max_attempts
     │  §4-4
     ▼
 GREEN                 コミット + タグ + contracts 確定
```

**位相ごとにソルバーの呼び出しを分ける**のは、テストを書く文脈と実装を書く文脈を
混ぜないため。TEST_WRITE のソルバーには `goal` を渡さない（acceptance と contracts のみ）。

---

## 4. 関門の判定条件

判定はすべて機械可読な事実に基づく。人間の判断が入るのは REVIEW_GATE のみ。

テスト実行は常に:

```
.venv/bin/pytest <files_test...> \
  --junitxml=.runner/report.xml \
  -p no:cacheprovider \
  --strict-markers -q
```

判定は **exit code ではなく junit XML** を読んで行う。

### 4-1. RED_GATE（BOOTSTRAP 1-2 の実装）

以下を**すべて**満たすときのみ合格:

| # | 条件 | 防ぐもの |
|---|---|---|
| R1 | 収集されたテスト数 == `expected_tests` | テスト0件 / 水増し / 不足 |
| R2 | `<error>` 要素が **0 件** | 収集エラー・ImportError を red と誤認 |
| R3 | `skipped` が **0 件** | 全 skip の exit 0 |
| R4 | 全テストが `<failure>` を持つ | 一部が既に通っている＝テストが自明 |
| R5 | 全 `<failure>` の `type` が `AssertionError` または `Failed` のみ | 下記 |

**R5 が本体。** `ImportError` / `ModuleNotFoundError` / `AttributeError` / `TypeError` /
`NameError` での失敗は **red と認めない**。

これにより、赤の意味が「まだ実装がない」から
**「呼び出しは全部成立していて、値だけが違う」**に変わる。
副次的に、実装を1行も書く前に**契約のシグネチャが正しいことが検証される**。

不合格時の扱い:
- R5 違反（AttributeError 等）→ STUB をやり直させる（`stub_attempts` 上限 2）
- R1 違反 → テストと `expected_tests` の不一致。**プランナーへエスカレーション**
- R4 違反（スタブが通ってしまった）→ テストが自明。**プランナーへエスカレーション**

### 4-2. REVIEW_GATE（任意・既定 ON）

ランナーは `files_test` の内容と `acceptance` を並べた差分を出力して停止する。
人間は「このテストは受け入れ条件を符号化しているか」だけを見る。**実装は見ない。**

- 承認 → `runner approve --step <id>` で FREEZE へ
- 却下 → TEST_WRITE からやり直し（`review_rejections` を台帳に記録）

これは BOOTSTRAP 1-1 の唯一の漏れ口（受け入れ条件→テストコードの翻訳を
ソルバーが単独で行う）に対する関門。1ステップあたり数分で、凍結前の1回だけ。

`review_gate: false` にできるが、その場合 `acceptance` は全項目が
具体値（given の数値と then の期待値）を持つことをリンタが要求する（§8）。

### 4-3. FREEZE（BOOTSTRAP 1-3 の実装）

**主機構（剥奪）:**
```
chown -R runner:runner tests/
chmod -R a-w tests/
chmod a-w conftest.py pytest.ini pyproject.toml   # 存在するもの
```

**トリップワイヤ（検知）** — `.runner/freeze/<step_id>.json` に記録:

| 記録項目 | 検出できる細工 |
|---|---|
| `files_test` 各ファイルの sha256 | 直接の書き換え |
| 全階層の `conftest.py` の sha256 と**存在しないパスの一覧** | conftest の新規追加による fixture 差し替え |
| `pytest.ini` / `pyproject.toml` / `tox.ini` / `setup.cfg` の sha256 | `addopts`、収集ルート、マーカーの改変 |
| `--collect-only -q` のテスト ID 全集合の sha256 | 件数を保ったままの入れ替え |
| `expected_tests` | 削除 |
| `pip freeze` の sha256 | 環境の変更 |

「存在しないパスの一覧」は重要。ハッシュは**あるファイル**しか守らないので、
`tests/conftest.py` や リポジトリ直下の `sitecustomize.py` の**新規作成**が素通りする。

### 4-4. VERIFY（IMPL の各試行後）

順に判定し、最初に落ちた時点で打ち切る:

1. **凍結整合** — `.runner/freeze/<step_id>.json` を再照合。1つでも不一致 → **即エスカレーション**（リトライしない。テストに手を入れた事実は試行回数の問題ではない）
2. **経路許可** — `git status --porcelain --untracked-files=all` の全パスが `files_write` に含まれるか。含まれないパスが1つでもあれば → 即エスカレーション
3. **テスト結果** — `<error>` 0、`skipped` 0、収集数 == `expected_tests`、`<failure>` 0
4. 3 が不合格 → `attempt += 1`。`attempt < max_attempts` なら IMPL に戻る

2 は権限だけでは足りない部分（`src/` 内で宣言外のファイルを作る）を埋めるための検知。
`.git/` と `tests/` と `plan/` は権限で既に守られている。

### 4-5. GREEN

```
git add -A
git commit -m "step(<id>): <goal 1行>"
git tag step/<id>
```

`contracts.provides` を `.runner/contracts/<id>.json` に確定保存。以降のステップは
**この確定済み contracts のみ**を参照する（tasks.json の記述ではなく）。

---

## 5. ブリーフの組み立て（BOOTSTRAP 1-5 の実装）

ソルバーに渡す入力は、位相ごとに以下だけ。**tasks.json 全体は渡さない。**

```
[TEST_WRITE]
  plan/CONTEXT.md（静的・100行以内）
  当該ステップの acceptance[]
  depends_on から解決した contracts（.runner/contracts/*.json）
  files_test のパス一覧
  ※ goal は渡さない

[STUB]
  当該ステップの contracts.provides
  files_write のパス一覧
  ※ acceptance も goal も渡さない（テストを覗いて誤魔化す余地を消す）

[IMPL]
  plan/CONTEXT.md
  当該ステップの goal
  depends_on から解決した contracts
  凍結済みテストの内容（読み取り専用）
  直近の失敗した pytest 出力（当該ステップ内の前試行のみ）
  files_write のパス一覧
```

**入力量はステップ番号に依存しない**（`depends_on` の数にのみ依存する）。
BOOTSTRAP 1-5 の「1回あたりの入力量が一定」はここで実現される。

CONTEXT.md に contracts を蓄積してはならない。CONTEXT.md は静的。

---

## 6. エスカレーションと再開（BOOTSTRAP 1-4 の実装）

### 6-1. 台帳 `plan/ledger.jsonl`（追記専用・runner 所有）

```jsonl
{"ts":"2026-08-13T10:22:31Z","step":"03","phase":"RED_GATE","result":"pass","tests":5}
{"ts":"...","step":"03","phase":"VERIFY","attempt":1,"result":"fail","failed":["test_empty_query"]}
{"ts":"...","step":"03","phase":"ESCALATE","reason":"max_attempts","escalation_no":1}
{"ts":"...","step":"03","phase":"GREEN","commit":"a1b2c3d","escalation_no":1}
```

**プランナーはセッションを跨いで記憶を失う**ので、これが唯一の履歴。
再開時、ランナーは台帳から現在位相を復元する。

### 6-2. エスカレーション自体の上限

BOOTSTRAP 1-4 は試行の上限しか定めていないため、(a) を繰り返す外側のループが無限になる。

> **同一ステップの `escalation_no` が 2 以上のとき、(a)「goal の書き方を締める」を禁止する。**
> 選べるのは (b) 受け入れ条件の書き直し、または (c) 上流からの作り直しのみ。

ランナーは ESCALATION.md にこの制約を明記して出力する（プランナーが忘れても効くように）。

### 6-3. 失敗した実装の扱い

```
git checkout -b escalate/<step_id>/<escalation_no>
git add -A && git commit -m "escalated attempt"
git checkout <last green> && git reset --hard
```

失敗した実装は**ブランチに保存し、プランナーだけが読む**。
再開時のソルバーには渡さない ── 壊れた方針への固着を避けるため。
ソルバーは常に「最後の green + 書き直されたステップ」からやり直す。

### 6-4. `ESCALATION.md`

```markdown
# ESCALATION: step <id>

## 事実
- 停止理由: max_attempts | freeze_violation | path_violation | red_gate_R4 | ...
- 試行回数: 3 / 3
- このステップのエスカレーション回数: 2
- 失敗ブランチ: escalate/03/2
- 最後の green: step/02 (a1b2c3d)

## 落ちたテスト
（junit XML から: テスト名 / assertion の期待値と実際値）

## 凍結マニフェスト差分
（freeze_violation の場合のみ。何がどう変わったか）

## プランナーへの制約
- escalation_no >= 2 のため、**(a) は選択できない**。(b) か (c) のみ。
- (c) を選ぶ場合、破棄する green ステップの id を明記すること。
- **いかなる場合も acceptance を緩める形で応じないこと。**
```

---

## 7. tasks.json に必要な追加フィールド

BOOTSTRAP.md §3 の記述に対し、ランナーが機構として動くために以下が必須:

```json
{
  "id": "03",
  "kind": "unit",
  "goal": "...",
  "depends_on": ["01", "02"],
  "acceptance": [
    {"case": "normal",   "given": "...", "then": "..."},
    {"case": "boundary", "given": "...", "then": "..."},
    {"case": "error",    "given": "...", "then": "..."}
  ],
  "contracts": {
    "provides": ["def tokenize(text: str) -> list[Token]", "..."],
    "invariants": ["同じ入力に対し常に同じ出力", "空文字列では空リスト"]
  },
  "files_write": ["src/pkg/tokenizer.py"],
  "files_test":  ["tests/test_tokenizer.py"],
  "expected_tests": 5,
  "max_attempts": 3,
  "review_gate": true
}
```

追加の理由:

| フィールド | なぜ必要か |
|---|---|
| `depends_on` | 番号順だけでは 1-4(c) の「破棄すべき green」を機械計算できない |
| `expected_tests` | R1（テスト0件・削除の検出）が実装できない |
| `kind: "integration"` | 結合ステップを**終盤だけでなく早期にも**置くための識別。リンタが配置を検査する |
| `contracts.invariants` | 型だけでは意味が運べず、後続が誤解したまま green になる |
| `acceptance` の構造化 | 正常/境界/異常の充足をリンタが検査できる |

---

## 8. tasks.json リンタ（`runner validate`）

**プランナーの出力に対する唯一の客観的関門。** 実行前に必ず通す。

| # | 検査 |
|---|---|
| L1 | JSON Schema 準拠 |
| L2 | `depends_on` が自分より若い id のみを参照し、循環がない |
| L3 | 各ステップの `contracts.requires` が、依存先のいずれかの `provides` に存在する |
| L4 | `files_write` が全ステップで重複しない（1ファイル1所有者） |
| L5 | `files_write` ∩ `files_test` == ∅ |
| L6 | `acceptance` に `normal` / `boundary` / `error` が最低1つずつ |
| L7 | `expected_tests` >= `acceptance` の件数 |
| L8 | `review_gate: false` のステップは、全 `acceptance` の `given`/`then` が具体値を含む（数値・リテラル・例外型のいずれか。形容詞のみは不可） |
| L9 | `kind: "integration"` が**最初の3ステップ以内に1つ以上**存在する（歩く骨格） |
| L10 | `kind: "integration"` が最終ステップに1つ以上存在する |
| L11 | どのステップからも参照されない `provides` がない（デッドコントラクト） |

L9 は BOOTSTRAP.md §3 ルール6 への修正を機構化したもの。結合を終盤にしか置かないと、
契約の意味的な不整合が最も高くつく地点で発覚し、1-4(c) の破棄量が最大になる。

---

## 9. CLI

```
runner validate                    # §8。それ以外の全コマンドの前提
runner run --step <id>             # 1ステップだけ回す
runner run --all                   # green が続く限り進み、停止条件で止まる
runner approve --step <id>         # REVIEW_GATE の承認
runner reject  --step <id> [--note] # REVIEW_GATE の却下
runner status                      # 台帳から各ステップの位相を表示
runner replan                      # ESCALATION.md 適用後、tasks.json を再検証して再開
```

### 終了コード

| code | 意味 |
|---|---|
| 0 | 対象範囲すべて green |
| 10 | REVIEW_GATE で人間待ち |
| 20 | エスカレーション（`ESCALATION.md` を参照） |
| 30 | リンタ不合格（tasks.json が不正） |
| 40 | 環境異常（venv 不在、権限設定の不備、プロキシ不通など） |

**exit 0 以外はすべて人間に戻る。** 自動で先に進む経路を作らないこと。

---

## 10. v1 でやらないこと

- ステップの並列実行
- ソルバーの複数モデル切り替え
- テスト実行のタイムアウト以外のリソース制限（cgroup 等）
- Web UI / 進捗ダッシュボード（`runner status` の標準出力で足りる）
- ランナー自身をこのループ方式で開発すること（**鶏卵になる。初版は手書きして捨てる**）

---

## 11. 未決事項

1. **ソルバーの実体** — Codex CLI を想定しているが、`--uid-owner solver` での egress 制限下で
   動くか未検証。API キーは `solver` の環境変数に置く（VM 専用の失効可能なキー、上限額つき）
2. **プロキシ構成の要否** — §1-3 の簡易版で始め、IP 変動で壊れた時点で上げるか、最初から立てるか
3. **`.venv` の作成タイミング** — プロビジョニング時に `runner` が作り、以降 solver からは
   読み取り専用。依存追加は CONTEXT.md の変更＝プランナーの仕事とする、で確定してよいか
4. **テスト実行のタイムアウト値** — 無限ループする実装が普通に出るので必須。
   ステップごとに指定させるか、全体固定（例 120s）か
