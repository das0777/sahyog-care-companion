"""Put a model API key in .env without it appearing on screen or in shell history."""

import getpass
import os
import re
from pathlib import Path

PROVIDERS = {
    "sk-or-": ("openrouter", "OPENROUTER_API_KEY"),
    "sk-ant-": ("anthropic", "ANTHROPIC_API_KEY"),
}

env = Path(".env")
key = getpass.getpass("Paste your API key (nothing will show), then press Enter: ").strip()
match = next((v for prefix, v in PROVIDERS.items() if key.startswith(prefix)), None)
if match is None:
    raise SystemExit("Expected a key starting sk-or- or sk-ant-; .env is unchanged.")
provider, name = match
text = env.read_text()
for var, value in ((name, key), ("LLM_PROVIDER", provider)):
    line = f"{var}={value}"
    text, found = re.subn(rf"^{var}=.*$", lambda _, line=line: line, text, flags=re.M)
    if not found:
        text = text.rstrip("\n") + f"\n{line}\n"
env.write_text(text)
os.chmod(env, 0o600)
print(f"Saved to .env for {provider}.")
