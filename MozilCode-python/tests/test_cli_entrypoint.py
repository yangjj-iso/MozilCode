from __future__ import annotations

from types import SimpleNamespace
import sys

import pytest

from mozilcode.config import AppConfig, ProviderConfig
from mozilcode import __main__ as cli
from mozilcode.permissions import PermissionMode


def test_main_without_prompt_requires_headless_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["mozilcode"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "A prompt is required for headless CLI execution" in err


def test_drain_cli_notifications_uses_shared_task_format() -> None:
    task = SimpleNamespace(
        id="task-1",
        name="worker",
        status="completed",
        result="done",
        start_time=10.0,
        end_time=12.0,
        progress=SimpleNamespace(input_tokens=3, output_tokens=5),
    )
    task_manager = SimpleNamespace(poll_completed=lambda: [task])
    team_manager = SimpleNamespace(drain_lead_mailbox=lambda: ["mailbox-note"])

    notes = cli._drain_cli_notifications(task_manager, team_manager)

    assert len(notes) == 2
    assert "Task ID: task-1" in notes[0]
    assert "Agent: worker" in notes[0]
    assert "Tokens: input=3, output=5" in notes[0]
    assert "<task_id>" not in notes[0]
    assert notes[1] == "mailbox-note"


@pytest.mark.asyncio
async def test_run_prompt_uses_shared_agent_factory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    created: dict[str, object] = {}

    class FakeMemoryHub:
        def __init__(self) -> None:
            self.shutdown_called = False

        async def shutdown(self) -> None:
            self.shutdown_called = True

    class FakeAgent:
        def __init__(self) -> None:
            self.memory_hub = FakeMemoryHub()
            self.prompts: list[str] = []

        async def run_to_completion(self, prompt, _conversation=None) -> str:
            self.prompts.append(prompt)
            return "done"

    async def fake_create_agent_from_config(config, work_dir, permission_mode, hook_engine):
        agent = FakeAgent()
        deps = SimpleNamespace(
            task_manager=SimpleNamespace(
                poll_completed=lambda: [],
                running_task_states=lambda: {},
                completed_task_ids=lambda: [],
                notification_queue_size=lambda: 0,
                has_running_tasks=lambda: False,
            ),
            team_manager=SimpleNamespace(
                has_teams=lambda: False,
                team_names=lambda: [],
                drain_lead_mailbox=lambda: [],
            ),
        )
        created.update(
            agent=agent,
            config=config,
            work_dir=work_dir,
            permission_mode=permission_mode,
            hook_engine=hook_engine,
        )
        return agent, deps

    import mozilcode.agent_factory as agent_factory

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        agent_factory,
        "create_agent_from_config",
        fake_create_agent_from_config,
    )
    config = AppConfig(
        providers=[
            ProviderConfig(
                name="local",
                protocol="openai-compat",
                base_url="http://127.0.0.1:9999/v1",
                model="smoke-model",
            )
        ]
    )
    hook_engine = object()

    await cli._run_prompt(config, PermissionMode.ACCEPT_EDITS, hook_engine, "hello")

    agent = created["agent"]
    assert isinstance(agent, FakeAgent)
    assert created["config"] is config
    assert created["work_dir"] == str(tmp_path)
    assert created["permission_mode"] == PermissionMode.ACCEPT_EDITS
    assert created["hook_engine"] is hook_engine
    assert agent.prompts == ["hello"]
    assert agent.memory_hub.shutdown_called is True
    assert capsys.readouterr().out.strip() == "done"


@pytest.mark.asyncio
async def test_run_prompt_shutdowns_memory_hub_when_agent_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    created: dict[str, object] = {}

    class FakeMemoryHub:
        def __init__(self) -> None:
            self.shutdown_called = False

        async def shutdown(self) -> None:
            self.shutdown_called = True

    class FailingAgent:
        def __init__(self) -> None:
            self.memory_hub = FakeMemoryHub()

        async def run_to_completion(self, _prompt, _conversation=None) -> str:
            raise RuntimeError("model failed")

    async def fake_create_agent_from_config(*_args):
        agent = FailingAgent()
        created["agent"] = agent
        return agent, SimpleNamespace(
            task_manager=SimpleNamespace(),
            team_manager=SimpleNamespace(),
        )

    import mozilcode.agent_factory as agent_factory

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        agent_factory,
        "create_agent_from_config",
        fake_create_agent_from_config,
    )
    config = AppConfig(
        providers=[
            ProviderConfig(
                name="local",
                protocol="openai-compat",
                base_url="http://127.0.0.1:9999/v1",
                model="smoke-model",
            )
        ]
    )

    with pytest.raises(RuntimeError, match="model failed"):
        await cli._run_prompt(config, PermissionMode.DEFAULT, None, "hello")

    agent = created["agent"]
    assert isinstance(agent, FailingAgent)
    assert agent.memory_hub.shutdown_called is True
