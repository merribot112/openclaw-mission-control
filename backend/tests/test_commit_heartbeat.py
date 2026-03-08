# ruff: noqa: INP001
"""Unit tests for AgentLifecycleService.commit_heartbeat status transitions.

Covers:
- Issue #231: commit_heartbeat must transition "updating" agents to "online"
- Regression guard: "provisioning" → "online" transition still works
- Non-transitioned statuses (deleting, online, offline) are preserved
- Explicit status_value overrides the computed transition
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.agents import Agent
from app.services.openclaw.provisioning_db import AgentLifecycleService


def _make_agent(status: str) -> Agent:
    agent = Agent(
        name="Test Agent",
        gateway_id=uuid4(),
    )
    agent.id = uuid4()
    agent.status = status
    agent.last_seen_at = None
    agent.wake_attempts = 1
    agent.checkin_deadline_at = None
    agent.last_provision_error = "some prior error"
    return agent


def _make_service() -> AgentLifecycleService:
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return AgentLifecycleService(session)


@pytest.mark.asyncio
async def test_commit_heartbeat_provisioning_transitions_to_online() -> None:
    """Regression: heartbeat from a 'provisioning' agent must yield 'online'."""
    agent = _make_agent("provisioning")
    service = _make_service()

    with patch.object(AgentLifecycleService, "record_heartbeat"):
        result = await service.commit_heartbeat(agent=agent, status_value=None)

    assert result.status == "online"
    assert agent.last_seen_at is not None
    assert agent.wake_attempts == 0
    assert agent.last_provision_error is None


@pytest.mark.asyncio
async def test_commit_heartbeat_updating_transitions_to_online() -> None:
    """Issue #231: heartbeat from an 'updating' agent must yield 'online'."""
    agent = _make_agent("updating")
    service = _make_service()

    with patch.object(AgentLifecycleService, "record_heartbeat"):
        result = await service.commit_heartbeat(agent=agent, status_value=None)

    assert result.status == "online"
    assert agent.last_seen_at is not None
    assert agent.wake_attempts == 0
    assert agent.last_provision_error is None


@pytest.mark.asyncio
async def test_commit_heartbeat_online_stays_online() -> None:
    """Heartbeat from an already-online agent keeps 'online' status."""
    agent = _make_agent("online")
    service = _make_service()

    with patch.object(AgentLifecycleService, "record_heartbeat"):
        result = await service.commit_heartbeat(agent=agent, status_value=None)

    assert result.status == "online"


@pytest.mark.asyncio
async def test_commit_heartbeat_explicit_status_value_overrides() -> None:
    """An explicit status_value is always applied, overriding the transition logic."""
    agent = _make_agent("updating")
    service = _make_service()

    with patch.object(AgentLifecycleService, "record_heartbeat"):
        result = await service.commit_heartbeat(agent=agent, status_value="degraded")

    assert result.status == "degraded"


@pytest.mark.asyncio
async def test_commit_heartbeat_offline_stays_offline() -> None:
    """Heartbeat from an offline agent without a status_value stays 'offline'.

    The heartbeat only transitions upward from provisioning/updating states.
    """
    agent = _make_agent("offline")
    service = _make_service()

    with patch.object(AgentLifecycleService, "record_heartbeat"):
        await service.commit_heartbeat(agent=agent, status_value=None)

    # 'offline' is not in the auto-transition set; it must stay offline.
    assert agent.status == "offline"


@pytest.mark.asyncio
async def test_commit_heartbeat_resets_wake_escalation_state() -> None:
    """Successful heartbeat always clears wake escalation counters."""
    from datetime import datetime

    agent = _make_agent("updating")
    agent.wake_attempts = 3
    agent.checkin_deadline_at = datetime(2024, 1, 1)
    agent.last_provision_error = "gateway timeout"
    service = _make_service()

    with patch.object(AgentLifecycleService, "record_heartbeat"):
        await service.commit_heartbeat(agent=agent, status_value=None)

    assert agent.wake_attempts == 0
    assert agent.checkin_deadline_at is None
    assert agent.last_provision_error is None
    assert agent.last_seen_at is not None
