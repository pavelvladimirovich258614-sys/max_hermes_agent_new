"""F-TEAM-02: Team add dry-run — validation, pending state, preview.

This module handles:
- /team-add: validate + create pending state + return preview
- /team-cancel <id>: delete pending state
- /team-confirm <id>: stub (disabled until F-TEAM-03)

No files are created in profiles/ or role_registry.yaml.
Only pending JSON files in /root/.hermes/state/team_add_pending/.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PENDING_DIR = Path.home() / ".hermes" / "state" / "team_add_pending"
PROFILES_DIR = Path.home() / ".hermes" / "profiles"
REGISTRY_PATH = Path.home() / ".hermes" / "plugins" / "max" / "role_registry.yaml"

PENDING_TTL_SECONDS = 600  # 10 minutes
SOUL_MIN_CHARS = 100
SOUL_MAX_CHARS = 12000
NAME_MAX_LEN = 32
ROUTE_MAX_LEN = 32
TITLE_MAX_LEN = 64

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
ROUTE_RE = re.compile(r"^/[a-z][a-z0-9_-]{0,31}$")

# Secrets patterns to reject in SOUL
_SECRET_PATTERNS = [
    re.compile(r"ghp_[a-zA-Z0-9]{30,}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"BOT_TOKEN", re.IGNORECASE),
    re.compile(r"API_KEY", re.IGNORECASE),
    re.compile(r"API_SECRET", re.IGNORECASE),
    re.compile(r"[0-9]{8,}:[a-zA-Z_-]{30,}"),  # TG token format
    re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
]

# Reserved routes that cannot be used for team-add
RESERVED_ROUTES = {
    "/status", "/model", "/new", "/reset", "/stop", "/retry", "/undo",
    "/help", "/commands", "/menu", "/roles",
    "/team-add", "/team-confirm", "/team-cancel", "/team-list",
    "/copy", "/prompt", "/marketing", "/dev",
    "/crypto", "/flora",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_id() -> str:
    """Generate short pending id: ta_YYYYMMDD_HHMMSS_<rand>."""
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand = secrets.token_hex(3)  # 6 hex chars
    return f"ta_{now}_{rand}"


def _soul_hash_short(soul: str) -> str:
    return hashlib.sha256(soul.encode()).hexdigest()[:12]


def _check_secrets(text: str) -> List[str]:
    """Return list of detected secret patterns."""
    found = []
    for pat in _SECRET_PATTERNS:
        m = pat.search(text)
        if m:
            found.append(m.group()[:8] + "...")
    return found


def _get_existing_routes() -> set:
    """Read role_registry.yaml and return set of active commands."""
    routes = set()
    try:
        import yaml  # type: ignore
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        roles = data.get("roles", {}) if data else {}
        for _key, entry in roles.items():
            if entry.get("enabled") and entry.get("command"):
                routes.add(entry["command"].lower())
    except Exception:
        pass
    return routes


def _get_existing_profiles() -> set:
    """Return set of existing profile directory names."""
    if not PROFILES_DIR.exists():
        return set()
    return {d.name for d in PROFILES_DIR.iterdir() if d.is_dir()}


def _pending_path(pending_id: str) -> Path:
    return PENDING_DIR / f"{pending_id}.json"


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Atomic write JSON with mode 600."""
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(PENDING_DIR), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.chmod(tmp_path, 0o600)
        shutil.move(tmp_path, str(path))
    except Exception:
        # Cleanup tmp on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationResult:
    """Result of /team-add validation."""

    def __init__(self, ok: bool, errors: List[str], fields: Optional[Dict] = None):
        self.ok = ok
        self.errors = errors
        self.fields = fields or {}

    def __bool__(self) -> bool:
        return self.ok


