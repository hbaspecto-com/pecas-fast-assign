"""Print shell env-var assignments needed to compile native dependencies
from source on this platform.

aequilibrae ships no macOS wheel on PyPI, so pip must build its C++
extension from source there; that extension needs an OpenMP-capable
compiler, which Apple's system clang is not. On platforms with prebuilt
wheels (Linux, Windows) nothing needs to be printed.

Run with the project venv's Python so PyYAML (a project dependency) is
already available. Prints nothing on success paths that need no special
env; warnings go to stderr so they don't get eval'd as env assignments.
"""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.yaml"


def brew_prefix(package: str) -> str | None:
    if shutil.which("brew") is None:
        return None
    try:
        return subprocess.check_output(["brew", "--prefix", package], text=True).strip()
    except subprocess.CalledProcessError:
        return None


def main() -> int:
    if platform.system() != "Darwin":
        return 0

    settings = yaml.safe_load(SETTINGS_PATH.read_text())
    macos = (settings.get("build") or {}).get("macos") or {}
    compiler_pkg = macos.get("compiler")
    openmp_pkg = macos.get("openmp_runtime")
    if not compiler_pkg or not openmp_pkg:
        return 0

    llvm_prefix = brew_prefix(compiler_pkg)
    libomp_prefix = brew_prefix(openmp_pkg)
    if not llvm_prefix or not libomp_prefix:
        print(
            f"warning: could not locate Homebrew packages '{compiler_pkg}' and/or "
            f"'{openmp_pkg}' needed to compile native extensions on macOS. "
            f"Install with: brew install {compiler_pkg} {openmp_pkg}",
            file=sys.stderr,
        )
        return 0

    # Quoted so eval'ing this output doesn't split LDFLAGS's space-separated
    # flags into a separate (and invalid) shell command.
    print(f'CC="{llvm_prefix}/bin/clang"')
    print(f'CXX="{llvm_prefix}/bin/clang++"')
    print(f'CPPFLAGS="-I{libomp_prefix}/include"')
    print(f'LDFLAGS="-L{libomp_prefix}/lib -Wl,-rpath,{libomp_prefix}/lib"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
