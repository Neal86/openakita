from pathlib import Path


def replace_exact(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text("utf-8")
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"{label} marker changed")
    path.write_text(text.replace(old, new, 1), "utf-8")


def main() -> None:
    path = Path("src/openakita/hermes/native_runtime.py")
    replace_exact(
        path,
        '''            result = await asyncio.to_thread(_execute)\n        return {\n''',
        '''            worker_task = asyncio.create_task(asyncio.to_thread(_execute))\n            cancelled: asyncio.CancelledError | None = None\n            result: dict[str, Any] | None = None\n            try:\n                result = await asyncio.shield(worker_task)\n            except asyncio.CancelledError as exc:\n                cancelled = exc\n            finally:\n                if not worker_task.done():\n                    try:\n                        result = await asyncio.shield(worker_task)\n                    except asyncio.CancelledError:\n                        result = await worker_task\n                elif result is None and not worker_task.cancelled():\n                    result = worker_task.result()\n                if cancelled is not None:\n                    raise cancelled\n            if result is None:\n                raise NativeHermesExecutionError("Hermes conversation produced no result")\n        return {\n''',
        "non-stream cancellation guard",
    )
    replace_exact(
        path,
        '''            loop = asyncio.get_running_loop()\n            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()\n            snapshot = prepare_native_hermes_capabilities(\n''',
        '''            loop = asyncio.get_running_loop()\n            queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=128)\n            stream_closed = threading.Event()\n            snapshot = prepare_native_hermes_capabilities(\n''',
        "bounded stream queue",
    )
    replace_exact(
        path,
        '''            emitted_delta = threading.Event()\n\n            def _on_delta(delta: Any) -> None:\n''',
        '''            emitted_delta = threading.Event()\n\n            def _enqueue(event: dict[str, Any] | None) -> None:\n                if stream_closed.is_set():\n                    return\n                future = asyncio.run_coroutine_threadsafe(queue.put(event), loop)\n                while not stream_closed.is_set():\n                    try:\n                        future.result(timeout=0.5)\n                        return\n                    except TimeoutError:\n                        continue\n                    except Exception:\n                        return\n                future.cancel()\n\n            def _on_delta(delta: Any) -> None:\n''',
        "stream backpressure helper",
    )
    replace_exact(
        path,
        '''                    loop.call_soon_threadsafe(\n                        queue.put_nowait,\n                        {"type": "text_delta", "content": text, "runtime": "native"},\n                    )\n''',
        '''                    _enqueue(\n                        {"type": "text_delta", "content": text, "runtime": "native"}\n                    )\n''',
        "delta backpressure",
    )
    replace_exact(
        path,
        '''                        loop.call_soon_threadsafe(\n                            queue.put_nowait,\n                            {"type": "final", "content": str(final), "runtime": "native"},\n                        )\n                except NativeHermesUnavailable as exc:\n                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error_kind": "unavailable", "error": str(exc), "runtime": "native"})\n                except Exception as exc:\n                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error_kind": "execution", "error": str(exc), "runtime": "native"})\n                finally:\n                    loop.call_soon_threadsafe(queue.put_nowait, None)\n''',
        '''                        _enqueue(\n                            {"type": "final", "content": str(final), "runtime": "native"}\n                        )\n                except NativeHermesUnavailable as exc:\n                    _enqueue(\n                        {\n                            "type": "error",\n                            "error_kind": "unavailable",\n                            "error": str(exc),\n                            "runtime": "native",\n                        }\n                    )\n                except Exception as exc:\n                    _enqueue(\n                        {\n                            "type": "error",\n                            "error_kind": "execution",\n                            "error": str(exc),\n                            "runtime": "native",\n                        }\n                    )\n                finally:\n                    _enqueue(None)\n''',
        "worker bounded enqueue",
    )
    replace_exact(
        path,
        '''            finally:\n                if not worker_task.done():\n                    try:\n                        await asyncio.shield(worker_task)\n                    except asyncio.CancelledError:\n                        await worker_task\n                if cancelled is not None:\n                    raise cancelled\n''',
        '''            finally:\n                stream_closed.set()\n                if not worker_task.done():\n                    try:\n                        await asyncio.shield(worker_task)\n                    except asyncio.CancelledError:\n                        await worker_task\n                if cancelled is not None:\n                    raise cancelled\n''',
        "stream cancellation signal",
    )


if __name__ == "__main__":
    main()
