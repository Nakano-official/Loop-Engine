# host/ — Windows 側の付属物

サンドボックスの外、ホスト側に置くもの。`provision/` がディストロの中を作るのに対し、
こちらは**ディストロを起動して繋ぐところ**を担当する。

WSL2 では起動と生存管理がホスト側の責務になった（`RUNNER_SPEC.md` §1-6）ので、
ここが無いとサンドボックスはそもそも上がってこない。

| ファイル | 置き場所 | 役割 |
|---|---|---|
| `loop-dev.cmd` | `C:\Users\<you>\bin\loop-dev.cmd`（PATH の通った場所） | ディストロ起動 → sshd 待機 → VS Code Remote-SSH 起動 |
| `wsl-keepalive.vbs` | このリポジトリのまま（タスクが絶対パスで参照する） | VM を**窓を出さずに**生かし続ける。下の keepalive タスクの実体 |
| `loop-pull.cmd` | このリポジトリのまま | **すべての** `repo*.git` を run ごとのミラーに引く。**VHDX を失っても残る唯一の複製** |

**ASCII のみで書くこと。** PowerShell 5.1 と cmd.exe は BOM 無し UTF-8 を ANSI として
読むため、日本語コメントを入れると行継続として誤解釈され、変数が黙って null になる
（`provision/README.md` §3-6）。

## リポジトリに入っていないもの

手で作る必要があるが、内容が短いのでここに手順だけ置く。

### keepalive スケジュールタスク（必須）

これが無いと VM が約60秒のアイドルで停止し、SSH が使えなくなる
（`provision/README.md` §3-1）。**タスクは `wsl.exe` を直接起動せず、
`wsl-keepalive.vbs` 越しに起動する**（理由は下の「窓を出さない」）。

```powershell
$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute "C:\Windows\System32\wscript.exe" `
  -Argument '"C:\dev\roop-engin\roop\host\wsl-keepalive.vbs"'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "WSL-keepalive-Ubuntu-24-04" `
  -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
```

`schtasks /create` ではなく `ScheduledTasks` モジュールを使うのは、
**`ExecutionTimeLimit` を無制限（`PT0S`）にできるのがこちらだけ**だから。
`schtasks` の既定は72時間で、越えるとタスクスケジューラが keepalive を止める。

`-RestartCount 3` により、keepalive が異常終了しても1分後に自動で戻る
（`.vbs` が `wsl.exe` の終了コードをそのまま返すのはこのため）。ただし
**ログオフで落ちた場合は戻らない** ── トリガが onlogon なので次のログオンまで待つ。

`wsl --shutdown` を打つと巻き添えで死ぬ。自動復帰を待たずに戻すなら
`schtasks /run /tn "WSL-keepalive-Ubuntu-24-04"`。

#### 窓を出さない

以前はタスクが `wsl.exe` を直接起動していた。`/rl limited` の対話タスクなので
**コンソール窓が開き、タスクバーに残る**。中身は `sleep infinity` なので何も表示されず、
見た目はただの空のターミナルで、**それを閉じると VM が落ちる。**
しかも onlogon なので自動では戻らない。1〜2時間ループを流している最中に、
誤クリック1回で全部止まるという壊れ方をする。

`WScript.Shell.Run(..., 0, True)` なら、同じ wsl.exe クライアントセッションを
窓なしで保持できる。アイドル判定が数えているのは窓ではなく**クライアントセッション**なので、
生存条件は変わらない（切り替え中も VM は落ちなかった。実測 2026-08-19）。

生きているかは窓ではなくプロセスで見る:

```powershell
Get-CimInstance Win32_Process -Filter "Name='wsl.exe' or Name='wscript.exe'" |
  Select-Object ProcessId, ParentProcessId, Name
```

`wscript.exe` の親が `svchost.exe`（タスクスケジューラ）になっていれば正しい。

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

### ホスト側のミラー（バックアップ）

ループの成果物は3段で外に出る。**段が上がるほど失いにくくなる:**

| 段 | どこへ | 何から守るか |
|---|---|---|
| 1 | `project` → `/srv/loop/repo.git` | `reset` / `clean`。**同じ VHDX の中**なので、それ以上は守らない |
| 2 | `repo.git` → `C:\dev\roop-engin\project` | **VHDX の消失**。ここで初めて別のディスクに乗る |
| 3 | ミラー → GitHub など | ホストの故障。やるなら**鍵はホストだけが持つ** |

段1 はランナーが自動でやる（`loop.py` の `publish()`、GREEN と `plan apply` の直後）。
段2 が `loop-pull.cmd`。**引数も事前のクローンも要らない** ── サンドボックスにある
`repo*.git` を全部列挙し、無ければクローン、有れば fetch する。

```
/srv/loop/repo.runN.git  ->  C:\dev\roop-engin\project.runN   （不変。ff のみ）
/srv/loop/repo.git       ->  C:\dev\roop-engin\project        （現行。毎回作り直す）
```

**run ごとにディレクトリを分けるのは整頓ではなく保存のため。** どの run も
`step-S1`…`step-S11` という同じタグ名を作るので、1つのクローンに引くと `--force` で
前の run のタグを上書きするしかなく、`main` も動かせば**古い run のコミットを指す ref が
1つも残らない**。到達不能なオブジェクトは `git gc` が消し、gc は普通のコマンドの中で
勝手に走る。**誰も見ていない時点でバックアップが消える。**

この形はサンドボックス側が既に採っているもの（`project.run5` / `repo.run5.git`）と同じ。
**コピーはコピー元と同じ形をしているべき**で、`ls` 一発で何を持っているか分かる。

`project`（現行 run）は毎回 `reset --hard` と `clean` で作り直す。run ごとに
`repo.git` は新しい root コミットから始まるので ff できないため。
**したがって `project\` に自分の物を置かないこと** ── 維持されるのではなく作り直される。
その回の内容は次の pull までに `project.runN` として捕まっているので、失われるものは無い。

**押すのではなく引くのは意図的**。サンドボックスは生成されたコードを実行する場所なので、
外に届く認証情報をその中に置かない。段3 をやる場合も同じで、GitHub の鍵は
**VM に入れず**、ホストのミラーから押す。

### `.wslconfig`

`C:\Users\<you>\.wslconfig`。必須項目は `provision/README.md` §2-2。
**変更の反映には `wsl --shutdown` が必要**で、それは keepalive を殺すので必ずセットで扱う。
