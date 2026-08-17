# host/ — Windows 側の付属物

サンドボックスの外、ホスト側に置くもの。`provision/` がディストロの中を作るのに対し、
こちらは**ディストロを起動して繋ぐところ**を担当する。

WSL2 では起動と生存管理がホスト側の責務になった（`RUNNER_SPEC.md` §1-6）ので、
ここが無いとサンドボックスはそもそも上がってこない。

| ファイル | 置き場所 | 役割 |
|---|---|---|
| `loop-dev.cmd` | `C:\Users\<you>\bin\loop-dev.cmd`（PATH の通った場所） | ディストロ起動 → sshd 待機 → VS Code Remote-SSH 起動 |

**ASCII のみで書くこと。** PowerShell 5.1 と cmd.exe は BOM 無し UTF-8 を ANSI として
読むため、日本語コメントを入れると行継続として誤解釈され、変数が黙って null になる
（`provision/README.md` §3-6）。

## リポジトリに入っていないもの

手で作る必要があるが、内容が短いのでここに手順だけ置く。

### keepalive スケジュールタスク（必須）

これが無いと VM が約60秒のアイドルで停止し、SSH が使えなくなる
（`provision/README.md` §3-1）。

```powershell
schtasks /create /tn "WSL-keepalive-Ubuntu-24-04" /sc onlogon /rl limited `
  /tr "C:\Windows\System32\wsl.exe -d Ubuntu-24.04 -u root --exec /usr/bin/sleep infinity"
schtasks /change /tn "WSL-keepalive-Ubuntu-24-04" /ri 0 /du 0000:00
```

`wsl --shutdown` を打つと巻き添えで死ぬので、そのあとは
`schtasks /run /tn "WSL-keepalive-Ubuntu-24-04"` で戻す。

### `~/.ssh/config`

```
Host loop-dev
    HostName 127.0.0.1
    Port 2222
    User maint
    IdentityFile C:\Users\<you>\.ssh\id_ed25519
    IdentitiesOnly yes
    # WSL は再作成でホスト鍵が変わるため、未知なら自動受け入れ
    StrictHostKeyChecking accept-new
    ServerAliveInterval 30
    ServerAliveCountMax 6
```

`runner` へ push するための別エントリ（git 経路専用、鍵も別）:

```
Host loop-runner
    HostName 127.0.0.1
    Port 2222
    User runner
    IdentityFile C:\Users\<you>\.ssh\loop-runner_ed25519
    IdentitiesOnly yes
```

プランナーの作業クローンはこれを使う:

```
git clone ssh://loop-runner/srv/loop/repo.git
```

### `.wslconfig`

`C:\Users\<you>\.wslconfig`。必須項目は `provision/README.md` §2-2。
**変更の反映には `wsl --shutdown` が必要**で、それは keepalive を殺すので必ずセットで扱う。
