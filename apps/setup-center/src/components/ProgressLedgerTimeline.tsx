import { useMemo, useState } from "react";

/**
 * One progress-ledger entry, mirroring the payload shape the v2
 * supervisor emits on the ``progress_ledger`` channel (ADR-0006
 * + ADR-0004 §dual-ledger).
 *
 * Backend ``ProgressLedger`` carries five user-facing fields:
 *   is_request_satisfied, is_in_loop, is_progress_being_made,
 *   next_speaker, instruction_or_question.
 * They land in the ``payload`` of a :class:`StreamEvent`; the
 * timeline component renders that payload directly.
 */
export interface ProgressLedgerEvent {
  /** Backend ``StreamEvent.event_id`` -- used as React key. */
  id: string;
  /** Emitted-at timestamp string (ISO-8601). */
  ts: string;
  /** Whether the supervisor judged the user's request satisfied. */
  is_request_satisfied: boolean;
  /** Whether the supervisor detected a loop in this turn. */
  is_in_loop: boolean;
  /** Whether forward progress was made this turn. */
  is_progress_being_made: boolean;
  /** Next-speaker hint from the supervisor (node role / id / name). */
  next_speaker: string;
  /** Verbatim instruction the supervisor will hand to next_speaker. */
  instruction_or_question: string;
}

export interface ProgressLedgerTimelineProps {
  /** Newest-last sequence of ledger entries. */
  events: ProgressLedgerEvent[];
  /** Resolve a raw node id/role to a human (Chinese) display name. */
  nodeNameOf?: (id: string) => string;
  /** Whether a command is still running (drives the live pulse). */
  running?: boolean;
  /** Optional ``data-testid`` for the outer container. */
  "data-testid"?: string;
}

type SegStatus = "running" | "done" | "loop" | "stall";

interface Segment {
  key: string;
  node: string;
  lines: string[];
  status: SegStatus;
  satisfied: boolean;
  ts: string;
}

// UI issue #3: the old component rendered English status pills
// (DONE/LOOP/PROGRESS/STALL). The whole product runs in Chinese, so the
// process log must be Chinese too. These are the user-facing labels.
const STATUS_LABEL: Record<SegStatus, string> = {
  running: "进行中",
  done: "已完成",
  loop: "检测到循环",
  stall: "停滞",
};

const STATUS_CLASS: Record<SegStatus, string> = {
  running: "plt-pill plt-pill-running",
  done: "plt-pill plt-pill-done",
  loop: "plt-pill plt-pill-loop",
  stall: "plt-pill plt-pill-stall",
};

function fmtTs(ts: string): string {
  if (!ts) return "";
  // Accept ISO strings and epoch numbers alike.
  const d = /^\d+$/.test(ts) ? new Date(Number(ts)) : new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(11, 19);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/**
 * Render the v2 live-process feed as a connected, conversational timeline.
 *
 * Redesign (exploratory testing v12): the previous version rendered one big
 * shadcn Card per ledger entry with English badges and "(尚未指定)/(无指令)"
 * placeholders, sitting in a detached strip above the chat — the "大白块 +
 * 割裂 + 英文" the user reported. This version:
 *
 *  * groups consecutive events by node into ONE segment (a node's whole turn
 *    is a single bubble, not N cards),
 *  * shows each node's actual content lines (not just an action verb),
 *  * auto-collapses every COMPLETED node to a one-line summary (click to
 *    expand) and keeps only the active node expanded with a live pulse,
 *  * is fully Chinese, and
 *  * renders NOTHING when there are no meaningful events, so the old
 *    "暂无进度记录…" banner never sits permanently above a finished task.
 *
 * It is meant to live INSIDE the message scroll column (not a bounded strip),
 * so the command center reads as a single conversation that scrolls as one.
 */
export function ProgressLedgerTimeline({
  events,
  nodeNameOf,
  running = false,
  ...rest
}: ProgressLedgerTimelineProps) {
  const [openKeys, setOpenKeys] = useState<Record<string, boolean>>({});

  const segments = useMemo<Segment[]>(() => {
    const resolve = (id: string) => (nodeNameOf ? nodeNameOf(id) : id) || id;
    // Drop empty-shell entries (no speaker AND no instruction AND not a
    // terminal "satisfied" marker) — those were the bulk of the "大白块".
    const meaningful = events.filter(
      (e) =>
        (e.next_speaker && e.next_speaker.trim()) ||
        (e.instruction_or_question && e.instruction_or_question.trim()) ||
        e.is_request_satisfied,
    );
    const segs: Segment[] = [];
    for (const e of meaningful) {
      const node = resolve((e.next_speaker || "").trim()) || "协调";
      const line = (e.instruction_or_question || "").trim();
      const last = segs[segs.length - 1];
      let status: SegStatus = "running";
      if (e.is_request_satisfied) status = "done";
      else if (e.is_in_loop) status = "loop";
      else if (!e.is_progress_being_made) status = "stall";
      if (last && last.node === node && !last.satisfied) {
        if (line && !last.lines.includes(line)) last.lines.push(line);
        last.status = status;
        last.satisfied = last.satisfied || e.is_request_satisfied;
        last.ts = e.ts || last.ts;
      } else {
        segs.push({
          key: e.id,
          node,
          lines: line ? [line] : [],
          status,
          satisfied: e.is_request_satisfied,
          ts: e.ts,
        });
      }
    }
    return segs;
  }, [events, nodeNameOf]);

  if (segments.length === 0) return null;

  const lastIdx = segments.length - 1;

  return (
    <div className="plt-feed" data-testid={rest["data-testid"] ?? "progress-ledger-timeline"}>
      {segments.map((seg, idx) => {
        const isActive = running && idx === lastIdx && seg.status === "running";
        // Active node stays open; completed nodes collapse to one line unless
        // the user explicitly expanded them.
        const open = openKeys[seg.key] ?? isActive;
        const summary = seg.lines[seg.lines.length - 1] || STATUS_LABEL[seg.status];
        return (
          <div
            key={seg.key}
            className={`plt-seg${isActive ? " plt-seg-active" : ""}`}
            data-testid="progress-ledger-entry"
          >
            <div className={`plt-rail${isActive ? " plt-rail-active" : ""}`}>
              <span className={`plt-dot plt-dot-${seg.status}${isActive ? " plt-dot-pulse" : ""}`} />
            </div>
            <div className="plt-body">
              <button
                type="button"
                className="plt-head"
                onClick={() => setOpenKeys((p) => ({ ...p, [seg.key]: !open }))}
              >
                <span className="plt-node">{seg.node}</span>
                <span className={STATUS_CLASS[seg.status]}>{STATUS_LABEL[seg.status]}</span>
                <span className="plt-time">{fmtTs(seg.ts)}</span>
                {seg.lines.length > 0 && (
                  <span className="plt-caret">{open ? "▾" : "▸"}</span>
                )}
              </button>
              {open ? (
                seg.lines.length > 0 && (
                  <div className="plt-lines">
                    {seg.lines.map((ln, i) => (
                      <div className="plt-line" key={i}>{ln}</div>
                    ))}
                  </div>
                )
              ) : (
                <div className="plt-summary" title={summary}>{summary}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default ProgressLedgerTimeline;
