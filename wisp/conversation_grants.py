"""Per-conversation permission grant manager (H7).

Models HeyClicky's "Allow once / Always / Not now" permission model:
  - `HARD_STOP_KINDS = frozenset({'purchase', 'send', 'delete', 'payment'})`
    always require confirmation even when an `'always'` grant exists.
  - `GrantScope(conversation_id, app_class)` scopes grants by conversation
    and active application class.
  - `parse_voice_grant_reply(spoken_text)` maps natural spoken answers to
    `'allow_once' | 'always' | 'not_now'`.
"""
from __future__ import annotations

import dataclasses
import re

HARD_STOP_KINDS: frozenset[str] = frozenset(
    {"purchase", "send", "delete", "payment"}
)

ALLOW_ONCE = "allow_once"
ALWAYS = "always"
NOT_NOW = "not_now"
VALID_DECISIONS: frozenset[str] = frozenset({ALLOW_ONCE, ALWAYS, NOT_NOW})
GRANT_CARD_OPTIONS: tuple[str, str, str] = ("Allow once", "Always", "Not now")

_NONWORD = re.compile(r"[^a-z0-9' ]+")
_TOKEN_SPLIT = re.compile(r"[._\-/\s:]+")

_NOT_NOW_PHRASES = (
    "not now",
    "not right now",
    "no thanks",
    "don't allow",
    "do not allow",
    "don't do it",
    "do not",
    "never mind",
    "hold on",
    "skip it",
)
_NOT_NOW_WORDS = frozenset(
    {
        "no",
        "nope",
        "nah",
        "cancel",
        "deny",
        "denied",
        "don't",
        "never",
        "stop",
        "skip",
        "wait",
        "later",
        "refuse",
        "pass",
    }
)

_ALWAYS_PHRASES = (
    "always allow",
    "allow always",
    "every time",
    "all the time",
    "for this app",
    "trust this app",
    "keep allowing",
)
_ALWAYS_WORDS = frozenset({"always"})

_ALLOW_ONCE_PHRASES = (
    "allow once",
    "just once",
    "this time",
    "just this once",
    "one time",
    "once only",
    "go ahead",
    "go for it",
    "do it",
    "sounds good",
)
_ALLOW_ONCE_WORDS = frozenset(
    {
        "once",
        "yes",
        "yeah",
        "yep",
        "yup",
        "sure",
        "ok",
        "okay",
        "allow",
        "approve",
        "approved",
        "confirm",
        "proceed",
        "fine",
        "first",
        "1",
    }
)


_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'",
                              "\u2032": "'", "`": "'"})
_NEGATED_ALWAYS = re.compile(r"\b(?:not|never|no|isn't|don't)\s+always\b")
_ONE_TIME_PHRASES = (
    "just once",
    "this once",
    "just this once",
    "this time",
    "one time",
    "once only",
    "allow once",
    "only once",
)


def _norm(text: str | None) -> str:
    # Curly apostrophes become ASCII first, so "don\u2019t" stays "don't"
    # instead of splitting into "don t" and losing the denial.
    lowered = (text or "").translate(_APOSTROPHES).lower()
    return " ".join(_NONWORD.sub(" ", lowered).split())


def parse_voice_grant_reply(spoken_text: str | None) -> str | None:
    """Map a spoken response to `'allow_once' | 'always' | 'not_now'`, or None
    when the utterance does not map to any grant decision.

    Negations are checked first so phrases like 'no, not now' or 'never allow'
    never resolve as a grant.
    """
    t = _norm(spoken_text)
    if not t:
        return None
    if t in ("allow_once", "always", "not_now"):
        return t

    words = set(t.split())

    for phrase in _NOT_NOW_PHRASES:
        if phrase in t:
            return NOT_NOW
    if words & _NOT_NOW_WORDS:
        return NOT_NOW

    # An explicit one-time limit, or a negated "always", must never become
    # a persistent grant ("not always, just this once").
    if _NEGATED_ALWAYS.search(t):
        if any(p in t for p in _ONE_TIME_PHRASES):
            return ALLOW_ONCE
        return NOT_NOW
    if any(p in t for p in _ONE_TIME_PHRASES):
        return ALLOW_ONCE

    for phrase in _ALWAYS_PHRASES:
        if phrase in t:
            return ALWAYS
    if words & _ALWAYS_WORDS:
        return ALWAYS

    for phrase in _ALLOW_ONCE_PHRASES:
        if phrase in t:
            return ALLOW_ONCE
    if words & _ALLOW_ONCE_WORDS:
        return ALLOW_ONCE

    return None


@dataclasses.dataclass(frozen=True)
class GrantScope:
    """Permission grant scope keyed by `conversation_id` and `app_class`."""

    conversation_id: str
    app_class: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "conversation_id",
            str(self.conversation_id or "").strip(),
        )
        object.__setattr__(
            self,
            "app_class",
            str(self.app_class or "").strip().lower(),
        )