def validate_team_add(
    name: str,
    route: str,
    title: str,
    soul: str,
) -> ValidationResult:
    """Validate all /team-add fields. Returns ValidationResult."""

    errors: List[str] = []

    # --- name ---
    if not name:
        errors.append("name: пустое значение")
    elif not NAME_RE.match(name):
        errors.append(
            f"name: только lowercase буквы, цифры, _, -. "
            f"Начинается с буквы. Длина 2–{NAME_MAX_LEN}"
        )
    elif len(name) > NAME_MAX_LEN:
        errors.append(f"name: макс {NAME_MAX_LEN} символов")

    # --- route ---
    if not route:
        errors.append("route: пустое значение")
    elif not ROUTE_RE.match(route):
        errors.append(
            f"route: должен начинаться с /, только lowercase буквы, "
            f"цифры, _, -. Длина 2–{ROUTE_MAX_LEN + 1}"
        )
    elif route.lower() in RESERVED_ROUTES:
        errors.append(f"route: {route} — системная команда, выбери другой")
    elif route.lower() in _get_existing_routes():
        errors.append(f"route: {route} — уже используется")

    # --- title ---
    if not title:
        errors.append("title: пустое значение")
    elif len(title) > TITLE_MAX_LEN:
        errors.append(f"title: макс {TITLE_MAX_LEN} символов")

    # --- soul ---
    if not soul:
        errors.append("SOUL: отсутствует. Добавь SOUL:текст_инструкции в конец команды")
    elif len(soul) < SOUL_MIN_CHARS:
        errors.append(
            f"SOUL: слишком короткий ({len(soul)} chars), "
            f"минимум {SOUL_MIN_CHARS}"
        )
    elif len(soul) > SOUL_MAX_CHARS:
        errors.append(
            f"SOUL: слишком длинный ({len(soul)} chars), "
            f"максимум {SOUL_MAX_CHARS}"
        )
    else:
        secret_hits = _check_secrets(soul)
        if secret_hits:
            errors.append(
                f"SOUL: обнаружены секреты/ключи: {', '.join(secret_hits)}. "
                f"Убери их из инструкции"
            )

    # --- profile uniqueness ---
    if name and name in _get_existing_profiles():
        errors.append(f"name: профиль '{name}' уже существует")

    if errors:
        return ValidationResult(ok=False, errors=errors)

    return ValidationResult(
        ok=True,
        errors=[],
        fields={
            "name": name,
            "route": route.lower(),
            "title": title,
            "soul": soul,
            "soul_len": len(soul),
            "soul_hash_short": _soul_hash_short(soul),
        },
    )


# ---------------------------------------------------------------------------
# Parse /team-add command
# ---------------------------------------------------------------------------

def parse_team_add_args(text: str) -> Tuple[Dict[str, str], Optional[str]]:
    """Parse /team-add name=X route=/X title="Y" [SOUL:text]

    Returns (params_dict, error_message).
    params_dict keys: name, route, title, soul (optional)
    """
    # Remove /team-add prefix
    rest = text
    for prefix in ("/team-add", "/team_add"):
        if rest.lower().startswith(prefix):
            rest = rest[len(prefix):].strip()
            break

    if not rest:
        return {}, (
            "Формат: /team-add name=<имя> route=/<команда> "
            "title=\"<название>\" SOUL:<инструкция>\n\n"
            "Пример:\n"
            "/team-add name=designer route=/design "
            "title=\"Дизайнер\" SOUL:Ты дизайнер визуалов..."
        )

    params: Dict[str, str] = {}

    # Extract SOUL: first (everything after last SOUL: prefix)
    soul_marker = "SOUL:"
    soul_idx = rest.find(soul_marker)
    if soul_idx >= 0:
        params["soul"] = rest[soul_idx + len(soul_marker):].strip()
        rest = rest[:soul_idx].strip()

    # Parse key=value pairs
    # title can be quoted: title="Дизайнер"
    kv_pattern = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')
    for m in kv_pattern.finditer(rest):
        key = m.group(1).lower()
        value = m.group(2) if m.group(2) is not None else m.group(3)
        params[key] = value

    return params, None


# ---------------------------------------------------------------------------
# Pending state CRUD
# ---------------------------------------------------------------------------

def create_pending(
    user_id: str,
    name: str,
    route: str,
    title: str,
    soul: str,
) -> Dict[str, Any]:
    """Create pending state file, return full pending record."""

    pending_id = _generate_id()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=PENDING_TTL_SECONDS)

    record = {
        "id": pending_id,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "ttl_seconds": PENDING_TTL_SECONDS,
        "creator_user_id": str(user_id),
        "name": name,
        "route": route,
        "title": title,
        "soul": soul,
        "soul_len": len(soul),
        "soul_sha256": hashlib.sha256(soul.encode()).hexdigest(),
        "status": "dry_run",
    }

    _atomic_write_json(_pending_path(pending_id), record)
    return record


def read_pending(pending_id: str) -> Optional[Dict[str, Any]]:
    """Read pending state, return None if not found or expired."""
    path = _pending_path(pending_id)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            record = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # Check expiry
    expires = record.get("expires_at", "")
    try:
        exp_dt = datetime.fromisoformat(expires)
        if datetime.now(timezone.utc) > exp_dt:
            # Auto-expire: delete
            try:
                path.unlink()
            except OSError:
                pass
            return None
    except (ValueError, TypeError):
        pass

    return record


def delete_pending(pending_id: str) -> bool:
    """Delete pending state. Returns True if found and deleted."""
    path = _pending_path(pending_id)
    if path.exists():
        try:
            path.unlink()
            return True
        except OSError:
            return False
    return False


