"""Skills system — load task-type-specific behavioural instructions from Markdown (SAD v10 §12)."""

from .loader import load_skill, load_skills

__all__ = ["load_skill", "load_skills"]
