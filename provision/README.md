# loop-runner VM のプロビジョニング

RUNNER_SPEC.md の実行環境（§1）を再現するための手順とスクリプト。

VM を作り直すときはこの手順をなぞる。**§3 の落とし穴は4つとも実際に踏んだもの**で、
どれも「一見成功して、後から静かに壊れる」種類なので飛ばさないこと。

---

## 1. 構成

| | |
|---|---|
| VM 名 | `loop-runner` |
| OS | Ubuntu Server 24.04.4 LTS (minimal) |
| CPU / RAM / Disk | 2 vCPU / 4096 MB / 20 GB（可変・上限） |
| NIC | NAT 1枚 + ポートフォワード `127.0.0.1:2222` → `22` |
| Guest Additions | 入れない（共有フォルダを使わないため） |

アカウント:

| ユーザー | uid | sudo | SSH | 用途 |
|---|---|---|---|---|
| `admin` | 1000 | あり | 鍵のみ | プロビジョニングと保守。普段使わない |
| `runner` | 1001 | **なし** | 鍵のみ | ループの実行主体。VS Code はここに繋ぐ |
| `solver` | 1002 | **なし** | **不可**（`DenyUsers`） | 実装を書くだけ |

---

## 2. 作り直す手順

ホスト（Windows / PowerShell）で実行する。`$VBM` は `VBoxManage.exe` のパス。

### 2-1. 鍵を作る（**Bash で**。理由は §3-4）

```bash
ssh-keygen -t ed25519 -f /c/Users/<you>/.ssh/loop-runner_ed25519 -N '' -C loop-runner-vm
# 必ず検証する。空パスフレーズで復号できなければ失敗している
ssh-keygen -y -f /c/Users/<you>/.ssh/loop-runner_ed25519 -P ''
```

公開鍵を `autoinstall_user_data` の `authorized-keys:` に貼る。

### 2-2. VM の器を作る

```powershell
& $VBM createvm --name loop-runner --ostype Ubuntu24_LTS_64 --register
# paravirtprovider はホストの仮想化バックエンドで決める（§3-7 を必ず読むこと）
#   Hyper-V が有効なホスト（VirtualBox が NEM モードで動く）→ none
#   Hyper-V が無効なホスト（ネイティブ VT-x）        → kvm（性能が上）
& $VBM modifyvm loop-runner --memory 4096 --cpus 2 --vram 16 `
    --paravirtprovider none --rtc-use-utc on --graphicscontroller vmsvga
& $VBM modifyvm loop-runner --nic1 nat --nat-pf1 "ssh,tcp,127.0.0.1,2222,,22"
& $VBM createmedium disk --filename "$dir\loop-runner.vdi" --size 20480 --format VDI
& $VBM storagectl loop-runner --name SATA --add sata --controller IntelAhci --portcount 2 --bootable on
& $VBM storageattach loop-runner --storagectl SATA --port 0 --device 0 --type hdd --medium "$dir\loop-runner.vdi"
& $VBM storagectl loop-runner --name IDE --add ide
& $VBM storageattach loop-runner --storagectl IDE --port 0 --device 0 --type dvddrive --medium emptydrive
```

### 2-3. 無人インストール

```powershell
& $VBM unattended install loop-runner `
  --iso="<path>\ubuntu-24.04.4-live-server-amd64.iso" `
  --user=admin --user-password=<PW> --full-user-name="Loop Admin" `
  --hostname=loop-runner.localdomain `
  --locale=en_US --country=US --time-zone=Asia/Tokyo `
  --package-selection-adjustment=minimal `
  --no-install-additions `
  --script-template="<repo>\provision\autoinstall_user_data" `
  --extra-install-kernel-parameters="autoinstall ds=nocloud\;s=file:///cdrom/ --- quiet noprompt noshell" `
  --start-vm=headless
```

完了判定は **`ssh -i <key> -p 2222 admin@127.0.0.1 hostname` が通ること**。
SSH ポートが開いたことを判定条件にしてはいけない（§3-3）。

### 2-4. プロビジョニング

```bash
ssh ... admin@127.0.0.1 'mkdir -p /tmp/loop-provision'
scp ... provision/*.sh <key>.pub admin@127.0.0.1:/tmp/loop-provision/
ssh ... admin@127.0.0.1 "cd /tmp/loop-provision && sed -i 's/\r\$//' *.sh && echo '<PW>' | sudo -S -p '' bash provision.sh"
```

