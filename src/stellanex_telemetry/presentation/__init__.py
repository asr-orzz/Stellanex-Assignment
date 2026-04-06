"""Presentation layer for desktop UI and future view models."""

from stellanex_telemetry.presentation.alert_inbox import (
    AlertInboxItemViewModel,
    AlertInboxSummaryViewModel,
    AlertInboxViewModel,
    build_alert_inbox_view_model,
)
from stellanex_telemetry.presentation.history_charts import (
    HistoryChartPointViewModel,
    MetricHistoryChartViewModel,
    StationHistoryDashboardViewModel,
    build_station_history_dashboard_view_model,
)
from stellanex_telemetry.presentation.insight_panel import (
    InsightNarrativeViewModel,
    RecommendationItemViewModel,
    StationInsightPanelViewModel,
    build_station_insight_panel_view_model,
)
from stellanex_telemetry.presentation.shell import (
    DesktopShellContext,
    TelemetryDesktopShell,
    create_desktop_shell,
    launch_desktop_shell,
)
from stellanex_telemetry.presentation.station_explorer import (
    StationExplorerRowViewModel,
    StationExplorerViewModel,
    build_station_explorer_view_model,
    filter_station_explorer_rows,
    sort_station_explorer_rows,
)
from stellanex_telemetry.presentation.theme import DesktopTheme, build_desktop_theme
from stellanex_telemetry.presentation.view_models import (
    AlertItemViewModel,
    FleetKpiViewModel,
    FleetOverviewViewModel,
    KeyValueRowViewModel,
    MetricCardViewModel,
    PriorityStationViewModel,
    RegionHealthViewModel,
    StationDetailViewModel,
    StationHeaderViewModel,
    TelemetryPointViewModel,
    build_fleet_overview_view_model,
    build_station_detail_view_model,
)

__all__ = [
    "AlertItemViewModel",
    "AlertInboxItemViewModel",
    "AlertInboxSummaryViewModel",
    "AlertInboxViewModel",
    "DesktopShellContext",
    "DesktopTheme",
    "FleetKpiViewModel",
    "FleetOverviewViewModel",
    "HistoryChartPointViewModel",
    "InsightNarrativeViewModel",
    "KeyValueRowViewModel",
    "MetricHistoryChartViewModel",
    "MetricCardViewModel",
    "PriorityStationViewModel",
    "RecommendationItemViewModel",
    "RegionHealthViewModel",
    "StationExplorerRowViewModel",
    "StationExplorerViewModel",
    "StationDetailViewModel",
    "StationHistoryDashboardViewModel",
    "StationInsightPanelViewModel",
    "StationHeaderViewModel",
    "TelemetryDesktopShell",
    "TelemetryPointViewModel",
    "build_alert_inbox_view_model",
    "build_station_explorer_view_model",
    "build_desktop_theme",
    "build_fleet_overview_view_model",
    "build_station_history_dashboard_view_model",
    "build_station_insight_panel_view_model",
    "build_station_detail_view_model",
    "create_desktop_shell",
    "filter_station_explorer_rows",
    "launch_desktop_shell",
    "sort_station_explorer_rows",
]
