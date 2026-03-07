from __future__ import annotations

import json
from datetime import datetime, timezone

from agent.config.loader import Config
from agent.models.state import ConversationState


class PromptBuilder:
    def __init__(self, config: Config) -> None:
        self._config = config

    def build(self, state: ConversationState) -> str:
        template = self._config.system_prompt.template

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

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

        # Append dynamic sections from config
        dynamic = self._config.system_prompt.dynamic_sections
        if dynamic:
            sections = "\n".join(dynamic.values())
            template = f"{template}\n\n{sections}"

        return template

    def _build_state_context(self, state: ConversationState) -> str:
        return (
            f"Session: {state.session_id}\n"
            f"Messages in context: {len(state.messages)}"
        )