def list_pending() -> List[Dict[str, Any]]:
    """List all non-expired pending records (without SOUL content)."""
    if not PENDING_DIR.exists():
        return []
    results = []
    for path in sorted(PENDING_DIR.glob("ta_*.json")):
        record = read_pending(path.stem)
        if record:
            # Don't include full SOUL in listing
            safe = {k: v for k, v in record.items() if k != "soul"}
            safe["soul_len"] = record.get("soul_len", 0)
            results.append(safe)
    return results


# ---------------------------------------------------------------------------
# Preview formatter
# ---------------------------------------------------------------------------

def format_preview(record: Dict[str, Any]) -> str:
    """Format pending record as preview message for MAX."""

    name = record.get("name", "?")
    route = record.get("route", "?")
    title = record.get("title", "?")
    soul_len = record.get("soul_len", 0)
    soul_hash = record.get("soul_sha256", "")[:12]
    pid = record.get("id", "?")
    expires = record.get("expires_at", "?")

    # Truncate expires for readability
    if "T" in str(expires):
        expires = str(expires)[:19]

    lines = [
        "📋 Preview: New Agent (dry-run)",
        "",
        f"  name:     {name}",
        f"  route:    {route}",
        f"  title:    {title}",
        f"  soul_len: {soul_len} chars",
        f"  soul_hash: {soul_hash}...",
        "",
        "Files that WOULD be created (in F-TEAM-03):",
        f"  ✅ /root/.hermes/profiles/{name}/SOUL.md",
        f"  ✅ /root/.hermes/profiles/{name}/config.yaml",
        f"  ⚠️ role_registry.yaml (append entry)",
        "",
        "Safety checks: ✅ passed",
        "Restart required: yes (in F-TEAM-03)",
        "",
        f"Expires: {expires} UTC",
        f"ID: {pid}",
        "",
        "Next:",
        f"  /team-confirm {pid}",
        f"  /team-cancel  {pid}",
    ]
    return "\n".join(lines)


def format_validation_errors(errors: List[str]) -> str:
    """Format validation errors for MAX."""
    lines = ["❌ /team-add: валидация не пройдена", ""]
    for err in errors:
        lines.append(f"  • {err}")
    lines.append("")
    lines.append(
        "Формат: /team-add name=X route=/X title=\"Y\" SOUL:инструкция"
    )
    return "\n".join(lines)


def format_cancel_ok(pending_id: str) -> str:
    return f"✅ Pending {pending_id} отменён и удалён."


def format_cancel_not_found(pending_id: str) -> str:
    return f"⚠️ Pending {pending_id} не найден (истёк или уже отменён)."


def format_confirm_disabled(pending_id: str) -> str:
    return (
        f"⚠️ /team-confirm {pending_id}\n"
        f"Preview найден, но confirm отключён.\n"
        f"Создание профилей будет реализовано в F-TEAM-03."
    )


def format_confirm_not_found(pending_id: str) -> str:
    return f"⚠️ Pending {pending_id} не найден (истёк или отменён)."


def format_parse_error(msg: str) -> str:
    return f"❌ /team-add: {msg}"


def format_no_pending() -> str:
    return "📋 Нет pending запросов на создание агентов."


# ---------------------------------------------------------------------------
# F-TEAM-03: Real confirm — create profile + registry entry
# ---------------------------------------------------------------------------

# Minimal config.yaml template for new agent profiles
_MINIMAL_CONFIG_YAML = """\
model:
  provider: zai
  default: glm-5.1
agent:
  max_turns: 20
  gateway_timeout: 300
toolsets:
  - hermes-cli
terminal:
  backend: local
  timeout: 60
display:
  language: ru
logging:
  level: INFO
"""

_BACKUP_DIR = Path.home() / ".hermes" / "state" / "team_add_backups"


