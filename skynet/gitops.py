"""Operaciones git que usa el Core (checkpoints, commit si pasa, rollback si falla)."""
from __future__ import annotations

import subprocess
from pathlib import Path

SKYNET_DIR = ".skynet"  # estado de tareas dentro del repo; excluido de git localmente


class GitError(Exception):
    pass


def git(repo: Path, *args: str, check: bool = True, timeout: int = 120) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if check and r.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def is_repo(repo: Path) -> bool:
    try:
        return git(repo, "rev-parse", "--is-inside-work-tree", check=False).strip() == "true" and \
            Path(git(repo, "rev-parse", "--show-toplevel").strip()).resolve() == repo.resolve()
    except (FileNotFoundError, NotADirectoryError):
        return False


def ensure_repo(repo: Path) -> None:
    """Inicializa git si hace falta y excluye .skynet/ sin tocar el .gitignore del usuario."""
    repo.mkdir(parents=True, exist_ok=True)
    if not is_repo(repo):
        git(repo, "init", "-b", "main")
    if not git(repo, "config", "user.email", check=False).strip():
        git(repo, "config", "user.email", "skynet@localhost")
        git(repo, "config", "user.name", "Skynet")
    exclude = Path(git(repo, "rev-parse", "--git-path", "info/exclude").strip())
    if not exclude.is_absolute():
        exclude = repo / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if f"{SKYNET_DIR}/" not in current.splitlines():
        exclude.write_text(current.rstrip("\n") + ("\n" if current else "") + f"{SKYNET_DIR}/\n", encoding="utf-8")


def head(repo: Path) -> str | None:
    out = git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).strip()
    return out or None


def status(repo: Path) -> str:
    return git(repo, "status", "--porcelain")


def is_dirty(repo: Path) -> bool:
    return bool(status(repo).strip())


def commit_all(repo: Path, message: str) -> str | None:
    """Commit de todo lo cambiado. Devuelve el sha, o None si no había nada."""
    git(repo, "add", "-A")
    if not git(repo, "diff", "--cached", "--name-only").strip():
        return None
    git(repo, "commit", "-q", "--no-verify", "-m", message)
    return head(repo)


def rollback(repo: Path, sha: str | None) -> None:
    """Vuelve al checkpoint: deshace cambios y borra archivos nuevos (respeta .skynet/ e ignorados)."""
    if sha:
        git(repo, "reset", "-q", "--hard", sha)
    else:
        git(repo, "reset", "-q", "--hard", check=False)
    git(repo, "clean", "-fdq")


def log_oneline(repo: Path, n: int = 10) -> str:
    return git(repo, "log", f"-{n}", "--oneline", check=False).strip()


def diff_stat(repo: Path) -> str:
    return git(repo, "diff", "--stat", "HEAD", check=False).strip() if head(repo) else ""


def tracked_files(repo: Path, limit: int = 300) -> list[str]:
    files = git(repo, "ls-files", check=False).splitlines()
    return files[:limit]
