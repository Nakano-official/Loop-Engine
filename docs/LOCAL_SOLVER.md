# LOCAL_SOLVER.md — ローカルソルバーの導入と失敗表

solver（実装する役）にローカルモデル（Qwen3.5-9B / nonthinking）を据えるための手順書。
**Claude を介さずに最後まで進める**ことを目的に書いてある。ここは操作だけ。

> **solver はローカルモデルだけ**（REDESIGN §10 決定 11）。solver の通信は loopback の 8080 だけに
> 閉じてある（`provision/roles.json`）。ループからは、窓口の `attempt` が `solver-run` を通して呼ぶ。

---

## 0. この文書の作り方について

**費用は「動かすこと」ではなく「曖昧な失敗が生む往復」で発生する。**
だから以下は、失敗が起きない前提では書いていない。失敗が起きたとき、

- どこで落ちたかを**スクリプト自身が名乗る**（`smoke-local` は番号付きで PASS/FAIL を出す）
- 対処が**その場に書いてある**（下の失敗表）
- それでも分からないときに**貼るものが1つに決まっている**（`smoke-local` 末尾の `--- paste this ---` ブロック）

という形にしてある。人に聞く前に、まず `smoke-local` を通すこと。

---

## 1. 手順

### 1-1. llama.cpp を入れる（**ビルドが必要**）

```bash
/usr/lib/wsl/lib/nvidia-smi     # WSL 内から GPU が見えるか。PATH には無い
```

**リリースバイナリでは済まない。** llama.cpp は Linux 向けの CUDA バイナリを
配布しておらず（Windows 向けのみ）、Linux 用の Vulkan ビルドは WSL では
`llvmpipe`（ソフトウェアラスタライザ）しか見つけられない ── つまり GPU で動いて
いるように見えて CPU で回る。2026-09-01 にこの箱で実測。

```bash
# CUDA ツールチェーン（ドライバは Windows 側。ここでは入れない）
curl -sSLO https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb && sudo apt-get update
VER=$(apt-cache search '^cuda-nvcc-[0-9]' | awk '{print $1}' | sed 's/cuda-nvcc-//' | sort -V | tail -1)
sudo apt-get install -y "cuda-nvcc-$VER" "cuda-cudart-dev-$VER" "libcublas-dev-$VER"

git clone --depth 1 https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON \
      -DCMAKE_CUDA_ARCHITECTURES=75 -DLLAMA_CURL=OFF
cmake --build build -j"$(nproc)" --target llama-server
sudo install -m 755 build/bin/llama-server /usr/local/bin/
```

`75` は Turing（RTX 2060）。**アーキテクチャを1つに絞ること**と
**`llama-server` だけを作ること**で、ビルド時間の大半が消える。
それでも6コアで30分前後かかる（`ggml-cuda` の flash-attention テンプレートが大半）。

### 1-1b. この箱の実測値（2026-09-01）

| | |
|---|---|
| GPU | RTX 2060 / **VRAM 6144 MiB** / driver 591.59 / `/dev/dxg` あり |
| CPU / RAM | 6コア / 7.8 GiB（WSL VM の割当） |
| 選んだ量子化 | `Qwen3.5-9B-IQ4_XS.gguf` **4.81 GB** |
| ctx | **8192**（`--cache-type-k/v q8_0`）。max_output 4096 |

VRAM 6 GB に対し重みが 4.81 GB なので、残りで KV キャッシュと計算バッファを賄う。
`Q4_K_M`（5.29 GB）は full offload では入らない。入らなければ `Q3_K_M`（4.35 GB）へ。
**ctx を上げるより量子化を落とすほうが先** ── ブリーフ＋対象ファイルは 2〜3k トークンで、
8192 は既に余裕がある。

### 1-2. 重みを置く

```bash
sudo install -o root -g llm -m 0440 <model>.gguf /srv/loop/models/model.gguf
```

4bit 量子化で約 6GB。**0440 root:llm** なのは、solver アカウントに自分を動かしている
モデルのファイルを読ませる理由が無いため（取り上げたものを返さない）。

### 1-3. 配る

```bash
cd /srv/loop/provision   # ホストから rsync 済みのもの
sudo ./70-local-solver.sh
```

