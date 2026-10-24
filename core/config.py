"""Settings from .env plus config/*.yaml. Import `settings`, `isos`, `jobs`, `policy` everywhere.
Nothing operational is hardcoded here: every threshold, owner, location and model name lives in
config/ or .env."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

CONFIG_DIR = Path(os.getenv("CONFIG_DIR", "config"))


class Settings(BaseModel):
    iso: str = os.getenv("ISO", "CAISO")
    location: str = os.getenv("LOCATION", "")
    policy_name: str = os.getenv("POLICY", "dispatcher")  # dispatcher | baseline
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8080"))
    public_url: str = os.getenv("PUBLIC_URL", "http://localhost:8080")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "")
    azure_project_endpoint: str = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "")
    azure_model_deployment: str = os.getenv("AZURE_MODEL_DEPLOYMENT", "")
    azure_cs_endpoint: str = os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT", "")
    azure_cs_key: str = os.getenv("AZURE_CONTENT_SAFETY_KEY", "")
    appinsights: str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    slack_bot_token: str = os.getenv("SLACK_BOT_TOKEN", "")
    slack_app_token: str = os.getenv("SLACK_APP_TOKEN", "")
    pjm_api_key: str = os.getenv("PJM_API_KEY", "")
    calibration_path: str = os.getenv("CALIBRATION_PATH", "runs/calibration.json")

    @property
    def use_azure_agent(self) -> bool:
        return bool(self.azure_project_endpoint)


def _load(name: str) -> dict:
    p = CONFIG_DIR / name
    return yaml.safe_load(p.read_text()) if p.exists() else {}


settings = Settings()
isos: dict = _load("isos.yaml")
jobs: dict = _load("jobs.yaml")
policy: dict = _load("policy.yaml")
site: dict = _load("site.yaml")


def available_isos() -> list[str]:
    """ISOs the UI may offer: every configured one, minus PJM when it has no API key."""
    names = list(isos.get("isos", {}))
    if not settings.pjm_api_key:
        names = [n for n in names if n != "PJM"]
    return names
