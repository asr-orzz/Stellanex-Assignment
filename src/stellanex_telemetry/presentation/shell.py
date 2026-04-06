from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from stellanex_telemetry.application import (
    DatasetDescriptor,
    DatasetImportReport,
    DatasetRuntime,
    DatasetWorkspace,
    FleetHealthAggregator,
    FleetHealthSnapshot,
    OperatorInsightService,
    StationDetailResult,
    StationDetailQuery,
    StationDetailQueryService,
    TelemetryQuery,
    ThresholdAlertPolicyEngine,
    TelemetryAnomalyDetector,
)
from stellanex_telemetry.application.contracts import StationRepository, TelemetryRepository
from stellanex_telemetry.config import AppConfig
from stellanex_telemetry.presentation.alert_inbox import (
    AlertInboxItemViewModel,
    AlertInboxSummaryViewModel,
    build_alert_inbox_view_model,
)
from stellanex_telemetry.presentation.history_charts import (
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
from stellanex_telemetry.presentation.station_explorer import (
    StationExplorerRowViewModel,
    build_station_explorer_view_model,
    filter_station_explorer_rows,
    sort_station_explorer_rows,
)
from stellanex_telemetry.presentation.theme import DesktopTheme, build_desktop_theme
from stellanex_telemetry.presentation.view_models import (
    FleetKpiViewModel,
    FleetOverviewViewModel,
    PriorityStationViewModel,
    RegionHealthViewModel,
    build_fleet_overview_view_model,
)


@dataclass(frozen=True, slots=True)
class DesktopShellContext:
    config: AppConfig
    dataset_workspace: DatasetWorkspace
    active_dataset_key: str
    station_repository: StationRepository
    telemetry_repository: TelemetryRepository
    alert_engine: ThresholdAlertPolicyEngine
    anomaly_detector: TelemetryAnomalyDetector
    health_aggregator: FleetHealthAggregator
    insight_service: OperatorInsightService
    station_detail_service: StationDetailQueryService


class TelemetryDesktopShell(tk.Tk):
    """Desktop shell scaffold for the operator console."""

    def __init__(self, context: DesktopShellContext, *, theme: DesktopTheme | None = None) -> None:
        super().__init__()
        self._context = context
        self._theme = theme or build_desktop_theme()
        self._theme.apply_window(self)
        self._station_repository = context.station_repository
        self._telemetry_repository = context.telemetry_repository
        self._current_dataset_descriptor = _resolve_dataset_descriptor(
            context.dataset_workspace.list_datasets(),
            context.active_dataset_key,
        )
        self._dataset_catalog = tuple(context.dataset_workspace.list_datasets())
        self._last_import_report: DatasetImportReport | None = None
        self._dataset_status_message = ""
        self._dataset_selector_var = tk.StringVar(self, context.active_dataset_key)
        self._dataset_status_var = tk.StringVar(self, "")
        self._dataset_selector_updating = False
        self._section_hosts: dict[str, tk.Misc] = {}
        self._signal_canvas: tk.Canvas | None = None
        self._explorer_tree: ttk.Treeview | None = None
        self._dataset_selector: ttk.Combobox | None = None
        self._explorer_preview_host: tk.Frame | None = None
        self._history_content_canvas: tk.Canvas | None = None
        self._history_content_frame: tk.Frame | None = None
        self._history_content_window_id: int | None = None
        self._history_dashboard_host: tk.Frame | None = None
        self._explorer_summary_label: tk.Label | None = None
        self._explorer_sort_label: tk.Label | None = None
        self._dataset_summary_label: tk.Label | None = None
        self._dataset_runtime_label: tk.Label | None = None
        self._dataset_actions_label: tk.Label | None = None
        self._explorer_rows_by_id: dict[str, StationExplorerRowViewModel] = {}
        self._station_detail_cache: dict[str, StationDetailResult] = {}
        self._station_history_cache: dict[str, StationHistoryDashboardViewModel] = {}
        self._station_insight_cache: dict[str, StationInsightPanelViewModel] = {}
        self._explorer_selected_station_id: str | None = None
        self._explorer_sort_key = "priority"
        self._explorer_sort_descending = False
        self._explorer_search_var = tk.StringVar(self, "")
        self._explorer_region_var = tk.StringVar(self, "All regions")
        self._explorer_status_var = tk.StringVar(self, "All statuses")
        self._explorer_priority_only_var = tk.BooleanVar(self, False)
        self._reference_time = datetime.now(timezone.utc)
        self._fleet_snapshot = FleetHealthSnapshot(
            generated_at=self._reference_time,
            station_snapshots=(),
            region_snapshots=(),
            fleet_health_score=0.0,
            active_alerts=(),
            total_stations=0,
            healthy_stations=0,
            warning_stations=0,
            critical_stations=0,
            maintenance_stations=0,
            offline_stations=0,
        )
        self._anomaly_alerts: tuple[object, ...] = ()
        self._overview_view_model = build_fleet_overview_view_model(self._fleet_snapshot)
        self._alert_inbox_view_model = build_alert_inbox_view_model(self._fleet_snapshot)
        self._station_explorer_view_model = build_station_explorer_view_model(self._fleet_snapshot)

        self.title(context.config.app_name)
        self.geometry("1460x920")
        self.minsize(1240, 820)

        self._configure_ttk_styles()
        self._bind_station_explorer_state()
        self._bind_dataset_controls()
        self._reload_runtime_models()
        self._build_shell()
        self.bind("<Configure>", self._on_resize)

    @property
    def fleet_snapshot(self) -> FleetHealthSnapshot:
        return self._fleet_snapshot

    def _configure_ttk_styles(self) -> None:
        theme = self._theme
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure(
            "Telemetry.Treeview",
            background=theme.palette.surface,
            fieldbackground=theme.palette.surface,
            foreground=theme.palette.text_primary,
            bordercolor=theme.palette.border,
            borderwidth=0,
            rowheight=30,
            relief="flat",
            font=theme.typography.body,
        )
        style.map(
            "Telemetry.Treeview",
            background=[("selected", theme.palette.accent_soft)],
            foreground=[("selected", theme.palette.text_primary)],
        )
        style.configure(
            "Telemetry.Treeview.Heading",
            background=theme.palette.surface_alt,
            foreground=theme.palette.text_primary,
            bordercolor=theme.palette.border,
            relief="flat",
            font=theme.typography.body_strong,
            padding=(10, 8),
        )
        style.map(
            "Telemetry.Treeview.Heading",
            background=[("active", theme.palette.accent_soft)],
        )
        style.configure(
            "Telemetry.Vertical.TScrollbar",
            background=theme.palette.surface_alt,
            troughcolor=theme.palette.surface,
            bordercolor=theme.palette.border,
            arrowcolor=theme.palette.text_primary,
            relief="flat",
        )
        style.configure(
            "Telemetry.TCombobox",
            fieldbackground=theme.palette.surface,
            background=theme.palette.surface,
            foreground=theme.palette.text_primary,
            bordercolor=theme.palette.border,
            lightcolor=theme.palette.border,
            darkcolor=theme.palette.border,
            arrowcolor=theme.palette.accent,
            relief="flat",
            padding=6,
        )
        style.map(
            "Telemetry.TCombobox",
            fieldbackground=[("readonly", theme.palette.surface)],
            selectbackground=[("readonly", theme.palette.accent_soft)],
            selectforeground=[("readonly", theme.palette.text_primary)],
        )

    def _bind_station_explorer_state(self) -> None:
        self._explorer_search_var.trace_add("write", self._on_station_explorer_filters_changed)
        self._explorer_region_var.trace_add("write", self._on_station_explorer_filters_changed)
        self._explorer_status_var.trace_add("write", self._on_station_explorer_filters_changed)
        self._explorer_priority_only_var.trace_add("write", self._on_station_explorer_filters_changed)

    def _bind_dataset_controls(self) -> None:
        self._dataset_selector_var.trace_add("write", self._on_dataset_selection_changed)

    def _on_dataset_selection_changed(self, *_: str) -> None:
        if self._dataset_selector_updating:
            return

        selected_key = self._dataset_selector_var.get().strip()
        if not selected_key:
            return
        if selected_key == self._current_dataset_descriptor.dataset_key:
            return

        try:
            self._load_dataset_runtime(selected_key)
        except (LookupError, RuntimeError) as exc:
            self._dataset_status_message = f"Dataset switch failed: {exc}"
            self._set_dataset_selector_value(self._current_dataset_descriptor.dataset_key)
            self._update_dataset_status_labels()
            return

        self._rebuild_shell()

    def _reload_runtime_models(self) -> None:
        self._reference_time = _resolve_reference_time(self._telemetry_repository)
        self._fleet_snapshot = self._context.health_aggregator.build_snapshot(
            self._station_repository,
            self._telemetry_repository,
            generated_at=self._reference_time,
        )
        self._anomaly_alerts = self._context.anomaly_detector.evaluate_latest(
            self._station_repository,
            self._telemetry_repository,
            generated_at=self._reference_time,
        )
        self._overview_view_model = build_fleet_overview_view_model(
            self._fleet_snapshot,
            anomaly_alerts=self._anomaly_alerts,
        )
        self._alert_inbox_view_model = build_alert_inbox_view_model(
            self._fleet_snapshot,
            anomaly_alerts=self._anomaly_alerts,
        )
        self._station_explorer_view_model = build_station_explorer_view_model(
            self._fleet_snapshot,
            anomaly_alerts=self._anomaly_alerts,
        )
        self._explorer_rows_by_id = {
            row.station_id: row for row in self._station_explorer_view_model.rows
        }
        if (
            self._explorer_selected_station_id is None
            or self._explorer_selected_station_id not in self._explorer_rows_by_id
        ):
            self._explorer_selected_station_id = (
                self._station_explorer_view_model.rows[0].station_id
                if self._station_explorer_view_model.rows
                else None
            )
        self._station_detail_cache.clear()
        self._station_history_cache.clear()
        self._station_insight_cache.clear()
        self._update_dataset_status_labels()

    def _refresh_dataset_catalog(self) -> None:
        self._dataset_catalog = tuple(self._context.dataset_workspace.refresh_catalog())
        self._current_dataset_descriptor = _resolve_dataset_descriptor(
            self._dataset_catalog,
            self._current_dataset_descriptor.dataset_key,
        )
        self._set_dataset_selector_value(self._current_dataset_descriptor.dataset_key)
        self._update_dataset_status_labels()

    def _load_dataset_runtime(
        self,
        dataset_key: str,
        *,
        status_message: str | None = None,
    ) -> None:
        runtime = self._context.dataset_workspace.load_dataset(dataset_key)
        self._apply_dataset_runtime(runtime, status_message=status_message)

    def _apply_dataset_runtime(
        self,
        runtime: DatasetRuntime,
        *,
        status_message: str | None = None,
    ) -> None:
        self._station_repository = runtime.station_repository
        self._telemetry_repository = runtime.telemetry_repository
        self._current_dataset_descriptor = runtime.descriptor
        self._set_dataset_selector_value(runtime.descriptor.dataset_key)
        self._dataset_status_message = (
            status_message
            or f"Loaded dataset '{runtime.descriptor.label}' with {_station_count(self._station_repository)} stations and {_reading_count(self._telemetry_repository)} readings."
        )
        self._reload_runtime_models()

    def _set_dataset_selector_value(self, dataset_key: str) -> None:
        if self._dataset_selector_var.get() == dataset_key:
            return
        self._dataset_selector_updating = True
        try:
            self._dataset_selector_var.set(dataset_key)
        finally:
            self._dataset_selector_updating = False

    def _refresh_active_dataset(self) -> None:
        current_descriptor = self._current_dataset_descriptor
        self._refresh_dataset_catalog()
        try:
            self._load_dataset_runtime(
                current_descriptor.dataset_key,
                status_message=(
                    f"Refreshed dataset '{self._current_dataset_descriptor.label}' from disk at "
                    f"{self._reference_time.strftime('%d %b %Y %H:%M UTC')}."
                ),
            )
        except (LookupError, RuntimeError) as exc:
            self._dataset_status_message = f"Refresh failed: {exc}"
            self._update_dataset_status_labels()
            return
        self._rebuild_shell()

    def _import_staged_datasets(self) -> None:
        try:
            report = self._context.dataset_workspace.import_available()
        except RuntimeError as exc:
            self._dataset_status_message = f"Import failed: {exc}"
            self._update_dataset_status_labels()
            return

        self._last_import_report = report
        self._refresh_dataset_catalog()
        self._dataset_status_message = _import_report_text(report)
        self._update_dataset_status_labels()
        self._rebuild_shell()

    def _update_dataset_status_labels(self) -> None:
        descriptor = self._current_dataset_descriptor
        summary_text = (
            f"{descriptor.label}\n"
            f"{_station_count(self._station_repository)} stations | "
            f"{_reading_count(self._telemetry_repository)} readings"
        )
        runtime_text = (
            f"Origin: {descriptor.origin.upper()} | Catalog: {len(self._dataset_catalog)} datasets\n"
            f"Updated: {_format_dataset_updated_at(descriptor)}"
        )
        action_text = self._dataset_status_message or _default_dataset_action_text(
            descriptor,
            imports_dir=self._context.config.paths.imports_dir,
        )
        self._dataset_status_var.set(action_text)

        if self._dataset_selector is not None:
            self._dataset_selector.configure(values=tuple(item.dataset_key for item in self._dataset_catalog))
        if self._dataset_summary_label is not None:
            self._dataset_summary_label.configure(text=summary_text)
        if self._dataset_runtime_label is not None:
            self._dataset_runtime_label.configure(text=runtime_text)
        if self._dataset_actions_label is not None:
            self._dataset_actions_label.configure(text=action_text)

    def _rebuild_shell(self) -> None:
        self._section_hosts = {}
        self._signal_canvas = None
        self._explorer_tree = None
        self._dataset_selector = None
        self._explorer_preview_host = None
        self._history_content_canvas = None
        self._history_content_frame = None
        self._history_content_window_id = None
        self._history_dashboard_host = None
        self._explorer_summary_label = None
        self._explorer_sort_label = None
        self._dataset_summary_label = None
        self._dataset_runtime_label = None
        self._dataset_actions_label = None
        for child in self.winfo_children():
            child.destroy()
        self._build_shell()

    def _build_shell(self) -> None:
        theme = self._theme
        spacing = theme.spacing

        root_frame = tk.Frame(self, bg=theme.palette.background)
        root_frame.pack(fill="both", expand=True, padx=spacing.lg, pady=spacing.lg)

        header = theme.panel(root_frame, tone="dark")
        header.pack(fill="x")
        self._build_header(header)

        body = tk.Frame(root_frame, bg=theme.palette.background)
        body.pack(fill="both", expand=True, pady=(spacing.lg, 0))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        rail = theme.panel(body, tone="surface_alt")
        rail.grid(row=0, column=0, sticky="ns", padx=(0, spacing.lg))
        rail.grid_propagate(False)
        rail.configure(width=250)
        self._build_navigation(rail)

        workspace = tk.Frame(body, bg=theme.palette.background)
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.grid_columnconfigure(0, weight=3)
        workspace.grid_columnconfigure(1, weight=2)
        workspace.grid_rowconfigure(0, weight=2)
        workspace.grid_rowconfigure(1, weight=3)
        self._build_workspace(workspace)

    def _build_header(self, master: tk.Frame) -> None:
        theme = self._theme
        spacing = theme.spacing

        content = tk.Frame(master, bg=theme.palette.surface_dark)
        content.pack(fill="both", expand=True, padx=spacing.lg, pady=spacing.lg)
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)

        left = tk.Frame(content, bg=theme.palette.surface_dark)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, spacing.lg))

        eyebrow_row = tk.Frame(left, bg=theme.palette.surface_dark)
        eyebrow_row.pack(anchor="w")
        theme.pill(
            eyebrow_row,
            text=f"LIVE {self._current_dataset_descriptor.origin.upper()} DATASET",
            tone="dark",
        ).pack(side="left", padx=(0, spacing.sm))
        theme.pill(
            eyebrow_row,
            text=f"CATALOG {len(self._dataset_catalog)} READY",
            tone="accent",
        ).pack(side="left", padx=(0, spacing.sm))
        theme.pill(eyebrow_row, text=f"REFERENCE {self._reference_time.strftime('%d %b %Y %H:%M UTC')}", tone="signal").pack(side="left")

        theme.label(
            left,
            text=self._context.config.app_name,
            role="hero_title",
            tone="dark",
            background=theme.palette.surface_dark,
        ).pack(anchor="w", pady=(spacing.sm, spacing.xs))
        theme.label(
            left,
            text=(
                "An operator-first desktop console for tracing fleet conditions, triaging station risk, "
                "and navigating industrial telemetry without reading raw log exports."
            ),
            role="body",
            tone="dark",
            background=theme.palette.surface_dark,
            wraplength=620,
        ).pack(anchor="w")
        theme.label(
            left,
            text=(
                f"Active dataset: {self._current_dataset_descriptor.label} | "
                f"{self._current_dataset_descriptor.description}"
            ),
            role="body_strong",
            tone="signal",
            background=theme.palette.surface_dark,
            wraplength=620,
        ).pack(anchor="w", pady=(spacing.sm, 0))

        stats = tk.Frame(left, bg=theme.palette.surface_dark)
        stats.pack(anchor="w", pady=(spacing.md, 0))
        self._build_stat_chip(stats, "Stations", str(_station_count(self._station_repository)))
        self._build_stat_chip(stats, "Telemetry", str(_reading_count(self._telemetry_repository)))
        self._build_stat_chip(stats, "Fleet Score", f"{self._fleet_snapshot.fleet_health_score:.2f}")
        self._build_stat_chip(stats, "Attention", str(self._fleet_snapshot.warning_stations + self._fleet_snapshot.critical_stations))

        right = tk.Frame(content, bg=theme.palette.surface_dark)
        right.grid(row=0, column=1, sticky="nsew")

        signal_shell = tk.Frame(right, bg=theme.palette.surface_dark)
        signal_shell.pack(fill="both", expand=True)

        stat_stack = tk.Frame(signal_shell, bg=theme.palette.surface_dark)
        stat_stack.pack(fill="x")

        self._build_signal_summary(
            stat_stack,
            title="Command Post",
            body=_command_post_text(self._fleet_snapshot, anomaly_count=len(self._anomaly_alerts)),
        )

        self._signal_canvas = tk.Canvas(signal_shell, height=92, highlightthickness=0, bd=0)
        self._signal_canvas.pack(fill="x", pady=(spacing.md, 0))
        self._theme.paint_signal_canvas(self._signal_canvas)

    def _build_navigation(self, master: tk.Frame) -> None:
        theme = self._theme
        spacing = theme.spacing

        content = tk.Frame(master, bg=theme.palette.surface_alt)
        content.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)

        theme.label(
            content,
            text="OPERATIONS FABRIC",
            role="caption",
            tone="accent",
            background=theme.palette.surface_alt,
        ).pack(anchor="w")
        theme.label(
            content,
            text="Shell Modules",
            role="section_title",
            tone="primary",
            background=theme.palette.surface_alt,
        ).pack(anchor="w", pady=(spacing.xs, spacing.md))

        for index, (label, selected) in enumerate(
            (
                ("Fleet Overview", True),
                ("Station Explorer", False),
                ("Alert Inbox", False),
                ("Trend Insights", False),
                ("Import Queue", False),
            )
        ):
            button = theme.nav_button(content, text=label, selected=selected)
            button.pack(fill="x", pady=(0, spacing.xs))
            if index == 0:
                self._section_hosts["nav_selected"] = button  # retained for future shell interactions

        theme.divider(content).pack(fill="x", pady=spacing.md)

        dataset_card = theme.panel(content, tone="surface")
        dataset_card.pack(fill="x")
        card_body = tk.Frame(dataset_card, bg=theme.palette.surface)
        card_body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)
        theme.label(
            card_body,
            text="Dataset Control",
            role="card_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w")
        self._dataset_summary_label = theme.label(
            card_body,
            text="",
            role="body_strong",
            tone="primary",
            background=theme.palette.surface,
            wraplength=180,
        )
        self._dataset_summary_label.pack(anchor="w", pady=(spacing.sm, 0))
        self._dataset_runtime_label = theme.label(
            card_body,
            text="",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
            wraplength=180,
        )
        self._dataset_runtime_label.pack(anchor="w", pady=(spacing.xs, 0))
        selector_shell = tk.Frame(card_body, bg=theme.palette.surface)
        selector_shell.pack(fill="x", pady=(spacing.md, 0))
        theme.label(
            selector_shell,
            text="Catalog Key",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(0, spacing.xs))
        self._dataset_selector = ttk.Combobox(
            selector_shell,
            textvariable=self._dataset_selector_var,
            values=tuple(item.dataset_key for item in self._dataset_catalog),
            state="readonly",
            style="Telemetry.TCombobox",
        )
        self._dataset_selector.pack(fill="x")
        action_row = tk.Frame(card_body, bg=theme.palette.surface)
        action_row.pack(fill="x", pady=(spacing.md, 0))
        tk.Button(
            action_row,
            text="Refresh Active",
            command=self._refresh_active_dataset,
            font=theme.typography.body_strong,
            fg=theme.palette.text_primary,
            bg=theme.palette.accent_soft,
            activeforeground=theme.palette.text_primary,
            activebackground=theme.palette.accent,
            relief="flat",
            bd=0,
            padx=spacing.sm,
            pady=spacing.sm,
            cursor="arrow",
        ).pack(side="left", padx=(0, spacing.xs))
        tk.Button(
            action_row,
            text="Import Staged",
            command=self._import_staged_datasets,
            font=theme.typography.body_strong,
            fg=theme.palette.text_on_dark,
            bg=theme.palette.surface_dark,
            activeforeground=theme.palette.text_on_dark,
            activebackground=theme.palette.accent,
            relief="flat",
            bd=0,
            padx=spacing.sm,
            pady=spacing.sm,
            cursor="arrow",
        ).pack(side="left")
        self._dataset_actions_label = theme.label(
            card_body,
            text="",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
            wraplength=180,
        )
        self._dataset_actions_label.pack(anchor="w", pady=(spacing.md, 0))
        theme.label(
            card_body,
            text=f"Demo path: {self._context.config.paths.demo_data_dir}",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
            wraplength=180,
        ).pack(anchor="w", pady=(spacing.xs, 0))
        theme.label(
            card_body,
            text=f"Runtime path: {self._context.config.paths.runtime_dir}",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
            wraplength=180,
        ).pack(anchor="w", pady=(spacing.xs, 0))
        theme.label(
            card_body,
            text=f"Imports path: {self._context.config.paths.imports_dir}",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
            wraplength=180,
        ).pack(anchor="w", pady=(spacing.xs, 0))
        self._update_dataset_status_labels()

        theme.divider(content).pack(fill="x", pady=spacing.md)
        theme.label(
            content,
            text="Live modules: overview, alert inbox, station explorer, trend charts, and dataset import controls.",
            role="body",
            tone="muted",
            background=theme.palette.surface_alt,
            wraplength=190,
        ).pack(anchor="w")

    def _build_workspace(self, master: tk.Frame) -> None:
        theme = self._theme
        spacing = theme.spacing

        overview_host = self._build_overview_panel(master)
        overview_host.grid(row=0, column=0, sticky="nsew", padx=(0, spacing.md), pady=(0, spacing.md))
        self._section_hosts["overview"] = overview_host

        inbox_host = self._build_alert_inbox_panel(master)
        inbox_host.grid(row=0, column=1, sticky="nsew", pady=(0, spacing.md))
        self._section_hosts["alerts"] = inbox_host

        explorer_host = self._build_station_explorer_panel(master)
        explorer_host.grid(row=1, column=0, sticky="nsew", padx=(0, spacing.md))
        self._section_hosts["explorer"] = explorer_host

        insight_host = self._build_history_dashboard_panel(master)
        insight_host.grid(row=1, column=1, sticky="nsew")
        self._section_hosts["insights"] = insight_host

    def _build_overview_panel(self, master: tk.Misc) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing
        view_model = self._overview_view_model

        panel = theme.panel(master, tone="surface")
        body = tk.Frame(panel, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.lg, pady=spacing.lg)

        header = tk.Frame(body, bg=theme.palette.surface)
        header.pack(fill="x")
        pills = tk.Frame(header, bg=theme.palette.surface)
        pills.pack(anchor="w")
        theme.pill(pills, text="STAGE 1 LIVE", tone="signal").pack(side="left", padx=(0, spacing.sm))
        theme.pill(pills, text=f"REFERENCE {view_model.reference_time_text}", tone="accent").pack(side="left")
        theme.label(
            header,
            text="Fleet Overview Workbench",
            role="section_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.sm, spacing.xs))
        theme.label(
            header,
            text=view_model.summary_text,
            role="body",
            tone="muted",
            background=theme.palette.surface,
            wraplength=760,
        ).pack(anchor="w")

        theme.divider(body, tone="soft").pack(fill="x", pady=spacing.md)

        kpi_grid = tk.Frame(body, bg=theme.palette.surface)
        kpi_grid.pack(fill="x")
        for index, card_view in enumerate(view_model.kpi_cards):
            kpi_grid.grid_columnconfigure(index, weight=1)
            card = self._build_overview_kpi_card(kpi_grid, card_view)
            card.grid(row=0, column=index, sticky="nsew", padx=(0, spacing.sm if index < len(view_model.kpi_cards) - 1 else 0))

        lower = tk.Frame(body, bg=theme.palette.surface)
        lower.pack(fill="both", expand=True, pady=(spacing.md, 0))
        lower.grid_columnconfigure(0, weight=2)
        lower.grid_columnconfigure(1, weight=3)
        lower.grid_rowconfigure(0, weight=1)

        regions = theme.panel(lower, tone="surface_alt")
        regions.grid(row=0, column=0, sticky="nsew", padx=(0, spacing.md))
        self._build_region_digest(regions)

        priority = theme.panel(lower, tone="surface_alt")
        priority.grid(row=0, column=1, sticky="nsew")
        self._build_priority_watchlist(priority)
        return panel

    def _build_alert_inbox_panel(self, master: tk.Misc) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing
        view_model = self._alert_inbox_view_model

        panel = theme.panel(master, tone="surface")
        body = tk.Frame(panel, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.lg, pady=spacing.lg)

        header = tk.Frame(body, bg=theme.palette.surface)
        header.pack(fill="x")
        pills = tk.Frame(header, bg=theme.palette.surface)
        pills.pack(anchor="w")
        theme.pill(pills, text="STAGE 4 LIVE", tone="signal").pack(side="left", padx=(0, spacing.sm))
        theme.pill(pills, text="ACTIVE EVENT QUEUE", tone="accent").pack(side="left")
        theme.label(
            header,
            text="Signal Inbox",
            role="section_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.sm, spacing.xs))
        theme.label(
            header,
            text=view_model.summary_text,
            role="body",
            tone="muted",
            background=theme.palette.surface,
            wraplength=420,
        ).pack(anchor="w")

        theme.divider(body, tone="soft").pack(fill="x", pady=spacing.md)

        summary_grid = tk.Frame(body, bg=theme.palette.surface)
        summary_grid.pack(fill="x")
        for index, card_view in enumerate(view_model.summary_cards):
            summary_grid.grid_columnconfigure(index, weight=1)
            card = self._build_alert_summary_card(summary_grid, card_view)
            card.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0, spacing.sm if index < len(view_model.summary_cards) - 1 else 0),
            )

        list_shell = theme.panel(body, tone="surface_alt")
        list_shell.pack(fill="both", expand=True, pady=(spacing.md, 0))
        list_body = tk.Frame(list_shell, bg=theme.palette.surface_alt)
        list_body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)

        if not view_model.items:
            theme.label(
                list_body,
                text=view_model.empty_title,
                role="card_title",
                tone="signal",
                background=theme.palette.surface_alt,
            ).pack(anchor="w")
            theme.label(
                list_body,
                text=view_model.empty_body,
                role="body",
                tone="muted",
                background=theme.palette.surface_alt,
                wraplength=380,
            ).pack(anchor="w", pady=(spacing.xs, 0))
            return panel

        for index, item_view in enumerate(view_model.items):
            card = self._build_alert_inbox_item_card(list_body, item_view)
            card.pack(fill="x", pady=(0, spacing.sm if index < len(view_model.items) - 1 else 0))
        return panel

    def _build_station_explorer_panel(self, master: tk.Misc) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        panel = theme.panel(master, tone="surface")
        body = tk.Frame(panel, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.lg, pady=spacing.lg)

        header = tk.Frame(body, bg=theme.palette.surface)
        header.pack(fill="x")
        pills = tk.Frame(header, bg=theme.palette.surface)
        pills.pack(anchor="w")
        theme.pill(pills, text="STAGE 2 LIVE", tone="signal").pack(side="left", padx=(0, spacing.sm))
        theme.pill(pills, text="INDEXED CATALOG", tone="accent").pack(side="left")
        theme.label(
            header,
            text="Station Explorer Bay",
            role="section_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.sm, spacing.xs))
        theme.label(
            header,
            text=(
                "Search the station catalog, filter by region and operating state, and reorder live telemetry rows "
                "to spot stale feeds or high-stress sites quickly. "
                f"{self._station_explorer_view_model.summary_text}."
            ),
            role="body",
            tone="muted",
            background=theme.palette.surface,
            wraplength=760,
        ).pack(anchor="w")

        controls = theme.panel(body, tone="surface_alt")
        controls.pack(fill="x", pady=(spacing.md, 0))
        controls_body = tk.Frame(controls, bg=theme.palette.surface_alt)
        controls_body.pack(fill="x", padx=spacing.md, pady=spacing.md)
        controls_body.grid_columnconfigure(0, weight=3)
        controls_body.grid_columnconfigure(1, weight=1)
        controls_body.grid_columnconfigure(2, weight=1)
        controls_body.grid_columnconfigure(3, weight=0)
        controls_body.grid_columnconfigure(4, weight=0)

        self._build_search_control(controls_body).grid(row=0, column=0, sticky="ew", padx=(0, spacing.md))
        self._build_region_filter_control(controls_body).grid(row=0, column=1, sticky="ew", padx=(0, spacing.md))
        self._build_status_filter_control(controls_body).grid(row=0, column=2, sticky="ew", padx=(0, spacing.md))
        self._build_priority_toggle_control(controls_body).grid(row=0, column=3, sticky="ew", padx=(0, spacing.md))
        self._build_reset_button(controls_body).grid(row=0, column=4, sticky="se")

        summary_row = tk.Frame(body, bg=theme.palette.surface)
        summary_row.pack(fill="x", pady=(spacing.md, spacing.sm))
        self._explorer_summary_label = theme.label(
            summary_row,
            text="",
            role="body_strong",
            tone="primary",
            background=theme.palette.surface,
        )
        self._explorer_summary_label.pack(side="left")
        self._explorer_sort_label = theme.label(
            summary_row,
            text="",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        )
        self._explorer_sort_label.pack(side="right")

        table_shell = theme.panel(body, tone="surface_alt")
        table_shell.pack(fill="both", expand=True)
        table_body = tk.Frame(table_shell, bg=theme.palette.surface_alt)
        table_body.pack(fill="both", expand=True, padx=spacing.sm, pady=spacing.sm)
        table_body.grid_rowconfigure(0, weight=1)
        table_body.grid_columnconfigure(0, weight=1)

        columns = ("station", "region", "status", "health", "updated", "load", "temperature", "signals")
        tree = ttk.Treeview(
            table_body,
            columns=columns,
            show="headings",
            selectmode="browse",
            style="Telemetry.Treeview",
        )
        tree.grid(row=0, column=0, sticky="nsew")
        tree.bind("<<TreeviewSelect>>", self._on_station_explorer_select)
        self._configure_station_explorer_columns(tree)
        self._explorer_tree = tree

        scrollbar = ttk.Scrollbar(
            table_body,
            orient="vertical",
            command=tree.yview,
            style="Telemetry.Vertical.TScrollbar",
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        preview = theme.panel(body, tone="surface_alt")
        preview.pack(fill="x", pady=(spacing.sm, 0))
        self._explorer_preview_host = tk.Frame(preview, bg=theme.palette.surface_alt)
        self._explorer_preview_host.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)

        self._refresh_station_explorer()
        return panel

    def _build_history_dashboard_panel(self, master: tk.Misc) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        panel = theme.panel(master, tone="surface")
        body = tk.Frame(panel, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.lg, pady=spacing.lg)

        header = tk.Frame(body, bg=theme.palette.surface)
        header.pack(fill="x")
        pills = tk.Frame(header, bg=theme.palette.surface)
        pills.pack(anchor="w")
        theme.pill(pills, text="STAGE 5 LIVE", tone="signal").pack(side="left", padx=(0, spacing.sm))
        theme.pill(pills, text="TREND + INSIGHT", tone="accent").pack(side="left")
        theme.label(
            header,
            text="Trend Insight Deck",
            role="section_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.sm, spacing.xs))
        theme.label(
            header,
            text=(
                "The deck follows the station currently selected in the explorer, combining telemetry charts with "
                "operator-ready narratives and recommended next actions."
            ),
            role="body",
            tone="muted",
            background=theme.palette.surface,
            wraplength=420,
        ).pack(anchor="w")

        host_shell = theme.panel(body, tone="surface_alt")
        host_shell.pack(fill="both", expand=True, pady=(spacing.md, 0))
        host_shell.grid_rowconfigure(0, weight=1)
        host_shell.grid_columnconfigure(0, weight=1)
        self._history_content_canvas = tk.Canvas(
            host_shell,
            bg=theme.palette.surface_alt,
            highlightthickness=0,
            bd=0,
        )
        self._history_content_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            host_shell,
            orient="vertical",
            command=self._history_content_canvas.yview,
            style="Telemetry.Vertical.TScrollbar",
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._history_content_canvas.configure(yscrollcommand=scrollbar.set)

        self._history_content_frame = tk.Frame(self._history_content_canvas, bg=theme.palette.surface_alt)
        self._history_content_window_id = self._history_content_canvas.create_window(
            (0, 0),
            window=self._history_content_frame,
            anchor="nw",
        )
        self._history_content_frame.bind("<Configure>", self._on_history_content_configure)
        self._history_content_canvas.bind("<Configure>", self._on_history_canvas_configure)

        self._history_dashboard_host = tk.Frame(self._history_content_frame, bg=theme.palette.surface_alt)
        self._history_dashboard_host.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)

        self._render_history_dashboard(
            self._resolve_selected_history_dashboard(),
            self._resolve_selected_insight_panel(),
        )
        return panel

    def _render_history_dashboard(
        self,
        dashboard: StationHistoryDashboardViewModel | None,
        insight_panel: StationInsightPanelViewModel | None,
    ) -> None:
        if self._history_dashboard_host is None:
            return

        theme = self._theme
        spacing = theme.spacing
        for child in self._history_dashboard_host.winfo_children():
            child.destroy()

        if dashboard is None:
            theme.label(
                self._history_dashboard_host,
                text="Trend Insight Deck",
                role="card_title",
                tone="primary",
                background=theme.palette.surface_alt,
            ).pack(anchor="w")
            theme.label(
                self._history_dashboard_host,
                text="Select a station in the explorer to render its recent telemetry, narratives, and operator recommendations.",
                role="body",
                tone="muted",
                background=theme.palette.surface_alt,
                wraplength=420,
            ).pack(anchor="w", pady=(spacing.xs, 0))
            return

        header = tk.Frame(self._history_dashboard_host, bg=theme.palette.surface_alt)
        header.pack(fill="x")
        theme.pill(header, text=dashboard.status_label.upper(), tone=dashboard.status_tone).pack(side="left", padx=(0, spacing.sm))
        theme.pill(header, text=dashboard.active_signal_text.upper(), tone=_history_signal_tone(dashboard)).pack(side="left")
        theme.label(
            header,
            text=dashboard.health_score_text,
            role="caption",
            tone="muted",
            background=theme.palette.surface_alt,
        ).pack(side="right")

        theme.label(
            self._history_dashboard_host,
            text=dashboard.title,
            role="card_title",
            tone="primary",
            background=theme.palette.surface_alt,
        ).pack(anchor="w", pady=(spacing.sm, 0))
        theme.label(
            self._history_dashboard_host,
            text=f"{dashboard.subtitle} | Last updated {dashboard.last_updated_text}",
            role="body",
            tone="muted",
            background=theme.palette.surface_alt,
            wraplength=420,
        ).pack(anchor="w", pady=(spacing.xs, spacing.sm))
        theme.label(
            self._history_dashboard_host,
            text=dashboard.status_reason,
            role="body_strong",
            tone="primary",
            background=theme.palette.surface_alt,
            wraplength=420,
        ).pack(anchor="w")
        theme.label(
            self._history_dashboard_host,
            text=dashboard.history_window_text,
            role="caption",
            tone="muted",
            background=theme.palette.surface_alt,
            wraplength=420,
        ).pack(anchor="w", pady=(spacing.xs, spacing.md))

        self._render_insight_panel(self._history_dashboard_host, insight_panel)
        if insight_panel is not None:
            theme.divider(self._history_dashboard_host, tone="soft").pack(fill="x", pady=spacing.md)

        for index, chart_view in enumerate(dashboard.charts):
            card = self._build_history_chart_card(self._history_dashboard_host, chart_view)
            card.pack(fill="x", pady=(0, spacing.sm if index < len(dashboard.charts) - 1 else 0))

    def _render_insight_panel(
        self,
        master: tk.Misc,
        insight_panel: StationInsightPanelViewModel | None,
    ) -> None:
        if insight_panel is None:
            return

        theme = self._theme
        spacing = theme.spacing

        summary_card = theme.panel(master, tone="surface")
        summary_body = tk.Frame(summary_card, bg=theme.palette.surface)
        summary_body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)
        header = tk.Frame(summary_body, bg=theme.palette.surface)
        header.pack(fill="x")
        theme.pill(header, text="OPERATOR BRIEF", tone=insight_panel.summary_tone).pack(side="left")
        theme.label(
            header,
            text="Insight service",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(side="right")
        theme.label(
            summary_body,
            text=insight_panel.summary_title,
            role="card_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.sm, spacing.xs))
        theme.label(
            summary_body,
            text=insight_panel.summary_body,
            role="body",
            tone="primary",
            background=theme.palette.surface,
            wraplength=420,
        ).pack(anchor="w")
        summary_card.pack(fill="x")

        sections = tk.Frame(master, bg=theme.palette.surface_alt)
        sections.pack(fill="x", pady=(spacing.md, spacing.md))
        sections.grid_columnconfigure(0, weight=1)
        sections.grid_columnconfigure(1, weight=1)

        narrative_card = self._build_narrative_stack(sections, insight_panel.narratives)
        narrative_card.grid(row=0, column=0, sticky="nsew", padx=(0, spacing.sm))
        recommendation_card = self._build_recommendation_stack(sections, insight_panel.recommendations)
        recommendation_card.grid(row=0, column=1, sticky="nsew")

    def _build_narrative_stack(
        self,
        master: tk.Misc,
        narratives: tuple[InsightNarrativeViewModel, ...],
    ) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        card = theme.panel(master, tone="surface")
        body = tk.Frame(card, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)
        theme.label(
            body,
            text="Trend Narratives",
            role="card_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w")

        for index, narrative in enumerate(narratives):
            item = tk.Frame(body, bg=theme.palette.surface)
            item.pack(fill="x", pady=(spacing.sm if index == 0 else spacing.xs, 0))
            theme.pill(item, text=narrative.title.upper(), tone=narrative.tone).pack(anchor="w")
            theme.label(
                item,
                text=narrative.detail,
                role="body",
                tone="primary",
                background=theme.palette.surface,
                wraplength=180,
            ).pack(anchor="w", pady=(spacing.xs, 0))
        return card

    def _build_recommendation_stack(
        self,
        master: tk.Misc,
        recommendations: tuple[RecommendationItemViewModel, ...],
    ) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        card = theme.panel(master, tone="surface")
        body = tk.Frame(card, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)
        theme.label(
            body,
            text="Recommended Actions",
            role="card_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w")

        for index, recommendation in enumerate(recommendations):
            item = tk.Frame(body, bg=theme.palette.surface)
            item.pack(fill="x", pady=(spacing.sm if index == 0 else spacing.xs, 0))
            top = tk.Frame(item, bg=theme.palette.surface)
            top.pack(fill="x")
            theme.pill(top, text=recommendation.priority_label.upper(), tone=recommendation.tone).pack(side="left", padx=(0, spacing.xs))
            theme.label(
                top,
                text=recommendation.title,
                role="body_strong",
                tone="primary",
                background=theme.palette.surface,
            ).pack(side="left")
            theme.label(
                item,
                text=recommendation.detail,
                role="body",
                tone="primary",
                background=theme.palette.surface,
                wraplength=180,
            ).pack(anchor="w", pady=(spacing.xs, 0))
        return card

    def _on_history_content_configure(self, _: tk.Event[tk.Misc]) -> None:
        if self._history_content_canvas is None:
            return
        self._history_content_canvas.configure(scrollregion=self._history_content_canvas.bbox("all"))

    def _on_history_canvas_configure(self, event: tk.Event[tk.Misc]) -> None:
        if self._history_content_canvas is None or self._history_content_window_id is None:
            return
        self._history_content_canvas.itemconfigure(self._history_content_window_id, width=event.width)

    def _build_history_chart_card(self, master: tk.Misc, chart_view: MetricHistoryChartViewModel) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        card = theme.panel(master, tone="surface")
        accent_rail = tk.Frame(card, bg=theme.tone_color(chart_view.tone), width=5)
        accent_rail.pack(side="left", fill="y")

        body = tk.Frame(card, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)

        top_row = tk.Frame(body, bg=theme.palette.surface)
        top_row.pack(fill="x")
        theme.pill(top_row, text=chart_view.label.upper(), tone=chart_view.tone).pack(side="left")
        theme.label(
            top_row,
            text=chart_view.current_value_text,
            role="body_strong",
            tone="primary",
            background=theme.palette.surface,
        ).pack(side="right")

        meta_row = tk.Frame(body, bg=theme.palette.surface)
        meta_row.pack(fill="x", pady=(spacing.xs, spacing.sm))
        theme.label(
            meta_row,
            text=f"Average {chart_view.average_value_text}",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(side="left")
        theme.label(
            meta_row,
            text=f"Delta {chart_view.delta_value_text}",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(side="right")

        canvas = tk.Canvas(
            body,
            height=106,
            bg=theme.palette.surface,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill="x")
        canvas.bind(
            "<Configure>",
            lambda _event, chart=chart_view, target=canvas: self._paint_history_chart(target, chart),
        )
        self._paint_history_chart(canvas, chart_view)

        footer_row = tk.Frame(body, bg=theme.palette.surface)
        footer_row.pack(fill="x", pady=(spacing.sm, 0))
        left_footer = tk.Frame(footer_row, bg=theme.palette.surface)
        left_footer.pack(side="left")
        theme.label(
            left_footer,
            text=chart_view.range_value_text,
            role="caption",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w")
        theme.label(
            left_footer,
            text=chart_view.limit_text,
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.xs, 0))

        right_footer = tk.Frame(footer_row, bg=theme.palette.surface)
        right_footer.pack(side="right")
        theme.label(
            right_footer,
            text=chart_view.window_text,
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(anchor="e")
        theme.label(
            right_footer,
            text=f"Axis {chart_view.axis_min:.1f} -> {chart_view.axis_max:.1f}",
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(anchor="e", pady=(spacing.xs, 0))

        return card

    def _paint_history_chart(self, canvas: tk.Canvas, chart_view: MetricHistoryChartViewModel) -> None:
        theme = self._theme
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("history")
        canvas.configure(bg=theme.palette.surface, highlightthickness=0, bd=0)

        if not chart_view.points:
            canvas.create_text(
                width / 2,
                height / 2,
                text="No telemetry history",
                fill=theme.palette.text_muted,
                font=theme.typography.caption,
                tags="history",
            )
            return

        left = 14
        right = width - 14
        top = 12
        bottom = height - 18

        grid_color = theme.palette.border
        for ratio in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = top + ((bottom - top) * ratio)
            canvas.create_line(left, y, right, y, fill=grid_color, width=1, tags="history")

        axis_min = chart_view.axis_min
        axis_max = chart_view.axis_max
        axis_span = axis_max - axis_min if axis_max != axis_min else 1.0

        def to_y(value: float) -> float:
            normalized = (value - axis_min) / axis_span
            return bottom - (normalized * (bottom - top))

        for bound, tone in ((chart_view.lower_bound, "warning"), (chart_view.upper_bound, "critical")):
            if bound is None:
                continue
            y = to_y(bound)
            dash_color = theme.tone_color(tone)
            canvas.create_line(
                left,
                y,
                right,
                y,
                fill=dash_color,
                width=1,
                dash=(4, 3),
                tags="history",
            )

        point_count = len(chart_view.points)
        x_step = (right - left) / max(point_count - 1, 1)
        coordinates: list[float] = []
        quality_marks: list[tuple[float, float, str]] = []
        for index, point in enumerate(chart_view.points):
            x = left + (index * x_step if point_count > 1 else (right - left) / 2)
            y = to_y(point.value)
            coordinates.extend((x, y))
            if point.quality_label != "Ok":
                quality_marks.append((x, y, point.quality_label))

        line_color = theme.tone_color(chart_view.tone)
        if len(coordinates) >= 4:
            canvas.create_line(
                *coordinates,
                fill=line_color,
                width=2,
                smooth=True,
                splinesteps=16,
                tags="history",
            )
        else:
            x, y = coordinates
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=line_color, outline="", tags="history")

        for x, y, quality_label in quality_marks:
            mark_tone = "warning" if quality_label in {"Degraded", "Estimated"} else "critical"
            mark_color = theme.tone_color(mark_tone)
            canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=mark_color, outline="", tags="history")

        last_x = coordinates[-2]
        last_y = coordinates[-1]
        canvas.create_oval(last_x - 4, last_y - 4, last_x + 4, last_y + 4, fill=line_color, outline="", tags="history")

        canvas.create_text(
            left,
            top - 2,
            text=f"{chart_view.axis_max:.1f}",
            fill=theme.palette.text_muted,
            font=theme.typography.caption,
            anchor="sw",
            tags="history",
        )
        canvas.create_text(
            left,
            bottom + 4,
            text=f"{chart_view.axis_min:.1f}",
            fill=theme.palette.text_muted,
            font=theme.typography.caption,
            anchor="nw",
            tags="history",
        )
        canvas.create_text(
            left + 52,
            bottom + 4,
            text=chart_view.points[0].timestamp_text,
            fill=theme.palette.text_muted,
            font=theme.typography.caption,
            anchor="nw",
            tags="history",
        )
        canvas.create_text(
            right,
            bottom + 4,
            text=chart_view.points[-1].timestamp_text,
            fill=theme.palette.text_muted,
            font=theme.typography.caption,
            anchor="ne",
            tags="history",
        )

    def _create_placeholder_panel(
        self,
        master: tk.Misc,
        *,
        title: str,
        eyebrow: str,
        description: str,
        footnote: str,
    ) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        panel = theme.panel(master, tone="surface")
        body = tk.Frame(panel, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.lg, pady=spacing.lg)

        header = tk.Frame(body, bg=theme.palette.surface)
        header.pack(fill="x")
        theme.pill(header, text=eyebrow, tone="accent").pack(side="left")
        theme.label(
            body,
            text=title,
            role="section_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.sm, spacing.xs))
        theme.label(
            body,
            text=description,
            role="body",
            tone="muted",
            background=theme.palette.surface,
            wraplength=420,
        ).pack(anchor="w")

        theme.divider(body, tone="soft").pack(fill="x", pady=spacing.md)
        theme.label(
            body,
            text=footnote,
            role="body_strong",
            tone="primary",
            background=theme.palette.surface,
            wraplength=420,
        ).pack(anchor="w")
        return panel

    def _build_search_control(self, master: tk.Misc) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        shell = tk.Frame(master, bg=theme.palette.surface_alt)
        theme.label(
            shell,
            text="Search",
            role="caption",
            tone="muted",
            background=theme.palette.surface_alt,
        ).pack(anchor="w", pady=(0, spacing.xs))

        input_shell = tk.Frame(
            shell,
            bg=theme.palette.surface,
            highlightthickness=1,
            highlightbackground=theme.palette.border,
        )
        input_shell.pack(fill="x")
        entry = tk.Entry(
            input_shell,
            textvariable=self._explorer_search_var,
            relief="flat",
            bd=0,
            bg=theme.palette.surface,
            fg=theme.palette.text_primary,
            insertbackground=theme.palette.text_primary,
            font=theme.typography.body,
        )
        entry.pack(fill="x", padx=spacing.md, pady=spacing.sm)
        return shell

    def _build_region_filter_control(self, master: tk.Misc) -> tk.Frame:
        return self._build_combobox_control(
            master,
            label="Region",
            variable=self._explorer_region_var,
            values=("All regions", *self._station_explorer_view_model.region_options),
        )

    def _build_status_filter_control(self, master: tk.Misc) -> tk.Frame:
        return self._build_combobox_control(
            master,
            label="Status",
            variable=self._explorer_status_var,
            values=("All statuses", *self._station_explorer_view_model.status_options),
        )

    def _build_combobox_control(
        self,
        master: tk.Misc,
        *,
        label: str,
        variable: tk.StringVar,
        values: tuple[str, ...],
    ) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        shell = tk.Frame(master, bg=theme.palette.surface_alt)
        theme.label(
            shell,
            text=label,
            role="caption",
            tone="muted",
            background=theme.palette.surface_alt,
        ).pack(anchor="w", pady=(0, spacing.xs))

        combobox = ttk.Combobox(
            shell,
            textvariable=variable,
            values=values,
            state="readonly",
            style="Telemetry.TCombobox",
        )
        combobox.pack(fill="x")
        return shell

    def _build_priority_toggle_control(self, master: tk.Misc) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        shell = tk.Frame(master, bg=theme.palette.surface_alt)
        theme.label(
            shell,
            text="Focus",
            role="caption",
            tone="muted",
            background=theme.palette.surface_alt,
        ).pack(anchor="w", pady=(0, spacing.xs))
        toggle = tk.Checkbutton(
            shell,
            text="Priority only",
            variable=self._explorer_priority_only_var,
            onvalue=True,
            offvalue=False,
            bg=theme.palette.surface_alt,
            fg=theme.palette.text_primary,
            activebackground=theme.palette.surface_alt,
            activeforeground=theme.palette.text_primary,
            selectcolor=theme.palette.surface,
            bd=0,
            highlightthickness=0,
            font=theme.typography.body_strong,
            anchor="w",
        )
        toggle.pack(anchor="w", pady=(spacing.sm, 0))
        return shell

    def _build_reset_button(self, master: tk.Misc) -> tk.Button:
        theme = self._theme
        spacing = theme.spacing

        return tk.Button(
            master,
            text="Reset View",
            command=self._reset_station_explorer_view,
            font=theme.typography.body_strong,
            fg=theme.palette.text_on_dark,
            bg=theme.palette.surface_dark,
            activeforeground=theme.palette.text_on_dark,
            activebackground=theme.palette.accent,
            relief="flat",
            bd=0,
            padx=spacing.md,
            pady=spacing.sm,
            cursor="arrow",
        )

    def _configure_station_explorer_columns(self, tree: ttk.Treeview) -> None:
        columns = {
            "station": ("Station", 220, self._sort_station_explorer_by),
            "region": ("Region", 110, self._sort_station_explorer_by),
            "status": ("Status", 100, self._sort_station_explorer_by),
            "health": ("Score", 70, self._sort_station_explorer_by),
            "updated": ("Last Updated", 135, self._sort_station_explorer_by),
            "load": ("Load", 80, self._sort_station_explorer_by),
            "temperature": ("Temp", 80, self._sort_station_explorer_by),
            "signals": ("Signals", 95, self._sort_station_explorer_by),
        }
        for column_name, (title, width, callback) in columns.items():
            tree.heading(column_name, text=title, command=lambda key=column_name: callback(key))
            tree.column(column_name, width=width, minwidth=width - 10, anchor="w", stretch=column_name == "station")

    def _refresh_station_explorer(self) -> None:
        if self._explorer_tree is None:
            return

        rows = filter_station_explorer_rows(
            self._station_explorer_view_model.rows,
            search_text=self._explorer_search_var.get(),
            region=self._explorer_region_var.get(),
            status_label=self._explorer_status_var.get(),
            priority_only=self._explorer_priority_only_var.get(),
        )
        rows = sort_station_explorer_rows(
            rows,
            sort_key=self._explorer_sort_key,
            descending=self._explorer_sort_descending,
        )
        self._explorer_rows_by_id = {row.station_id: row for row in rows}

        tree = self._explorer_tree
        tree.delete(*tree.get_children())
        for row in rows:
            tree.insert(
                "",
                "end",
                iid=row.station_id,
                values=(
                    row.title,
                    row.region,
                    row.status_label,
                    row.health_score_text,
                    row.last_updated_text,
                    row.load_text,
                    row.temperature_text,
                    row.signal_text,
                ),
            )

        selected_station_id = self._explorer_selected_station_id
        if selected_station_id not in self._explorer_rows_by_id:
            selected_station_id = rows[0].station_id if rows else None
        self._explorer_selected_station_id = selected_station_id

        if selected_station_id is not None:
            tree.selection_set(selected_station_id)
            tree.focus(selected_station_id)
            tree.see(selected_station_id)

        priority_count = sum(1 for row in rows if row.is_priority)
        total_count = len(self._station_explorer_view_model.rows)
        if self._explorer_summary_label is not None:
            if rows:
                self._explorer_summary_label.configure(
                    text=f"{len(rows)} of {total_count} stations shown | {priority_count} priority in view"
                )
            else:
                self._explorer_summary_label.configure(text="No stations match the current explorer filters.")

        if self._explorer_sort_label is not None:
            self._explorer_sort_label.configure(
                text=(
                    f"Sorted by {_sort_label(self._explorer_sort_key)} "
                    f"({'descending' if self._explorer_sort_descending else 'ascending'}) | Click table headers to reorder"
                )
            )

        self._refresh_station_context_panels()

    def _render_station_explorer_preview(self, row: StationExplorerRowViewModel | None) -> None:
        if self._explorer_preview_host is None:
            return

        theme = self._theme
        spacing = theme.spacing
        for child in self._explorer_preview_host.winfo_children():
            child.destroy()

        if row is None:
            theme.label(
                self._explorer_preview_host,
                text="Explorer Preview",
                role="card_title",
                tone="primary",
                background=theme.palette.surface_alt,
            ).pack(anchor="w")
            theme.label(
                self._explorer_preview_host,
                text="Adjust the filters or search text to bring stations back into view.",
                role="body",
                tone="muted",
                background=theme.palette.surface_alt,
                wraplength=620,
            ).pack(anchor="w", pady=(spacing.xs, 0))
            return

        header = tk.Frame(self._explorer_preview_host, bg=theme.palette.surface_alt)
        header.pack(fill="x")
        theme.pill(header, text=row.status_label.upper(), tone=row.status_tone).pack(side="left", padx=(0, spacing.sm))
        theme.pill(header, text=row.signal_text.upper(), tone=_signal_tone(row)).pack(side="left")
        theme.label(
            header,
            text=f"Rank #{row.priority_rank}",
            role="caption",
            tone="muted",
            background=theme.palette.surface_alt,
        ).pack(side="right")

        theme.label(
            self._explorer_preview_host,
            text=row.title,
            role="card_title",
            tone="primary",
            background=theme.palette.surface_alt,
        ).pack(anchor="w", pady=(spacing.sm, 0))
        theme.label(
            self._explorer_preview_host,
            text=f"{row.subtitle} | Quality {row.quality_label}",
            role="body",
            tone="muted",
            background=theme.palette.surface_alt,
        ).pack(anchor="w", pady=(spacing.xs, spacing.sm))

        facts = tk.Frame(self._explorer_preview_host, bg=theme.palette.surface_alt)
        facts.pack(fill="x")
        self._build_preview_fact(facts, label="Health", value=row.health_score_text, tone=row.status_tone).pack(side="left", padx=(0, spacing.lg))
        self._build_preview_fact(facts, label="Updated", value=row.last_updated_text, tone="signal").pack(side="left", padx=(0, spacing.lg))
        self._build_preview_fact(
            facts,
            label="Metrics",
            value=f"{row.voltage_text} | {row.load_text} | {row.temperature_text}",
            tone="primary",
        ).pack(side="left")

        theme.divider(self._explorer_preview_host, tone="soft").pack(fill="x", pady=spacing.sm)
        theme.label(
            self._explorer_preview_host,
            text=row.focus_text,
            role="body",
            tone="primary",
            background=theme.palette.surface_alt,
            wraplength=620,
        ).pack(anchor="w")
        theme.label(
            self._explorer_preview_host,
            text=f"Tags: {row.tags_text}",
            role="caption",
            tone="muted",
            background=theme.palette.surface_alt,
            wraplength=620,
        ).pack(anchor="w", pady=(spacing.sm, 0))

    def _build_preview_fact(self, master: tk.Misc, *, label: str, value: str, tone: str) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        fact = tk.Frame(master, bg=theme.palette.surface_alt)
        theme.label(
            fact,
            text=label.upper(),
            role="caption",
            tone=tone,
            background=theme.palette.surface_alt,
        ).pack(anchor="w")
        theme.label(
            fact,
            text=value,
            role="body_strong",
            tone="primary",
            background=theme.palette.surface_alt,
        ).pack(anchor="w", pady=(spacing.xs, 0))
        return fact

    def _on_station_explorer_filters_changed(self, *_: str) -> None:
        self._refresh_station_explorer()

    def _on_station_explorer_select(self, _: tk.Event[tk.Misc]) -> None:
        if self._explorer_tree is None:
            return
        selection = self._explorer_tree.selection()
        self._explorer_selected_station_id = selection[0] if selection else None
        self._refresh_station_context_panels()

    def _sort_station_explorer_by(self, sort_key: str) -> None:
        if self._explorer_sort_key == sort_key:
            self._explorer_sort_descending = not self._explorer_sort_descending
        else:
            self._explorer_sort_key = sort_key
            self._explorer_sort_descending = _default_sort_direction(sort_key)
        self._refresh_station_explorer()

    def _reset_station_explorer_view(self) -> None:
        self._explorer_search_var.set("")
        self._explorer_region_var.set("All regions")
        self._explorer_status_var.set("All statuses")
        self._explorer_priority_only_var.set(False)
        self._explorer_sort_key = "priority"
        self._explorer_sort_descending = False
        self._refresh_station_explorer()

    def _refresh_station_context_panels(self) -> None:
        selected_row = (
            self._explorer_rows_by_id.get(self._explorer_selected_station_id)
            if self._explorer_selected_station_id is not None
            else None
        )
        self._render_station_explorer_preview(selected_row)
        self._render_history_dashboard(
            self._resolve_selected_history_dashboard(),
            self._resolve_selected_insight_panel(),
        )

    def _resolve_selected_history_dashboard(self) -> StationHistoryDashboardViewModel | None:
        if self._explorer_selected_station_id is None:
            return None

        cached = self._station_history_cache.get(self._explorer_selected_station_id)
        if cached is not None:
            return cached

        detail = self._resolve_station_detail(self._explorer_selected_station_id)
        dashboard = build_station_history_dashboard_view_model(detail)
        self._station_history_cache[self._explorer_selected_station_id] = dashboard
        return dashboard

    def _resolve_selected_insight_panel(self) -> StationInsightPanelViewModel | None:
        if self._explorer_selected_station_id is None:
            return None

        cached = self._station_insight_cache.get(self._explorer_selected_station_id)
        if cached is not None:
            return cached

        detail = self._resolve_station_detail(self._explorer_selected_station_id)
        report = self._context.insight_service.build_report(detail)
        panel = build_station_insight_panel_view_model(report)
        self._station_insight_cache[self._explorer_selected_station_id] = panel
        return panel

    def _resolve_station_detail(self, station_id: str) -> StationDetailResult:
        cached = self._station_detail_cache.get(station_id)
        if cached is not None:
            return cached

        detail = self._context.station_detail_service.get_station_detail(
            self._station_repository,
            self._telemetry_repository,
            StationDetailQuery(station_id=station_id),
        )
        self._station_detail_cache[station_id] = detail
        return detail

    def _build_stat_chip(self, master: tk.Misc, label: str, value: str) -> None:
        theme = self._theme
        spacing = theme.spacing

        chip = tk.Frame(master, bg=theme.palette.surface_dark)
        chip.pack(side="left", padx=(0, spacing.md))
        theme.label(
            chip,
            text=label.upper(),
            role="caption",
            tone="signal",
            background=theme.palette.surface_dark,
        ).pack(anchor="w")
        theme.label(
            chip,
            text=value,
            role="card_title",
            tone="dark",
            background=theme.palette.surface_dark,
        ).pack(anchor="w")

    def _build_signal_summary(self, master: tk.Misc, *, title: str, body: str) -> None:
        theme = self._theme
        spacing = theme.spacing

        theme.label(
            master,
            text=title,
            role="card_title",
            tone="dark",
            background=theme.palette.surface_dark,
        ).pack(anchor="w")
        theme.label(
            master,
            text=body,
            role="body",
            tone="dark",
            background=theme.palette.surface_dark,
            wraplength=360,
        ).pack(anchor="w", pady=(spacing.xs, 0))

    def _on_resize(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is self and self._signal_canvas is not None:
            self._theme.paint_signal_canvas(self._signal_canvas)

    def _build_overview_kpi_card(self, master: tk.Misc, card_view: FleetKpiViewModel) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        card = theme.panel(master, tone="surface_alt")
        accent_rail = tk.Frame(card, bg=theme.tone_color(card_view.tone), width=6)
        accent_rail.pack(side="left", fill="y")

        body = tk.Frame(card, bg=theme.palette.surface_alt)
        body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)
        theme.label(
            body,
            text=card_view.label.upper(),
            role="caption",
            tone=card_view.tone,
            background=theme.palette.surface_alt,
        ).pack(anchor="w")
        theme.label(
            body,
            text=card_view.value_text,
            role="section_title",
            tone="primary",
            background=theme.palette.surface_alt,
        ).pack(anchor="w", pady=(spacing.xs, spacing.xs))
        theme.label(
            body,
            text=card_view.detail_text,
            role="body",
            tone="muted",
            background=theme.palette.surface_alt,
            wraplength=160,
        ).pack(anchor="w")
        return card

    def _build_region_digest(self, master: tk.Misc) -> None:
        theme = self._theme
        spacing = theme.spacing

        body = tk.Frame(master, bg=theme.palette.surface_alt)
        body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)
        theme.label(
            body,
            text="Regional Health",
            role="card_title",
            tone="primary",
            background=theme.palette.surface_alt,
        ).pack(anchor="w")
        theme.label(
            body,
            text="Compare average scores and the current operating mix across every grid region.",
            role="body",
            tone="muted",
            background=theme.palette.surface_alt,
            wraplength=220,
        ).pack(anchor="w", pady=(spacing.xs, spacing.md))

        grid = tk.Frame(body, bg=theme.palette.surface_alt)
        grid.pack(fill="both", expand=True)
        for index, region_view in enumerate(self._overview_view_model.region_cards):
            row = index // 2
            column = index % 2
            grid.grid_columnconfigure(column, weight=1)
            grid.grid_rowconfigure(row, weight=1)
            card = self._build_region_card(grid, region_view)
            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0, spacing.sm if column == 0 else 0),
                pady=(0, spacing.sm if row == 0 else 0),
            )

    def _build_alert_summary_card(self, master: tk.Misc, card_view: AlertInboxSummaryViewModel) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        card = theme.panel(master, tone="surface_alt")
        accent_rail = tk.Frame(card, bg=theme.tone_color(card_view.tone), width=6)
        accent_rail.pack(side="left", fill="y")

        body = tk.Frame(card, bg=theme.palette.surface_alt)
        body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)
        theme.label(
            body,
            text=card_view.label.upper(),
            role="caption",
            tone=card_view.tone,
            background=theme.palette.surface_alt,
        ).pack(anchor="w")
        theme.label(
            body,
            text=card_view.value_text,
            role="card_title",
            tone="primary",
            background=theme.palette.surface_alt,
        ).pack(anchor="w", pady=(spacing.xs, spacing.xs))
        theme.label(
            body,
            text=card_view.detail_text,
            role="caption",
            tone="muted",
            background=theme.palette.surface_alt,
            wraplength=120,
        ).pack(anchor="w")
        return card

    def _build_alert_inbox_item_card(self, master: tk.Misc, item_view: AlertInboxItemViewModel) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        card = theme.panel(master, tone="surface")
        accent_rail = tk.Frame(card, bg=theme.tone_color(item_view.badge_tone), width=5)
        accent_rail.pack(side="left", fill="y")

        body = tk.Frame(card, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)

        top_row = tk.Frame(body, bg=theme.palette.surface)
        top_row.pack(fill="x")
        theme.pill(top_row, text=item_view.badge_text, tone=item_view.badge_tone).pack(side="left", padx=(0, spacing.sm))
        theme.pill(top_row, text=item_view.metric_text.upper(), tone="neutral").pack(side="left")
        theme.label(
            top_row,
            text=item_view.timestamp_text,
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(side="right")

        theme.label(
            body,
            text=item_view.station_title,
            role="card_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.sm, 0))
        theme.label(
            body,
            text=item_view.station_subtitle,
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.xs, spacing.sm))

        facts = tk.Frame(body, bg=theme.palette.surface)
        facts.pack(fill="x")
        self._build_preview_fact(facts, label="Source", value=item_view.source_text, tone=item_view.badge_tone).pack(side="left", padx=(0, spacing.lg))
        self._build_preview_fact(facts, label="Status", value=item_view.status_text, tone=item_view.badge_tone).pack(side="left", padx=(0, spacing.lg))
        self._build_preview_fact(facts, label="Health", value=item_view.health_score_text, tone="primary").pack(side="left")

        theme.divider(body, tone="soft").pack(fill="x", pady=spacing.sm)
        theme.label(
            body,
            text=item_view.context_text,
            role="body",
            tone="primary",
            background=theme.palette.surface,
            wraplength=390,
        ).pack(anchor="w")
        theme.label(
            body,
            text=item_view.observed_text,
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.sm, 0))
        theme.label(
            body,
            text=f"Latest reading | {item_view.reading_text}",
            role="mono",
            tone="primary",
            background=theme.palette.surface,
            wraplength=390,
        ).pack(anchor="w", pady=(spacing.xs, 0))
        return card

    def _build_region_card(self, master: tk.Misc, region_view: RegionHealthViewModel) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        card = theme.panel(master, tone="surface")
        body = tk.Frame(card, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)

        header = tk.Frame(body, bg=theme.palette.surface)
        header.pack(fill="x")
        theme.pill(header, text=region_view.region_name.upper(), tone=region_view.tone).pack(side="left")
        theme.label(
            header,
            text=region_view.health_score_text,
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(side="right")
        theme.label(
            body,
            text=region_view.station_mix_text,
            role="body_strong",
            tone="primary",
            background=theme.palette.surface,
            wraplength=200,
        ).pack(anchor="w", pady=(spacing.sm, spacing.xs))
        theme.label(
            body,
            text=region_view.signal_text,
            role="body",
            tone="muted",
            background=theme.palette.surface,
            wraplength=200,
        ).pack(anchor="w")
        return card

    def _build_priority_watchlist(self, master: tk.Misc) -> None:
        theme = self._theme
        spacing = theme.spacing

        body = tk.Frame(master, bg=theme.palette.surface_alt)
        body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)
        theme.label(
            body,
            text="Priority Stations",
            role="card_title",
            tone="primary",
            background=theme.palette.surface_alt,
        ).pack(anchor="w")
        theme.label(
            body,
            text="The fleet score ranks these sites first for operator review based on status, health score, and telemetry watch signals.",
            role="body",
            tone="muted",
            background=theme.palette.surface_alt,
            wraplength=420,
        ).pack(anchor="w", pady=(spacing.xs, spacing.md))

        for index, station_view in enumerate(self._overview_view_model.priority_cards):
            card = self._build_priority_station_card(body, station_view)
            card.pack(fill="x", pady=(0, spacing.sm if index < len(self._overview_view_model.priority_cards) - 1 else 0))

    def _build_priority_station_card(self, master: tk.Misc, station_view: PriorityStationViewModel) -> tk.Frame:
        theme = self._theme
        spacing = theme.spacing

        card = theme.panel(master, tone="surface")
        accent_rail = tk.Frame(card, bg=theme.tone_color(station_view.badge_tone), width=5)
        accent_rail.pack(side="left", fill="y")

        body = tk.Frame(card, bg=theme.palette.surface)
        body.pack(fill="both", expand=True, padx=spacing.md, pady=spacing.md)

        top_row = tk.Frame(body, bg=theme.palette.surface)
        top_row.pack(fill="x")
        theme.pill(top_row, text=station_view.badge_text, tone=station_view.badge_tone).pack(side="left")
        theme.label(
            top_row,
            text=station_view.health_score_text,
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(side="right")

        theme.label(
            body,
            text=station_view.title,
            role="card_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.sm, 0))
        theme.label(
            body,
            text=station_view.subtitle,
            role="caption",
            tone="muted",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.xs, spacing.sm))
        theme.label(
            body,
            text=station_view.telemetry_text,
            role="caption",
            tone="signal",
            background=theme.palette.surface,
        ).pack(anchor="w")
        theme.label(
            body,
            text=station_view.metric_text,
            role="mono",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w", pady=(spacing.xs, spacing.sm))
        theme.divider(body, tone="soft").pack(fill="x", pady=(0, spacing.sm))
        theme.label(
            body,
            text=station_view.focus_text,
            role="body",
            tone="primary",
            background=theme.palette.surface,
            wraplength=420,
        ).pack(anchor="w")
        return card


def create_desktop_shell(context: DesktopShellContext) -> TelemetryDesktopShell:
    return TelemetryDesktopShell(context)


def launch_desktop_shell(context: DesktopShellContext) -> None:
    shell = create_desktop_shell(context)
    shell.mainloop()


def _resolve_dataset_descriptor(
    descriptors: Sequence[DatasetDescriptor],
    dataset_key: str,
) -> DatasetDescriptor:
    available = tuple(descriptors)
    if not available:
        raise LookupError("No datasets are available to the desktop shell.")
    for descriptor in available:
        if descriptor.dataset_key == dataset_key:
            return descriptor
    return available[0]


def _resolve_reference_time(telemetry_repository: TelemetryRepository) -> datetime:
    latest = telemetry_repository.list_readings(TelemetryQuery(newest_first=True, limit=1))
    if latest:
        return latest[0].recorded_at
    return datetime.now(timezone.utc)


def _station_count(station_repository: StationRepository) -> int:
    station_count = getattr(station_repository, "station_count", None)
    if isinstance(station_count, int):
        return station_count
    return len(station_repository.list_stations())


def _reading_count(telemetry_repository: TelemetryRepository) -> int:
    reading_count = getattr(telemetry_repository, "reading_count", None)
    if isinstance(reading_count, int):
        return reading_count
    return len(telemetry_repository.list_readings())


def _format_dataset_updated_at(descriptor: DatasetDescriptor) -> str:
    if descriptor.updated_at is None:
        return "Unknown"
    return descriptor.updated_at.astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC")


def _default_dataset_action_text(descriptor: DatasetDescriptor, *, imports_dir: object) -> str:
    return (
        f"{descriptor.label} is active. Use Refresh Active to reload it from disk, or drop a manifest "
        f"or CSV pair into '{imports_dir}' and click Import Staged."
    )


def _import_report_text(report: DatasetImportReport) -> str:
    if report.imported_count > 0:
        imported_labels = ", ".join(item.label for item in report.imported_datasets[:2])
        if report.imported_count > 2:
            imported_labels = f"{imported_labels}, +{report.imported_count - 2} more"
        issue_suffix = ""
        if report.warning_count or report.error_count:
            issue_suffix = (
                f" Review {report.warning_count} warning(s) and {report.error_count} error(s) "
                "in the import log."
            )
        return (
            f"Imported {report.imported_count} dataset(s) from {report.discovered_sources} staged source(s): "
            f"{imported_labels}. Select a dataset key above to load it.{issue_suffix}"
        )
    if report.error_count > 0:
        return (
            f"Import scan found {report.error_count} error(s) across {report.discovered_sources} staged source(s). "
            "No datasets were promoted into the runtime catalog."
        )
    if report.warning_count > 0:
        return (
            f"Import scan completed with {report.warning_count} warning(s) and no promoted datasets. "
            "Check the staged files in the imports directory and try again."
        )
    return (
        "No import-ready datasets were found. Stage a manifest or paired station/telemetry CSV files in the "
        "imports directory, then click Import Staged again."
    )


def _command_post_text(snapshot: FleetHealthSnapshot, *, anomaly_count: int) -> str:
    threshold_text = (
        "No threshold breaches are active."
        if snapshot.active_alert_count == 0
        else f"{snapshot.active_alert_count} threshold breaches are active."
    )
    anomaly_text = (
        "Telemetry watch is clear."
        if anomaly_count == 0
        else f"{anomaly_count} telemetry anomalies remain on the watchlist."
    )
    return (
        f"Fleet score is {snapshot.fleet_health_score:.2f}/100 with "
        f"{snapshot.warning_stations + snapshot.critical_stations} stations currently prioritized. "
        f"{threshold_text} {anomaly_text}"
    )


def _default_sort_direction(sort_key: str) -> bool:
    return sort_key in {"load", "temperature", "signals", "updated"}


def _sort_label(sort_key: str) -> str:
    labels = {
        "priority": "priority ranking",
        "station": "station name",
        "region": "region",
        "status": "status",
        "health": "health score",
        "updated": "last updated",
        "load": "load",
        "temperature": "temperature",
        "signals": "signal count",
    }
    return labels.get(sort_key, sort_key)


def _signal_tone(row: StationExplorerRowViewModel) -> str:
    if row.signal_count > 0:
        return row.status_tone if row.status_tone != "signal" else "warning"
    if row.is_priority:
        return row.status_tone
    return "signal"


def _history_signal_tone(dashboard: StationHistoryDashboardViewModel) -> str:
    if dashboard.active_signal_text == "Clear":
        return "signal"
    if "threshold" in dashboard.active_signal_text and "anomaly" in dashboard.active_signal_text:
        return "critical"
    if "threshold" in dashboard.active_signal_text:
        return "warning"
    return "accent"
