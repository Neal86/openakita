#!/usr/bin/env python3
"""Patch Agent deletion to clean Hermes execution state without reformatting agents.py."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src/openakita/api/routes/agents.py"

MARKER = '''    logger.info(f"[Agents API] Deleted profile: {profile_id}")
    emit_agent_profiles_changed("deleted", profile_id=profile_id)
'''
REPLACEMENT = '''    # Remove the dedicated container but preserve its volume by default. Shared
    # Hermes keeps running because other Agents may still use it.
    try:
        from openakita.hermes.bindings import AgentHermesBindingStore
        from openakita.hermes.execution import (
            AgentExecutionStore,
            ExecutionMode,
            HermesInstanceMode,
            HermesInstanceStore,
        )
        from openakita.hermes.lifecycle import HermesLifecycleService

        execution_store = AgentExecutionStore()
        execution = execution_store.get(profile_id)
        if (
            execution.execution_mode == ExecutionMode.HERMES
            and execution.hermes_instance_mode == HermesInstanceMode.DEDICATED
            and execution.hermes_instance_id
        ):
            instance = HermesInstanceStore().get(execution.hermes_instance_id)
            if instance is not None:
                await HermesLifecycleService().remove(instance, delete_data=False)
        execution_store.delete(profile_id)
        AgentHermesBindingStore().delete(profile_id)
    except Exception as exc:
        # Agent deletion itself remains authoritative. Keep the saved instance
        # record when Docker cleanup fails so the instance page can retry it.
        logger.warning("[Agents API] Hermes cleanup failed for %s: %s", profile_id, exc)

    logger.info(f"[Agents API] Deleted profile: {profile_id}")
    emit_agent_profiles_changed("deleted", profile_id=profile_id)
'''


def main() -> None:
    text = PATH.read_text("utf-8")
    if "Hermes cleanup failed for %s" in text:
        print("Hermes Agent cleanup already integrated")
        return
    if MARKER not in text:
        raise RuntimeError("Agent deletion marker not found")
    PATH.write_text(text.replace(MARKER, REPLACEMENT, 1), "utf-8")
    print("Hermes Agent cleanup integrated")


if __name__ == "__main__":
    main()
