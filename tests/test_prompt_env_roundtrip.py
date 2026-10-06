"""Prompt fields retain user-authored text across Settings and runtime reloads."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.system.env_utils import read_env_file, write_env_file
from ui import settings_env

PROMPTS = [
    "'Tis a useful assistant",
    "'preserve these literal quotes'",
    '"preserve these double quotes"',
    "  preserve surrounding spaces  ",
    "Explain ${OPENWAND_QA_UNSET_VAR} literally",
    r"Keep \backslashes\ exactly",
    "first line\nsecond line",
    "Unicode 中文 café 🪄",
    "control\x00character and \x01",
    "first\r\nsecond and tab\t",
    "openwand-json-b64:ImhlbGxvIg==",
]
PROMPT_KEYS = [
    "SYSTEM_PROMPT_UTILITY",
    "OPENWAND_CODEX_SYSTEM_PROMPT",
    "OPENWAND_CLAUDE_SYSTEM_PROMPT",
    "CHAT_ELABORATE_PROMPT",
    "LIVE_VOICE_SYSTEM_PROMPT",
    "GPT_SOVITS_PROMPT_TEXT",
    "CALLER_1_INTENT_2_PROMPT",
]


class PromptEnvRoundtripTests(unittest.TestCase):
    def test_prompt_write_read_is_literal(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENWAND_QA_UNSET_VAR": ""}):
            path = Path(tmp) / ".env"
            for key in PROMPT_KEYS:
                for prompt in PROMPTS:
                    with self.subTest(key=key, prompt=prompt):
                        path.write_text("", encoding="utf-8")
                        write_env_file(path, {key: prompt})
                        self.assertEqual(read_env_file(path)[key], prompt)
                        write_env_file(path, {key: prompt})
                        self.assertEqual(read_env_file(path)[key], prompt)
                        self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 1)

    def test_settings_and_runtime_reload_keep_prompts_literal(self):
        import config

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            prompts = {
                "SYSTEM_PROMPT_UTILITY": "  'Tis a useful assistant\nExplain ${OPENWAND_QA_UNSET_VAR} 中文  ",
                "OPENWAND_CODEX_SYSTEM_PROMPT": '  Keep \\backslashes\\ and "quotes"  ',
                "OPENWAND_CLAUDE_SYSTEM_PROMPT": "'paired literal quotes'",
            }
            write_env_file(path, {**prompts, "CONFIG_TEST_VALUE": "${OPENWAND_QA_SET_VAR}",
                                  "PROMPT_REFERENCE": "${SYSTEM_PROMPT_UTILITY}"})
            original_path = config._ENV_FILE
            with patch.dict(os.environ, {"OPENWAND_QA_SET_VAR": "expanded"}), \
                    patch.object(settings_env, "ENV_PATH", path), \
                    patch.object(config, "_ENV_FILE", path):
                try:
                    settings_values = settings_env.read_settings_env()
                    for key, value in prompts.items():
                        self.assertEqual(settings_values[key], value)
                    self.assertEqual(settings_values["CONFIG_TEST_VALUE"], "expanded")
                    self.assertEqual(settings_values["PROMPT_REFERENCE"], prompts["SYSTEM_PROMPT_UTILITY"])
                    config.reload()
                    self.assertEqual(config.SYSTEM_PROMPT_UTILITY, prompts["SYSTEM_PROMPT_UTILITY"])
                    self.assertEqual(config.OPENWAND_CODEX_SYSTEM_PROMPT, prompts["OPENWAND_CODEX_SYSTEM_PROMPT"])
                    self.assertEqual(config.OPENWAND_CLAUDE_SYSTEM_PROMPT, prompts["OPENWAND_CLAUDE_SYSTEM_PROMPT"])
                    self.assertEqual(os.environ["SYSTEM_PROMPT_UTILITY"], prompts["SYSTEM_PROMPT_UTILITY"])
                finally:
                    config._ENV_FILE = original_path
                    config.reload()


if __name__ == "__main__":
    unittest.main()
