from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ColorPalette:
    background: str
    surface: str
    surface_alt: str
    surface_dark: str
    border: str
    accent: str
    accent_soft: str
    signal: str
    warning: str
    critical: str
    text_primary: str
    text_muted: str
    text_on_dark: str


@dataclass(frozen=True, slots=True)
class TypographyScale:
    hero_title: tuple[str, int, str]
    section_title: tuple[str, int, str]
    card_title: tuple[str, int, str]
    body: tuple[str, int]
    body_strong: tuple[str, int, str]
    caption: tuple[str, int]
    mono: tuple[str, int]


@dataclass(frozen=True, slots=True)
class SpacingScale:
    xs: int = 6
    sm: int = 10
    md: int = 16
    lg: int = 24
    xl: int = 32


@dataclass(frozen=True, slots=True)
class DesktopTheme:
    palette: ColorPalette
    typography: TypographyScale
    spacing: SpacingScale

    def apply_window(self, root: tk.Tk) -> None:
        root.configure(bg=self.palette.background)

    def panel(self, master: tk.Misc, *, tone: str = "surface") -> tk.Frame:
        return tk.Frame(
            master,
            bg=self._surface_color(tone),
            bd=0,
            highlightthickness=1,
            highlightbackground=self.palette.border,
        )

    def label(
        self,
        master: tk.Misc,
        *,
        text: str,
        role: str = "body",
        tone: str = "primary",
        background: str | None = None,
        anchor: str = "w",
        justify: str = "left",
        wraplength: int | None = None,
    ) -> tk.Label:
        kwargs: dict[str, object] = {
            "text": text,
            "font": self._font(role),
            "fg": self._text_color(tone),
            "bg": background or self.palette.background,
            "anchor": anchor,
            "justify": justify,
            "bd": 0,
        }
        if wraplength is not None:
            kwargs["wraplength"] = wraplength
        return tk.Label(master, **kwargs)

    def pill(self, master: tk.Misc, *, text: str, tone: str = "accent") -> tk.Label:
        background, foreground = self._pill_colors(tone)
        return tk.Label(
            master,
            text=text,
            font=self.typography.caption,
            fg=foreground,
            bg=background,
            padx=self.spacing.sm,
            pady=self.spacing.xs // 2,
            bd=0,
        )

    def nav_button(self, master: tk.Misc, *, text: str, selected: bool = False) -> tk.Button:
        background = self.palette.surface_dark if selected else self.palette.surface_alt
        foreground = self.palette.text_on_dark if selected else self.palette.text_primary
        active_background = self.palette.accent if selected else self.palette.surface
        active_foreground = self.palette.text_on_dark if selected else self.palette.text_primary
        return tk.Button(
            master,
            text=text,
            font=self.typography.body_strong,
            fg=foreground,
            bg=background,
            activeforeground=active_foreground,
            activebackground=active_background,
            relief="flat",
            bd=0,
            padx=self.spacing.md,
            pady=self.spacing.sm,
            anchor="w",
            highlightthickness=0,
            cursor="arrow",
        )

    def divider(self, master: tk.Misc, *, vertical: bool = False, tone: str = "border") -> tk.Frame:
        color = self.palette.border if tone == "border" else self.palette.accent_soft
        if vertical:
            return tk.Frame(master, bg=color, width=1)
        return tk.Frame(master, bg=color, height=1)

    def paint_signal_canvas(self, canvas: tk.Canvas) -> None:
        palette = self.palette
        width = max(canvas.winfo_width(), 1)
        height = max(canvas.winfo_height(), 1)
        canvas.delete("signal")
        canvas.configure(bg=palette.surface_dark, highlightthickness=0, bd=0)

        for row_index in range(0, height, 26):
            canvas.create_line(
                0,
                row_index,
                width,
                row_index,
                fill="#31434D",
                width=1,
                tags="signal",
            )
        for offset in range(-height, width + height, 28):
            canvas.create_line(
                offset,
                0,
                offset + height,
                height,
                fill="#3A515B",
                width=1,
                tags="signal",
            )

        marker_width = max(width // 8, 14)
        for index in range(5):
            x0 = width - ((index + 1) * (marker_width + 10))
            x1 = x0 + marker_width
            y1 = height - 20
            y0 = y1 - ((index + 2) * 14)
            fill = palette.accent if index % 2 == 0 else palette.signal
            canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="", tags="signal")

    def _surface_color(self, tone: str) -> str:
        surfaces = {
            "surface": self.palette.surface,
            "surface_alt": self.palette.surface_alt,
            "dark": self.palette.surface_dark,
        }
        return surfaces[tone]

    def _text_color(self, tone: str) -> str:
        tones = {
            "primary": self.palette.text_primary,
            "muted": self.palette.text_muted,
            "dark": self.palette.text_on_dark,
            "accent": self.palette.accent,
            "warning": self.palette.warning,
            "critical": self.palette.critical,
            "signal": self.palette.signal,
        }
        return tones[tone]

    def _font(self, role: str) -> tuple[str, int] | tuple[str, int, str]:
        fonts = {
            "hero_title": self.typography.hero_title,
            "section_title": self.typography.section_title,
            "card_title": self.typography.card_title,
            "body": self.typography.body,
            "body_strong": self.typography.body_strong,
            "caption": self.typography.caption,
            "mono": self.typography.mono,
        }
        return fonts[role]

    def _pill_colors(self, tone: str) -> tuple[str, str]:
        colors = {
            "accent": (self.palette.accent_soft, self.palette.accent),
            "signal": ("#DDEDE8", self.palette.signal),
            "warning": ("#F4E1CC", self.palette.warning),
            "critical": ("#F0D7D3", self.palette.critical),
            "neutral": ("#E8E1D8", self.palette.text_primary),
            "dark": ("#31434D", self.palette.text_on_dark),
        }
        return colors[tone]


def build_desktop_theme() -> DesktopTheme:
    return DesktopTheme(
        palette=ColorPalette(
            background="#EFE8DC",
            surface="#FBF7F0",
            surface_alt="#F3ECE1",
            surface_dark="#1F2C33",
            border="#D5C6B1",
            accent="#B86A30",
            accent_soft="#EEDBC6",
            signal="#25716A",
            warning="#A4631F",
            critical="#9A4436",
            text_primary="#1F262A",
            text_muted="#5F696C",
            text_on_dark="#F7F3ED",
        ),
        typography=TypographyScale(
            hero_title=("Bahnschrift SemiBold", 24, "bold"),
            section_title=("Bahnschrift SemiBold", 18, "bold"),
            card_title=("Bahnschrift SemiBold", 14, "bold"),
            body=("Segoe UI", 10),
            body_strong=("Segoe UI Semibold", 10, "bold"),
            caption=("Segoe UI", 9),
            mono=("Cascadia Code", 9),
        ),
        spacing=SpacingScale(),
    )
