"""Reconcile existing PR outcomes without publishing, merging or starting work."""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from agentic_delivery.config import Settings, load_settings
from agentic_delivery.integrations.github_observation import read_pull
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.store import Store, digest_json

logger = logging.getLogger(__name__)


async def poll_once(
    settings: Settings,
    store: Store,
    *,
    after: str = "",
    settings_provider: Callable[[], Settings] | None = None,
) -> str:
    if not settings.github_poll_enabled:
        return ""
    repositories = tuple(r.id for r in settings.repositories if r.github_repository_id)
    rows = store.publication_page(repositories, after=after)
    for row in rows:
        repository = settings.repository(row["repository"])
        try:
            current = settings_provider() if settings_provider else settings
            if (
                not current.github_poll_enabled
                or current.database_url != settings.database_url
                or current.repository(repository.id) != repository
                or current.github_app_id != settings.github_app_id
                or current.github_installation_id != settings.github_installation_id
                or current.github_private_key_env != settings.github_private_key_env
            ):
                return ""
            observation = await read_pull(settings, repository, row["number"])
            # Recheck revocation after network I/O, before recording any provider fact.
            if settings_provider and settings_provider() != current:
                return ""
            payload = {"pull_request": observation.model_dump(mode="json")}
            digest = digest_json(payload)
            store.observe_publication(
                row["workflow_id"],
                payload,
                {
                    "provider": "github-rest",
                    "integration_id": str(settings.github_installation_id),
                    "delivery_id": digest,
                    "semantic_key": digest,
                    "digest": digest,
                    "payload": payload,
                },
            )
        except Exception as exc:
            logger.error("GitHub observation failed (%s)", type(exc).__name__)
    # Rotate bounded pages so an old or failing PR cannot starve later publications.
    return rows[-1]["workflow_id"] if len(rows) == 50 else ""


async def monitor(config: Path) -> None:
    initial = load_settings(config)
    store = Store(create_database(initial.database_url))
    after = ""
    try:
        while True:
            settings = load_settings(config)
            if settings.database_url != initial.database_url:
                raise ValueError("GitHub monitor database changed; restart required")
            after = await poll_once(
                settings, store, after=after, settings_provider=lambda: load_settings(config)
            )
            await asyncio.sleep(settings.github_poll_seconds)
    finally:
        store.engine.dispose()
