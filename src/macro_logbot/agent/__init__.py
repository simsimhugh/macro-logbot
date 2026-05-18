"""Agent Core — MVP 직접 loop.

Spec reference: docs/design/02-설계문서.md (v1.1) §5.2 Agent Core

NOTE: spec 은 LangGraph state graph 를 명시하지만, MVP 단순화로
직접 while loop 사용. LangGraph 으로의 migration 은 FOLLOWUP.
"""

from macro_logbot.agent.core import MAX_ITERS_DEFAULT, AgentRunResult, run_agent

__all__ = ["MAX_ITERS_DEFAULT", "AgentRunResult", "run_agent"]
