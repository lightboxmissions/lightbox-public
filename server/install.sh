#!/usr/bin/env bash
# =====================================================================
#  Lunis - one-command SERVER installer (Ubuntu / Debian)
#
#  Run this ON your own Linux box (the machine that will BE the server).
#  It installs and auto-starts everything Lunis needs:
#    - the Lunis web app            (port 8090)
#    - llama.cpp + Qwen2.5-3B model    (port 8080)  the AI tutor
#    - LibreTranslate                  (port 5000)  offline translation
#  ...all as auto-restarting services that come back on reboot.
#
#  Usage:
#    git clone https://github.com/lunislearning/Lunis.git ~/lunis
#    cd ~/lunis && bash server/install.sh
#
#  Safe to re-run: it skips anything already installed.
# =====================================================================
set -euo pipefail

# --- where things live -------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
APP="$REPO/app"

MODEL_DIR="$HOME/models"
MODEL_FILE="qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_URL="${LUNIS_MODEL_URL:-https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf?download=true}"
LLAMA_DIR="$HOME/llama.cpp"
LT_VENV="$HOME/libretranslate-venv"
UNIT_DIR="$HOME/.config/systemd/user"

say()  { echo -e "\n\033[1;36m==> $*\033[0m"; }
ok()   { echo -e "    \033[1;32m[ok]\033[0m $*"; }
warn() { echo -e "    \033[1;33m[!]\033[0m $*"; }

echo   "======================================="
echo   "  Lunis server installer"
echo   "======================================="
echo   "  Repo:  $REPO"
echo   "  App :  $APP"

# --- 1. system packages ------------------------------------------------
say "Installing system packages (needs sudo)"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv git curl build-essential cmake
ok "packages installed"

# --- 2. build llama.cpp (the AI engine) --------------------------------
if [ -x "$LLAMA_DIR/build/bin/llama-server" ]; then
    ok "llama.cpp already built"
else
    say "Building llama.cpp (a few minutes on a CPU box)"
    if [ -d "$LLAMA_DIR/.git" ]; then (cd "$LLAMA_DIR" && git pull --ff-only || true)
    else git clone --depth 1 https://github.com/ggml-org/llama.cpp "$LLAMA_DIR"; fi
    cmake -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" -DCMAKE_BUILD_TYPE=Release
    cmake --build "$LLAMA_DIR/build" -j "$(nproc)" --config Release
    ok "llama.cpp built"
fi

# --- 3. download the model (~1.9 GB, one time) -------------------------
mkdir -p "$MODEL_DIR"
if [ -f "$MODEL_DIR/$MODEL_FILE" ]; then
    ok "model already present ($MODEL_FILE)"
else
    say "Downloading the Qwen2.5-3B model (~1.9 GB - this can take a while)"
    curl -L --fail -C - -o "$MODEL_DIR/$MODEL_FILE.part" "$MODEL_URL"
    mv "$MODEL_DIR/$MODEL_FILE.part" "$MODEL_DIR/$MODEL_FILE"
    ok "model downloaded"
fi

# --- 4. LibreTranslate (offline translation) ---------------------------
if [ -x "$LT_VENV/bin/libretranslate" ]; then
    ok "LibreTranslate already installed"
else
    say "Installing LibreTranslate in its own virtualenv"
    python3 -m venv "$LT_VENV"
    "$LT_VENV/bin/pip" install --upgrade pip
    "$LT_VENV/bin/pip" install libretranslate
    ok "LibreTranslate installed"
fi

# --- 5. lesson videos + the transcripts the tutor reads ----------------
# The videos are not in the git repo (CC BY-NC-SA, ~570 MB; see NOTICE.md).
# They are published as a release asset and fetched here, so one command gets
# both the code and the content. If the download fails the install continues:
# everything except the video lessons works without them.
say "Downloading lesson videos (~570 MB, one time)"
if ( cd "$REPO" && python3 scripts/fetch_content.py --download ); then
    ok "lesson videos ready"
else
    warn "could not download the lesson videos"
    warn "everything else (Reading Hub, Homework Helper, dashboard) still works"
    warn "to retry later:  python3 scripts/fetch_content.py --download"
fi

say "Preparing lesson transcripts"
if [ -d "$REPO/content" ] && ls "$REPO/content"/*.srt >/dev/null 2>&1; then
    ( cd "$REPO" && python3 app/prep.py ) || warn "prep.py had a hiccup (non-fatal)"
else
    warn "no lesson videos present - skipping transcripts"
fi

# --- 6. create the auto-start services ---------------------------------
say "Creating auto-start services (systemd --user)"
mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/lunis-llama.service" <<EOF
[Unit]
Description=llama.cpp (Qwen2.5-3B) for Lunis
After=network.target
[Service]
Type=simple
ExecStart=$LLAMA_DIR/build/bin/llama-server -m $MODEL_DIR/$MODEL_FILE --host 127.0.0.1 --port 8080 -c 4096 -t $(nproc)
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
EOF

cat > "$UNIT_DIR/lunis-translate.service" <<EOF
[Unit]
Description=LibreTranslate for Lunis
After=network.target
[Service]
Type=simple
ExecStart=$LT_VENV/bin/libretranslate --host 127.0.0.1 --port 5000 --load-only en,fr,es,de
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
EOF

cat > "$UNIT_DIR/lunis.service" <<EOF
[Unit]
Description=Lunis math tutor web app
After=network.target lunis-llama.service lunis-translate.service
[Service]
Type=simple
WorkingDirectory=$APP
ExecStart=/usr/bin/python3 $APP/server.py
Restart=always
RestartSec=3
[Install]
WantedBy=default.target
EOF
ok "service files written to $UNIT_DIR"

# --- 7. enable + start -------------------------------------------------
say "Enabling and starting everything"
loginctl enable-linger "$USER" >/dev/null 2>&1 || warn "could not enable linger (services still start while you're logged in)"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
systemctl --user daemon-reload
systemctl --user enable --now lunis-llama lunis-translate lunis
ok "services enabled (they now start on boot)"

# --- 8. health check ---------------------------------------------------
say "Checking the app is up"
CODE=000
for i in $(seq 1 20); do
    CODE=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/ || true)
    [ "$CODE" = "200" ] && break
    sleep 1
done

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "======================================="
if [ "$CODE" = "200" ]; then
    echo -e "  \033[1;32mLunis is RUNNING\033[0m"
else
    echo -e "  \033[1;33mApp not answering yet (HTTP $CODE)\033[0m"
    echo   "  Check: systemctl --user status lunis"
fi
echo   "======================================="
echo   "  Open it from this machine:   http://127.0.0.1:8090"
[ -n "${IP:-}" ] && echo "  From other devices on the LAN: http://$IP:8090"
echo
echo   "  Notes:"
echo   "   - The AI model and translator load in the background; the very first"
echo   "     AI answer (and first LibreTranslate start) can take a minute."
echo   "   - Manage services:  systemctl --user status|restart lunis"
echo   "                       systemctl --user status lunis-llama lunis-translate"
echo   "   - Logs:             journalctl --user -u lunis -n 50"
echo   "   - First time you open it, an on-screen wizard sets the teacher password."
echo   "   - To let kids connect over Wi-Fi with no internet, turn on a hotspot:"
echo   "       nmcli device wifi hotspot ssid lunis password <choose-one>"
echo
