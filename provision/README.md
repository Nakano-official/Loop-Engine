# loop サンドボックス（WSL2）のプロビジョニング

RUNNER_SPEC.md の実行環境（§1）を再現するための手順とスクリプト。

実行基盤は **WSL2 の `Ubuntu-24.04` ディストロ**。VirtualBox は使わない（理由は §6）。

作り直すときはこの手順をなぞる。**§3 の落とし穴は全部、踏んだか実機で確認したもの**で、
どれも「一見成功して、後から静かに壊れる」種類なので飛ばさないこと。

---

## 1. 構成

| | |
|---|---|
| ディストロ | WSL2 `Ubuntu-24.04`（Ubuntu 24.04.1 LTS / systemd 有効） |
| CPU / RAM | `.wslconfig` で 6 プロセッサ / 8GB / swap 4GB（ホストは 8C8T / 16GB） |
| ディスク | ext4 on VHDX（`sparseVhd=true`） |
| ネットワーク | `networkingMode=NAT` + `localhostForwarding=true` |
| SSH | ディストロ内 sshd が **2222 番で listen**。Windows からは `127.0.0.1:2222` |
| Windows ドライブ | **マウントしない**（`automount enabled=false`） |
| Windows 実行ファイル | **起動不可**（`interop enabled=false`） |
| WSLg | **無効**（`.wslconfig` `guiApplications=false`。2026-08-17 適用・反映確認済み。§3-8） |

アカウント:

| ユーザー | uid | sudo | SSH | 用途 |
|---|---|---|---|---|
| `maint` | 1000 | あり | 鍵のみ | プロビジョニングと保守。VS Code Remote-SSH はここに繋ぐ |
| `runner` | 1001 | **なし** | 鍵のみ | ループの実行主体。ホストからの git push を受ける |
| `solver` | 1002 | **なし** | **不可**（`AllowUsers` に載せない + `DenyUsers`） | 実装を書くだけ |

`maint` は VirtualBox 構成での `admin` に相当する。WSL2 のディストロには
既定ユーザーが必ず1人いるので、それを保守用として使い、ループ用の2人を足す形にした。

ホスト側の付属物（詳細と再作成手順は `host/README.md`）:

| もの | 場所 | 役割 |
|---|---|---|
| `loop-dev` ランチャ | `C:\Users\yoshi\bin\loop-dev.cmd`（原本は `host/loop-dev.cmd`） | ディストロ起動 → sshd 待機 → VS Code Remote-SSH 起動 |
| SSH 設定 | `C:\Users\yoshi\.ssh\config` の `Host loop-dev` / `Host loop-runner` | `127.0.0.1:2222` / 鍵のみ |
| keepalive タスク | タスクスケジューラ `WSL-keepalive-Ubuntu-24-04` | **これが無いと VM がアイドルで落ちる**（§3-1） |
| リソース設定 | `C:\Users\yoshi\.wslconfig` | メモリ/CPU/NAT/sparseVhd/WSLg |

---

## 2. 作り直す手順

ホスト側は PowerShell、ディストロ内は bash。**`.ps1` を書き起こさずインライン実行すること**（§3-6）。

### 2-1. 鍵を作る（**Bash で**。理由は §3-5）

保守用（`maint`）とループ用（`runner`）で鍵を分ける。前者は人が対話で使い、
後者はホストの作業クローンから git push するためだけに使う。

```bash
ssh-keygen -t ed25519 -f /c/Users/<you>/.ssh/id_ed25519         -N '' -C loop-dev
ssh-keygen -t ed25519 -f /c/Users/<you>/.ssh/loop-runner_ed25519 -N '' -C loop-runner
# 必ず検証する。空パスフレーズで復号できなければ失敗している
ssh-keygen -y -f /c/Users/<you>/.ssh/id_ed25519          -P ''
ssh-keygen -y -f /c/Users/<you>/.ssh/loop-runner_ed25519 -P ''
```

### 2-2. ディストロを用意する

```powershell
wsl --install -d Ubuntu-24.04     # 既定ユーザー(maint)を対話で作る
wsl -l -v                         # Ubuntu-24.04 / Running / 2 であることを確認
```

`/etc/wsl.conf` を次の内容にする（`[boot] systemd=true` が無いと `systemctl` が使えず、
sshd の管理も 50-lockdown.sh の検証も成立しない）:

```ini
[boot]
systemd=true

[user]
default=maint

[automount]
enabled=false

[interop]
enabled=false
appendWindowsPath=false
```