def confirm_pending(pending_id: str, user_id: str) -> Tuple[bool, str]:
    """Confirm a pending agent creation: validate, create files, update registry.

    Returns (success, message).
    """
    record = read_pending(pending_id)
    if not record:
        return False, format_confirm_not_found(pending_id)

    # Check creator
    if str(record.get("creator_user_id", "")) != str(user_id):
        return False, f"⚠️ Только создатель может подтвердить."

    # Check TTL
    expires = record.get("expires_at", "")
    if expires:
        exp = datetime.fromisoformat(expires)
        if datetime.now(timezone.utc) > exp:
            delete_pending(pending_id)
            return False, f"⚠️ Pending {pending_id} истёк. Создайте заново."

    name = record["name"]
    route = record["route"]
    title = record["title"]
    soul = record["soul"]

    # Re-validate
    vr = validate_team_add(name, route, title, soul)
    if not vr.ok:
        return False, format_validation_errors(vr.errors)

    profile_dir = PROFILES_DIR / name
    soul_path = profile_dir / "SOUL.md"
    config_path = profile_dir / "config.yaml"

    # Double-check no conflicts
    if profile_dir.exists():
        return False, f"❌ Профиль {name} уже существует."
    if _route_in_registry(route):
        return False, f"❌ Route {route} уже в registry."

    # Backup registry before edit
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = _BACKUP_DIR / f"role_registry_{ts}.bak"
    shutil.copy2(str(REGISTRY_PATH), str(backup_path))

    # Create profile directory and files
    try:
        profile_dir.mkdir(parents=True, exist_ok=False)

        # Write SOUL.md
        soul_path.write_text(soul, encoding="utf-8")
        soul_path.chmod(0o600)

        # Write minimal config.yaml
        config_path.write_text(_MINIMAL_CONFIG_YAML, encoding="utf-8")
        config_path.chmod(0o600)
    except Exception as e:
        # Rollback on failure
        if profile_dir.exists():
            shutil.rmtree(str(profile_dir), ignore_errors=True)
        return False, f"❌ Ошибка создания профиля: {e}"

    # Append entry to registry
    try:
        entry = f"""

  {name}:
    enabled: true
    command: {route}
    profile: {name}
    profile_path: {profile_dir}
    soul_path: {soul_path}
    display_name: "{title}"
    emoji: "🤖"
    description: "Added via /team-add"
"""
        with open(str(REGISTRY_PATH), "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        # Rollback profile + restore registry
        shutil.rmtree(str(profile_dir), ignore_errors=True)
        shutil.copy2(str(backup_path), str(REGISTRY_PATH))
        return False, f"❌ Ошибка обновления registry: {e}"

    # Mark pending as confirmed (update status, keep record briefly)
    record["status"] = "confirmed"
    record["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    _write_pending_file(pending_id, record)

    return True, (
        f"✅ Агент \"{title}\" создан!\n\n"
        f"  name:     {name}\n"
        f"  route:    {route}\n"
        f"  profile:  {profile_dir}\n"
        f"  registry: updated\n"
        f"  backup:   {backup_path.name}\n\n"
        f"⚠️ Нужен restart gateway:\n"
        f"  systemctl --user restart hermes-gateway\n\n"
        f"После restart: {route} <задача>"
    )


def rollback_agent(name: str, user_id: str) -> Tuple[bool, str]:
    """Rollback a created agent: remove profile, remove registry entry.

    Returns (success, message).
    """
    profile_dir = PROFILES_DIR / name
    if not profile_dir.exists():
        return False, f"⚠️ Профиль {name} не найден."

    # Backup registry before edit
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = _BACKUP_DIR / f"role_registry_pre_rollback_{ts}.bak"
    shutil.copy2(str(REGISTRY_PATH), str(backup_path))

    # Remove profile directory
    try:
        shutil.rmtree(str(profile_dir), ignore_errors=False)
    except Exception as e:
        return False, f"❌ Ошибка удаления профиля: {e}"

    # Remove entry from registry
    try:
        content = REGISTRY_PATH.read_text(encoding="utf-8")
        # Remove the block for this agent
        # Pattern: from "  name:" to next "  \\w" or end
        import re as _re
        pattern = _re.compile(
            rf"\n  {re.escape(name)}:\s*\n(?:    [^\n]*\n)*",
            _re.MULTILINE,
        )
        new_content = pattern.sub("\n", content)
        REGISTRY_PATH.write_text(new_content, encoding="utf-8")
    except Exception as e:
        # Restore from backup
        shutil.copy2(str(backup_path), str(REGISTRY_PATH))
        return False, f"❌ Ошибка обновления registry: {e}"

    # Clean up any pending for this name
    if PENDING_DIR.exists():
        for pf in PENDING_DIR.glob("ta_*.json"):
            try:
                rec = json.loads(pf.read_text(encoding="utf-8"))
                if rec.get("name") == name:
                    pf.unlink()
            except (json.JSONDecodeError, OSError):
                pass

    return True, (
        f"✅ Rollback \"{name}\" выполнен.\n\n"
        f"  profile: удалён\n"
        f"  registry: entry удалён\n"
        f"  backup: {backup_path.name}\n\n"
        f"⚠️ Нужен restart gateway:\n"
        f"  systemctl --user restart hermes-gateway"
    )


def _route_in_registry(route: str) -> bool:
    """Check if route already exists in registry YAML."""
    if not REGISTRY_PATH.exists():
        return False
    content = REGISTRY_PATH.read_text(encoding="utf-8")
    return f"command: {route}" in content


def _write_pending_file(pending_id: str, record: Dict[str, Any]) -> None:
    """Write/update pending JSON file."""
    path = _pending_path(pending_id)
    if not path:
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def format_confirm_success(name: str, route: str, title: str) -> str:
    return f"✅ Агент \"{title}\" ({name}) создан. Route: {route}"


def format_rollback_success(name: str) -> str:
    return f"✅ Rollback \"{name}\" выполнен."