uid `llm` の作成、`/srv/loop/models` の権限、3本のスクリプトの設置まで。
**sudoers は変更しない** — `solver-run` が持つ Runas(solver) の1つの許可で足りる。

### 1-4. サーバを起動する

```bash
sudo systemctl enable --now loop-llm          # systemd がある場合
# 無い場合:
sudo -u llm setsid nohup /srv/loop/bin/llm-serve >/srv/loop/models/serve.out 2>&1 &
```

VM が生きている間だけ生きる。**`wsl --shutdown` 厳禁**（README 3-2）。

### 1-5. 配管を確かめる ← ここまで Claude 不要

```bash
sudo -u solver /srv/loop/bin/smoke-local
```

7項目。全部 PASS なら「配管は問題ではない」ことが確定する。
7番だけ FAIL する場合、それは**配管ではなくモデルの話**で、スクリプトがそう言う。

## 2. 失敗表

### `solver-local` の終了コード

| コード | 意味 | 対処 |
|---|---|---|
| 0 | 動いた（**中身が駄目でも 0**） | 下記「0 で返るのに何も起きない」参照 |
| 2 | 引数かブリーフが読めない | `solver-run` の呼び方。通常は起きない |
| 5 | ブリーフに `# Files you may create or modify` が無い | ブリーフの書式が変わった。`engine/briefs.py` と突き合わせる |
| 6 | プロンプトがコンテキストに入らない | `llm-serve` の `--ctx-size` と `LOOP_LLM_CTX` を上げる。上げられないならモジュールを分ける（2026-10-10 の迷路では、組み立ての例の重複が原因だった） |
| 7 | 推論サーバに届かない／拒否された | `pgrep -a -u llm llama-server`。落ちていれば 1-4 |
| 124 | 制限時間内に返らない | 窓口の制限時間（`engine/window.py`）を上げる。CPU 推論なら数倍必要 |

**非ゼロは、通しを「エンジン」として止める**（7 だけは窓口が数回やり直す）。どの段に戻しても直らないから。
だから「モデルが下手」は**絶対に非ゼロにしない**設計にしてある（下記）。下手なら試行の失敗として数える。

### 症状から引く

**0 で返るのに何も書かれない / VERIFY が毎回同じ失敗**
モデルが JSON を守れなかったか、許可外のパスを返した。`solver-local` が
`wrote nothing` / `refused [...]` と標準出力に書いている（試行の結果の `output` に入る）。
これは**設計どおり**の挙動 ── モデルの失敗は試行を1回消費するだけで、通しは止まらない。
何度も続くならステップが大きすぎる（次項）。

**ステップが大きすぎる**
`files_write` が2ファイル以上、あるいは実装が100行を超える見込みなら、9B には重い。
対処は `max_attempts` を増やすことではなく、**bootstrap をやり直してステップを細かくする**
（1ステップ＝1関数、`files_write` は1つ、テストは3本まで）。ただし bootstrap は
プランナー＝Claude を使うので、**1本目の結果を見てから**判断する。

**thinking が消えていない**（`smoke-local` の 6 が FAIL、または `<think>` 警告）
順に: (a) `llm-serve` に `--jinja` があるか ── これが無いとテンプレートが走らず
`enable_thinking` は黙って無視される。(b) その GGUF のテンプレートが
`enable_thinking` を読むか。**プロンプトで「考えるな」と書くのは対処ではない**
（要請は破られる。テンプレート側で経路を消す）。

**server too old**（不明なフィールドで 400、`/props` が `n_ctx` を返さない）
`chat_template_kwargs` と `response_format: json_schema` に対応した llama.cpp が要る。
新しいリリースバイナリに入れ替える。

**遅い**（`smoke-local` の 4 が FAIL、tok/s が1桁）
GPU に載っていない。`nvidia-smi` と `--n-gpu-layers`。載せられないなら設計は変わらないが、
`timeouts.solver` を大きく取り直し、1本の実時間の見積もりを作り直す。

**サーバに繋がらず `EHOSTUNREACH`（No route to host）で落ちる**
llama-server のポートが、`provision/roles.json` の solver の `loopback_tcp` と違う。solver は
表に書いたポートにしか出られない。表を直して `10-roles.sh` と `25-egress.sh` を当て直す。
`ECONNREFUSED`（Connection refused）なら規則は通っていて、サーバが上がっていない。
