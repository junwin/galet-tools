"""The standalone example is an executable integration check for both handlers."""

from pathlib import Path
import runpy


def test_episodic_and_curation_example():
    example = Path(__file__).resolve().parents[1] / "examples" / "curate_chat.py"
    runpy.run_path(str(example), run_name="__main__")



def test_procedural_and_invalidation_example():
    example = Path(__file__).resolve().parents[1] / "examples" / "memory_tools.py"
    runpy.run_path(str(example), run_name="__main__")
