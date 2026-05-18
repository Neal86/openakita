"""V2 brain surface — canonical home for ``Brain`` plus ``SupervisorBrain`` protocol.

Per ADR-0001 (fork-style rewrite), ADR-0003 (agent/ packaging), and the
Phase 2 sub-commit plan (commit 16), the canonical import path for the
agent's LLM gateway moves to :mod:`openakita.agent.brain`. This is also
where the new :class:`SupervisorBrain` protocol lives so the v2
supervisor (``runtime.supervisor.Supervisor``) can depend on a typed
seam instead of the concrete legacy class.

Current shape
-------------
:class:`Brain`, :class:`Response`, and :class:`Context` are re-exported
from the legacy ``core.brain`` body. :class:`SupervisorBrain` is a
brand-new :class:`typing.Protocol` capturing the minimum surface a
runtime-side supervisor needs from a brain: one async call to think
and an introspection hook for the current endpoint.

Why only protocol-level rewrite right now? The legacy Brain weighs
~1700 LOC because it carries multi-endpoint failover, compiler-LLM
circuit breaker, multimodal block conversion, streaming, and the
v1 tool-call adapter. Splitting all of that into ``runtime/llm/`` and
``runtime/streaming/`` requires breaking changes for ~20 caller sites;
the plan stages that deep refactor for Phase 8 once ``core/`` is
removed. Keeping the rewrite as protocol + re-export here keeps parity
tests green and lets ``runtime.supervisor`` already type against
:class:`SupervisorBrain`.

Migration guidance
------------------
* New code: ``from openakita.agent.brain import Brain, SupervisorBrain``
* Old code remains valid through the cutover.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from openakita.core.brain import Brain, Context, Response

__all__ = [
    "Brain",
    "Context",
    "Response",
    "SupervisorBrain",
]


@runtime_checkable
class SupervisorBrain(Protocol):
    """Minimum brain surface a v2 supervisor depends on.

    Implementing this protocol — either via the legacy :class:`Brain`
    or a future ``runtime/llm/SupervisorLLM`` — is enough to drive
    a ``runtime.state_graph.StateGraph`` step. The protocol is
    :func:`runtime_checkable` so the legacy Brain passes
    ``isinstance(brain, SupervisorBrain)`` checks without inheritance.
    """

    async def think_lightweight(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> Response:
        """Lightweight one-shot completion used by supervisor routing.

        Returns a :class:`Response` whose ``content`` and ``tool_calls``
        feed directly into the state-graph dispatcher.
        """

    def get_current_endpoint_info(self) -> dict[str, Any]:
        """Return ``{"endpoint": ..., "model": ..., "ok": bool, ...}``.

        Used by the supervisor to attach LLM provenance to ledger
        entries and to surface failover state to the UI.
        """
