"""Fetch the exact public source revisions used by the hierarchy adapters.

Run with uv; credentials and environment files are not read.
"""
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "reference"
REFERENCES = {
    "jev-doc-search": ("https://github.com/VectifyAI/jev-doc-search.git",
                       "7b1008c437c8c9a88da8a427a76052fb0454977a"),
    "PageIndex": ("https://github.com/VectifyAI/PageIndex.git",
                  "6d23caf416858f2ca136840305d1f479a86f6ef7"),
}


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Verify existing checkouts without network or mutations")
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, (url, revision) in REFERENCES.items():
        path = ROOT / name
        if not path.exists():
            if args.check:
                raise SystemExit(f"Missing reference {name}; run setup_references.py first")
            subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout", url, str(path)], check=True)
            subprocess.run(["git", "checkout", "--detach", revision], cwd=path, check=True)
        actual = git("rev-parse", "HEAD", cwd=path)
        if actual != revision or git("status", "--porcelain", cwd=path):
            raise SystemExit(f"Reference {name} differs from the pinned revision; existing files were preserved")
        print(f"Verified {name}: {revision}")


if __name__ == "__main__":
    main()