`40-perms.sh` が solver 視点の assert を10項目走らせる。1つでも落ちたら異常終了する。

### 2-5. スナップショット

```powershell
& $VBM controlvm loop-runner acpipowerbutton   # 停止してから取る
& $VBM snapshot loop-runner take base --description "..."
```

---

## 3. 落とし穴

### 3-1. VirtualBox 標準テンプレートは SSH サーバを入れない

`UnattendedTemplates/ubuntu_autoinstall_user_data` に `ssh:` セクションがない。
そのまま使うと**ヘッドレス VM に一切入れなくなる**。

→ `autoinstall_user_data`（このディレクトリ）を `--script-template` で指定する。
公開鍵も同時に焼き込むので、初回から鍵認証で入れる。

### 3-2. `ds=nocloud;s=/cdrom/` では cloud-init が起動しない

VirtualBox 7.1 が生成する GRUB 行は `ds=nocloud\;s=/cdrom/` という古い書き方。
**Ubuntu 24.04.2 以降の cloud-init 24.x は NoCloud のシード指定にスキーム付き URL を
要求する**ようになり、素のパスを黙って無視する。結果、インストーラは
`waiting for cloud-init...` で**永久に停止**する（エラーは出ない）。

→ `--extra-install-kernel-parameters` で `s=file:///cdrom/` に上書きする。
なお VirtualBox はこのオプションを **`--dry-run` では grub.cfg に反映しない**ので、
確認は本番実行後に `Unattended-*-grub.cfg` を読むこと。

### 3-3. インストール完了を SSH ポートで判定してはいけない

Ubuntu のライブインストーラ自身が sshd を動かしている。**インストール前から
ポート 2222 は開いており、バナーも返る。** ポート監視は必ず誤検知する。

さらに、その時のホスト鍵が `known_hosts` に記録されると、インストール後に
ホスト鍵が変わって接続が拒否される（`StrictHostKeyChecking=no` はホスト鍵の
**変更**を素通ししない）。判定用の `known_hosts` は毎回捨てること。

→ 判定は **`admin` に鍵でログインして `hostname` が返るか**。ライブ環境には
`admin` も鍵も存在しないので区別できる。

### 3-4. PowerShell から `ssh-keygen -N ''` は空パスフレーズにならない

`-N '""'` も `--%` 経由の `-N ""` も、**空文字ではないパスフレーズ**として渡る。
生成自体は成功するので気づかない。症状は接続時の

```
debug1: Server accepts key: ...
Permission denied (publickey,password).
```

サーバ側ログは `Connection reset by authenticating user admin [preauth]`。
**サーバは鍵を受理していて、クライアントが署名できずに切っている。**
`authorized_keys` を疑って時間を溶かす典型。

→ 鍵の生成は Bash で行い、`ssh-keygen -y -f <key> -P ''` で必ず検証する。

### 3-5. sshd の drop-in は「先に読んだ値が勝つ」

cloud-init が `/etc/ssh/sshd_config.d/50-cloud-init.conf` に
`PasswordAuthentication yes` を書く（autoinstall の `allow-pw: true` 由来）。
`99-loop.conf` は**後から読まれるので負ける**。設定を書いても効かない。

→ ファイル名を `00-loop.conf` にする。そして `sshd -T` で**実効値を検証する**。
`50-lockdown.sh` はこの検証を持っており、効いていなければ異常終了する。

### 3-6. `set -o pipefail` 下の `... | grep -q`

`grep -q` は最初のマッチで即終了する。すると上流が SIGPIPE で死に、
**pipefail がパイプライン全体を失敗扱いにする。マッチしているのに失敗する。**
検証スクリプトで踏むと「正しい設定を誤りと判定する」ので厄介。

→ 一度変数に取ってから判定する。`50-lockdown.sh` の末尾を参照。

---

### 3-7. Hyper-V が有効なホストでは `--paravirtprovider kvm` がカーネルをハングさせる

Windows で Hyper-V / WSL2 / Virtual Machine Platform / メモリ整合性 のいずれかが
有効だと、VirtualBox は VT-x を直接使えず **NEM モード（Hyper-V の API 経由）**で動く。
この状態で Linux ゲストに `--paravirtprovider kvm` を与えると、kvm-clock まわりで
CPU ロックアップが起きる。

