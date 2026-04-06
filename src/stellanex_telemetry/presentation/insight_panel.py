from __future__ import annotations

from dataclasses import dataclass

from stellanex_telemetry.application import (
    InsightNarrative,
    OperatorRecommendation,
    StationInsightReport,
)


@dataclass(frozen=True, slots=True)
class InsightNarrativeViewModel:
    title: str
    detail: str
    tone: str


@dataclass(frozen=True, slots=True)
class RecommendationItemViewModel:
    title: str
    detail: str
    priority_label: str
    tone: str


@dataclass(frozen=True, slots=True)
class StationInsightPanelViewModel:
    summary_title: str
    summary_body: str
    summary_tone: str
    narratives: tuple[InsightNarrativeViewModel, ...]
    recommendations: tuple[RecommendationItemViewModel, ...]


def build_station_insight_panel_view_model(report: StationInsightReport) -> StationInsightPanelViewModel:
    return StationInsightPanelViewModel(
        summary_title=report.summary_title,
        summary_body=report.summary_body,
        summary_tone=report.summary_tone,
        narratives=tuple(_build_narrative_view_model(item) for item in report.narratives),
        recommendations=tuple(_build_recommendation_view_model(item) for item in report.recommendations),
    )


def _build_narrative_view_model(item: InsightNarrative) -> InsightNarrativeViewModel:
    return InsightNarrativeViewModel(
        title=item.title,
        detail=item.detail,
        tone=item.tone,
    )


def _build_recommendation_view_model(item: OperatorRecommendation) -> RecommendationItemViewModel:
    return RecommendationItemViewModel(
        title=item.title,
        detail=item.detail,
        priority_label=item.priority_label,
        tone=item.tone,
    )