def is_hard_stop(
    action_kind: str = "",
    tool_name: str = "",
    arg: str = "",
) -> bool:
    """Return True if the action or tool belongs to `HARD_STOP_KINDS`
    (`purchase`, `send`, `delete`, `payment`). Hard-stop actions always
    require explicit confirmation regardless of existing grants."""
    for raw in (action_kind, tool_name, arg):
        if not raw:
            continue
        lowered = str(raw).strip().lower()
        if lowered in HARD_STOP_KINDS:
            return True
        tokens = {tok for tok in _TOKEN_SPLIT.split(lowered) if tok}
        if tokens & HARD_STOP_KINDS:
            return True
    return False


class ConversationGrantManager:
    """Manages per-conversation and per-app-class permission grants.

    Semantics:
      - `'allow_once'`: permits a single non-hard-stop action in the exact
        `GrantScope(conversation_id, app_class)` (or approves a single
        prompted step without persisting a future grant).
      - `'always'`: persists for the exact `(conversation_id, app_class)` scope
        across non-hard-stop steps so subsequent computer-use steps in that
        app, in that conversation, do not re-prompt. It never carries over to
        another conversation.
      - `'not_now'`: denies the step and records no grant.
      - Any action whose kind is in `HARD_STOP_KINDS` (`purchase`, `send`,
        `delete`, `payment`) NEVER bypasses confirmation, even when an
        `'always'` grant is active for the conversation and app class.
    """

    def __init__(self) -> None:
        self._always_scopes: set[GrantScope] = set()
        self._once_counts: dict[GrantScope, int] = {}
        self.audit_log: list[dict] = []

    def _coerce_scope(
        self,
        scope: GrantScope | tuple[str, str] | str,
        app_class: str = "",
    ) -> GrantScope:
        if isinstance(scope, GrantScope):
            return scope
        if isinstance(scope, tuple) and len(scope) == 2:
            return GrantScope(scope[0], scope[1])
        return GrantScope(str(scope), app_class)

    def record_decision(
        self,
        scope: GrantScope | tuple[str, str] | str,
        decision: str,
        app_class: str = "",
        action_kind: str = "computer_use",
    ) -> str:
        """Record a grant decision (`'allow_once' | 'always' | 'not_now'`) for
        `scope`. Raises ValueError on an unrecognized decision."""
        sc = self._coerce_scope(scope, app_class)
        norm = parse_voice_grant_reply(decision) if decision not in VALID_DECISIONS else decision
        if norm not in VALID_DECISIONS:
            raise ValueError(f"invalid grant decision: {decision!r}")

        hard = is_hard_stop(action_kind)
        if norm == ALWAYS and not hard:
            self._always_scopes.add(sc)
        elif norm == ALLOW_ONCE and not hard:
            self._once_counts[sc] = self._once_counts.get(sc, 0) + 1
        elif norm == NOT_NOW:
            self._once_counts.pop(sc, None)
        return norm

    grant = record_decision

    def is_granted(
        self,
        scope: GrantScope | tuple[str, str] | str,
        action_kind: str = "computer_use",
        app_class: str = "",
        consume_once: bool = False,
    ) -> bool:
        """Check whether `scope` is currently granted for `action_kind`.
        Always returns False when `action_kind` is in `HARD_STOP_KINDS`."""
        if is_hard_stop(action_kind):
            return False
        sc = self._coerce_scope(scope, app_class)
        if sc in self._always_scopes:
            return True
        rem = self._once_counts.get(sc, 0)
        if rem > 0:
            if consume_once:
                if rem <= 1:
                    self._once_counts.pop(sc, None)
                else:
                    self._once_counts[sc] = rem - 1
            return True
        return False

    def authorize(
        self,
        scope: GrantScope | tuple[str, str] | str,
        action_kind: str = "computer_use",
        prompt_fn=None,
        app_class: str = "",
    ) -> bool:
        """Authorize an action in `scope`, prompting via `prompt_fn` only when
        no applicable grant exists or when `action_kind` is a hard stop."""
        sc = self._coerce_scope(scope, app_class)
        hard = is_hard_stop(action_kind)

        if not hard and self.is_granted(sc, action_kind=action_kind, consume_once=True):
            self.audit_log.append(
                {
                    "conversation_id": sc.conversation_id,
                    "app_class": sc.app_class,
                    "action_kind": action_kind,
                    "prompted": False,
                    "allowed": True,
                    "decision": "granted",
                }
            )
            return True

        if prompt_fn is None:
            self.audit_log.append(
                {
                    "conversation_id": sc.conversation_id,
                    "app_class": sc.app_class,
                    "action_kind": action_kind,
                    "prompted": False,
                    "allowed": False,
                    "decision": NOT_NOW,
                }
            )
            return False

        raw_reply = prompt_fn(sc, action_kind)
        if isinstance(raw_reply, bool):
            decision = ALLOW_ONCE if raw_reply else NOT_NOW
        else:
            decision = parse_voice_grant_reply(str(raw_reply)) or NOT_NOW

        if decision == ALWAYS and not hard:
            self._always_scopes.add(sc)

        allowed = decision in (ALLOW_ONCE, ALWAYS)
        self.audit_log.append(
            {
                "conversation_id": sc.conversation_id,
                "app_class": sc.app_class,
                "action_kind": action_kind,
                "prompted": True,
                "allowed": allowed,
                "decision": decision,
            }
        )
        return allowed


GrantManager = ConversationGrantManager
