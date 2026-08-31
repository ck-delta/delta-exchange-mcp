import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
ARTIFACTS = ("delta-exchange-mcp-qna.md", "delta-exchange-mcp-qna.jsonl")


def test_generated_finetune_artifacts_match_source(tmp_path: Path) -> None:
    source = ROOT / "finetune"
    shutil.copyfile(source / "generate_qna.py", tmp_path / "generate_qna.py")

    subprocess.run(
        [sys.executable, str(tmp_path / "generate_qna.py")],
        check=True,
        capture_output=True,
        text=True,
    )

    for name in ARTIFACTS:
        assert (tmp_path / name).read_bytes() == (source / name).read_bytes()
