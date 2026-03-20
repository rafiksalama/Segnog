"""Pipeline configuration registry — feature flags for the observe pipeline."""

from dataclasses import dataclass

from ..config import (
    get_pipeline_extract_knowledge,
    get_pipeline_hebbian_reinforcement,
    get_pipeline_hydrate_ontology,
    get_pipeline_judge_observation,
    get_pipeline_reinterpret_on_cold_start,
)


@dataclass
class PipelineConfig:
    extract_knowledge: bool = True
    hebbian_reinforcement: bool = True
    judge_observation: bool = True
    reinterpret_on_cold_start: bool = True
    hydrate_ontology: bool = True


def load_pipeline_config() -> PipelineConfig:
    """Load pipeline feature flags from settings."""
    return PipelineConfig(
        extract_knowledge=get_pipeline_extract_knowledge(),
        hebbian_reinforcement=get_pipeline_hebbian_reinforcement(),
        judge_observation=get_pipeline_judge_observation(),
        reinterpret_on_cold_start=get_pipeline_reinterpret_on_cold_start(),
        hydrate_ontology=get_pipeline_hydrate_ontology(),
    )
