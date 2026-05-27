from __future__ import annotations

import unittest
from pathlib import Path


class DeploymentArtifactTests(unittest.TestCase):
    def test_docker_and_env_artifacts_exist(self) -> None:
        dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
        compose = Path("docker-compose.yml").read_text(encoding="utf-8")
        env_example = Path(".env.example").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")
        requirements = Path("requirements.txt").read_text(encoding="utf-8")
        workflow = Path(".github/workflows/deploy-ecs.yml").read_text(encoding="utf-8")
        docker_smoke_sh = Path("scripts/docker-smoke.sh").read_text(encoding="utf-8")
        docker_smoke_ps1 = Path("scripts/docker-smoke.ps1").read_text(encoding="utf-8")

        self.assertIn("uvicorn", dockerfile)
        self.assertIn("requirements.txt", dockerfile)
        self.assertIn("pip install --no-cache-dir -r requirements.txt", dockerfile)
        self.assertIn("meme_collector_data", compose)
        self.assertIn("OPENAI_API_KEY", env_example)
        self.assertIn("OPENAI_BASE_URL", env_example)
        self.assertNotIn("TAVILY_API_KEY", env_example)
        self.assertIn("openai-agents", requirements)
        self.assertIn("Backup and restore", readme)
        self.assertIn("Linux ECS notes", readme)
        self.assertIn("GitHub Actions ECS deployment", readme)
        self.assertIn("git pull --ff-only", workflow)
        self.assertIn("docker compose up --build -d", workflow)
        self.assertIn("docker compose -p", docker_smoke_sh)
        self.assertIn("curl -fsS", docker_smoke_sh)
        self.assertIn("meme_collector.sqlite3", docker_smoke_sh)
        self.assertIn("docker compose -p", docker_smoke_ps1)
        self.assertIn("Invoke-WebRequest", docker_smoke_ps1)


if __name__ == "__main__":
    unittest.main()
