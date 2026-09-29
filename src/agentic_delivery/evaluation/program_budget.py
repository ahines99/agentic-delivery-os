"""Prospective shared account envelopes; no execution or historical cost authority."""

import json
import os
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal
from uuid import uuid4

from pydantic import Field, TypeAdapter, model_validator

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.store import digest_json

if TYPE_CHECKING:
    from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore

Amount = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]


class ProgramBudgetFailure(ValueError):
    """Unavailable shared capacity or identity; reservations are never silently released."""


def _require(value: bool) -> None:
    if not value:
        raise ProgramBudgetFailure("Program budget capacity or binding is unavailable")


def _encoded_budget(value: dict[str, Any]) -> str:
    from agentic_delivery.evaluation.execution_store import _budget_terms

    _budget_terms(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _ceiling(value: dict[str, Any]) -> int:
    from agentic_delivery.evaluation.execution_store import _budget_terms

    model, infrastructure = _budget_terms(value)
    return (
        model.model_microdollars
        if infrastructure is None
        else min(
            infrastructure["total_microdollars"],
            model.model_microdollars + infrastructure["infrastructure_microdollars"],
        )
    )


class ProgramBudgetPolicy(Contract):
    schema_version: Literal[1] = 1
    program_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    authorization_digest: Digest
    cap_microdollars: int = Field(strict=True, gt=0, le=1_000_000_000)
    approved_ledger_identities: tuple[Digest, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def unique_targets(self) -> "ProgramBudgetPolicy":
        _require(len(set(self.approved_ledger_identities)) == len(self.approved_ledger_identities))
        return self


class ProgramAccountEnvelope(Contract):
    ledger_identity: Digest
    account_id: str
    budget_digest: Digest
    ceiling_microdollars: Amount
    state: Literal["HELD", "ACTIVE", "CLOSED"]
    closed_microdollars: Amount | None


class ProgramBudgetSnapshot(Contract):
    registry_identity: Digest
    policy: ProgramBudgetPolicy
    bound_ledger_identities: tuple[Digest, ...]
    envelopes: tuple[ProgramAccountEnvelope, ...]
    held_microdollars: Amount
    closed_microdollars: Amount
    available_microdollars: Amount
    # Registry metadata is not a census of historical/pre-registry spending or invoices.
    historical_costs_included: Literal[False] = False
    complete_program_cost: Literal[False] = False
    execution_authorized: Literal[False] = False


_SCHEMA = (
    "CREATE TABLE program (id INTEGER PRIMARY KEY, nonce TEXT NOT NULL, policy TEXT NOT NULL)",
    "CREATE TABLE targets (identity TEXT PRIMARY KEY, nonce TEXT NOT NULL)",
    "CREATE TABLE envelopes (account TEXT PRIMARY KEY, "
    "target TEXT NOT NULL REFERENCES targets(identity), "
    "budget TEXT NOT NULL, ceiling INTEGER NOT NULL, state TEXT NOT NULL, closed INTEGER)",
)


class ProgramBudgetRegistry:
    """One trusted local registry serializes envelopes across explicitly approved ledgers.

    Owners/controllers and database files are trusted. Current guard covers this program's
    accounting mutations; existing data, model and execution grants remain separately required.
    """

    @classmethod
    def create(
        cls, path: Path, policy: ProgramBudgetPolicy, *, current_guard: Callable[[], None]
    ) -> "ProgramBudgetRegistry":
        current_guard()
        policy = ProgramBudgetPolicy.model_validate(policy.model_dump())
        path = cls._path(path)
        # Exclusive creation never overwrites an existing database or silently reinitializes it.
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with sqlite3.connect(path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for statement in _SCHEMA:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO program VALUES (1, ?, ?)",
                (uuid4().hex, policy.model_dump_json()),
            )
            current_guard()
        return cls(path, current_guard=current_guard)

    @staticmethod
    def _path(path: Path) -> Path:
        path = path.resolve()
        _require(
            path.parent.is_dir()
            and re.fullmatch(r"delivery_eval_program_[A-Za-z0-9_-]+\.(db|sqlite)", path.name)
            is not None
        )
        return path

    def __init__(self, path: Path, *, current_guard: Callable[[], None]) -> None:
        self.path = self._path(path)
        self.current_guard = current_guard
        stamp = self.path.stat()
        self._file = (stamp.st_dev, stamp.st_ino)
        current_guard()
        with self._connection() as connection:
            self._schema(connection)
            rows = connection.execute("SELECT id, nonce, policy FROM program").fetchall()
            _require(len(rows) == 1 and rows[0][0] == 1)
            _require(re.fullmatch(r"[0-9a-f]{32}", rows[0][1]) is not None)
            self._program_row = tuple(rows[0])
            self.policy = ProgramBudgetPolicy.model_validate_json(rows[0][2])
            self.identity = digest_json(
                {
                    "kind": "prospective-program-budget",
                    "nonce": rows[0][1],
                    "policy": self.policy.model_dump(mode="json"),
                    "path": os.path.normcase(str(self.path)),
                }
            )
            self._snapshot(connection)
        current_guard()

    def _schema(self, connection: sqlite3.Connection) -> None:
        objects = connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        expected = {statement.split()[2]: statement for statement in _SCHEMA}
        _require(len(objects) == len(expected))
        _require(all(kind == "table" and expected.get(name) == sql for kind, name, sql in objects))

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        stamp = self.path.stat()
        _require((stamp.st_dev, stamp.st_ino) == self._file)
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=30)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            stamp = self.path.stat()
            _require((stamp.st_dev, stamp.st_ino) == self._file)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self.current_guard()
        with self._connection() as connection:
            self._schema(connection)
            _require(self.policy.model_dump_json() == self._program_row[2])
            _require(
                connection.execute("SELECT id, nonce, policy FROM program").fetchall()
                == [self._program_row]
            )
            self._snapshot(connection)
            yield connection
            self._snapshot(connection)
            self.current_guard()

    def _snapshot(self, connection: sqlite3.Connection) -> ProgramBudgetSnapshot:
        targets = connection.execute(
            "SELECT identity, nonce FROM targets ORDER BY identity"
        ).fetchall()
        _require(
            all(
                t in self.policy.approved_ledger_identities and re.fullmatch(r"[0-9a-f]{32}", n)
                for t, n in targets
            )
        )
        rows = connection.execute(
            "SELECT target, account, budget, ceiling, state, closed FROM envelopes ORDER BY account"
        ).fetchall()
        _require(len(rows) <= 10000)
        budgets = [json.loads(row[2]) for row in rows]
        _require(
            all(
                _encoded_budget(budget) == row[2] and _ceiling(budget) == row[3]
                for budget, row in zip(budgets, rows, strict=True)
            )
        )
        envelopes = tuple(
            ProgramAccountEnvelope(
                ledger_identity=r[0],
                account_id=r[1],
                budget_digest=digest_json(budget),
                ceiling_microdollars=r[3],
                state=r[4],
                closed_microdollars=r[5],
            )
            for budget, r in zip(budgets, rows, strict=True)
        )
        held = closed = 0
        for envelope in envelopes:
            _require(envelope.ledger_identity in {t[0] for t in targets})
            _require(re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", envelope.account_id) is not None)
            if envelope.state == "CLOSED":
                _require(envelope.closed_microdollars is not None)
                assert envelope.closed_microdollars is not None
                _require(envelope.closed_microdollars <= envelope.ceiling_microdollars)
                closed += envelope.closed_microdollars
            else:
                _require(envelope.closed_microdollars is None)
                held += envelope.ceiling_microdollars
        _require(held + closed <= self.policy.cap_microdollars)
        return ProgramBudgetSnapshot(
            registry_identity=self.identity,
            policy=self.policy,
            bound_ledger_identities=tuple(t[0] for t in targets),
            envelopes=envelopes,
            held_microdollars=held,
            closed_microdollars=closed,
            available_microdollars=self.policy.cap_microdollars - held - closed,
        )

    def snapshot(self) -> ProgramBudgetSnapshot:
        with self._transaction() as connection:
            return self._snapshot(connection)

    def bind_empty_target(self, identity: str) -> str:
        TypeAdapter(Digest).validate_python(identity)
        with self._transaction() as connection:
            _require(identity in self.policy.approved_ledger_identities)
            _require(
                connection.execute(
                    "SELECT 1 FROM envelopes WHERE target=? LIMIT 1", (identity,)
                ).fetchone()
                is None
            )
            old = connection.execute(
                "SELECT nonce FROM targets WHERE identity=?", (identity,)
            ).fetchone()
            if old is not None:
                return str(old[0])
            nonce = uuid4().hex
            connection.execute("INSERT INTO targets VALUES (?, ?)", (identity, nonce))
            return nonce

    def _target(self, connection: sqlite3.Connection, identity: str, nonce: str) -> None:
        _require(identity in self.policy.approved_ledger_identities)
        _require(
            connection.execute("SELECT nonce FROM targets WHERE identity=?", (identity,)).fetchone()
            == (nonce,)
        )

    def hold_account(
        self,
        target: str,
        nonce: str,
        account: str,
        budget: dict[str, Any],
        ceiling: int,
        *,
        account_exists: bool,
    ) -> None:
        TypeAdapter(Amount).validate_python(ceiling)
        _require(re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", account) is not None)
        budget_document = _encoded_budget(budget)
        _require(ceiling == _ceiling(budget))
        with self._transaction() as connection:
            self._target(connection, target, nonce)
            old = connection.execute(
                "SELECT target, budget, ceiling, state FROM envelopes WHERE account=?", (account,)
            ).fetchone()
            if old is not None:
                _require(old[:3] == (target, budget_document, ceiling))
                _require(account_exists or old[3] == "HELD")
                return
            _require(not account_exists)
            _require(self._snapshot(connection).available_microdollars >= ceiling)
            connection.execute(
                "INSERT INTO envelopes VALUES (?, ?, ?, ?, 'HELD', NULL)",
                (account, target, budget_document, ceiling),
            )

    def activate(self, target: str, nonce: str, account: str, budget: dict[str, Any]) -> None:
        with self._transaction() as connection:
            self._target(connection, target, nonce)
            old = connection.execute(
                "SELECT target, budget, state FROM envelopes WHERE account=?", (account,)
            ).fetchone()
            _require(old is not None and old[:2] == (target, _encoded_budget(budget)))
            assert old is not None
            if old[2] == "HELD":
                connection.execute(
                    "UPDATE envelopes SET state='ACTIVE' WHERE account=?", (account,)
                )

    def require_active(self, target: str, nonce: str, account: str, budget: dict[str, Any]) -> None:
        with self._transaction() as connection:
            self._target(connection, target, nonce)
            _require(
                connection.execute(
                    "SELECT target, budget, state FROM envelopes WHERE account=?", (account,)
                ).fetchone()
                == (target, _encoded_budget(budget), "ACTIVE")
            )

    def close_account(self, store: "EvaluationExecutionStore", account: str) -> None:
        """Require concrete irreversible local closure before releasing unused capacity."""
        from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore

        _require(type(store) is EvaluationExecutionStore and store.program_budget is self)
        self.current_guard()
        target, nonce, budget, actual = store._closed_program_summary(account)
        TypeAdapter(Amount).validate_python(actual)
        with self._transaction() as connection:
            self._target(connection, target, nonce)
            old = connection.execute(
                "SELECT target, budget, ceiling, state, closed FROM envelopes WHERE account=?",
                (account,),
            ).fetchone()
            _require(old is not None and old[:2] == (target, _encoded_budget(budget)))
            assert old is not None
            _require(actual <= old[2] and old[3] in {"ACTIVE", "CLOSED"})
            if old[3] == "CLOSED":
                _require(old[4] == actual)
            else:
                connection.execute(
                    "UPDATE envelopes SET state='CLOSED', closed=? WHERE account=?",
                    (actual, account),
                )
