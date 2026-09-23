#!/usr/bin/env python3
"""
doctor.py — check the setup before you waste an hour on it.

    python -m scripts.doctor

Ten checks, in the order things actually break. Each failure prints the exact
command that fixes it. The last check spends about 10 tokens proving the model
really answers; everything before it is free.

Nothing here is part of the exercise. It exists so that a bad environment
announces itself in five seconds instead of halfway through a grader run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

def find_root() -> Path:
    """
    Locate the repository root, wherever this file has been put.

    Deriving it as `__file__/../..` assumes doctor.py sits in scripts/. When
    someone drops it in the project root instead — which is the obvious thing
    to do with a file you were handed — that lands one level ABOVE the repo,
    and every path-based check then fails with a misleading message: no .env,
    no datasets, "the clone is incomplete". So look for the repo instead of
    assuming where it is.
    """
    markers = ("run_grader.py", "agent")

    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if all((candidate / m).exists() for m in markers):
            return candidate

    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if all((candidate / m).exists() for m in markers):
            return candidate

    return here.parent.parent


ROOT = find_root()
sys.path.insert(0, str(ROOT))

PASS, FAIL, WARN = "  ok  ", " FAIL ", " warn "
_failed = 0
_warned = 0


def ok(label: str, detail: str = "") -> None:
    print(f"[{PASS}] {label}" + (f"   {detail}" if detail else ""))


def warn(label: str, detail: str) -> None:
    global _warned
    _warned += 1
    print(f"[{WARN}] {label}   {detail}")


def fail(label: str, detail: str, fix: str) -> None:
    global _failed
    _failed += 1
    print(f"[{FAIL}] {label}   {detail}")
    for line in fix.splitlines():
        print(f"         {line}")


def env_file_keys() -> set:
    """Which variables .env actually defines, so we can tell it from the shell."""
    path = ROOT / ".env"
    if not path.exists():
        return set()
    keys = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if value.strip():
            keys.add(name.strip())
    return keys


def source_of(name: str, from_file: set) -> str:
    return ".env" if name in from_file else "your shell"


def mask(value: str) -> str:
    """Enough to tell two keys apart, not enough to use one."""
    if not value:
        return "(empty)"
    if len(value) <= 12:
        return value[:2] + "*" * (len(value) - 2)
    return f"{value[:6]}...{value[-4:]}  ({len(value)} chars)"


def identify_key(value: str) -> tuple[str, str | None]:
    """
    Name the credential from its prefix, and say so when it is in the wrong
    variable. "I have an API key" covers at least five different things and
    only two of them belong in AWS_BEARER_TOKEN_BEDROCK.

        ABSK...              Bedrock API key, long-term      (132 chars)
        bedrock-api-key-...  Bedrock API key, short-term     (1000+ chars)
        sk-ant-...           Anthropic API key               (not AWS)
        AKIA...              IAM access key, permanent
        ASIA...              IAM access key, temporary

    Returns (description, problem or None).
    """
    if value.startswith("ABSK"):
        return "Bedrock API key (long-term)", None
    if value.startswith("bedrock-api-key-"):
        return "Bedrock API key (short-term, expires within 12h)", None
    if value.startswith("sk-ant-"):
        return (
            "an ANTHROPIC api key",
            "That is an Anthropic API key, not an AWS one. It will never work\n"
            "against Bedrock.\n"
            "Either:  set ANTHROPIC_API_KEY=<this key> and LLM_BACKEND=anthropic\n"
            "Or:      get a Bedrock API key from the AWS console instead.",
        )
    if value.startswith(("AKIA", "ASIA")):
        return (
            "an IAM access key id",
            "That is an IAM access key, not a Bedrock API key. It belongs in a\n"
            "different variable and needs its secret alongside it.\n"
            "Fix:  clear AWS_BEARER_TOKEN_BEDROCK, then set\n"
            "      AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY"
            + ("\n      plus AWS_SESSION_TOKEN (ASIA keys are temporary)"
               if value.startswith("ASIA") else ""),
        )
    if len(value) < 40:
        return (
            "an unrecognised value",
            "That is too short to be a Bedrock API key. A long-term key is ~132\n"
            "characters starting ABSK; a short-term one is 1000+ characters\n"
            "starting bedrock-api-key-. Check the paste was not truncated.",
        )
    return "an unrecognised key format", None


# ---------------------------------------------------------------------------
def check_python() -> None:
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 9):
        fail(
            "python version",
            f"{major}.{minor} is too old",
            "Install Python 3.11 or newer.\n"
            "  macOS:  brew install python@3.12\n"
            "  then:   rm -rf .venv && python3.12 -m venv .venv && "
            "source .venv/bin/activate",
        )
    elif (major, minor) == (3, 9):
        warn(
            "python version",
            "3.9 — the workshop code runs on it, but some packages no longer\n"
            "         publish wheels for 3.9. If pip refuses anthropic or pandas,\n"
            "         that is why:\n"
            "           brew install python@3.12\n"
            "           rm -rf .venv && python3.12 -m venv .venv\n"
            "           source .venv/bin/activate && pip install -r requirements.txt",
        )
    else:
        ok("python version", f"{major}.{minor}")


def check_location() -> None:
    """Where this script was run from, and whether it found the repo."""
    expected = ROOT / "scripts" / "doctor.py"
    actual = Path(__file__).resolve()
    if actual != expected and (ROOT / "run_grader.py").exists():
        warn(
            "script location",
            f"running from {actual.parent.name or actual.parent}/ rather than "
            f"scripts/\n         (harmless — repo found at {ROOT})",
        )


def check_venv() -> None:
    active = sys.prefix != sys.base_prefix
    if active:
        ok("virtualenv", Path(sys.prefix).name)
    else:
        warn(
            "virtualenv",
            "not active — packages are going to your system Python\n"
            "         python3 -m venv .venv && source .venv/bin/activate",
        )


def check_cwd() -> None:
    if (Path.cwd().resolve() / "run_grader.py").exists():
        ok("working directory", str(Path.cwd()))
    elif (ROOT / "run_grader.py").exists():
        # The doctor found the repo anyway, but the other entry points resolve
        # their imports relative to the working directory and will not.
        warn(
            "working directory",
            f"you are in {Path.cwd()}\n"
            f"         run_grader.py and run_chatbot.py need the repo root:\n"
            f"           cd {ROOT}",
        )
    else:
        fail(
            "working directory",
            f"{Path.cwd()} is not the repository root, and no repository was found",
            "cd into the folder you cloned, then run this again.",
        )


def check_packages() -> None:
    required = [("dotenv", "python-dotenv"), ("pandas", "pandas")]
    missing = []
    for module, package in required:
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        fail(
            "core packages",
            f"missing: {', '.join(missing)}",
            "pip install -r requirements.txt",
        )
    else:
        ok("core packages", "dotenv, pandas")


def check_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        fail(
            ".env file",
            "not found",
            "cp .env.example .env\n"
            "Then open .env and fill in your credentials.",
        )
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path)
    except ImportError:
        return
    ok(".env file", str(env_path))


def check_backend() -> str:
    backend = (os.getenv("LLM_BACKEND") or "").strip().lower()
    if not backend:
        fail(
            "LLM_BACKEND",
            "not set",
            "Add to .env:  LLM_BACKEND=bedrock",
        )
        return ""
    if backend not in {"local", "anthropic", "bedrock", "openai"}:
        fail(
            "LLM_BACKEND",
            f"{backend!r} is not valid",
            "Valid: local, anthropic, bedrock, openai",
        )
        return ""
    ok("LLM_BACKEND", backend)
    return backend


def check_sdk(backend: str) -> None:
    if backend not in {"bedrock", "anthropic"}:
        return
    try:
        import anthropic
    except ImportError:
        fail(
            "anthropic sdk",
            "not installed",
            "pip install -r requirements.txt",
        )
        return

    version = getattr(anthropic, "__version__", "0.0.0")
    parts = []
    for chunk in str(version).split(".")[:3]:
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)

    using_token = bool((os.getenv("AWS_BEARER_TOKEN_BEDROCK") or "").strip())
    if backend == "bedrock" and using_token and tuple(parts) < (0, 88, 0):
        fail(
            "anthropic sdk",
            f"{version} — too old for Bedrock API keys",
            "Bearer token auth arrived in 0.88.0. Below that your key is\n"
            "ignored and the error blames credentials.\n"
            "pip install -U 'anthropic>=0.88'",
        )
    else:
        ok("anthropic sdk", version)


def check_region(backend: str) -> None:
    if backend != "bedrock":
        return
    region = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "").strip()
    if not region:
        fail(
            "AWS_REGION",
            "not set — the SDK will not guess",
            "Add to .env:  AWS_REGION=us-east-1\n"
            "Use the region your Bedrock access is in.",
        )
    else:
        ok("AWS_REGION", region)


def check_credentials(backend: str) -> None:
    if backend != "bedrock":
        return

    token = (os.getenv("AWS_BEARER_TOKEN_BEDROCK") or "").strip()
    access = (os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
    secret = (os.getenv("AWS_SECRET_ACCESS_KEY") or "").strip()
    session = (os.getenv("AWS_SESSION_TOKEN") or "").strip()
    profile = (os.getenv("AWS_PROFILE") or "").strip()

    if token and (access or profile):
        from_file = env_file_keys()
        other = "AWS_ACCESS_KEY_ID" if access else "AWS_PROFILE"
        token_src = source_of("AWS_BEARER_TOKEN_BEDROCK", from_file)
        other_src = source_of(other, from_file)
        fail(
            "credentials",
            "two credential types set at once",
            f"AWS_BEARER_TOKEN_BEDROCK comes from {token_src}.\n"
            f"{other} comes from {other_src}.\n"
            "The SDK refuses both: 'Cannot specify both api_key and AWS credentials'.\n"
            + (
                f"Fix:  unset {other} AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN\n"
                "      (and remove the export from ~/.zshrc so it does not come back)"
                if other_src == "your shell"
                else f"Fix:  comment out {other} in .env"
            ),
        )
        return

    if token:
        if token.startswith(("'", '"')) or token.endswith(("'", '"')):
            fail(
                "credentials",
                "the key has quotes around it",
                "Remove them. .env needs  KEY=value  with no quotes.",
            )
            return
        description, problem = identify_key(token)
        if problem:
            fail("credentials", f"AWS_BEARER_TOKEN_BEDROCK holds {description}", problem)
        else:
            ok("credentials", f"{description}  {mask(token)}")
        return

    if access:
        if not secret:
            fail(
                "credentials",
                "AWS_ACCESS_KEY_ID set, AWS_SECRET_ACCESS_KEY missing",
                "Set both, or switch to AWS_BEARER_TOKEN_BEDROCK.",
            )
            return
        temporary = access.startswith("ASIA") or bool(session)
        if temporary and not session:
            fail(
                "credentials",
                f"{mask(access)} is a temporary key but AWS_SESSION_TOKEN is missing",
                "An ASIA... key is short-term and is not valid on its own.\n"
                "Copy the session token too, or use a Bedrock API key instead.",
            )
        else:
            kind = "temporary (session token present)" if temporary else "long-term IAM user"
            ok("credentials", f"IAM SigV4, {kind}  {mask(access)}")
        try:
            import boto3  # noqa: F401

            ok("boto3", "installed (needed for SigV4)")
        except ImportError:
            fail(
                "boto3",
                "not installed, and SigV4 needs it",
                "pip install boto3\n"
                "Or switch to a Bedrock API key, which needs no boto3.",
            )
        return

    if profile:
        ok("credentials", f"AWS profile {profile!r}")
        return

    fail(
        "credentials",
        "none found",
        "Set ONE of these in .env:\n"
        "  AWS_BEARER_TOKEN_BEDROCK=...        (a Bedrock API key)\n"
        "  AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY\n"
        "  AWS_PROFILE=...",
    )


def check_model(backend: str) -> None:
    if backend != "bedrock":
        return
    model = (os.getenv("LLM_MODEL") or "").strip()
    if not model:
        warn("LLM_MODEL", "not set — the default inference profile will be used")
        return
    looks_like_profile = model.startswith(("global.", "us.", "eu.", "apac.", "arn:aws:"))
    if not looks_like_profile:
        fail(
            "LLM_MODEL",
            f"{model!r} looks like a bare model id",
            "Bedrock rejects bare ids with 'on-demand throughput isn't supported'.\n"
            "Use an inference profile:\n"
            "  LLM_MODEL=global.anthropic.claude-haiku-4-5-20251001-v1:0",
        )
    else:
        ok("LLM_MODEL", model)


def check_data() -> None:
    needed = [
        ROOT / "data" / "bank_products.md",
        ROOT / "data" / "user_accounts.json",
        ROOT / "datasets" / "pentesting_public.csv",
        ROOT / "datasets" / "functionality.csv",
    ]
    missing = [p.name for p in needed if not p.exists()]
    if missing:
        fail(
            "repository files",
            f"missing: {', '.join(missing)}",
            "The clone is incomplete. Re-clone the repository.",
        )
    else:
        ok("repository files", "data and datasets present")


def check_live_call(backend: str) -> None:
    if _failed:
        print(f"\n[{WARN}] live model call   skipped — fix the failures above first")
        return
    print(f"[ .... ] live model call   calling {backend}...", end="\r", flush=True)
    try:
        from agent.llm import call_llm

        response = call_llm(
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            max_tokens=10,
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001 — this is the diagnostic
        print(" " * 70, end="\r")
        message = str(exc).strip()
        first, *rest = message.splitlines()
        fail("live model call", first, "\n".join(rest) if rest else "See the error above.")
        return
    print(" " * 70, end="\r")
    text = (response.text or "").strip().replace("\n", " ")
    if not text:
        fail(
            "live model call",
            "the model returned nothing",
            "Credentials work but the response was empty. Try again; if it\n"
            "persists, the model id may not be served in this region.",
        )
        return
    ok("live model call", f"{text[:40]!r}  usage={response.usage}")


# ---------------------------------------------------------------------------
def main() -> int:
    print("\n  Workshop setup check\n  " + "-" * 60)
    check_python()
    check_venv()
    check_location()
    check_cwd()
    check_packages()
    check_env_file()
    backend = check_backend()
    check_sdk(backend)
    check_region(backend)
    check_credentials(backend)
    check_model(backend)
    check_data()
    check_live_call(backend)

    print("  " + "-" * 60)
    if _failed:
        print(f"\n  {_failed} check(s) failed. Fix the top one first — they cascade.\n")
        return 1
    if _warned:
        print(f"\n  Ready, with {_warned} warning(s).\n")
        return 0
    print("\n  Everything is ready. Next:  python run_grader.py --quick\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())