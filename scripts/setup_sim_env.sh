#!/bin/sh
# setup_sim_env.sh — single setup entry point for the jn_sim simulator host.
#
# Spec: docs/spec_sim.md R1.5. POSIX sh, so it runs under macOS /bin/sh and
# (once T21 lands) Ubuntu's dash. It never uses sudo and never installs system
# packages: if something is missing it prints the exact command to fix it and
# stops. Running it twice is safe.
#
# It creates .venv/ at the repo root, installs the pinned requirements.lock,
# and installs the package editable (its deps are already pinned by the lock).

set -eu

# Repo root is the parent of this script's directory.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$REPO_ROOT"

LOCK="$REPO_ROOT/requirements.lock"
VENV="$REPO_ROOT/.venv"

die() {
    echo "setup_sim_env.sh: $1" >&2
    exit 1
}

if [ ! -f "$LOCK" ]; then
    die "requirements.lock not found at $LOCK.
    On a checkout, restore it:  git checkout -- requirements.lock
    Or regenerate it:           ~/.local/bin/uv pip compile --universal -p 3.12 requirements.in -o requirements.lock"
fi

OS=$(uname -s)
PY=""

case "$OS" in
Darwin)
    # macOS: Homebrew's python3.12 (framework build, suits the macosx backend).
    # 3.12 everywhere so the Mac matches the Jetson (spec §2).
    if command -v brew >/dev/null 2>&1; then
        PREFIX=$(brew --prefix python@3.12 2>/dev/null || true)
        if [ -n "$PREFIX" ] && [ -x "$PREFIX/bin/python3.12" ]; then
            PY="$PREFIX/bin/python3.12"
        fi
    fi
    # Fall back to the well-known Homebrew locations if `brew` is absent.
    if [ -z "$PY" ]; then
        for cand in \
            /opt/homebrew/opt/python@3.12/bin/python3.12 \
            /usr/local/opt/python@3.12/bin/python3.12; do
            if [ -x "$cand" ]; then
                PY="$cand"
                break
            fi
        done
    fi
    if [ -z "$PY" ]; then
        if command -v brew >/dev/null 2>&1; then
            die "Homebrew python@3.12 not found. Install it with:
    brew install python@3.12"
        else
            die "Homebrew not found, and no python@3.12 at the usual paths.
    Install Homebrew from https://brew.sh, then:
    brew install python@3.12"
        fi
    fi
    ;;
Linux)
    die "Linux support is an optional task (T21) and is not built yet.
    See docs/spec_sim.md T21. Use macOS for now."
    ;;
*)
    die "unsupported OS '$OS'. Only macOS is supported in the core build
    (Linux is optional, T21)."
    ;;
esac

WANT=$("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')
echo "setup_sim_env.sh: interpreter $PY (Python $WANT)"

VPY="$VENV/bin/python"

# Create the venv once; reuse it on re-runs, but only if it was built with the
# same interpreter version. Reusing a venv from a different Python silently
# installs into the wrong place (review F2).
if [ -x "$VPY" ]; then
    HAVE=$("$VPY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo "unknown")
    WANT_MM=${WANT%.*}
    HAVE_MM=${HAVE%.*}
    if [ "$HAVE_MM" != "$WANT_MM" ]; then
        die "existing .venv uses Python $HAVE but this host wants $WANT.
    Move the old venv aside (do not delete it), then re-run this script:
        mv '$VENV' \"\${TMPDIR:-/tmp}/jn-venv-$HAVE_MM\""
    fi
    echo "setup_sim_env.sh: reusing existing venv at $VENV (Python $HAVE)"
else
    echo "setup_sim_env.sh: creating venv at $VENV"
    "$PY" -m venv "$VENV"
fi

echo "setup_sim_env.sh: installing pinned requirements.lock (numpy, matplotlib, pytest + transitive)"
"$VPY" -m pip install --quiet -r "$LOCK"

echo "setup_sim_env.sh: installing jn_sim editable (--no-deps; its deps are pinned above)"
"$VPY" -m pip install --quiet --no-deps -e "$REPO_ROOT"

echo "setup_sim_env.sh: done. Activate with: . $VENV/bin/activate"
