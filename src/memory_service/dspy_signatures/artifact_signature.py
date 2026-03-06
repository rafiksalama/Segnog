"""
DSPy Signature for Artifact Extraction

Post-mission: extract artifact entries (files, downloads, reports, datasets, code)
from completed mission data. Used by curation pipeline to populate the artifact registry.
"""

from typing import List
from pydantic import BaseModel, Field

import dspy


class ArtifactEntryModel(BaseModel):
    """A single extracted artifact entry."""
    name: str = Field(
        description="Filename or short identifier. Examples: 'report.pdf', "
                    "'search_results.json', 'analysis_output.md'. Keep concise."
    )
    artifact_type: str = Field(
        description="One of: 'file' (general saved file), 'download' (fetched from web), "
                    "'report' (generated analysis/report), 'dataset' (extracted/compiled data), "
                    "'code' (generated code/script)"
    )
    path: str = Field(
        description="File system path or URL where the artifact exists. "
                    "Extract from tool outputs (write-file paths, download URLs, etc). "
                    "If no explicit path found, use the best available identifier."
    )
    description: str = Field(
        description="What this artifact contains and why it was created. "
                    "1-3 sentences, specific and self-contained. Include key details "
                    "like data format, row counts, topics covered."
    )
    labels: List[str] = Field(
        description="3-7 semantic labels for retrieval. Lowercase, hyphenated. "
                    "Include: content topic ('financial-analysis'), format ('pdf', 'csv'), "
                    "domain ('machine-learning'), tool used ('web-search'), "
                    "artifact kind ('report', 'dataset'). "
                    "Be specific: 'stock-price-data' not just 'data'."
    )
    reasoning: str = Field(
        description="Brief explanation of how this artifact was identified in the "
                    "mission data. 1 sentence."
    )


class ArtifactExtractionResult(BaseModel):
    """Structured result from artifact extraction."""
    entries: List[ArtifactEntryModel] = Field(
        description="Extracted artifact entries. Only include TANGIBLE outputs: "
                    "files saved to disk, content downloaded, reports generated, "
                    "datasets compiled. Do NOT include ephemeral tool outputs or "
                    "intermediate reasoning. If no artifacts were produced, return "
                    "an empty list."
    )


class ArtifactExtractionSignature(dspy.Signature):
    """You are an artifact extraction specialist. Your job is to identify all tangible
    outputs produced during a completed mission -- files created, content downloaded,
    reports generated, datasets compiled, code written to disk.

    Focus on TANGIBLE, PERSISTENT outputs only:
    - Files saved via write-file or similar tools
    - Content downloaded from URLs and saved locally
    - Reports or analyses produced as the mission's deliverable
    - Datasets extracted, compiled, or transformed
    - Code files generated or modified

    Do NOT include:
    - Ephemeral search results (unless explicitly saved to a file)
    - Intermediate reasoning or chain-of-thought
    - Tool outputs that were only displayed, not saved
    - The agent's final text response (that's the output, not an artifact)

    If the mission produced NO tangible artifacts (e.g., it was a pure Q&A task),
    return an empty entries list.
    """

    mission_task: str = dspy.InputField(
        desc="The original task/question the agent was asked to accomplish"
    )
    mission_outcome: str = dspy.InputField(
        desc="Mission status ('success' or 'max_iterations') and iteration count"
    )
    execution_trace: str = dspy.InputField(
        desc="Complete execution trace: all tool calls with their full outputs, "
             "file operations, downloads, and any file paths mentioned"
    )
    plan_execution: str = dspy.InputField(
        desc="The execution plan with status of each step"
    )
    full_report: str = dspy.InputField(
        desc="The agent's complete final output/report"
    )

    extraction: ArtifactExtractionResult = dspy.OutputField(
        desc="List of tangible artifacts produced during the mission"
    )
