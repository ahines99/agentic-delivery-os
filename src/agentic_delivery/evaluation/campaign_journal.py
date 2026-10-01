"""Local campaign ordering journal, never execution or promotion authority."""

import json
import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field

from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.campaign import ExecutionCampaign, Split, _read
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.campaign_scoring import _resolve_campaign
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest, qualification_task_digest
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

PHASES: tuple[Split, ...] = ("development", "validation", "test")


class JournalConflict(ValueError):
    """Sanitized control denial; no execution, outcome or recovery permission."""


def _require(condition: bool) -> None:
    if not condition:
        raise JournalConflict("Campaign journal state or current decision does not match")


def _encoded(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ProviderCaseIdentity(Contract):
    """Trusted caller metadata; this journal does not query/authenticate the provider."""

    task_id: NonEmpty
    repository_id: int = Field(strict=True, gt=0)
    issue_node_id: str = Field(strict=True, min_length=1, max_length=200, pattern=r"^[\w=-]+$")


class PreparationAccountIdentity(Contract):
    ledger_identity: Digest
    account_id: str = Field(strict=True, min_length=1, max_length=200)
    inventory_artifact: Digest


class JournalPhaseAuthorization(Contract):
    """Caller decision pin only; no claim that numerical promotion gates passed."""

    schema_version: Literal[1] = 1
    campaign_artifact: Digest
    registration_digest: Digest
    phase: Split
    decision_artifact: Digest
    policy_digest: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class JournalEvent(Contract):
    campaign_artifact: Digest
    sequence: int = Field(strict=True, ge=1)
    event_id: str = Field(strict=True, min_length=1, max_length=200)
    kind: Literal[
        "REPORTING_POLICY",
        "PHASE",
        "SEALED_OPEN",
        "INTENT",
        "DISPATCH",
        "DISPATCH_FINISHED",
        "STOPPED",
        "UNKNOWN",
        "OUTCOME_REFERENCE",
    ]
    document: dict[str, Any]
    created_at: AwareDatetime
    previous_digest: Digest
    digest: Digest


class JournalRegistration(Contract):
    campaign_artifact: Digest
    registration_digest: Digest
    campaign_id: NonEmpty
    assigned: int = Field(strict=True, gt=0)
    created_at: AwareDatetime


_SCHEMA = (
    "CREATE TABLE journal_marker (version TEXT PRIMARY KEY, identity TEXT NOT NULL)",
    "CREATE TABLE campaigns (artifact TEXT PRIMARY KEY, campaign_id TEXT NOT NULL UNIQUE, "
    "digest TEXT NOT NULL, document TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE assignments (campaign TEXT REFERENCES campaigns(artifact), ordinal INTEGER, "
    "document TEXT NOT NULL, PRIMARY KEY(campaign, ordinal))",
    "CREATE TABLE events (campaign TEXT REFERENCES campaigns(artifact), sequence INTEGER, "
    "event_id TEXT NOT NULL, document TEXT NOT NULL, PRIMARY KEY(campaign, sequence), "
    "UNIQUE(campaign, event_id))",
    "CREATE TABLE exposures (identity TEXT PRIMARY KEY, campaign TEXT NOT NULL "
    "REFERENCES campaigns(artifact), event_digest TEXT NOT NULL)",
)
_COLUMNS = {
    "journal_marker": ("version", "identity"),
    "campaigns": ("artifact", "campaign_id", "digest", "document", "created_at"),
    "assignments": ("campaign", "ordinal", "document"),
    "events": ("campaign", "sequence", "event_id", "document"),
    "exposures": ("identity", "campaign", "event_digest"),
}


class CampaignJournal:
    """SQLite-only append journal; all worker/spending/proof checks remain external."""

    def __init__(
        self,
        path: Path,
        *,
        execution_ledger: EvaluationExecutionStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _require(isinstance(execution_ledger, EvaluationExecutionStore))
        self.path = path.absolute()
        self.ledger = execution_ledger
        self.ledger_identity = ledger_target_identity(execution_ledger)
        self.clock = clock
        with self._transaction(initialize=True) as connection:
            existing = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not existing:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO journal_marker VALUES ('campaign-journal-v1', ?)", (uuid4().hex,)
                )
            self._schema(connection)
            self._journal_binding(connection)
            self._exposures(connection)

    def _path(self) -> None:
        _require(ledger_target_identity(self.ledger) == self.ledger_identity)
        _require(self.path.parent.is_dir())
        _require(not self.path.is_symlink())
        if self.path.exists():
            _require(self.path.is_file())
        if self.ledger.sqlite:
            target = Path(str(self.ledger.engine.url.database)).resolve()
            _require(self.path.resolve() != target)
            if self.path.exists() and target.exists():
                _require(not os.path.samefile(self.path, target))

    @staticmethod
    def _schema(connection: sqlite3.Connection) -> None:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        _require(tables == set(_COLUMNS))
        _require(
            not connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('trigger', 'view')"
            ).fetchall()
        )
        for statement in _SCHEMA:
            name = statement.split()[2]
            _require(
                connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)
                ).fetchone()
                == (statement,)
            )
        for table, columns in _COLUMNS.items():
            _require(
                tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
                == columns
            )
        markers = connection.execute("SELECT version, identity FROM journal_marker").fetchall()
        _require(len(markers) == 1 and markers[0][0] == "campaign-journal-v1")
        _require(
            isinstance(markers[0][1], str) and bool(re.fullmatch(r"[a-f0-9]{32}", markers[0][1]))
        )

    def _journal_binding(self, connection: sqlite3.Connection) -> None:
        identity = digest_json(
            {
                "marker": connection.execute("SELECT identity FROM journal_marker").fetchone()[0],
                "path": os.path.normcase(str(self.path.resolve())),
            }
        )
        _require(getattr(self, "journal_identity", identity) == identity)
        self.journal_identity = identity
        for (document,) in connection.execute("SELECT document FROM campaigns"):
            _require(json.loads(document).get("journal_identity") == identity)

    @contextmanager
    def _transaction(self, *, initialize: bool = False) -> Iterator[sqlite3.Connection]:
        self._path()
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            if not initialize:
                self._schema(connection)
                self._journal_binding(connection)
                self._exposures(connection)
            yield connection
            connection.commit()
        except (sqlite3.Error, OSError):
            connection.rollback()
            raise JournalConflict("Campaign journal transaction unavailable") from None
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _now(self) -> datetime:
        value = self.clock()
        _require(value.tzinfo is not None and value.utcoffset() is not None)
        return value

    @staticmethod
    def _case(task: HistoricalTask, identity: ProviderCaseIdentity) -> dict[str, Any]:
        repository = task.repository_url.lower()
        match = re.fullmatch(
            re.escape(repository) + r"/issues/([1-9][0-9]*)", task.issue_url.lower()
        )
        _require(match is not None and identity.task_id == task.id)
        assert match is not None
        return {
            "task_id": task.id,
            "family": task.family,
            "split": task.split,
            "repository_url": repository,
            "repository_id": identity.repository_id,
            "issue_node_id": identity.issue_node_id,
            "issue_number": int(match[1]),
            "task_manifest_digest": qualification_task_digest(task.model_dump(mode="json")),
            "qualification_artifact": task.qualification_artifact,
        }

    def register_campaign(
        self,
        campaign_artifact: str,
        *,
        campaign_artifacts: ArtifactStore,
        configuration_artifacts: ArtifactStore,
        tasks: tuple[HistoricalTask, ...],
        identities: tuple[ProviderCaseIdentity, ...],
        preparation_accounts: tuple[PreparationAccountIdentity, ...],
    ) -> JournalRegistration:
        """Bind metadata and every ordinal atomically, without reading task source."""
        try:
            campaign = ExecutionCampaign.model_validate(
                _read(campaign_artifacts, campaign_artifact)
            )
            _require(campaign.specification.preregistered_at <= self._now())
            arms = _resolve_campaign(campaign, configuration_artifacts)
        except (OSError, ValueError):
            raise JournalConflict("Frozen campaign metadata unavailable or invalid") from None
        normalized_tasks = tuple(
            HistoricalTask.model_validate(t.model_dump(mode="json")) for t in tasks
        )
        identities = tuple(ProviderCaseIdentity.model_validate(i.model_dump()) for i in identities)
        preparation_accounts = tuple(
            PreparationAccountIdentity.model_validate(p.model_dump()) for p in preparation_accounts
        )
        by_id = {identity.task_id: identity for identity in identities}
        _require(len(by_id) == len(identities) == len(normalized_tasks) == len(campaign.tasks))
        _require(
            set(by_id)
            == {task.id for task in normalized_tasks}
            == {task.task_id for task in campaign.tasks}
        )
        cases = tuple(
            self._case(task, by_id[task.id])
            for task in sorted(normalized_tasks, key=lambda t: t.id)
        )
        for task, case in zip(campaign.tasks, cases, strict=True):
            _require(
                task.task_id == case["task_id"]
                and task.family == case["family"]
                and task.split == case["split"]
                and task.repository_url.lower() == case["repository_url"]
                and task.task_manifest_digest == case["task_manifest_digest"]
                and task.qualification_artifact == case["qualification_artifact"]
            )
        for key in ("issue_node_id",):
            _require(len({case[key] for case in cases}) == len(cases))
        _require(
            len({(case["repository_id"], case["issue_number"]) for case in cases}) == len(cases)
        )
        _require(
            len({(case["repository_url"], case["issue_number"]) for case in cases}) == len(cases)
        )
        repository_ids: dict[str, int] = {}
        repository_urls: dict[int, str] = {}
        for case in cases:
            _require(
                repository_ids.setdefault(case["repository_url"], case["repository_id"])
                == case["repository_id"]
            )
            _require(
                repository_urls.setdefault(case["repository_id"], case["repository_url"])
                == case["repository_url"]
            )
        _require(bool(preparation_accounts))
        _require(
            len({(p.ledger_identity, p.account_id) for p in preparation_accounts})
            == len(preparation_accounts)
        )
        document = {
            "schema_version": 1,
            "campaign": campaign.model_dump(mode="json"),
            "campaign_artifact": campaign_artifact,
            "journal_identity": self.journal_identity,
            "execution_ledger_identity": self.ledger_identity,
            "source_commit": campaign.specification.scoring_code_commit,
            "configurations": {arm: ref for arm, (ref, _) in sorted(arms.items())},
            "cases": cases,
            "preparation_accounts": [
                p.model_dump(mode="json")
                for p in sorted(
                    preparation_accounts, key=lambda p: (p.ledger_identity, p.account_id)
                )
            ],
        }
        digest = digest_json(document)
        with self._transaction() as connection:
            previous = connection.execute(
                "SELECT digest FROM campaigns WHERE artifact=?", (campaign_artifact,)
            ).fetchone()
            if previous is not None:
                _require(previous[0] == digest)
                return self._registration(connection, campaign_artifact)[0]
            self._unexposed(connection, cases, campaign_artifact)
            now = self._now().isoformat()
            connection.execute(
                "INSERT INTO campaigns VALUES (?, ?, ?, ?, ?)",
                (
                    campaign_artifact,
                    campaign.specification.campaign_id,
                    digest,
                    _encoded(document),
                    now,
                ),
            )
            for assignment in campaign.schedule:
                connection.execute(
                    "INSERT INTO assignments VALUES (?, ?, ?)",
                    (
                        campaign_artifact,
                        assignment.ordinal,
                        _encoded(assignment.model_dump(mode="json")),
                    ),
                )
            return self._registration(connection, campaign_artifact)[0]

    @staticmethod
    def _keys(case: dict[str, Any]) -> tuple[str, ...]:
        return (
            _encoded(["repo-issue", case["repository_url"], case["issue_number"]]),
            _encoded(["provider-repo-issue", case["repository_id"], case["issue_number"]]),
            _encoded(["provider-issue-node", case["issue_node_id"]]),
            _encoded(["declared-family", case["family"]]),
        )

    def _unexposed(self, connection: sqlite3.Connection, cases: Any, campaign: str) -> None:
        for case in cases:
            if case["split"] == "test":
                for key in self._keys(case):
                    row = connection.execute(
                        "SELECT campaign FROM exposures WHERE identity=?", (key,)
                    ).fetchone()
                    _require(row is None or row[0] == campaign)

    @classmethod
    def _exposures(cls, connection: sqlite3.Connection) -> None:
        """The index must match recorded opening/intents, including earlier development use."""
        expected: dict[str, set[tuple[str, str]]] = {}
        for (campaign,) in connection.execute("SELECT artifact FROM campaigns"):
            _, document = cls._registration(connection, campaign)
            cases = {case["task_id"]: case for case in document["cases"]}
            for event in cls._events(connection, campaign):
                selected = []
                if event.kind == "SEALED_OPEN":
                    selected = [case for case in cases.values() if case["split"] == "test"]
                elif event.kind == "INTENT" and event.document["assignment"]["split"] != "test":
                    selected = [cases[event.document["assignment"]["task_id"]]]
                for case in selected:
                    for key in cls._keys(case):
                        expected.setdefault(key, set()).add((campaign, event.digest))
        observed = connection.execute(
            "SELECT identity, campaign, event_digest FROM exposures"
        ).fetchall()
        _require({row[0] for row in observed} == set(expected))
        _require(all((row[1], row[2]) in expected[row[0]] for row in observed))

    @classmethod
    def _expose(
        cls, connection: sqlite3.Connection, cases: Any, campaign: str, event: JournalEvent
    ) -> None:
        for key in sorted({key for case in cases for key in cls._keys(case)}):
            connection.execute(
                "INSERT OR IGNORE INTO exposures VALUES (?, ?, ?)", (key, campaign, event.digest)
            )

    @staticmethod
    def _registration(
        connection: sqlite3.Connection, campaign: str
    ) -> tuple[JournalRegistration, dict[str, Any]]:
        row = connection.execute(
            "SELECT campaign_id, digest, document, created_at FROM campaigns WHERE artifact=?",
            (campaign,),
        ).fetchone()
        _require(row is not None)
        assert row is not None
        document = json.loads(row[2])
        _require(digest_json(document) == row[1])
        _require(
            document["campaign_artifact"] == campaign
            and document["campaign"]["specification"]["campaign_id"] == row[0]
        )
        assignments = connection.execute(
            "SELECT ordinal, document FROM assignments WHERE campaign=? ORDER BY ordinal",
            (campaign,),
        ).fetchall()
        _require([json.loads(item[1]) for item in assignments] == document["campaign"]["schedule"])
        _require([item[0] for item in assignments] == list(range(len(assignments))))
        return JournalRegistration(
            campaign_artifact=campaign,
            registration_digest=row[1],
            campaign_id=row[0],
            assigned=len(assignments),
            created_at=row[3],
        ), document

    @classmethod
    def _events(cls, connection: sqlite3.Connection, campaign: str) -> list[JournalEvent]:
        registration, document = cls._registration(connection, campaign)
        schedule = document["campaign"]["schedule"]
        rows = connection.execute(
            "SELECT sequence, event_id, document FROM events WHERE campaign=? ORDER BY sequence",
            (campaign,),
        ).fetchall()
        result: list[JournalEvent] = []
        previous = "0" * 64
        phase: JournalPhaseAuthorization | None = None
        intents: dict[str, int] = {}
        closed: set[int] = set()
        outcomes: set[int] = set()
        active_dispatches: set[int] = set()
        dispatched: set[int] = set()
        opened = False
        for index, row in enumerate(rows, 1):
            event = JournalEvent.model_validate_json(row[2])
            _require(
                event.campaign_artifact == campaign
                and event.sequence == row[0] == index
                and event.event_id == row[1]
                and event.previous_digest == previous
            )
            _require(digest_json(event.model_dump(mode="json", exclude={"digest"})) == event.digest)
            _require(
                event.created_at >= (result[-1].created_at if result else registration.created_at)
            )
            data = event.document
            if event.kind == "REPORTING_POLICY":
                _require(
                    index == 1
                    and event.event_id == "reporting-policy"
                    and set(data) == {"policy_artifact"}
                    and isinstance(data["policy_artifact"], str)
                    and bool(re.fullmatch(r"[a-f0-9]{64}", data["policy_artifact"]))
                )
            elif event.kind == "PHASE":
                _require(set(data) == {"authorization"})
                current = JournalPhaseAuthorization.model_validate(data["authorization"])
                _require(
                    current.campaign_artifact == campaign
                    and current.registration_digest == registration.registration_digest
                    and current.issued_at <= event.created_at < current.expires_at
                    and event.event_id == "phase:" + digest_json(current.model_dump(mode="json"))
                )
                prior = PHASES.index(phase.phase) if phase else -1
                target = PHASES.index(current.phase)
                _require(target in {prior, prior + 1})
                _require(
                    all(
                        a["ordinal"] in closed
                        for a in schedule
                        if PHASES.index(a["split"]) < target
                    )
                )
                phase = current
            elif event.kind in {"SEALED_OPEN", "INTENT"}:
                _require(phase is not None)
                assert phase is not None
                _require(phase.issued_at <= event.created_at < phase.expires_at)
                _require(
                    data.get("authorization_digest") == digest_json(phase.model_dump(mode="json"))
                )
                _require(len(intents) < len(schedule) and set(intents.values()) <= closed)
                assignment = schedule[len(intents)]
                _require(assignment["split"] == phase.phase)
                if event.kind == "SEALED_OPEN":
                    _require(set(data) == {"authorization_digest", "decision_artifact"})
                    _require(
                        not opened and phase.phase == "test" and event.event_id == "sealed-open"
                    )
                    _require(data["decision_artifact"] == phase.decision_artifact)
                    opened = True
                else:
                    _require(
                        set(data) == {"intent_id", "ordinal", "assignment", "authorization_digest"}
                    )
                    identity = data["intent_id"]
                    _require(
                        isinstance(identity, str)
                        and bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", identity))
                    )
                    _require(identity not in intents and event.event_id == "intent:" + identity)
                    _require(type(data["ordinal"]) is int and data["ordinal"] == len(intents))
                    _require(data["assignment"] == assignment and (phase.phase != "test" or opened))
                    intents[identity] = data["ordinal"]
            elif event.kind == "DISPATCH":
                _require(set(data) == {"intent_id", "ordinal", "authorization_digest"})
                _require(data["intent_id"] in intents and phase is not None)
                assert phase is not None
                ordinal = intents[data["intent_id"]]
                _require(
                    type(data["ordinal"]) is int
                    and data["ordinal"] == ordinal
                    and ordinal not in dispatched
                    and ordinal not in closed
                    and not active_dispatches
                    and event.event_id == "dispatch:" + data["intent_id"]
                    and phase.issued_at <= event.created_at < phase.expires_at
                    and data["authorization_digest"] == digest_json(phase.model_dump(mode="json"))
                )
                original = next(
                    e for e in result if e.kind == "INTENT" and e.document["ordinal"] == ordinal
                )
                _require(original.document["authorization_digest"] == data["authorization_digest"])
                dispatched.add(ordinal)
                active_dispatches.add(ordinal)
            elif event.kind == "DISPATCH_FINISHED":
                _require(set(data) == {"intent_id", "ordinal", "evidence_artifact"})
                _require(data["intent_id"] in intents)
                ordinal = intents[data["intent_id"]]
                _require(
                    type(data["ordinal"]) is int
                    and data["ordinal"] == ordinal
                    and ordinal in active_dispatches
                    and ordinal in outcomes
                    and event.event_id == "dispatch-finished:" + data["intent_id"]
                )
                outcome = next(
                    e
                    for e in result
                    if e.kind == "OUTCOME_REFERENCE" and e.document["ordinal"] == ordinal
                )
                _require(outcome.document == data)
                active_dispatches.remove(ordinal)
                closed.add(ordinal)
            else:
                _require(set(data) == {"intent_id", "ordinal", "evidence_artifact"})
                _require(isinstance(data["intent_id"], str) and data["intent_id"] in intents)
                ordinal = intents[data["intent_id"]]
                _require(
                    type(data["ordinal"]) is int
                    and data["ordinal"] == ordinal
                    and ordinal not in outcomes
                )
                _require(bool(re.fullmatch(r"observation:[A-Za-z0-9_.:-]{1,120}", event.event_id)))
                _require(
                    isinstance(data["evidence_artifact"], str)
                    and bool(re.fullmatch(r"[a-f0-9]{64}", data["evidence_artifact"]))
                )
                if ordinal not in active_dispatches:
                    closed.add(ordinal)
                if event.kind == "OUTCOME_REFERENCE":
                    outcomes.add(ordinal)
            result.append(event)
            previous = event.digest
        return result

    def _append(
        self,
        connection: sqlite3.Connection,
        campaign: str,
        events: list[JournalEvent],
        event_id: str,
        kind: Any,
        document: dict[str, Any],
    ) -> JournalEvent:
        now = self._now()
        _require(not events or events[-1].created_at <= now)
        value = {
            "campaign_artifact": campaign,
            "sequence": len(events) + 1,
            "event_id": event_id,
            "kind": kind,
            "document": document,
            "created_at": now,
            "previous_digest": events[-1].digest if events else "0" * 64,
            "digest": "0" * 64,
        }
        event = JournalEvent.model_validate(value)
        event = event.model_copy(
            update={"digest": digest_json(event.model_dump(mode="json", exclude={"digest"}))}
        )
        connection.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?)",
            (campaign, event.sequence, event_id, event.model_dump_json()),
        )
        events.append(event)
        return event

    def _grant(
        self, connection: sqlite3.Connection, provider: Callable[[], JournalPhaseAuthorization]
    ) -> JournalPhaseAuthorization:
        grant = JournalPhaseAuthorization.model_validate(provider().model_dump(mode="json"))
        registration, document = self._registration(connection, grant.campaign_artifact)
        _require(grant.registration_digest == registration.registration_digest)
        _require(document["execution_ledger_identity"] == self.ledger_identity)
        _require(grant.issued_at <= self._now() < grant.expires_at)
        return grant

    @staticmethod
    def _cas(events: list[JournalEvent], expected_sequence: int) -> None:
        _require(type(expected_sequence) is int and expected_sequence == len(events))

    @staticmethod
    def _closed(events: list[JournalEvent]) -> set[int]:
        closed = {
            e.document["ordinal"]
            for e in events
            if e.kind in {"STOPPED", "UNKNOWN", "OUTCOME_REFERENCE"}
        }
        dispatched = {e.document["ordinal"] for e in events if e.kind == "DISPATCH"}
        finished = {e.document["ordinal"] for e in events if e.kind == "DISPATCH_FINISHED"}
        return closed - (dispatched - finished)

    def claim_dispatch(
        self,
        *,
        intent_id: str,
        authorization_provider: Callable[[], JournalPhaseAuthorization],
        expected_sequence: int,
    ) -> JournalEvent:
        """One irreversible dispatch claim across this journal; no lease or automatic retry."""
        with self._transaction() as connection:
            grant = self._grant(connection, authorization_provider)
            events = self._events(connection, grant.campaign_artifact)
            self._cas(events, expected_sequence)
            for (campaign,) in connection.execute("SELECT artifact FROM campaigns"):
                history = self._events(connection, campaign)
                dispatched = {e.document["ordinal"] for e in history if e.kind == "DISPATCH"}
                finished = {e.document["ordinal"] for e in history if e.kind == "DISPATCH_FINISHED"}
                _require(dispatched == finished)
            intent = next(
                (e for e in events if e.kind == "INTENT" and e.document["intent_id"] == intent_id),
                None,
            )
            _require(intent is not None)
            assert intent is not None
            _require(
                not any(
                    e.document.get("intent_id") == intent_id and e.kind != "INTENT" for e in events
                )
            )
            phases = [e for e in events if e.kind == "PHASE"]
            _require(
                bool(phases)
                and phases[-1].document["authorization"] == grant.model_dump(mode="json")
            )
            _require(
                intent.document["authorization_digest"]
                == digest_json(grant.model_dump(mode="json"))
            )
            _require(self._grant(connection, authorization_provider) == grant)
            return self._append(
                connection,
                grant.campaign_artifact,
                events,
                "dispatch:" + intent_id,
                "DISPATCH",
                {
                    "intent_id": intent_id,
                    "ordinal": intent.document["ordinal"],
                    "authorization_digest": intent.document["authorization_digest"],
                },
            )

    def finish_dispatch(
        self,
        campaign_artifact: str,
        *,
        intent_id: str,
        outcome_artifact: str,
        expected_sequence: int,
    ) -> JournalEvent:
        """Trusted caller must validate completed proof first; metadata alone is no proof."""
        with self._transaction() as connection:
            events = self._events(connection, campaign_artifact)
            outcome = next(
                (
                    e
                    for e in events
                    if e.kind == "OUTCOME_REFERENCE" and e.document["intent_id"] == intent_id
                ),
                None,
            )
            _require(
                outcome is not None and outcome.document["evidence_artifact"] == outcome_artifact
            )
            assert outcome is not None
            _require(
                any(e.kind == "DISPATCH" and e.document["intent_id"] == intent_id for e in events)
            )
            previous = next(
                (
                    e
                    for e in events
                    if e.kind == "DISPATCH_FINISHED" and e.document["intent_id"] == intent_id
                ),
                None,
            )
            if previous is not None:
                _require(previous.document == outcome.document)
                return previous
            self._cas(events, expected_sequence)
            return self._append(
                connection,
                campaign_artifact,
                events,
                "dispatch-finished:" + intent_id,
                "DISPATCH_FINISHED",
                outcome.document,
            )

    def open_phase(
        self,
        *,
        authorization_provider: Callable[[], JournalPhaseAuthorization],
        expected_sequence: int,
    ) -> JournalEvent:
        """Record current caller phase decision; this does not evaluate promotion gates."""
        with self._transaction() as connection:
            grant = self._grant(connection, authorization_provider)
            events = self._events(connection, grant.campaign_artifact)
            event_id = "phase:" + digest_json(grant.model_dump(mode="json"))
            existing = next((e for e in events if e.event_id == event_id), None)
            if existing is not None:
                _require(events[-1].created_at <= self._now())
                _require(self._grant(connection, authorization_provider) == grant)
                return existing
            self._cas(events, expected_sequence)
            _, registration = self._registration(connection, grant.campaign_artifact)
            phases = [e for e in events if e.kind == "PHASE"]
            previous = PHASES.index(phases[-1].document["authorization"]["phase"]) if phases else -1
            target = PHASES.index(grant.phase)
            _require(target in {previous, previous + 1} and target >= 0)
            if target > previous:
                closed = self._closed(events)
                _require(
                    all(
                        a["ordinal"] in closed
                        for a in registration["campaign"]["schedule"]
                        if PHASES.index(a["split"]) < target
                    )
                )
            _require(self._grant(connection, authorization_provider) == grant)
            return self._append(
                connection,
                grant.campaign_artifact,
                events,
                event_id,
                "PHASE",
                {"authorization": grant.model_dump(mode="json")},
            )

    def claim_next(
        self,
        *,
        intent_id: str,
        authorization_provider: Callable[[], JournalPhaseAuthorization],
        expected_sequence: int,
    ) -> JournalEvent:
        """Persist the next intent before any caller export/effect; never grant a retry."""
        _require(bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", intent_id)))
        with self._transaction() as connection:
            grant = self._grant(connection, authorization_provider)
            events = self._events(connection, grant.campaign_artifact)
            phases = [e for e in events if e.kind == "PHASE"]
            _require(
                bool(phases)
                and phases[-1].document["authorization"] == grant.model_dump(mode="json")
            )
            previous = next(
                (e for e in events if e.kind == "INTENT" and e.document["intent_id"] == intent_id),
                None,
            )
            if previous is not None:
                _require(
                    previous.document["authorization_digest"]
                    == digest_json(grant.model_dump(mode="json"))
                )
                _require(events[-1].created_at <= self._now())
                _require(self._grant(connection, authorization_provider) == grant)
                return previous
            self._cas(events, expected_sequence)
            _, registration = self._registration(connection, grant.campaign_artifact)
            intents = [e for e in events if e.kind == "INTENT"]
            closed = self._closed(events)
            _require(all(e.document["ordinal"] in closed for e in intents))
            schedule = registration["campaign"]["schedule"]
            ordinal = len(intents)
            _require(ordinal < len(schedule) and schedule[ordinal]["split"] == grant.phase)
            self._unexposed(connection, registration["cases"], grant.campaign_artifact)
            _require(self._grant(connection, authorization_provider) == grant)
            if grant.phase == "test" and not any(e.kind == "SEALED_OPEN" for e in events):
                opening = self._append(
                    connection,
                    grant.campaign_artifact,
                    events,
                    "sealed-open",
                    "SEALED_OPEN",
                    {
                        "authorization_digest": digest_json(grant.model_dump(mode="json")),
                        "decision_artifact": grant.decision_artifact,
                    },
                )
                self._expose(
                    connection,
                    [case for case in registration["cases"] if case["split"] == "test"],
                    grant.campaign_artifact,
                    opening,
                )
            intent = self._append(
                connection,
                grant.campaign_artifact,
                events,
                "intent:" + intent_id,
                "INTENT",
                {
                    "intent_id": intent_id,
                    "ordinal": ordinal,
                    "assignment": schedule[ordinal],
                    "authorization_digest": digest_json(grant.model_dump(mode="json")),
                },
            )
            if grant.phase != "test":
                self._expose(
                    connection,
                    [
                        case
                        for case in registration["cases"]
                        if case["task_id"] == schedule[ordinal]["task_id"]
                    ],
                    grant.campaign_artifact,
                    intent,
                )
            return intent

    def record_observation(
        self,
        campaign_artifact: str,
        *,
        intent_id: str,
        observation_id: str,
        kind: Literal["STOPPED", "UNKNOWN", "OUTCOME_REFERENCE"],
        evidence_artifact: str,
        expected_sequence: int,
    ) -> JournalEvent:
        """Record trusted caller metadata, never infer a result or release a reservation."""
        _require(kind in {"STOPPED", "UNKNOWN", "OUTCOME_REFERENCE"})
        _require(bool(re.fullmatch(r"[a-f0-9]{64}", evidence_artifact)))
        _require(bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", observation_id)))
        with self._transaction() as connection:
            self._registration(connection, campaign_artifact)
            events = self._events(connection, campaign_artifact)
            intent = next(
                (e for e in events if e.kind == "INTENT" and e.document["intent_id"] == intent_id),
                None,
            )
            _require(intent is not None)
            assert intent is not None
            document = {
                "intent_id": intent_id,
                "ordinal": intent.document["ordinal"],
                "evidence_artifact": evidence_artifact,
            }
            event_id = "observation:" + observation_id
            previous = next((e for e in events if e.event_id == event_id), None)
            if previous is not None:
                _require(previous.kind == kind and previous.document == document)
                return previous
            self._cas(events, expected_sequence)
            outcomes = [
                e
                for e in events
                if e.kind == "OUTCOME_REFERENCE" and e.document["intent_id"] == intent_id
            ]
            _require(not outcomes)
            return self._append(connection, campaign_artifact, events, event_id, kind, document)

    def inspect(
        self, campaign_artifact: str
    ) -> tuple[JournalRegistration, tuple[JournalEvent, ...]]:
        """Read metadata only; observations are not validated scoring or accounting proof."""
        with self._transaction() as connection:
            registration, _ = self._registration(connection, campaign_artifact)
            return registration, tuple(self._events(connection, campaign_artifact))

    def pin_reporting_policy(
        self,
        campaign_artifact: str,
        *,
        policy_artifact: str,
        expected_sequence: int,
        current_guard: Callable[[], None],
    ) -> JournalEvent:
        """Pin caller-validated reporting rules before any phase or intent is recorded."""
        _require(bool(re.fullmatch(r"[a-f0-9]{64}", policy_artifact)))
        with self._transaction() as connection:
            current_guard()
            events = self._events(connection, campaign_artifact)
            if events and events[0].kind == "REPORTING_POLICY":
                _require(events[0].document == {"policy_artifact": policy_artifact})
                current_guard()
                return events[0]
            self._cas(events, expected_sequence)
            _require(not events)
            current_guard()
            return self._append(
                connection,
                campaign_artifact,
                events,
                "reporting-policy",
                "REPORTING_POLICY",
                {"policy_artifact": policy_artifact},
            )

    def registered_preparation_accounts(
        self, campaign_artifact: str
    ) -> tuple[PreparationAccountIdentity, ...]:
        """Return the immutable declared inventory; declarations are not accounting proof."""
        with self._transaction() as connection:
            _, document = self._registration(connection, campaign_artifact)
            return tuple(
                PreparationAccountIdentity.model_validate(value)
                for value in document["preparation_accounts"]
            )
