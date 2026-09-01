#!/usr/bin/env bash
# The local solver backend: an account for the model server, the two scripts,
# and a place for the weights. Idempotent.
#
#     sudo ./70-local-solver.sh
#
# NOT run by provision.sh, for the same reason as 60-egress.sh: it is only
# correct once you have decided to run a local model at all.
#
# No sudoers change is needed and none is made. solver-run already holds the one
# Runas(solver) grant, and it exec's this backend as the SAME uid -- the runner
# gains nothing it did not have, which is the property that made naming backends
# rather than commands worth the extra file.
set -euo pipefail
cd "$(dirname "$0")"

[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

# A fourth account, deliberately. The model server is neither the solver nor the
# runner: the solver reaches it over loopback and cannot restart it, read the
# weights, or change how it was started. Same reasoning as every other uid here
# -- the fence is the account, not an agreement about who calls what.
if ! id -u llm >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /home/llm --shell /usr/sbin/nologin llm
  chmod 700 /home/llm
  echo "created uid llm"
fi

# Weights and the server log. Root-owned; llm reads, nobody else needs to.
install -d -o root -g root -m 755 /srv/loop/models
chown root:llm /srv/loop/models
chmod 2750 /srv/loop/models

install -o root -g root -m 755 bin/llm-serve    /srv/loop/bin/llm-serve
install -o root -g root -m 755 bin/solver-local /srv/loop/bin/solver-local
install -o root -g root -m 755 bin/smoke-local  /srv/loop/bin/smoke-local

echo
echo "installed:"
echo "  /srv/loop/bin/llm-serve      (run as llm)"
echo "  /srv/loop/bin/solver-local   (exec'd by solver-run when a plan names it)"
echo "  /srv/loop/bin/smoke-local    (run as solver)"

# --------------------------------------------------------------------------
# The one step this script will NOT do blind.
# --------------------------------------------------------------------------
if ! command -v llama-server >/dev/null 2>&1; then
  cat <<'EOF'

llama-server is not on PATH, and this script deliberately does not install it:
a CUDA build guessed at from here is exactly the kind of failure that costs an
afternoon. Pick one, then re-run this script.

  (a) Release binary, CUDA:
        https://github.com/ggml-org/llama.cpp/releases  ->  llama-*-bin-ubuntu-x64-cuda.zip
        unzip into /usr/local/bin, then: llama-server --version

  (b) Build it:
        apt-get install -y build-essential cmake libcurl4-openssl-dev
        git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
        cmake -B build -DGGML_CUDA=ON && cmake --build build -j --config Release
        install build/bin/llama-server /usr/local/bin/

  No GPU visible in WSL?  nvidia-smi   inside the distro answers that. If it is
  absent, drop -DGGML_CUDA=ON, expect single-digit tokens/second, and read the
  timeout note in LOCAL_SOLVER.md before running a plan.
EOF
fi

if [ ! -r /srv/loop/models/model.gguf ] && [ -z "${LOOP_LLM_WEIGHTS:-}" ]; then
  cat <<'EOF'

No weights yet. Put the .gguf at /srv/loop/models/model.gguf:

    install -o root -g llm -m 0440 <downloaded>.gguf /srv/loop/models/model.gguf

0440 root:llm on purpose -- the solver account has no reason to read the model
it is being served by, and giving it the file back would be handing over
something the design just took away.
EOF
fi

# --------------------------------------------------------------------------
# Keeping the server up
# --------------------------------------------------------------------------
if [ -d /run/systemd/system ]; then
  cat > /etc/systemd/system/loop-llm.service <<'EOF'
[Unit]
Description=loop local inference server
After=network.target

[Service]
User=llm
ExecStart=/srv/loop/bin/llm-serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  echo
  echo "systemd is present. Start it with:"
  echo "    systemctl enable --now loop-llm"
  echo "    systemctl status loop-llm --no-pager"
else
  cat <<'EOF'

systemd is not running in this distro, so there is no unit to enable. Start the
server detached and leave it:

    sudo -u llm setsid nohup /srv/loop/bin/llm-serve >/srv/loop/models/serve.out 2>&1 &

It lives as long as the VM does. The VM lives as long as the keepalive task
does -- so the rule from README 3-2 applies here too: do NOT `wsl --shutdown`.
EOF
fi

cat <<'EOF'

Next:
    sudo -u solver /srv/loop/bin/smoke-local

Then, in plan/tasks.json:
    "solver_tiers": ["local", "codex"],
    "policy": {"retry": "resample"},
    "limits": {"attempts": 8}

WARNING about 60-egress.sh: with "codex" still in solver_tiers the solver needs
its outbound API host. Tightening egress to loopback-only breaks the fallback
tier, and it breaks it as a timeout rather than as an error. Tighten only once
the tier list is local-only.
EOF
