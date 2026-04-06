from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from datetime import datetime, timezone

from stellanex_telemetry.application import (
    FleetHealthAggregator,
    FleetHealthSnapshot,
    StationDetailQueryService,
    TelemetryQuery,
    ThresholdAlertPolicyEngine,
    TelemetryAnomalyDetector,
)
from stellanex_telemetry.application.contracts import StationRepository, TelemetryRepository
from stellanex_telemetry.config import AppConfig
from stellanex_telemetry.presentation.theme import DesktopTheme, build_desktop_theme


@dataclass(frozen=True, slots=True)
class DesktopShellContext:
    config: AppConfig
    station_repository: StationRepository
    telemetry_repository: TelemetryRepository
    alert_engine: ThresholdAlertPolicyEngine
    anomaly_detector: TelemetryAnomalyDetector
    health_aggregator: FleetHealthAggregator
    station_detail_service: StationDetailQueryService


class TelemetryDesktopShell(tk.Tk):
    """Desktop shell scaffold for the operator console."""

    def __init__(self, context: DesktopShellContext, *, theme: DesktopTheme | None = None) -> None:
        super().__init__()
        self._context = context
        self._theme = theme or build_desktop_theme()
        self._theme.apply_window(self)
        self._reference_time = _resolve_reference_time(context.telemetry_repository)
        self._fleet_snapshot = context.health_aggregator.build_snapshot(
            context.station_repository,
            context.telemetry_repository,
            generated_at=self._reference_time,
        )
        self._section_hosts: dict[str, tk.Frame] = {}
        self._signal_canvas: tk.Canvas | None = None

        self.title(context.config.app_name)
        self.geometry("1460x920")
        self.minsize(1240, 820)

        self._build_shell()
        self.bind("<Configure>", self._on_resize)

    @property
    def fleet_snapshot(self) -> FleetHealthSnapshot:
        return self._fleet_snapshot

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
        theme.pill(eyebrow_row, text="LIVE DEMO DATASET", tone="dark").pack(side="left", padx=(0, spacing.sm))
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

        stats = tk.Frame(left, bg=theme.palette.surface_dark)
        stats.pack(anchor="w", pady=(spacing.md, 0))
        self._build_stat_chip(stats, "Stations", str(_station_count(self._context.station_repository)))
        self._build_stat_chip(stats, "Telemetry", str(_reading_count(self._context.telemetry_repository)))
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
            body="Desktop shell is now live and wired to the repositories. The next commits will fill these zones with KPIs, explorer controls, charts, and alert workflows.",
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
            text="Dataset Wiring",
            role="card_title",
            tone="primary",
            background=theme.palette.surface,
        ).pack(anchor="w")
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

        theme.divider(content).pack(fill="x", pady=spacing.md)
        theme.label(
            content,
            text="Upcoming build order: overview widgets, station explorer, charts, alert stream, then narrative insights.",
            role="body",
            tone="muted",
            background=theme.palette.surface_alt,
            wraplength=190,
        ).pack(anchor="w")

    def _build_workspace(self, master: tk.Frame) -> None:
        theme = self._theme
        spacing = theme.spacing

        overview_host = self._create_placeholder_panel(
            master,
            title="Fleet Overview Workbench",
            eyebrow="STAGE 1",
            description=(
                "The shell is already fed by live fleet health data. In the next commit this host will become "
                "the KPI strip and critical-station summary deck."
            ),
            footnote=f"Current fleet score {self._fleet_snapshot.fleet_health_score:.2f} across {self._fleet_snapshot.total_stations} stations.",
        )
        overview_host.grid(row=0, column=0, sticky="nsew", padx=(0, spacing.md), pady=(0, spacing.md))
        self._section_hosts["overview"] = overview_host

        inbox_host = self._create_placeholder_panel(
            master,
            title="Signal Inbox",
            eyebrow="STAGE 2",
            description=(
                "This rail is reserved for active alerts and operator context. Right now it mirrors which "
                "stations would be surfaced first once the alert widgets land."
            ),
            footnote=_priority_station_text(self._fleet_snapshot),
        )
        inbox_host.grid(row=0, column=1, sticky="nsew", pady=(0, spacing.md))
        self._section_hosts["alerts"] = inbox_host

        explorer_host = self._create_placeholder_panel(
            master,
            title="Station Explorer Bay",
            eyebrow="STAGE 3",
            description=(
                "Search, region filters, and sortable station tables will mount here next. The shell layout "
                "already reserves a wide pane so the explorer can coexist with the analytics views."
            ),
            footnote="Reserved for commit 15: station explorer with filters and sort controls.",
        )
        explorer_host.grid(row=1, column=0, sticky="nsew", padx=(0, spacing.md))
        self._section_hosts["explorer"] = explorer_host

        insight_host = self._create_placeholder_panel(
            master,
            title="Insight Narrative Deck",
            eyebrow="STAGE 4",
            description=(
                "Historical charts, operator recommendations, and natural-language diagnostic notes will land "
                "here after the shell, overview, and explorer commits are in place."
            ),
            footnote="Reserved for commits 16 through 18: charts, alert context, and operator insights.",
        )
        insight_host.grid(row=1, column=1, sticky="nsew")
        self._section_hosts["insights"] = insight_host

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


def create_desktop_shell(context: DesktopShellContext) -> TelemetryDesktopShell:
    return TelemetryDesktopShell(context)


def launch_desktop_shell(context: DesktopShellContext) -> None:
    shell = create_desktop_shell(context)
    shell.mainloop()


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


def _priority_station_text(snapshot: FleetHealthSnapshot) -> str:
    top_stations = snapshot.top_priority_stations(3)
    if not top_stations:
        return "No priority stations are available yet."
    return "Priority sequence: " + " | ".join(
        f"{station_snapshot.station.station_id} ({station_snapshot.derived_status.value}, {station_snapshot.health_score}/100)"
        for station_snapshot in top_stations
    )
