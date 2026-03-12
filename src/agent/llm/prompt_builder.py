from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.config.loader import Config
from agent.utils.tz import AGENT_TZ
from agent.models.state import ConversationState


class PromptBuilder:
    def __init__(self, config: Config) -> None:
        self._config = config

    def build(self, state: ConversationState) -> str:
        template = self._config.system_prompt.template

        now = datetime.now(AGENT_TZ).strftime("%Y-%m-%d %H:%M:%S") + " (hora local Argentina)"

        replacements = {
            "{current_datetime}": now,
            "{agent.name}": self._config.agent.name,
            "{agent.greeting}": self._config.agent.greeting,
            "{personality.prompt}": self._config.personality.prompt,
            "{personality.tone}": self._config.personality.tone,
            "{personality.style}": self._config.personality.style,
            "{personality.formality}": self._config.personality.formality,
            "{personality.emoji_usage}": str(self._config.personality.emoji_usage),
        }
        for placeholder, value in replacements.items():
            template = template.replace(placeholder, value)

        # {actions} — JSON list of available action definitions
        actions_data = [a.model_dump() for a in self._config.actions.available]
        template = template.replace("{actions}", json.dumps(actions_data, indent=2))

        # {state_context} — expedition runtime context
        template = template.replace("{state_context}", self._build_state_context(state))

        # {knowledge_docs} — list of available documents in the KB
        docs_list = state.metadata.get("knowledge_docs", [])
        docs_str = "\n".join(f"- {d}" for d in docs_list) if docs_list else "No documents indexed yet."
        template = template.replace("{knowledge_docs}", docs_str)

        # Append dynamic sections from config
        dynamic = self._config.system_prompt.dynamic_sections
        if dynamic:
            sections = "\n".join(dynamic.values())
            template = f"{template}\n\n{sections}"

        return template

    def _build_state_context(self, state: ConversationState) -> str:
        lines = [
            f"Session: {state.session_id}",
            f"Messages in context: {len(state.messages)}",
        ]
        pos = state.metadata.get("current_position")
        if pos:
            lines.append(
                f"Current position (latest GPS fix): lat={pos['latitude']}, lon={pos['longitude']} — recorded at {pos['recorded_at']}"
            )
        else:
            lines.append("Current position: no GPS fix recorded yet")
        return "\n".join(lines)
