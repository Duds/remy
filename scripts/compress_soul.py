#!/usr/bin/env python3
"""
Compress SOUL.md into a more token-efficient SOUL.compact.md format.

Usage:
    python scripts/compress_soul.py [input_path] [output_path]

Defaults:
    input:  config/SOUL.md
    output: config/SOUL.compact.md

The script:
1. Reads the verbose SOUL.md
2. Applies compression rules (strip redundancy, condense sections)
3. Outputs a compact version
4. Reports token count before/after
5. Validates key sections are preserved
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from remy.utils.tokens import estimate_tokens


def compress_soul(content: str) -> str:
    """
    Apply compression rules to SOUL.md content.

    Rules:
    - Remove horizontal rules (---)
    - Condense multi-line explanations to single lines
    - Remove redundant headers like "## Setup Instructions"
    - Convert verbose bullet lists to inline bullet points
    - Strip excessive whitespace
    """
    lines = content.split("\n")
    output_lines = []
    skip_section = False
    in_list = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip horizontal rules
        if stripped == "---":
            continue

        # Skip setup instructions section (meta, not needed at runtime)
        if stripped.startswith("## Setup Instructions"):
            skip_section = True
            continue
        if skip_section and stripped.startswith("## "):
            skip_section = False
        if skip_section:
            continue

        # Condense "Consider:" style prompts
        if stripped.startswith("Define your agent's personality here. Consider:"):
            continue
        if stripped.startswith("- **") and "—" in stripped:
            # These are definition prompts, skip them
            if any(x in stripped for x in ["Tone —", "Directness —", "Wit —", "Opinions —", "Sycophancy —"]):
                continue

        # Condense verbose capability descriptions
        if stripped.startswith("- **") and " — " in stripped:
            # Convert "- **Email** — triaging, filtering..." to "Email triage"
            match = re.match(r"- \*\*(\w+)\*\* — (.+)", stripped)
            if match:
                capability = match.group(1)
                desc = match.group(2)
                # Keep first few words of description
                short_desc = " ".join(desc.split()[:3]).rstrip(".,")
                output_lines.append(f"- {capability}: {short_desc}")
                continue

        # Remove "What do you call the user?" prompts
        if "What do you call the user?" in stripped:
            continue
        if "A few examples to calibrate the voice:" in stripped:
            continue

        # Condense safety limits headers
        if stripped == "### What the Agent CANNOT Do":
            output_lines.append("No:")
            continue
        if stripped == "### What the Agent WILL Tell You":
            output_lines.append("Yes:")
            continue

        # Remove verbose explanations in parentheses at end of sections
        if stripped.startswith("(e.g.") or stripped.startswith("(timezone:"):
            continue

        # Keep the line
        output_lines.append(line)

    # Join and clean up excessive blank lines
    result = "\n".join(output_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def validate_sections(original: str, compressed: str) -> list[str]:
    """
    Validate that key sections are preserved in the compressed version.
    Returns a list of warnings for missing sections.
    """
    required_patterns = [
        (r"#.*[Nn]ame", "Agent name/identity"),
        (r"[Pp]ersonality|[Vv]oice|[Tt]one", "Personality/voice section"),
        (r"[Pp]rinciples?|[Oo]perating", "Operating principles"),
        (r"[Cc]ommands?|/help", "Commands list"),
        (r"[Ll]imits?|[Ss]afety|CANNOT", "Safety limits"),
        (r"[Tt]elegram|[Mm]arkdown", "Telegram formatting"),
    ]

    warnings = []
    for pattern, description in required_patterns:
        if not re.search(pattern, compressed, re.IGNORECASE):
            if re.search(pattern, original, re.IGNORECASE):
                warnings.append(f"Missing section: {description}")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Compress SOUL.md into a token-efficient format"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="config/SOUL.md",
        help="Input SOUL.md path (default: config/SOUL.md)",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default="config/SOUL.compact.md",
        help="Output path (default: config/SOUL.compact.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print compressed output without writing file",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    original = input_path.read_text(encoding="utf-8")
    compressed = compress_soul(original)

    # Token counts
    original_tokens = estimate_tokens(original)
    compressed_tokens = estimate_tokens(compressed)
    savings = original_tokens - compressed_tokens
    savings_pct = (savings / original_tokens * 100) if original_tokens > 0 else 0

    print(f"Original:   {original_tokens:,} tokens ({len(original):,} chars)")
    print(f"Compressed: {compressed_tokens:,} tokens ({len(compressed):,} chars)")
    print(f"Savings:    {savings:,} tokens ({savings_pct:.1f}%)")
    print()

    # Validation
    warnings = validate_sections(original, compressed)
    if warnings:
        print("Warnings:")
        for w in warnings:
            print(f"  ⚠️  {w}")
        print()

    if args.dry_run:
        print("--- Compressed output ---")
        print(compressed)
        print("--- End ---")
    else:
        output_path.write_text(compressed, encoding="utf-8")
        print(f"Written to: {output_path}")


if __name__ == "__main__":
    main()