観測した症状:

```
nmi_backtrace_stall_check: CPU 1: NMIs are not reaching exc_nmi() handler
last activity: 4294855847 jiffies ago
```

jiffies 値が 32bit ラップした異常値になっているのがタイマー起因のサイン。
**厄介なのは再現性がないこと** ── インストールと初回起動は正常に通り、
スナップショット後の再起動で初めてハングした。

ホストの状態は次で判定する:

```powershell
(Get-CimInstance Win32_ComputerSystem).HypervisorPresent   # True なら NEM モード
```

| ホスト | 設定 | 備考 |
|---|---|---|
| `HypervisorPresent = False` | `--paravirtprovider kvm` | ネイティブ VT-x。**これが唯一まともに動く構成** |
| `HypervisorPresent = True` | `--paravirtprovider none` | **緩和にしかならない。下記参照** |

#### `none` にしても直らなかった

`kvm` → `none` に変更後、再起動テストを回した結果:

| 周回 | 結果 |
|---|---|
| 1 | 正常（クリーン停止 → SSH 復帰 73秒） |
| 2 | **ハング**（3分経っても早期ブート画面のまま、SSH 応答なし） |

`kvm` のときより頻度は下がったが、**2回に1回ハングする**状態で、
数時間ループを回す基盤としては使えない。

**結論: Hyper-V が有効な Windows ホストでは、VirtualBox をこの用途に使わない。**
取れる手は3つ:

1. **Hyper-V が無効な別マシンを使う**（推奨。§4）
2. **そのマシンで Hyper-V を無効化する** ── VT-x に戻り安定するが、
   **WSL2 も Docker Desktop も動かなくなる**
   ```powershell
   # 管理者権限。要再起動
   bcdedit /set hypervisorlaunchtype off
   dism /online /disable-feature /featurename:VirtualMachinePlatform
   # 戻すとき: bcdedit /set hypervisorlaunchtype auto
   ```
3. **VirtualBox をやめて WSL2 側に寄せる** ── 既に Hyper-V が動いているなら、
   そちらがネイティブ。ただし `/mnt/c` の自動マウントと Windows 実行ファイルの
   相互運用（`powershell.exe` が呼べてしまう）を `/etc/wsl.conf` で明示的に
   切らないと隔離が成立しない。**既定では隔離されていない**点に注意

---

## 4. 別のマシンへ移す

**VM をエクスポートせず、このディレクトリのスクリプトで作り直すことを勧める。**
`base` スナップショットの状態は §2 の手順で完全に再現でき、4GB の転送が要らない。
移すのは `provision/` ディレクトリと ISO だけ。

移設先で最初に確認すること:

```powershell
(Get-CimInstance Win32_ComputerSystem).HypervisorPresent   # → §3-7 で設定を決める
(Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)
```

`HypervisorPresent = False` なら:

- `--paravirtprovider kvm` に戻せる（性能が上がる）
- CPU とメモリに余裕があれば `--cpus 4 --memory 8192` へ引き上げてよい。
  pytest の実行が速くなるぶん、ループ1周が短くなる

鍵は移設先で**作り直す**こと（§2-1）。秘密鍵を持ち歩かない。
作り直したら公開鍵を `autoinstall_user_data` に貼り替える。

VM をそのまま持っていく場合は:

```powershell
& $VBM export loop-runner -o loop-runner.ova
# 移設先で
& $VBM import loop-runner.ova
& $VBM modifyvm loop-runner --paravirtprovider <none|kvm>   # 移設先に合わせて設定し直す
```

ただし OVA にはホストの公開鍵が焼き込まれた状態が含まれるので、
**移設先で `authorized_keys` を新しい鍵に差し替えるまで、元のマシンの鍵で入れてしまう。**

---

## 5. 未適用

`60-egress.sh` は**実行していない**。ソルバーの CLI とその API エンドポイントが
未決のため（RUNNER_SPEC §11-1）。

適用するまで、`solver` アカウントは**外部ネットワークに自由に出られる**。
つまり「詰まったら `pip install` する」経路が開いたままで、
RUNNER_SPEC 1-3 の環境凍結は成立していない。

ソルバーを決めたら:

```bash
sudo ./60-egress.sh <api-domain>
```
