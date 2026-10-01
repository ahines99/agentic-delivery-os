"""Create operator credentials and private configuration; secrets go only to ignored files."""

import json
import secrets
from pathlib import Path

from agentic_delivery.config import Operator, Settings, token_digest


def main() -> None:
    destination = Path("config.local.json")
    if destination.exists():
        raise SystemExit("config.local.json exists; preserve it and edit intentionally")
    settings = Settings.model_validate_json(Path("config.example.json").read_text())
    Path(".local").mkdir(exist_ok=True)
    password_path = Path(".local/postgres-password")
    if not password_path.exists():
        password_path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    password = password_path.read_text().strip()
    Path(".local/compose.env").write_text(
        f"DELIVERY_POSTGRES_PASSWORD={password}\n", encoding="utf-8"
    )
    token = secrets.token_urlsafe(48)
    operator = Operator(
        id="local-maintainer",
        token_sha256=token_digest(token),
        repositories=tuple(repository.id for repository in settings.repositories),
        roles=("operator", "reviewer"),
    )
    settings = settings.model_copy(
        update={
            "operators": (operator,),
            "database_url": f"postgresql+psycopg://delivery:{password}@127.0.0.1:25432/delivery",
        }
    )
    Path(".local/operator-token").write_text(token, encoding="utf-8")
    destination.write_text(json.dumps(settings.model_dump(mode="json"), indent=2), encoding="utf-8")
    print("Created config.local.json and .local/operator-token. No secret printed.")
    print(
        "Configure database, model, sandbox image, and repository authorization before connecting."
    )


if __name__ == "__main__":
    main()