`C:\Users\yoshi\.wslconfig` はリポジトリ外にあるが、次の3つは隔離の前提:

```ini
[wsl2]
localhostForwarding=true    # 127.0.0.1:2222 で sshd に届く
networkingMode=NAT          # mirrored にしない
guiApplications=false       # WSLg を切る(§3-8)
```

残り（`memory` / `processors` / `swap` / `sparseVhd` / `autoMemoryReclaim`）は
性能配分の話で、隔離には関わらない。`host/README.md` を参照。

`mirrored` だとディストロから Windows の localhost サービスに到達できてしまい、
隔離が緩くなる。`guiApplications` は既定 true で、切らないと `/mnt/wslg` 経由の
経路が開いたままになる。

**`/etc/wsl.conf` と `.wslconfig` の変更は `wsl --terminate` では反映されない。**
`wsl --shutdown` が必要で、それをやったら keepalive タスクを再起動する（§3-2）。

### 2-3. sshd を 2222 で立てる

```bash
sudo apt-get update && sudo apt-get install -y openssh-server
sudo tee /etc/ssh/sshd_config.d/10-loop-dev.conf >/dev/null <<'EOF'
Port 2222
ListenAddress 0.0.0.0
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AllowUsers maint
X11Forwarding no
EOF
sudo systemctl enable --now ssh
```

`maint` の `~/.ssh/authorized_keys` に `id_ed25519.pub` を入れる。
ここで `AllowUsers maint` だけになるが、`runner` は 50-lockdown.sh が
`00-loop.conf` 側で足す（**足す順番に意味がある。§3-4**）。

22 ではなく 2222 を使うのは、Windows 側の 22 と衝突させないためと、
`localhostForwarding` で `127.0.0.1:2222` にそのまま出るようにするため。

