"""T2 constraint checker template — copy this into any project's scripts/ directory.

Usage:
    python3 scripts/check_constraints.py              # check current branch vs main
    python3 scripts/check_constraints.py --staged     # check staged changes only

Customization:
    1. Copy this file to your project as scripts/check_constraints.py
    2. Add project-specific rules to PROJECT_LLM_GROUPS below
    3. Adjust BASE_BRANCH if your default branch isn't 'main'
"""

import subprocess
import sys

# ---------------------------------------------------------------------------
# Import T1 (agency-level) rules from ~/Code/scripts/
# ---------------------------------------------------------------------------

sys.path.insert(0, "/Users/adam1/Code")

from scripts.t1_llm_constraint_rules import T1_LLM_PROMPT_GROUPS  # noqa: E402

try:
    from scripts.constraint_engine.llm_checker import PromptGroup, check_diff_with_llm
except ImportError:
    from constraint_engine.llm_checker import PromptGroup, check_diff_with_llm

# ---------------------------------------------------------------------------
# Project-specific rules (add yours here)
# ---------------------------------------------------------------------------
# Example:
#   from constraint_engine.llm_checker import PromptGroup
#   PROJECT_LLM_GROUPS: tuple[PromptGroup, ...] = (
#       PromptGroup(
#           id="P-A",
#           name="My Project Rules",
#           system_context="Reviewing Django code changes.",
#           rules=("P-001 [No direct main commits]: ...",),
#           file_prefixes=("apps/",),
#       ),
#   )

PROJECT_LLM_GROUPS: tuple[PromptGroup, ...] = ()

# Combined rules: T1 (shared) + project-specific
ALL_LLM_GROUPS: tuple[PromptGroup, ...] = T1_LLM_PROMPT_GROUPS + PROJECT_LLM_GROUPS

BASE_BRANCH = "main"

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def get_diff(staged: bool = False) -> str:
    if staged:
        result = subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True)
    else:
        result = subprocess.run(["git", "diff", BASE_BRANCH, "HEAD"], capture_output=True, text=True)
    return result.stdout


def main() -> None:
    staged = "--staged" in sys.argv
    diff = get_diff(staged=staged)

    if not diff.strip():
        print("No changes to check.")
        return

    violations, metadata = check_diff_with_llm(diff, ALL_LLM_GROUPS)

    if not violations:
        print("No violations found.")
        return

    for v in violations:
        print(f"FAIL   [{v.group}] Rule {v.rule_num}: {v.file}")
        print(f"       {v.explanation}")
        print()

    sys.exit(1)


if __name__ == "__main__":
    main()
