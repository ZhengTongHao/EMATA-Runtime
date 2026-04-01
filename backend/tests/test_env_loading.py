import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("EMATA_DATABASE_URL", "sqlite:///:memory:")

import app.main as main_module
from app.main import _load_env_file, _load_project_env_files


class EnvLoadingTestCase(unittest.TestCase):
    def test_load_env_file_populates_missing_keys_and_keeps_existing_values(self) -> None:
        with tempfile.TemporaryDirectory(prefix="emata-env-") as tempdir:
            env_path = Path(tempdir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "EMATA_LARK_APP_ID=from_file",
                        "EMATA_LARK_APP_SECRET=\"quoted-secret\"",
                        "# comment should be ignored",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"EMATA_LARK_APP_ID": "from_env"}, clear=True):
                _load_env_file(env_path)

                self.assertEqual(os.environ["EMATA_LARK_APP_ID"], "from_env")
                self.assertEqual(os.environ["EMATA_LARK_APP_SECRET"], "quoted-secret")

    def test_load_project_env_files_prefers_dotenv_over_example_but_preserves_process_env(self) -> None:
        with tempfile.TemporaryDirectory(prefix="emata-project-env-") as tempdir:
            project_root = Path(tempdir)
            (project_root / ".env.example").write_text(
                "\n".join(
                    [
                        "EMATA_DATABASE_URL=postgresql+psycopg://emata:emata@postgres:5432/emata",
                        "EMATA_STORAGE_BACKEND=minio",
                    ]
                ),
                encoding="utf-8",
            )
            (project_root / ".env").write_text(
                "\n".join(
                    [
                        "EMATA_DATABASE_URL=sqlite:///./emata.db",
                        "EMATA_STORAGE_BACKEND=filesystem",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"EMATA_UPLOAD_BASE_DIR": "from_process_env"}, clear=True):
                with patch.object(main_module, "PROJECT_ROOT", project_root):
                    _load_project_env_files()

                self.assertEqual(os.environ["EMATA_DATABASE_URL"], "sqlite:///./emata.db")
                self.assertEqual(os.environ["EMATA_STORAGE_BACKEND"], "filesystem")
                self.assertEqual(os.environ["EMATA_UPLOAD_BASE_DIR"], "from_process_env")


if __name__ == "__main__":
    unittest.main()
