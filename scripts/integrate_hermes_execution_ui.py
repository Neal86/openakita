#!/usr/bin/env python3
"""Apply small deterministic UI insertions without reformatting large source files."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_types() -> None:
    path = ROOT / "apps/setup-center/src/types.ts"
    text = path.read_text("utf-8")
    if '"execution_instances"' not in text:
        marker = '| "dashboard" | "agent_manager"'
        if marker not in text:
            raise RuntimeError("ViewId marker missing")
        text = text.replace(marker, '| "dashboard" | "agent_manager" | "execution_instances"', 1)
        path.write_text(text, "utf-8")


def patch_app() -> None:
    path = ROOT / "apps/setup-center/src/App.tsx"
    text = path.read_text("utf-8")
    if "const ExecutionInstancesView" not in text:
        marker = 'const AgentManagerView = lazy(() => import("./views/AgentManagerView").then(m => ({ default: m.AgentManagerView })));'
        if marker not in text:
            raise RuntimeError("AgentManager lazy import marker missing")
        text = text.replace(marker, marker + '\nconst ExecutionInstancesView = lazy(() => import("./views/ExecutionInstancesView").then(m => ({ default: m.ExecutionInstancesView })));', 1)
    if '"execution-instances": "execution_instances"' not in text:
        marker = '"agent-manager": "agent_manager", "agent-store": "agent_store",'
        if marker not in text:
            raise RuntimeError("hash route marker missing")
        text = text.replace(marker, '"agent-manager": "agent_manager", "execution-instances": "execution_instances", "agent-store": "agent_store",', 1)
    if 'if (view === "execution_instances")' not in text:
        marker = '''    if (view === "agent_manager") {
      return (
        <AgentManagerView
          apiBaseUrl={apiBaseUrl}
          visible={view === "agent_manager"}
        />
      );
    }
'''
        if marker not in text:
            raise RuntimeError("AgentManager return block missing")
        addition = marker + '''    if (view === "execution_instances") {
      return <ExecutionInstancesView apiBaseUrl={apiBaseUrl} />;
    }
'''
        text = text.replace(marker, addition, 1)
    path.write_text(text, "utf-8")


def patch_sidebar() -> None:
    path = ROOT / "apps/setup-center/src/components/Sidebar.tsx"
    text = path.read_text("utf-8")
    text = text.replace('const maViews: ViewId[] = ["dashboard", "org_editor", "pixel_office", "agent_manager"];', 'const maViews: ViewId[] = ["dashboard", "org_editor", "pixel_office", "agent_manager", "execution_instances"];')
    if 'view === "execution_instances"' not in text:
        marker = re.search(r'(\s*<div className=\{`navItem \$\{view === "agent_manager"[\s\S]*?</div>)', text)
        if not marker:
            raise RuntimeError("Agent manager sidebar marker missing")
        addition = marker.group(1) + '''
            <div className={`navItem ${view === "execution_instances" ? "navItemActive" : ""}`} onClick={() => onViewChange("execution_instances")} role="button" tabIndex={0} title="执行模式实例">
              <IconGear size={16} /> {!collapsed && <span>执行模式实例</span>}
            </div>'''
        text = text[: marker.start()] + addition + text[marker.end() :]
    path.write_text(text, "utf-8")


def patch_agent_manager() -> None:
    path = ROOT / "apps/setup-center/src/views/AgentManagerView.tsx"
    text = path.read_text("utf-8")
    if "ExecutionModeSection" not in text:
        marker = 'import { AgentIcon, AGENT_SVG_ICONS, isCustomAgentIcon } from "@/components/AgentIcon";'
        if marker not in text:
            raise RuntimeError("AgentManager import marker missing")
        text = text.replace(marker, marker + '\nimport { ExecutionModeSection } from "../components/ExecutionModeSection";', 1)
    if '<ExecutionModeSection' not in text:
        sheet_start = text.find('<Sheet open={editorOpen}')
        if sheet_start < 0:
            sheet_start = text.find('<Sheet')
        sheet_end = text.find('</SheetContent>', sheet_start)
        if sheet_start < 0 or sheet_end < 0:
            raise RuntimeError("Agent editor SheetContent marker missing")
        addition = '''
              {!isCreating && editingProfile.id && (
                <div className="mt-5">
                  <ExecutionModeSection apiBaseUrl={apiBaseUrl} profileId={editingProfile.id} disabled={saving} />
                </div>
              )}
'''
        text = text[:sheet_end] + addition + text[sheet_end:]
    path.write_text(text, "utf-8")


def main() -> None:
    patch_types()
    patch_app()
    patch_sidebar()
    patch_agent_manager()
    print("Hermes execution UI integration applied")


if __name__ == "__main__":
    main()
