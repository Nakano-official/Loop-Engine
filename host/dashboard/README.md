# Loop Engine operator dashboard

ホスト側で、ランナーの進捗、エスカレーション、全 Green 後の予定レビューを表示する
ローカル Web GUI です。人間の判断はダッシュボード自身が行わず、対象を固定した追記記録
として保存します。

## 設計上の境界

- `ALL_GREEN` から生じる予定レビューと、失敗によるエスカレーションを区別する
- ランナーの台帳と計画は読み取り専用。回答はホスト側の `.state/decisions.jsonl` に置く
- `127.0.0.1` だけで待ち受ける
- 状態変更 API はセッショントークンを要求する
- 成果物は `config.json` に人間が設定した ID だけを起動できる
- HTTP リクエスト、計画、ソルバー出力をコマンドラインに展開しない
- `shell=False` で引数配列をそのまま実行する

この最初の版は、回答をプランナーへ自動適用しません。回答の記録と計画変更を分離するのは
意図的です。`plan propose` は費用を使い、`plan apply` は評価基準を書き換えるため、GUIから
一操作で暗黙に実行してはいけません。

## 起動

`host/dashboard/config.example.json` を `host/dashboard/config.json` にコピーし、成果物の
起動コマンドと作業ディレクトリをホスト環境に合わせます。設定しなくても進捗画面は使えます。

リポジトリのルートから:

```powershell
python host/dashboard/server.py --project ..\project
```

または `host\loop-dashboard.cmd` を実行します。その後、ブラウザで
<http://127.0.0.1:8765> を開きます。

表示対象はホスト側ミラーです。最新の状態は先に `host\loop-pull.cmd` で取得してください。
サンドボックスへ外向きの認証情報を置かないため、同期方向は従来どおりホストからの pull
だけです。

## テスト

```powershell
python -m unittest discover -s host/dashboard/tests -v
```

実行時の回答と `config.json` は機械固有であり、Gitには含めません。