### 2-4. Node と エージェント CLI

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm i -g @anthropic-ai/claude-code @openai/codex   # 導入済みの構成に合わせる
```

**必ず `sudo npm i -g`（prefix が `/usr`）にすること。** ユーザーローカル prefix に入れて
`.bashrc` で PATH を足す形にすると、Ubuntu の `.bashrc` が非対話シェルで早期 return する
ため、SSH 経由の非対話実行やループから見えなくなる。nvm も同じ理由で使えない。

interop を切ると Windows 側の `npm`/`node` が PATH から消えるので、
ディストロ内にシステムワイドで入れる必要がある。

### 2-5. スクリプトを送り込んでプロビジョニング

`/mnt/c` が無いので、ファイルの受け渡しは **scp** で行う。

```bash
ssh -p 2222 maint@127.0.0.1 'mkdir -p /tmp/loop-provision'
scp -P 2222 provision/*.sh /c/Users/<you>/.ssh/loop-runner_ed25519.pub \
    maint@127.0.0.1:/tmp/loop-provision/
ssh -p 2222 maint@127.0.0.1 \
    "cd /tmp/loop-provision && sed -i 's/\r\$//' *.sh && sudo bash provision.sh"
```

最後の行が非対話で通るのは、WSL の既定ユーザーに `NOPASSWD` の sudoers
（`/etc/sudoers.d/90-maint`）が入っているから。VirtualBox 構成でパスワードを
`sudo -S` に流し込んでいたのは不要になった。**`maint` は実質 root** なので、
ループの三者に含めないこと（RUNNER_SPEC §0-1）。

`05-isolation.sh` が WSL 隔離（Windows パス非マウント、WSLg、systemd、NAT）を、
`40-perms.sh` が solver 視点の権限モデルを assert する。1つでも落ちたら異常終了する。
`05-` を最初に走らせるのは、隔離が効いていないディストロには**プロビジョニングする意味が
無い**（以降の全ステップが成功しつつ何も意味しなくなる）ため。

### 2-6. スナップショット

VirtualBox のスナップショットに相当するのは `wsl --export`。

```powershell
wsl --shutdown                                                   # export には停止が必要
wsl --export Ubuntu-24.04 D:\wsl-backup\loop-base.tar
# 復元: wsl --import Ubuntu-24.04-restore D:\wsl\restore D:\wsl-backup\loop-base.tar
```

**`wsl --shutdown` を使ったら keepalive タスクを再起動すること**（§3-2）。
export は数 GB になるのでリポジトリには入れない（`.gitignore` に `*.tar`）。

---

## 3. 落とし穴

### 3-1. keepalive タスクが無いと VM がアイドルで落ちる（最重要）

WSL2 は約60秒アイドルすると **VM ごと停止する**。sshd も一緒に落ちる。
`WSL-keepalive-Ubuntu-24-04`（ログオン時に `wsl -d Ubuntu-24.04 -u root --exec /usr/bin/sleep infinity`）
がこれを抑えている。

実測で確認した事実（2026-08-17）:

- `.wslconfig` の `vmIdleTimeout` は **`-1` でも大きな正の値でも効かない**
- **アイドル判定は `wsl.exe` クライアントセッションだけを数える。SSH のトラフィックは数えない。**
  そのため VS Code Remote-SSH で接続中でも VM は落ちる（接続途中で落ちて
  「リモートを開いています」で止まる、が実際に起きた）
- デタッチしたバックグラウンドプロセスも VM を保持しない

タスクを作り直すとき:

```powershell
schtasks /create /tn "WSL-keepalive-Ubuntu-24-04" /sc onlogon /rl limited `
  /tr "C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u root --exec /usr/bin/sleep infinity"
schtasks /change /tn "WSL-keepalive-Ubuntu-24-04" /ri 0 /du 0000:00   # 実行時間無制限
```

**帰結: この基盤では無人での長時間ループは回せない。** keepalive はログオンセッションに
紐づくので、ログオフすれば VM は落ちる。無人運用が必要になったら Hyper-V に移す（§5）。

### 3-2. `wsl --shutdown` を使うと keepalive が死ぬ

keepalive プロセスは `wsl --shutdown` で `STATUS_CONTROL_C_EXIT` で落ちる。
タスクは onlogon なので自動では戻らない。**このサンドボックスを触るとき
`wsl --shutdown` は使わない。** 使ったら明示的にタスクを再実行する:

```powershell
schtasks /run /tn "WSL-keepalive-Ubuntu-24-04"
```

`.wslconfig` の変更には `--shutdown` が要るので、そのときは必ずセットで行う。

### 3-3. iptables が入っていない

Ubuntu 24.04 の WSL イメージには `iptables` も `nft` も無い。
`60-egress.sh` は自分で `apt-get install -y iptables` する（nft バックエンドで動く）。

さらに **WSL2 の VM はアイドルで落ちるので、iptables ルールは頻繁に消える。**
VirtualBox 構成では「再起動まで持てばよい」で済んだが、ここでは
`iptables-persistent` による復元が実質必須。`60-egress.sh` の末尾を参照。

### 3-4. sshd の drop-in は「先に読んだ値が勝つ」。ただし `AllowUsers` は例外

sshd は各キーワードについて **最初に見た値**を採用する。`PasswordAuthentication` や
`Port` のような単一値のキーワードを後から `99-*.conf` で上書きしようとしても**負ける**。
エラーは出ないので、設定を書いたのに効いていない状態に気づけない。

→ `50-lockdown.sh` は `00-loop.conf` に書く（`10-loop-dev.conf` より先に読まれる）。
そして `sshd -T` で**実効値を検証する**。効いていなければ異常終了する。

**`AllowUsers` / `DenyUsers` はリスト値で、drop-in をまたいで累積する。**
`10-loop-dev.conf` の `AllowUsers maint` と `00-loop.conf` の
`AllowUsers maint runner` は、順序に関係なく合算されて `{maint, runner}` になる。
帰結として重要なのは逆方向で、**後から書く drop-in は許可を広げることしかできない。**
誰かを外すには、その名前を書いているファイル自体を直す必要がある。

さらに `sshd -T` の出力形式が罠になる。**1ユーザーにつき1行**で出る:

```
allowusers maint
allowusers runner
allowusers maint      ← 2つの drop-in に書かれているので重複して出る
denyusers solver
```

検証スクリプトで「最後の行」や「最初の行」だけを見ると誤判定する
（2026-08-17、実際に `50-lockdown.sh` がこれで正しい設定を FAIL と判定した）。
全行を集めて集合として扱うこと。

（VirtualBox 構成では単一値キーワードのほうの罠を cloud-init の
`50-cloud-init.conf` で踏んだ。書くファイル名は変わっても、原因と対処は同じ。）

### 3-5. PowerShell から `ssh-keygen -N ''` は空パスフレーズにならない

`-N '""'` も `--%` 経由の `-N ""` も、**空文字ではないパスフレーズ**として渡る。
生成自体は成功するので気づかない。症状は接続時の

```
debug1: Server accepts key: ...
Permission denied (publickey,password).
```

サーバ側ログは `Connection reset by authenticating user runner [preauth]`。
**サーバは鍵を受理していて、クライアントが署名できずに切っている。**
`authorized_keys` を疑って時間を溶かす典型。

→ 鍵の生成は Bash で行い、`ssh-keygen -y -f <key> -P ''` で必ず検証する。

### 3-6. `.ps1` に日本語コメントを書くと壊れる

PowerShell 5.1 は BOM 無し UTF-8 を ANSI として読む。日本語文字の末尾バイトが
バッククォート（行継続）と解釈され、**コメント行が次の行を飲み込み、変数が黙って null になる。**

→ `.ps1` / `.cmd` は ASCII のみで書く（`loop-dev.cmd` がそうなっている）か、
スクリプトを作らずインライン実行する。多段クォート（PowerShell → ssh → リモートシェル）も
崩れやすいので、複雑なものは base64 化して
`echo <b64> | base64 -d | bash` で渡すのが確実。

### 3-7. Git Bash から `wsl.exe` を叩くとパスが変換される

Git Bash 経由で `wsl -d Ubuntu-24.04 --exec /bin/true` を実行すると、
MSYS が `/bin/true` を Windows パスに変換して失敗する。
`/usr/bin/true` のように変換されない形を使う（`loop-dev.cmd` がそうしている）。

### 3-8. WSLg が Windows 側への通り道を開けたままにする

`automount` と `interop` を切っても、**WSLg（Linux GUI アプリ対応）は生きている。**
`/mnt/wslg` に Windows 側で動くコンポジタと PulseAudio サーバへのソケットがあり、
パーミッションは誰でも読める:

```
drwxrwxrwx  .X11-unix
srwxrwxrwx  PulseServer / PulseAudioRDPSink / PulseAudioRDPSource
```

つまり `solver` からもディスプレイ・音声・クリップボード連携の経路に届く。
`/etc/wsl.conf` にはこれを切る設定が無く、Windows 側の `.wslconfig` で閉じる:

```ini
[wsl2]
guiApplications=false
```

反映には `wsl --shutdown` が必要（→ keepalive 再起動、§3-2）。

2026-08-17 に適用済み。反映後の状態（確認済み）:

- `/mnt/wslg` 配下のソケットが**全て消える**（`find -type s` が 0 件）
- `/mnt/wslg/versions.txt` と `/doc` の overlay マウントも消える
- `/tmp/.X11-unix` は空、ログインシェルの `DISPLAY` / `WAYLAND_DISPLAY` / `PULSE_SERVER` も未設定

**ただし `/mnt/wslg` ディレクトリ自体は残る**（`run/user/<uid>` の空の骨組みだけ）。
そのためディレクトリの有無で判定すると誤検知する。`05-isolation.sh` は
**ソケットと `/mnt/wslg` 配下のマウント**を探して FAIL にしている。
意図して受け入れる場合は `ALLOW_WSLG=1` を付けて実行する
（この waiver は他のチェックには効かない）。

### 3-9. interop の binfmt ハンドラは切っても残る

`[interop] enabled=false` にしても `/proc/sys/fs/binfmt_misc/WSLInterop` は
登録されたまま（`enabled` / `interpreter /init` / `magic 4d5a`）。
**したがってハンドラの有無は隔離の証拠にならない。**

実際に効いていないことは実行して初めて分かる。2026-08-17 に root で `C:` を
drvfs マウントして `cmd.exe` を叩いた結果:

```
rc=1  WSL ERROR: UtilAcceptVsock:273: accept4 failed 110
```

`/init` が Windows 側に繋げず、vsock の accept でタイムアウトしている。
つまり実行経路は死んでいる。

**ただし root は `mount -t drvfs C: /somewhere` でいつでも C: を持ち込める**
（実測で成功する）。automount を切ることは root に対する防御ではない。
効いているのは「`solver` は sudo を持たないのでマウントできない」という点で、
**隔離の実質は権限モデル（`40-perms.sh`）と同じ土台に乗っている。**

だから `05-isolation.sh` は binfmt の登録を FAIL にせず、
**Windows パスが1つもマウントされていないこと**を主チェックにしている。

### 3-10. `set -o pipefail` 下の `... | grep -q`

`grep -q` は最初のマッチで即終了する。すると上流が SIGPIPE で死に、
**pipefail がパイプライン全体を失敗扱いにする。マッチしているのに失敗する。**
検証スクリプトで踏むと「正しい設定を誤りと判定する」ので厄介。

→ 一度変数に取ってから判定する。`50-lockdown.sh` の末尾と `05-isolation.sh` の
`loopback0` チェックを参照。

### 3-11. runner は自分が所有しないファイルを chmod できない

ソルバーが作ったファイルは `solver` 所有になる。ランナーは書き込みフェンスを
**開けても閉じられない** ── `chmod` は所有者か root にしか通らず、`chown` には root が要る。
ランナーに root を渡すのは本末転倒（関門を強制する側が関門を外せてしまう）。

→ ディレクトリが runner 所有なら、中のファイルは**削除できる**。読んで・消して・
runner として書き直すと所有権が移る（`runner/loop.py` の `adopt()`）。バイト列は同一なので
git も凍結マニフェストも影響を受けず、特権を1つも増やさない。

### 3-12. `/srv/loop/brief` に setgid が無いとブリーフが読まれない

runner が書いたブリーフのグループが `runner` になり、`solver` から読めなくなる。
症状は `solver-run` の `exited 2` だけで、原因から遠い。

→ `2750` にする（`20-layout.sh` / `40-perms.sh`）。ランナー側でも書き込み直後に
明示的に `chgrp solverw` している。ディレクトリのビットに依存しない。

### 3-13. Codex の `apply_patch` はワークスペースのルートを経由して書く

`/srv/loop/project` が `755 runner:runner` だと、`src/` に権限があっても**全ての編集が失敗する**。
しかもエラーは対象ファイル名で報告されるので `src/` の権限を疑わせる。
`bubblewrap` が未導入だと、さらに手前の「サンドボックス構築の失敗」として出る。

→ ルートを `3775`（setgid + **スティッキー**）にする。書けるだけでは穴で、
unlink と rename は親ディレクトリの権限で決まるため `conftest.py` を差し替えられてしまう
（= FREEZE の無効化）。スティッキーが「削除・改名は所有者のみ」に制限する。
`40-perms.sh` が「作れること」と「消せないこと」を両方 assert する。
併せて `apt install bubblewrap` を入れる（バンドル版へのフォールバックは不安定）。

### 3-14. `sudo -u runner` を `~/provision` を cwd にしたまま呼ぶと落ちる

`/home/maint` は 700 なので、runner が cwd を stat できず
`fatal: failed to stat '/home/maint/provision'` になる。git を呼ぶ行だけが死ぬ。

→ プロビジョニングスクリプトは中立なディレクトリから実行する（`cd /tmp`）。

### 3-15. `.pyc` は実行した uid の所有物になる

`tests/__pycache__` に solver 所有の `.pyc` が残ると、3-11 により
ランナーが `tests/` のモードを再適用できなくなる。

→ ランナーの pytest は `PYTHONDONTWRITEBYTECODE=1` で走らせ、
モード変更は `__pycache__` を除外する。

---

## 4. 未適用

`60-egress.sh` は**意図的に実行していない**（2026-08-18 判断）。

当初は「これを当てて初めて環境凍結が成立する」と書いていたが、**それは誤りだった**。
ネットワークを全開にしたまま測ったところ、4経路すべてが既に塞がっている:

| 試みたこと | 結果 | 効いている機構 |
|---|---|---|
| `.venv/bin/pip install requests` | Permission denied | `.venv` が runner 所有・`go-w` |
| `pip install --user requests` | externally-managed-environment | PEP 668 |
| `--user` で入れたものを `.venv/bin/python` から import | 見えない | venv は user site を無視する |
| `apt-get install` | dpkg lock: are you root? | sudo なし |

3つ目が要。**テストは必ず `.venv/bin/pytest` で走らせること** ── 素の `python3` に変えると
user site が復活し、この防御だけが崩れる。

そのうえで、egress 制限が買うのは環境凍結ではなく**持ち込みと持ち出し**の遮断であり、
ループの前提条件ではない。当てるかどうかはその脅威をどう見るかで決める。

**当てるなら IP 固定ではなくプロキシで作ること。** 観測したソルバーの宛先は
`chatgpt.com` の1つだけだが（`api.openai.com` は使われない ── あれは API キー経路）、
Cloudflare の後ろにあり複数アドレスに解決される。IP 固定は黙って陳腐化し、
WSL2 では VM が頻繁に止まるので規則の永続化が要る ──
**永続化した固定 IP は時限爆弾**（ローテーション後、原因の分かりにくい停止として出る）。

観測の手順（推測でドメインを並べないこと）:

```bash
# DROP ではなく LOG を1本入れて、実際に叩かれた宛先だけを採る
iptables -I OUTPUT 1 -m owner --uid-owner "$(id -u solver)" \
  -m conntrack --ctstate NEW -j LOG --log-prefix "LOOPOBS "
sudo -u runner /srv/loop/bin/smoke-solver
dmesg | grep LOOPOBS
```

### 認証（2026-08-18 時点）

- **`solver` = Codex CLI + ChatGPT サブスクリプション**。API キーは使わない。
  `sudo -u solver -H codex login --device-auth`（ブラウザはホスト側でよい）。
  **必ず `solver` として実行すること** ── 他アカウントでログインしても
  `/home/<other>` が 700 なので solver からは読めない。認証情報が
  `/home/solver/.codex` に入ることが、そのまま隔離になっている
- **`planner` = Claude の API キー**。`/etc/loop/planner.env`（`root:planner 0640`）。
  ベンダを分けているのは、基準を書く側と満たす側の相関した盲点を避けるためと、
  片方の枠・認証情報の事故がもう片方を巻き込まないようにするため

---

## 5. Hyper-V へ移す条件

WSL2 でよいのは「人が張り付いている間だけ回す」用途に限られる（§3-1）。
次のどれかが必要になったら Hyper-V の VM に移す:

- 無人で数時間以上ループを回す（ログオフしても走り続ける）
- ホストの再起動を挟んで自動復帰する
- ループ実行中に Windows 側で重い作業をしても影響を受けない

ディストロ内の構成（`provision/` の 10〜60）は**そのまま持っていける**。
変わるのはホスト側の起動・接続まわりと、スナップショットの取り方だけ。

## 6. なぜ VirtualBox をやめたか

当初は VirtualBox 7.x + Ubuntu Server 24.04 の無人インストールで作っていた
（`c4374f4` まではその手順がこのファイルにあった）。捨てた理由:

**Hyper-V が有効な Windows ホストでは VirtualBox が使えない。**
Hyper-V / WSL2 / Virtual Machine Platform / メモリ整合性 のいずれかが有効だと、
VirtualBox は VT-x を直接使えず NEM モード（Hyper-V の API 経由）で動く。
この状態で Linux ゲストは起動時に **2回に1回ハングした**:

```
nmi_backtrace_stall_check: CPU 1: NMIs are not reaching exc_nmi() handler
last activity: 4294855847 jiffies ago
```

jiffies が 32bit ラップした異常値になるのはタイマー起因のサイン。
`--paravirtprovider` を `kvm` → `none` に変えても頻度が下がるだけで解消しなかった。
再現性が無く（インストールと初回起動は通り、スナップショット後の再起動で初めてハング）、
数時間ループを回す基盤としては使えない。

Hyper-V を無効化すれば VT-x に戻って安定するが、**WSL2 も Docker Desktop も動かなくなる**。
すでに Hyper-V が動いているなら、そちらがネイティブなので WSL2 に寄せるほうが筋が良い。

WSL2 に移して失ったもの・得たもの:

| | VirtualBox | WSL2 |
|---|---|---|
| 起動の安定性 | 2回に1回ハング | 安定 |
| 隔離 | 既定で隔離 | **既定では隔離されない**（`/mnt/c` と interop を明示的に切る必要がある） |
| 無人実行 | できる | **できない**（§3-1） |
| スナップショット | `VBoxManage snapshot`（差分・軽い） | `wsl --export`（全体・数GB） |
| ホストからの root | できない | **いつでもできる**（`wsl -u root`） |

最後の行は重要で、脅威モデルが片方向になったことを意味する。守っているのは
「サンドボックスから Windows を守る」方向だけで、逆方向は守っていない。
RUNNER_SPEC §0-1 の「プランナーはサンドボックスに入らない」は機構ではなく規律である
（VirtualBox 構成でも規律だったが、WSL2 では踏み越えるコストがさらに低い）。

VirtualBox 特有の落とし穴（標準テンプレートに sshd が無い / `ds=nocloud` のスキーム、
インストール完了をポートで判定してはいけない）と `autoinstall_user_data` は、
この構成では使わないので削除した。必要なら `c4374f4` から拾える。
