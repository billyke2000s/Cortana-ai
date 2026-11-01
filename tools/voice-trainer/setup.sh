#!/usr/bin/env bash
# One-time setup for the local voice trainer.
# Run inside WSL2 Ubuntu (Windows) or Ubuntu Linux:   bash setup.sh
# Needs: an NVIDIA GPU with the normal Windows driver installed (WSL shares it).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PIPER="$HERE/piper1-gpl"

echo "== 1/5 System packages (asks for your Ubuntu password) =="
sudo apt-get update
sudo apt-get install -y build-essential cmake ninja-build espeak-ng \
  python3-venv python3-dev git ffmpeg

echo "== 2/5 Getting Piper (training code) =="
if [ ! -d "$PIPER" ]; then
  git clone https://github.com/OHF-voice/piper1-gpl.git "$PIPER"
fi
cd "$PIPER"

echo "== 3/5 Python environment =="
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip wheel setuptools
python3 -m pip install -e '.[train]'

echo "== 4/5 Building Piper's compiled parts =="
./build_monotonic_align.sh
python3 setup.py build_ext --inplace

echo "== 5/5 Extra tools (transcription + web app) =="
python3 -m pip install faster-whisper librosa soundfile numpy gradio huggingface_hub

echo
echo "== GPU check =="
if python3 -c "import torch,sys; ok=torch.cuda.is_available(); print('CUDA available:', ok, '|', torch.cuda.get_device_name(0) if ok else 'no GPU'); sys.exit(0 if ok else 1)"; then
  echo "GPU OK."
else
  echo "WARNING: PyTorch can't see your GPU. Training on CPU will be extremely slow."
  echo "Check 'nvidia-smi' works inside WSL and your Windows NVIDIA driver is up to date."
fi

cat > "$HERE/run.sh" <<EOF
#!/usr/bin/env bash
source "$PIPER/.venv/bin/activate"
python3 "$HERE/voice_trainer.py"
EOF
chmod +x "$HERE/run.sh"

echo
echo "Setup done. Start the trainer with:   bash $HERE/run.sh"
echo "Then open http://localhost:7860 in your Windows browser."
