from pathlib import Path
import unittest


class MineruDockerRuntimeConfigTestCase(unittest.TestCase):
    def test_docker_runtime_pins_model_tree_hash_inputs(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        install_script = (repo_root / "backend" / "scripts" / "install-mineru-runtime.sh").read_text(encoding="utf-8")
        compose_file = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
        env_example = (repo_root / ".env.example").read_text(encoding="utf-8")

        self.assertIn("MINERU_BUILD_MODEL_TREE_SHA256", install_script)
        self.assertIn("MINERU_BUILD_MODEL_TREE_SHA256", compose_file)
        self.assertIn("EMATA_MINERU_DOCKER_MODEL_TREE_SHA256", env_example)


if __name__ == "__main__":
    unittest.main()
