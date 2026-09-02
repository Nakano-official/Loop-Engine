# Loop Engine operator dashboard

ホスト側で、ランナーの進捗、エスカレーション、全 Green 後の予定レビューを表示する
ローカル Web GUI です。人間の判断はダッシュボード自身が行わず、対象を固定した追記記録
として保存します。

## 設計上の境界

- `ALL_GREEN` から生じる予定レビューと、失敗によるエスカレーションを区別する
- ランナーの台帳と計画は読み取り専用。回答はホスト側の `.state/decisions.jsonl` に置く
- **常に `127.0.0.1` だけで待ち受ける。** 外から見えるようにするのは `tailscale serve` の
  仕事で、このサーバは LAN にも一度も出ない
- `Host` ヘッダが**応答してよい名前の一覧**（ループバック＋公開名）に無ければ拒否する。
  ループバック束縛と CORS だけでは DNS リバインディング（攻撃者のドメインを `127.0.0.1`
  に解決させ、同一オリジンにする）を防げない。リバインドされた要求が偽装できない唯一の値が
  `Host`
- 公開名で来た要求は、`tailscale serve` が書く `Tailscale-User-Login` が
  `config.json` の名簿にある場合だけ通す。**このヘッダが意味を持つのは Host が先に
  一致したからで**、その順序が逆になったら何の保証も無い
- 状態変更 API はセッショントークンを要求する
- 判断の記録は**追記のみ**。既存の回答を読み直して書き戻す経路が無く、`decide` は
  ロックの下で「まだ保留か」の確認と追記をまとめて行う
- 成果物は `config.json` に人間が設定した ID だけを、**この機械の前からだけ**起動できる
- **リモートは「駄目だ」と言えるが「良い」とは言えない。** 予定レビューの承認は
  ローカルのみ。画面を見られない端末が「遊べた」と記録できてしまったら、
  *機械には画面が確認できないから人間に訊く* という関門そのものが無意味になる。
  差し戻し・エスカレーションへの回答・停止はどこからでもできる
- 記録には `scope` と `user` が入る。**どこから答えたかは答えの一部**
- HTTP リクエスト、計画、ソルバー出力をコマンドラインに展開しない
- `shell=False` で引数配列をそのまま実行する

この最初の版は、回答をプランナーへ自動適用しません。回答の記録と計画変更を分離するのは
意図的です。`plan propose` は費用を使い、`plan apply` は評価基準を書き換えるため、GUIから
一操作で暗黙に実行してはいけません。

## 起動

`host/dashboard/config.example.json` を `host/dashboard/config.json` にコピーし、成果物の
起動コマンドと作業ディレクトリをホスト環境に合わせます。設定しなくても進捗画面は使えます。

**`cwd` はミラーの直下ではなく `project\src` を指す**（例のとおり）。ランナーの計画は
pytest の慣習で `src/` レイアウトを採り、`src/` を `sys.path` に載せているのは
`conftest.py` の1行だけ ── **これを読み込むのは pytest だけ**なので、`project\` から
`python -m <pkg>` を叩くと `No module named` で即死する。テストが全部緑でも起動しない、
という形で現れる（run 7 で踏んだ。HANDOFF §3 の欠陥4）。

リポジトリのルートから:

```powershell
python host/dashboard/server.py --project ..\project
```

または `host\loop-dashboard.cmd` を実行します。その後、ブラウザで
<http://127.0.0.1:8443> を開きます。

## スマホ・他PCから見る（tailscale serve）

サーバはループバックのまま動かし、**外への口は Tailscale に持たせます**。ポートを開ける
のでも `0.0.0.0` で待ち受けるのでもないので、LAN からは見えません。

```powershell
tailscale serve --bg --https=8443 http://127.0.0.1:8443
tailscale serve status
```

`config.json` に公開名と名簿を書きます。**両方書いて初めて公開**で、`remote` が無い、
あるいは `users` が空なら「全員に公開」ではなく**誰にも公開しない**（fail closed）。

```json
"remote": {
  "host": "<machine>.<tailnet>.ts.net:8443",
  "users": ["you@example.com"]
}
```

`users` に書くのは Tailscale のログイン（`tailscale status` の右端に出るもの）。
`tailscale serve` はクライアントが送った `Tailscale-User-Login` を**上書き**するので、
tailnet の外から詐称はできません。

**`tailscale funnel` は使わないこと。** あれはインターネット全体への公開で、
このダッシュボードはエスカレーションの全文とプロジェクトのパスを出します。

表示対象はホスト側ミラーです。最新の状態は先に `host\loop-pull.cmd` で取得してください。
サンドボックスへ外向きの認証情報を置かないため、同期方向は従来どおりホストからの pull
だけです。

## テスト

```powershell
python -m unittest discover -s host/dashboard/tests -v
```

実行時の回答と `config.json` は機械固有であり、Gitには含めません。
