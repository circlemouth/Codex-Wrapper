import asyncio

from app import codex


def test_run_codex_last_message_runs_in_parallel(monkeypatch, tmp_path):
    """Ensure multiple Codex requests can execute concurrently."""

    # Configure settings for the test environment.
    monkeypatch.setattr(codex.settings, "codex_workdir", str(tmp_path))
    monkeypatch.setattr(codex.settings, "timeout_seconds", 5)
    monkeypatch.setattr(codex.settings, "max_parallel_requests", 2)

    async def _run() -> None:
        previous_limit = codex._parallel_limiter.max_parallel
        codex._parallel_limiter.configure(2)
        try:
            monkeypatch.setattr(
                codex, "_build_cmd_and_env", lambda *_, **__: ["codex", "exec"]
            )
            monkeypatch.setattr(codex, "_build_codex_env", lambda: {})

            active = 0
            max_active = 0
            release_events: list[asyncio.Event] = []

            async def fake_create_subprocess_exec(*cmd, **kwargs):
                nonlocal active, max_active
                out_path = cmd[-1]
                release = asyncio.Event()
                release_events.append(release)

                class FakeProcess:
                    def __init__(self) -> None:
                        self.returncode = 0

                    async def communicate(self):
                        nonlocal active, max_active
                        active += 1
                        max_active = max(max_active, active)
                        with open(out_path, "w", encoding="utf-8") as fh:
                            fh.write("done")
                        await release.wait()
                        active -= 1
                        return b"", b""

                    async def wait(self):
                        return 0

                    def kill(self):
                        release.set()

                return FakeProcess()

            monkeypatch.setattr(
                codex.asyncio,
                "create_subprocess_exec",
                fake_create_subprocess_exec,
            )

            task1 = asyncio.create_task(codex.run_codex_last_message("prompt-one"))
            task2 = asyncio.create_task(codex.run_codex_last_message("prompt-two"))

            while len(release_events) < 2:
                await asyncio.sleep(0)

            # Both tasks should hold a slot concurrently when the limit is 2.
            assert max_active == 2

            for event in release_events:
                event.set()

            result1, result2 = await asyncio.gather(task1, task2)
            assert result1 == "done"
            assert result2 == "done"
            assert max_active == 2
        finally:
            codex._parallel_limiter.configure(previous_limit)

    asyncio.run(_run())
