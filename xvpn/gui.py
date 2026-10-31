"""xVPN Manager desktop interface, inspired by familiar list-based desktop managers.

All tunnel operations remain in VPNBackend. In particular, displaying 'Active*'
never means successful traffic routing; users must verify their public IP.
"""
from __future__ import annotations

import ctypes
from datetime import datetime
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import webbrowser

from .branding import apply_application_icon, load_header_icon
from .backend import VPNBackend, VPNError, ConnectionAttempt
from .config_parser import ConfigError, parse_config
from .config_tools import make_mtu_test_copy, wireguard_settings
from .models import VPNProfile
from .prefs import Preferences
from .proton import (ProtonStatus, read_proton_status, launch_proton_app, find_proton_app,
                     PROTON_CONFIG_URL, PROTON_DOWNLOAD_URL, PROTON_PROCESS_NAMES)
from .store import ProfileStore
from .ui_logic import visible_profiles, sort_profiles, count_active, is_active_state

VERSION = "1.3.5"
PROVIDERS = {
    "Proton VPN": PROTON_DOWNLOAD_URL,
    "Windscribe": "https://windscribe.com/",
    "WireGuard": "https://www.wireguard.com/install/",
    "OpenVPN": "https://openvpn.net/community-downloads/",
}
PALETTES = {
    "light": dict(bg="#edf1f6", card="#ffffff", panel="#ffffff", text="#1b2a41",
                  secondary="#63758c", border="#d9e2ed", toolbar="#f7f9fc",
                  selection="#dceeff", select_text="#143e6e", heading="#f2f6fa",
                  blue="#1e67bd", green="#137e53", red="#b44747", log="#f9fbfd",
                  tree_alt="#f7fafd", disabled="#a5b3c3"),
    "dark": dict(bg="#111b2a", card="#182639", panel="#182639", text="#ecf3ff",
                 secondary="#a0b2ca", border="#32445b", toolbar="#1c2d43",
                 selection="#25486c", select_text="#ffffff", heading="#22364f",
                 blue="#60a5fa", green="#56d49b", red="#f18787", log="#162234",
                 tree_alt="#1b2b40", disabled="#61758b"),
}


class ProfileDialog(simpledialog.Dialog):
    """Editable display metadata. The destination country is NOT auto-verified."""

    def __init__(self, parent: tk.Misc, filename: str, profile: VPNProfile | None = None):
        self.filename = filename
        self.profile = profile
        self.result: tuple[str, str, str] | None = None
        super().__init__(parent, "Edit VPN profile" if profile else "Add VPN profile")

    def body(self, master: tk.Misc) -> tk.Widget:
        master.configure(padx=14, pady=12)
        self.name_var = tk.StringVar(value=self.profile.name if self.profile else Path(self.filename).stem)
        self.provider_var = tk.StringVar(value=self.profile.provider if self.profile else "Other / Custom")
        self.country_var = tk.StringVar(value=self.profile.country if self.profile else "Unknown")
        values = (
            ("Display name", self.name_var),
            ("VPN provider", self.provider_var),
            ("Country label", self.country_var),
        )
        for idx, (label, var) in enumerate(values):
            ttk.Label(master, text=label).grid(row=idx, column=0, sticky="w", padx=(0, 14), pady=7)
            if idx == 2:
                entry = ttk.Combobox(master, textvariable=var, width=36, values=(
                    "United States", "South Korea", "Japan", "Singapore", "Vietnam",
                    "Germany", "United Kingdom", "Netherlands", "Canada", "Unknown",
                ))
            elif idx == 1:
                entry = ttk.Combobox(master, textvariable=var, width=36, values=(
                    "Proton VPN", "Windscribe", "Other / Custom", "Private VPN",
                ))
            else:
                entry = ttk.Entry(master, textvariable=var, width=38)
            entry.grid(row=idx, column=1, sticky="ew", pady=7)
            if idx == 0:
                focus_widget = entry
        ttk.Label(master, text="Country is a display label; it does not change the VPN IP.",
                  foreground="#65758b").grid(row=3, column=0, columnspan=2, pady=(7, 0), sticky="w")
        master.columnconfigure(1, weight=1)
        return focus_widget

    def validate(self) -> bool:
        if not self.name_var.get().strip():
            messagebox.showwarning("Profile name", "Enter a name for this VPN profile.", parent=self)
            return False
        return True

    def apply(self) -> None:
        self.result = (self.name_var.get().strip(),
                       self.provider_var.get().strip() or "Other / Custom",
                       self.country_var.get().strip() or "Unknown")


class VPNManagerApp(tk.Tk):
    def __init__(self, store: ProfileStore | None = None, backend: VPNBackend | None = None,
                 prefs: Preferences | None = None) -> None:
        super().__init__()
        self.title(f"xVPN Manager {VERSION}")
        self._app_icon_loaded = apply_application_icon(self)
        self._center(1190, 770)
        self.minsize(990, 645)
        self.store = store or ProfileStore()
        self.prefs = prefs or Preferences()
        self.backend = backend or VPNBackend()
        self.profiles = self.store.load()
        for profile in self.profiles:
            profile.latency_ms = None  # Older DNS timings were not VPN latency.
        settings = self.prefs.load()
        self.theme_var = tk.StringVar(value=settings["theme"])
        self.proton_app_path = settings.get("proton_path", "")
        self.search_var = tk.StringVar()
        self.ip_var = tk.StringVar(value="Not checked")
        self.ip_location_var = tk.StringVar(value="Use Check IP to verify routing")
        self.connection_var = tk.StringVar(value="Checking tunnel state...")
        self.proton_state_var = tk.StringVar(value="Detecting Proton VPN...")
        self.proton_detail_var = tk.StringVar(value="Checking your installed Proton VPN application.")
        self.proton_install_var = tk.StringVar(value="Installation: checking...")
        self.proton_process_var = tk.StringVar(value="Application: checking...")
        self.proton_adapter_var = tk.StringVar(value="VPN adapter: checking...")
        self.proton_missing_var = tk.StringVar(value="Checking whether Proton VPN is installed...")
        self._missing_notice_shown = False
        self.proton_status = ProtonStatus(supported=(os.name == "nt"), installed=False)
        self.profile_count_var = tk.StringVar(value="0 profiles")
        self.selected_hint_var = tk.StringVar(value="Select a VPN profile")
        self.status_var = tk.StringVar(value="Ready  ·  Import .conf or .ovpn files to begin")
        self.filter_var = tk.StringVar(value="All profiles")
        self.details_var = tk.StringVar(value="Choose a profile to view its details.")
        self.endpoint_var = tk.StringVar(value="—")
        self.config_var = tk.StringVar(value="—")
        self.provider_var = tk.StringVar(value="—")
        self.country_var = tk.StringVar(value="—")
        self.protocol_var = tk.StringVar(value="—")
        self.state_detail_var = tk.StringVar(value="—")
        self.state_count_var = tk.StringVar(value="No active tunnels detected")
        self.busy = False
        self._closed = False
        self._polling = False
        self._sort_column = "name"
        self._sort_reverse = False
        self._category = "all"
        self.states: dict[str, str] = {}
        self.events: queue.Queue = queue.Queue()
        self.action_buttons: list[ttk.Button] = []
        self._sidebar_items: dict[str, str] = {}
        self._build_menu()
        self._make_styles()
        self._build_ui()
        self._apply_theme()
        self._refresh()
        self._log("Started xVPN Manager. Proton sign-in remains in the official app; adapter status is not proof of routing.")
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.search_var.trace_add("write", lambda *_: self._refresh())
        self.bind("<Control-o>", lambda _e: self._import())
        self.bind("<Control-f>", self._focus_search)
        self.bind("<Control-i>", lambda _e: self._check_ip())
        self.bind("<F5>", lambda _e: self._refresh_now())
        self.after(150, self._drain)
        self.after(250, self._poll_states)
        self.after(350, self._position_panes)

    def _center(self, width: int, height: int) -> None:
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(width, max(800, screen_width - 40))
        height = min(height, max(600, screen_height - 65))
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _make_styles(self) -> None:
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=0)
        file_menu.add_command(label="Add VPN profiles...     Ctrl+O", command=self._import)
        file_menu.add_command(label="Edit selected profile...", command=self._edit)
        file_menu.add_command(label="Remove selected profile", command=self._remove)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close)
        menu.add_cascade(label="File", menu=file_menu)
        self.view_menu = tk.Menu(menu, tearoff=0)
        self.view_menu.add_radiobutton(label="Light theme", variable=self.theme_var, value="light", command=self._change_theme)
        self.view_menu.add_radiobutton(label="Dark theme", variable=self.theme_var, value="dark", command=self._change_theme)
        self.view_menu.add_separator()
        self.view_menu.add_command(label="Refresh states     F5", command=self._refresh_now)
        menu.add_cascade(label="View", menu=self.view_menu)
        connection_menu = tk.Menu(menu, tearoff=0)
        connection_menu.add_command(label="Connect selected", command=self._connect)
        connection_menu.add_command(label="Disconnect selected", command=self._disconnect)
        connection_menu.add_command(label="Verify public IP     Ctrl+I", command=self._check_ip)
        connection_menu.add_command(label="Test TCP response (TCP OpenVPN only)", command=self._test)
        connection_menu.add_command(label="WireGuard diagnostics and MTU test...", command=self._diagnostics)
        menu.add_cascade(label="Connection", menu=connection_menu)
        tools_menu = tk.Menu(menu, tearoff=0)
        tools_menu.add_command(label="Open Proton VPN (official app)", command=self._open_proton)
        tools_menu.add_command(label="Locate Proton VPN executable...", command=self._locate_proton)
        tools_menu.add_command(label="Proton VPN configuration downloads", command=self._proton_configs)
        tools_menu.add_command(label="WireGuard diagnostics and MTU test...", command=self._diagnostics)
        tools_menu.add_separator()
        tools_menu.add_command(label="Setup and help", command=self._setup)
        tools_menu.add_command(label="Official VPN websites", command=self._providers)
        tools_menu.add_command(label="Restart as administrator (Windows)", command=self._elevate)
        menu.add_cascade(label="Tools", menu=tools_menu)
        help_menu = tk.Menu(menu, tearoff=0)
        help_menu.add_command(label=f"About xVPN Manager {VERSION}", command=self._about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menu)

    def _build_ui(self) -> None:
        # Compact qBittorrent-style structure: menu, toolbar, filters, list, detail tabs, status.
        self.header = tk.Frame(self, padx=18, pady=12)
        self.header.pack(fill="x")
        self._header_icon_image = load_header_icon(self)
        self.brand_icon = None
        if self._header_icon_image is not None:
            self.brand_icon = tk.Label(self.header, image=self._header_icon_image, borderwidth=0)
            self.brand_icon.pack(side="left", padx=(0, 11))
        self.brand = tk.Label(self.header, text="xVPN", font=("Segoe UI", 24, "bold"), anchor="w")
        self.brand.pack(side="left")
        self.tagline = tk.Label(self.header, text="   VPN CONTROL CENTER", font=("Segoe UI", 10, "bold"))
        self.tagline.pack(side="left", pady=(9, 0))
        self.security_note = tk.Label(self.header, text="Local profile control  •  No account password stored", font=("Segoe UI", 9))
        self.security_note.pack(side="right", pady=(9, 0))

        self.toolbar = ttk.Frame(self, padding=(13, 9))
        self.toolbar.pack(fill="x")
        self._tool_button(self.toolbar, "+  Add Profile", self._import, "Blue.TButton")
        self.toolbar_connect = self._tool_button(self.toolbar, "▶  Connect", self._connect, "Connect.TButton")
        self.toolbar_disconnect = self._tool_button(self.toolbar, "■  Disconnect", self._disconnect, "Tool.TButton")
        ttk.Separator(self.toolbar, orient="vertical").pack(side="left", fill="y", padx=12, pady=3)
        self._tool_button(self.toolbar, "↻  Check IP", self._check_ip, "Tool.TButton")
        self._tool_button(self.toolbar, "◈  Proton VPN", self._open_proton, "Blue.TButton")
        self._tool_button(self.toolbar, "⟳  Refresh", self._refresh_now, "Tool.TButton")
        ttk.Button(self.toolbar, text="Setup / Help", command=self._setup, style="Tool.TButton").pack(side="right", padx=4)

        self.overview_strip = tk.Frame(self, padx=17, pady=10)
        self.overview_strip.pack(fill="x")
        self.metric_a = self._metric(self.overview_strip, "VPN STATUS", self.connection_var)
        self.metric_b = self._metric(self.overview_strip, "PUBLIC IP", self.ip_var)
        self.metric_c = self._metric(self.overview_strip, "IP LOCATION", self.ip_location_var)
        self.metric_d = self._metric(self.overview_strip, "PROFILE LIBRARY", self.profile_count_var)

        # Pinned official-app status card, visible even with an empty profile library.
        self.proton_banner = tk.Frame(self, padx=15, pady=11, highlightthickness=1)
        self.proton_banner.pack(fill="x", padx=17, pady=(1, 5))
        self.proton_title = tk.Label(self.proton_banner, text="PROTON VPN  ·  OFFICIAL APP", font=("Segoe UI", 11, "bold"), anchor="w")
        self.proton_title.pack(side="left", padx=(0, 17))
        self.proton_status_label = tk.Label(self.proton_banner, textvariable=self.proton_state_var, font=("Segoe UI", 10, "bold"), anchor="w")
        self.proton_status_label.pack(side="left", fill="x", expand=True)
        ttk.Button(self.proton_banner, text="Open / Sign in", style="Blue.TButton", command=self._open_proton).pack(side="right", padx=(8, 0))
        ttk.Button(self.proton_banner, text="Details", style="Small.TButton", command=self._show_proton_tab).pack(side="right")
        self.proton_download_banner = ttk.Button(self.proton_banner, text="Download Proton VPN", style="Small.TButton", command=self._download_proton)
        # The download link sits in the always-visible banner when absent.
        # It is hidden when the official application is detected.

        self.content = ttk.Panedwindow(self, orient="horizontal")
        self.content.pack(fill="both", expand=True, padx=16, pady=(7, 0))
        self.left = ttk.Frame(self.content, width=220)
        self.content.add(self.left, weight=0)
        self.left.pack_propagate(False)
        self._sidebar_title = ttk.Label(self.left, text="  FILTERS", style="Section.TLabel")
        self._sidebar_title.pack(anchor="w", fill="x", pady=(0, 5))
        side_holder = ttk.Frame(self.left)
        side_holder.pack(fill="both", expand=True)
        self.sidebar = ttk.Treeview(side_holder, show="tree", selectmode="browse", style="Sidebar.Treeview")
        side_scroll = ttk.Scrollbar(side_holder, orient="vertical", command=self.sidebar.yview)
        self.sidebar.configure(yscrollcommand=side_scroll.set)
        side_scroll.pack(side="right", fill="y")
        self.sidebar.pack(side="left", fill="both", expand=True)
        self.sidebar.bind("<<TreeviewSelect>>", self._sidebar_changed)

        self.right = ttk.Frame(self.content)
        self.content.add(self.right, weight=1)
        list_header = ttk.Frame(self.right, padding=(12, 8))
        list_header.pack(fill="x")
        ttk.Label(list_header, text="VPN CONNECTIONS", style="Section.TLabel").pack(side="left")
        self.filter_label = ttk.Label(list_header, textvariable=self.filter_var, style="Muted.TLabel")
        self.filter_label.pack(side="left", padx=12)
        ttk.Button(list_header, text="Clear", command=self._clear_search, style="Small.TButton").pack(side="right", padx=(5, 0))
        self.search_entry = ttk.Entry(list_header, textvariable=self.search_var, width=30)
        self.search_entry.pack(side="right", padx=(5, 0))
        ttk.Label(list_header, text="Search:", style="Muted.TLabel").pack(side="right")

        self.right_split = ttk.Panedwindow(self.right, orient="vertical")
        self.right_split.pack(fill="both", expand=True)
        table_holder = ttk.Frame(self.right_split)
        self.right_split.add(table_holder, weight=4)
        cols = ("status", "name", "country", "provider", "protocol", "endpoint", "response")
        self.tree = ttk.Treeview(table_holder, columns=cols, show="headings", selectmode="browse", style="VPN.Treeview")
        self._columns = {
            "status": ("Status*", 99), "name": ("Profile", 180),
            "country": ("Country", 125), "provider": ("Provider", 132),
            "protocol": ("Protocol", 86), "endpoint": ("Server endpoint", 175),
            "response": ("TCP ms", 72),
        }
        for col, (heading, width) in self._columns.items():
            self.tree.heading(col, text=heading, command=lambda column=col: self._sort_by(column))
            self.tree.column(col, width=width, minwidth=70, stretch=(col in ("name", "endpoint")))
        self.tree.column("response", anchor="e")
        self.tree.column("status", anchor="center")
        scroll_y = ttk.Scrollbar(table_holder, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(table_holder, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Double-1>", self._double_click)
        self.tree.bind("<Return>", lambda _e: self._toggle_selected())
        self.tree.bind("<Delete>", lambda _e: self._remove())
        self.tree.bind("<Button-3>", self._context_menu)

        bottom = ttk.Frame(self.right_split)
        self.right_split.add(bottom, weight=2)
        self.details_tabs = ttk.Notebook(bottom)
        self.details_tabs.pack(fill="both", expand=True)
        summary_tab = ttk.Frame(self.details_tabs, padding=(15, 10))
        info_tab = ttk.Frame(self.details_tabs, padding=(15, 10))
        history_tab = ttk.Frame(self.details_tabs, padding=(8, 8))
        self.details_tabs.add(summary_tab, text="Overview")
        self.details_tabs.add(info_tab, text="Configuration")
        self.details_tabs.add(history_tab, text="Activity log")
        self.proton_tab = ttk.Frame(self.details_tabs, padding=(15, 10))
        self.details_tabs.add(self.proton_tab, text="Proton VPN")
        ttk.Label(self.proton_tab, text="Proton VPN · Official app integration", style="DetailTitle.TLabel").pack(anchor="w", pady=(0, 5))
        ttk.Label(self.proton_tab, textvariable=self.proton_detail_var, style="Muted.TLabel", wraplength=710).pack(anchor="w", pady=(0, 7))
        health_row = ttk.Frame(self.proton_tab)
        health_row.pack(fill="x", pady=(0, 7))
        for item in (self.proton_install_var, self.proton_process_var, self.proton_adapter_var):
            ttk.Label(health_row, textvariable=item, style="Muted.TLabel").pack(side="left", padx=(0, 22))
        proton_actions = ttk.Frame(self.proton_tab)
        proton_actions.pack(anchor="w", pady=(0, 7))
        self._tool_button(proton_actions, "Open Proton / Sign in", self._open_proton, "Blue.TButton")
        self._tool_button(proton_actions, "Locate Proton App...", self._locate_proton, "Tool.TButton")
        self._tool_button(proton_actions, "Check IP", self._check_ip, "Tool.TButton")
        self._tool_button(proton_actions, "Import Proton config", self._import, "Tool.TButton")
        self._tool_button(proton_actions, "Get WireGuard config", self._proton_configs, "Tool.TButton")
        self._tool_button(proton_actions, "Download Proton VPN", self._download_proton, "Tool.TButton")
        ttk.Label(self.proton_tab, textvariable=self.proton_missing_var, style="Muted.TLabel",
                  wraplength=750).pack(anchor="w", pady=(0, 5))
        ttk.Label(self.proton_tab,
                  text="Official Proton app handles login and Connect/Disconnect. Adapter Up* is not proof of routing. "
                       "To connect directly in xVPN, import a Proton WireGuard .conf file (separate mode).",
                  style="Muted.TLabel", wraplength=730).pack(anchor="w")
        ttk.Label(summary_tab, textvariable=self.selected_hint_var, style="DetailTitle.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(summary_tab, textvariable=self.details_var, style="Muted.TLabel", wraplength=770).pack(anchor="w")
        summary_actions = ttk.Frame(summary_tab)
        summary_actions.pack(anchor="w", pady=(12, 0))
        self.detail_connect = self._tool_button(summary_actions, "Connect", self._connect, "Connect.TButton")
        self.detail_disconnect = self._tool_button(summary_actions, "Disconnect", self._disconnect, "Tool.TButton")
        ttk.Button(summary_actions, text="Edit details", command=self._edit, style="Small.TButton").pack(side="left", padx=(5, 0))
        ttk.Button(summary_actions, text="Diagnostics", command=self._diagnostics, style="Small.TButton").pack(side="left", padx=(5, 0))
        for idx, (label, value) in enumerate((
            ("Status", self.state_detail_var), ("Provider", self.provider_var),
            ("Country", self.country_var), ("Protocol", self.protocol_var),
            ("Endpoint", self.endpoint_var), ("Config file", self.config_var),
        )):
            row, col = divmod(idx, 2)
            ttk.Label(info_tab, text=label, style="Muted.TLabel").grid(row=row, column=2*col, sticky="w", padx=(0, 8), pady=6)
            ttk.Label(info_tab, textvariable=value).grid(row=row, column=2*col+1, sticky="w", padx=(0, 24), pady=6)
        info_tab.columnconfigure(1, weight=1)
        info_tab.columnconfigure(3, weight=1)
        log_scroll = ttk.Scrollbar(history_tab)
        log_scroll.pack(side="right", fill="y")
        self.log_text = tk.Text(history_tab, height=6, wrap="word", font=("Consolas", 10),
                                state="disabled", borderwidth=0, yscrollcommand=log_scroll.set)
        self.log_text.pack(fill="both", expand=True)
        log_scroll.configure(command=self.log_text.yview)

        self.bottom_bar = tk.Frame(self, padx=15, pady=8)
        self.bottom_bar.pack(side="bottom", fill="x", before=self.content)
        self.status_label = tk.Label(self.bottom_bar, textvariable=self.status_var, anchor="w", font=("Segoe UI", 9))
        self.status_label.pack(side="left", fill="x", expand=True)
        self.count_label = tk.Label(self.bottom_bar, textvariable=self.state_count_var, font=("Segoe UI", 9))
        self.count_label.pack(side="right")
        self.progress = ttk.Progressbar(self.bottom_bar, mode="indeterminate", length=75, style="Horizontal.TProgressbar")
        self.progress.pack(side="right", padx=10)
        self.progress.pack_forget()  # Shown only while an operation is running.
        self._context = tk.Menu(self, tearoff=0)
        for label, command in [
            ("Connect", self._connect), ("Disconnect", self._disconnect),
            ("Verify public IP", self._check_ip), ("Edit profile...", self._edit),
            ("Open configuration folder", self._open_config_folder),
            ("Remove profile", self._remove),
        ]:
            self._context.add_command(label=label, command=command)

    def _position_panes(self) -> None:
        """Give the details tabs room to show their buttons and the status bar."""
        if self._closed:
            return
        try:
            height = self.right_split.winfo_height()
            if height > 250:
                self.right_split.sashpos(0, max(135, int(height * 0.36)))
        except tk.TclError:
            pass

    def _metric(self, parent, title: str, variable: tk.StringVar) -> tk.Frame:
        container = tk.Frame(parent, padx=13, pady=10, highlightthickness=1)
        container.pack(side="left", fill="both", expand=True, padx=(0, 8))
        title_label = tk.Label(container, text=title, anchor="w", font=("Segoe UI", 9, "bold"))
        title_label.pack(fill="x")
        value_label = tk.Label(container, textvariable=variable, anchor="w", font=("Segoe UI", 12, "bold"))
        value_label.pack(fill="x", pady=(4, 0))
        container._metric_labels = (title_label, value_label)
        return container

    def _tool_button(self, parent, text: str, callback, style: str) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=callback, style=style)
        button.pack(side="left", padx=(0, 6))
        self.action_buttons.append(button)
        return button

    def _apply_theme(self) -> None:
        c = PALETTES[self.theme_var.get()]
        self.configure(bg=c["bg"])
        self.style.configure(".", font=("Segoe UI", 10), background=c["panel"], foreground=c["text"])
        self.style.configure("TFrame", background=c["panel"])
        self.style.configure("TLabel", background=c["panel"], foreground=c["text"])
        self.style.configure("Muted.TLabel", background=c["panel"], foreground=c["secondary"])
        self.style.configure("Section.TLabel", background=c["panel"], foreground=c["text"], font=("Segoe UI", 10, "bold"))
        self.style.configure("DetailTitle.TLabel", background=c["panel"], foreground=c["text"], font=("Segoe UI", 13, "bold"))
        self.style.configure("TButton", padding=(12, 7), background=c["heading"], foreground=c["text"], borderwidth=1, relief="flat")
        self.style.map("TButton", background=[("active", c["selection"]), ("disabled", c["heading"])],
                       foreground=[("disabled", c["disabled"])])
        self.style.configure("Tool.TButton", padding=(10, 8), background=c["heading"], foreground=c["text"])
        self.style.configure("Small.TButton", padding=(9, 4), background=c["heading"], foreground=c["text"])
        self.style.configure("Blue.TButton", padding=(11, 8), background=c["blue"] if self.theme_var.get()=="light" else "#215994", foreground="white")
        self.style.map("Blue.TButton", background=[("active", "#16569d"), ("disabled", c["disabled"])], foreground=[("disabled", c["secondary"])])
        self.style.configure("Connect.TButton", padding=(12, 8), background="#188453" if self.theme_var.get()=="light" else "#166b4b", foreground="white")
        self.style.map("Connect.TButton", background=[("active", "#139c5e"), ("disabled", c["disabled"])], foreground=[("disabled", c["secondary"])])
        self.style.configure("TEntry", padding=6, fieldbackground=c["card"], foreground=c["text"], bordercolor=c["border"])
        self.style.configure("TCombobox", padding=5, fieldbackground=c["card"], foreground=c["text"])
        self.style.configure("VPN.Treeview", background=c["panel"], fieldbackground=c["panel"],
                             foreground=c["text"], borderwidth=0, rowheight=32)
        self.style.configure("VPN.Treeview.Heading", background=c["heading"], foreground=c["text"], padding=(9, 9), relief="flat")
        self.style.map("VPN.Treeview", background=[("selected", c["selection"])], foreground=[("selected", c["select_text"])])
        self.style.map("VPN.Treeview.Heading", background=[("active", c["selection"])])
        self.style.configure("Sidebar.Treeview", background=c["panel"], fieldbackground=c["panel"],
                             foreground=c["text"], rowheight=30, borderwidth=0)
        self.style.map("Sidebar.Treeview", background=[("selected", c["selection"])],
                       foreground=[("selected", c["select_text"])])
        self.style.configure("TNotebook", background=c["panel"], borderwidth=0)
        self.style.configure("TNotebook.Tab", background=c["heading"], foreground=c["secondary"], padding=(15, 7))
        self.style.map("TNotebook.Tab", background=[("selected", c["card"])], foreground=[("selected", c["text"])])
        self.style.configure("TPanedwindow", background=c["border"])
        self.style.configure("Horizontal.TProgressbar", troughcolor=c["heading"], background=c["blue"])
        self.style.configure("TSeparator", background=c["border"])
        self.header.configure(bg=c["bg"])
        if self.brand_icon is not None:
            self.brand_icon.configure(bg=c["bg"])
        self.brand.configure(bg=c["bg"], fg=c["blue"])
        self.tagline.configure(bg=c["bg"], fg=c["secondary"])
        self.security_note.configure(bg=c["bg"], fg=c["secondary"])
        self.overview_strip.configure(bg=c["bg"])
        self.proton_banner.configure(bg=c["card"], highlightbackground=c["border"])
        self.proton_title.configure(bg=c["card"], fg=c["text"])
        self.proton_status_label.configure(bg=c["card"], fg=c["green"] if self.proton_status.adapter_up else c["text"])
        for metric in (self.metric_a, self.metric_b, self.metric_c, self.metric_d):
            metric.configure(bg=c["card"], highlightbackground=c["border"])
            title_label, value_label = metric._metric_labels
            title_label.configure(bg=c["card"], fg=c["secondary"])
            value_label.configure(bg=c["card"], fg=c["text"])
        self.bottom_bar.configure(bg=c["bg"])
        self.status_label.configure(bg=c["bg"], fg=c["secondary"])
        self.count_label.configure(bg=c["bg"], fg=c["secondary"])
        self.tree.tag_configure("active", foreground=c["green"])
        self.tree.tag_configure("inactive", foreground=c["text"])
        self.tree.tag_configure("other", foreground=c["secondary"])
        self.tree.tag_configure("alternate", background=c["tree_alt"])
        self.log_text.configure(bg=c["log"], fg=c["text"], insertbackground=c["text"])
        self._refresh_proton_panel()
        self._refresh()

    def _change_theme(self) -> None:
        self._apply_theme()
        try:
            self.prefs.save(self.theme_var.get())
        except OSError as error:
            self._log(f"Could not save theme preference: {error}")

    def _focus_search(self, _event=None) -> None:
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")

    def _clear_search(self) -> None:
        self.search_var.set("")
        self._focus_search()

    def _sort_by(self, column: str) -> None:
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column, self._sort_reverse = column, False
        self._refresh()

    def _refresh_sidebar(self) -> None:
        selected = self._category
        self.sidebar.delete(*self.sidebar.get_children())
        all_count = len(self.profiles)
        active = count_active(self.states, self.profiles)
        inactive = sum(self.states.get(p.id) == "Inactive" for p in self.profiles)
        items = (
            ("all", f"All profiles  ({all_count})"),
            ("proton", "◈  Proton VPN (official app)"),
            ("active", f"Active tunnels  ({active})"),
            ("inactive", f"Inactive  ({inactive})"),
        )
        for key, label in items:
            self.sidebar.insert("", "end", iid=key, text="  " + label)
        countries = sorted({p.country for p in self.profiles}, key=str.casefold)
        providers = sorted({p.provider for p in self.profiles}, key=str.casefold)
        if countries:
            self.sidebar.insert("", "end", iid="countries", text="  COUNTRIES", open=True)
            for country in countries:
                self.sidebar.insert("countries", "end", iid="country:"+country,
                                    text=f"  {country}  ({sum(p.country == country for p in self.profiles)})")
        if providers:
            self.sidebar.insert("", "end", iid="providers", text="  PROVIDERS", open=True)
            for provider in providers:
                self.sidebar.insert("providers", "end", iid="provider:"+provider,
                                    text=f"  {provider}  ({sum(p.provider == provider for p in self.profiles)})")
        if not self.sidebar.exists(selected):
            selected = self._category = "all"
        self.sidebar.selection_set(selected)

    def _sidebar_changed(self, _event=None) -> None:
        selection = self.sidebar.selection()
        if not selection:
            return
        category = selection[0]
        if category in ("countries", "providers"):
            return
        if category == "proton":
            self._category = category
            self._refresh(update_sidebar=False)
            self._show_proton_tab()
            return
        if category != self._category:
            self._category = category
            self._refresh(update_sidebar=False)

    def _refresh(self, update_sidebar: bool = True) -> None:
        if not hasattr(self, "tree"):
            return
        chosen = self.tree.selection()
        old_id = chosen[0] if chosen else None
        category = "provider:Proton VPN" if self._category == "proton" else self._category
        rows = visible_profiles(self.profiles, self.states, category, self.search_var.get())
        rows = sort_profiles(rows, self.states, self._sort_column, self._sort_reverse)
        self.tree.delete(*self.tree.get_children())
        # An official-app row is separate from managed profiles; no fake .conf is created.
        show_proton = self._category in ("all", "proton", "provider:Proton VPN")
        show_proton = show_proton and (not self.search_var.get().strip() or
                                       any(k in "proton vpn official app" for k in [self.search_var.get().strip().lower()]))
        if show_proton:
            state = self.proton_status
            short_state = ("Adapter Up*" if state.adapter_up else "App open" if state.running else
                           "Installed" if state.installed else "Not installed")
            self.tree.insert("", "end", iid="proton-official", tags=("active" if state.adapter_up else "other",), values=(
                short_state, "Proton VPN · Official app", "—", "Proton VPN", "Official app", "Open to connect / disconnect", "—",
            ))
        for idx, profile in enumerate(rows):
            state = self.states.get(profile.id, "Checking...")
            response = f"{profile.latency_ms:.0f}" if profile.latency_ms is not None else "—"
            status_tag = "active" if state in ("Connected (WG)", "Active*") else "inactive" if state == "Inactive" else "other"
            tags = (status_tag, "alternate") if idx % 2 else (status_tag,)
            self.tree.insert("", "end", iid=profile.id, tags=tags, values=(
                state, profile.name, profile.country, profile.provider, profile.protocol,
                f"{profile.endpoint_host}:{profile.endpoint_port}" if profile.endpoint_host else "—", response,
            ))
        if old_id and self.tree.exists(old_id):
            self.tree.selection_set(old_id)
        elif self.tree.exists("proton-official"):
            self.tree.selection_set("proton-official")
        elif rows:
            self.tree.selection_set(rows[0].id)
        if update_sidebar:
            self._refresh_sidebar()
        self.filter_var.set(f"{len(rows) + int(show_proton)} shown")
        self.profile_count_var.set(f"{len(self.profiles)} profile{'s' if len(self.profiles) != 1 else ''}")
        active = count_active(self.states, self.profiles)
        if active:
            self.connection_var.set("WireGuard connected" if any(st == "Connected (WG)" for st in self.states.values()) else "Tunnel active · check status")
            self.state_count_var.set(f"{active} active  ·  {len(self.profiles)} total")
        elif self.profiles and any(p.id not in self.states for p in self.profiles):
            self.connection_var.set("Checking...")
            self.state_count_var.set(f"{len(self.profiles)} profiles")
        else:
            self.connection_var.set("Proton adapter active*" if self.proton_status.adapter_up else
                                    "Proton app running" if self.proton_status.running else "No managed tunnel")
            self.state_count_var.set(f"0 active  ·  {len(self.profiles)} total")
        self._selection_changed()

    def _selection_changed(self, _event=None) -> None:
        selection = self.tree.selection()
        if selection and selection[0] == "proton-official":
            self.selected_hint_var.set("Proton VPN · Official App")
            self.details_var.set(self.proton_status.explanation)
            self.state_detail_var.set(self.proton_status.label)
            self.provider_var.set("Proton VPN")
            self.country_var.set("Determined by Proton VPN")
            self.protocol_var.set("Official app")
            self.endpoint_var.set("Managed by Proton VPN")
            self.config_var.set("Not applicable · official app mode")
            self._update_connection_buttons()
            return
        p = next((p for p in self.profiles if selection and p.id == selection[0]), None)
        if not p:
            self.selected_hint_var.set("No VPN profiles yet" if not self.profiles else "No profile selected")
            self.details_var.set("Choose Add Profile to import an official .conf or .ovpn file." if not self.profiles else "Select a row above to view details.")
            for var in (self.endpoint_var, self.config_var, self.provider_var,
                        self.country_var, self.protocol_var, self.state_detail_var):
                var.set("—")
            self._update_connection_buttons()
            return
        state = self.states.get(p.id, "Checking...")
        self.selected_hint_var.set(p.name)
        if state == "Connected (WG)":
            detail = "WireGuard handshake verified recently. This confirms a responding peer, NOT internet routing. Use Check IP to verify the exit country."
        elif state == "No handshake":
            detail = "WireGuard is active but no authenticated server response is recorded. Deactivate it if browsing is blocked."
        elif state == "Handshake stale":
            detail = "The last WireGuard handshake is older than 3 minutes. Connection may be idle or interrupted. Check IP and the WireGuard log."
        elif state == "Active (unverified)":
            detail = "WireGuard tunnel is active but the handshake cannot be read. Open the official WireGuard client for diagnostics."
        elif state == "Active*":
            detail = "Local OpenVPN tunnel/process is running. Choose Check IP to verify whether internet traffic uses this VPN."
        elif state == "Inactive":
            detail = "Not connected. Select Connect, then Check IP to confirm the connection's public location."
        else:
            detail = "VPN state has not yet been confirmed. Use Refresh to check the local tunnel service."
        self.details_var.set(detail)
        self.state_detail_var.set(state + (" (not proof of routing)" if state == "Active*" else ""))
        self.endpoint_var.set(f"{p.endpoint_host}:{p.endpoint_port}" if p.endpoint_host else "—")
        self.config_var.set(str(Path(p.config_path)))
        self.provider_var.set(p.provider)
        self.country_var.set(p.country)
        self.protocol_var.set(p.protocol)
        self._update_connection_buttons()

    def _update_connection_buttons(self) -> None:
        if not hasattr(self, "toolbar_connect"):
            return
        p = self._selected(quiet=True)
        state = self.states.get(p.id, "Checking...") if p else None
        allow_connect = bool(p) and not is_active_state(state or "") and not self.busy
        allow_disconnect = bool(p) and is_active_state(state or "") and not self.busy
        for button in (self.toolbar_connect, self.detail_connect):
            button.state(["!disabled"] if allow_connect else ["disabled"])
        for button in (self.toolbar_disconnect, self.detail_disconnect):
            button.state(["!disabled"] if allow_disconnect else ["disabled"])

    def _selected(self, quiet: bool = False) -> VPNProfile | None:
        selected = self.tree.selection()
        profile = next((p for p in self.profiles if selected and p.id == selected[0]), None)
        if not profile and not quiet:
            if selected == ("proton-official",):
                messagebox.showinfo("Official Proton VPN", "Use Open / Sign in to control the official Proton VPN app.\n\nTo connect from xVPN, import a Proton WireGuard .conf profile.", parent=self)
            else:
                messagebox.showinfo("Select a profile", "Select a VPN profile from the list first.", parent=self)
        return profile

    def _double_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self._toggle_selected()

    def _toggle_selected(self) -> None:
        if self.tree.selection() == ("proton-official",):
            self._open_proton()
            return
        p = self._selected(quiet=True)
        if not p or self.busy:
            return
        if is_active_state(self.states.get(p.id, "")):
            self._disconnect()
        else:
            self._connect()

    def _context_menu(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        if row == "proton-official":
            proton_context = tk.Menu(self, tearoff=0)
            proton_context.add_command(label="Open Proton VPN official app", command=self._open_proton)
            proton_context.add_command(label="Check public IP", command=self._check_ip)
            proton_context.add_command(label="Proton VPN details", command=self._show_proton_tab)
            proton_context.tk_popup(event.x_root, event.y_root)
            proton_context.grab_release()
            return
        self._context.tk_popup(event.x_root, event.y_root)
        self._context.grab_release()

    def _log(self, text: str) -> None:
        if not hasattr(self, "log_text"):
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain(self) -> None:
        if self._closed:
            return
        try:
            while True:
                self.events.get_nowait()()
        except queue.Empty:
            pass
        self.after(130, self._drain)

    def _profile_state(self, profile: VPNProfile) -> str:
        if not self.backend.active(profile):
            return "Inactive"
        if profile.protocol != "WireGuard":
            return "Active*"  # OpenVPN has different verification mechanisms.
        handshake = self.backend.wireguard_handshake(profile)
        return {"verified": "Connected (WG)", "missing": "No handshake",
                "stale": "Handshake stale", "unavailable": "Active (unverified)"}.get(
                    handshake.state, "Active (unverified)")

    def _poll_states(self) -> None:
        if self._closed:
            return
        if not self.busy and not self._polling:
            self._polling = True
            snapshot = list(self.profiles)
            def work():
                found = {}
                for p in snapshot:
                    try:
                        found[p.id] = self._profile_state(p)
                    except Exception:
                        found[p.id] = "Unknown"
                try:
                    proton = read_proton_status(self.proton_app_path)
                except Exception as error:
                    proton = ProtonStatus(supported=(os.name == "nt"), installed=False, error=str(error))
                self.events.put(lambda: self._states_ready(found, proton))
            threading.Thread(target=work, daemon=True).start()
        self.after(6000, self._poll_states)

    def _states_ready(self, found: dict[str, str], proton: ProtonStatus | None = None) -> None:
        self._polling = False
        if proton is not None:
            old = self.proton_status
            self.proton_status = proton
            self._refresh_proton_panel()
            if old.label != proton.label:
                self._log(f"Proton VPN: {proton.label}")
                if not self.profiles and proton.installed:
                    self.status_var.set("Proton VPN detected. Open the official app to sign in and connect; use Check IP to verify.")
        valid = {p.id for p in self.profiles}
        self.states = {key: value for key, value in found.items() if key in valid}
        self._refresh()
        if (proton is not None and proton.supported and not proton.installed
                and not self._missing_notice_shown):
            self._missing_notice_shown = True
            self.after(200, self._proton_missing_notice)

    def _refresh_now(self) -> None:
        self.status_var.set("Refreshing local tunnel states...")
        self._poll_states_once()

    def _poll_states_once(self) -> None:
        if self._closed or self.busy or self._polling:
            return
        self._polling = True
        snapshot = list(self.profiles)
        def work():
            found = {}
            for p in snapshot:
                try:
                    found[p.id] = self._profile_state(p)
                except Exception:
                    found[p.id] = "Unknown"
            try:
                proton = read_proton_status(self.proton_app_path)
            except Exception as error:
                proton = ProtonStatus(supported=(os.name == "nt"), installed=False, error=str(error))
            self.events.put(lambda: self._states_ready(found, proton))
        threading.Thread(target=work, daemon=True).start()

    def _run_async(self, work, done=None) -> None:
        if self.busy:
            return
        self.busy = True
        self.progress.pack(side="right", padx=10)
        self.progress.start(15)
        for button in self.action_buttons:
            button.state(["disabled"])
        def finish(result=None, error=None):
            try:
                if error is not None:
                    self.status_var.set("Action failed — check error message")
                    self._log("Operation failed. See the error dialog for details.")
                    self._handle_vpn_error(str(error))
                elif done is not None:
                    done(result)
            finally:
                self.busy = False
                self.progress.stop()
                self.progress.pack_forget()
                for button in self.action_buttons:
                    button.state(["!disabled"])
                self._update_connection_buttons()
                self._poll_states_once()
        def target():
            try:
                result = work()
                self.events.put(lambda: finish(result=result))
            except Exception as error:
                msg = str(error)
                self.events.put(lambda: finish(error=msg))
        threading.Thread(target=target, daemon=True).start()

    def _handle_vpn_error(self, message: str) -> None:
        if "WireGuard is not installed" in message:
            if messagebox.askyesno("WireGuard required", "Install official WireGuard to use .conf profiles.\n\nOpen its website?", parent=self):
                webbrowser.open(PROVIDERS["WireGuard"])
        else:
            messagebox.showerror("xVPN Manager", message, parent=self)

    def _import(self) -> None:
        if self.busy:
            return
        downloads = Path.home() / "Downloads"
        filenames = filedialog.askopenfilenames(
            parent=self, title="Import trusted VPN configuration files",
            initialdir=str(downloads if downloads.is_dir() else Path.home()),
            filetypes=[("VPN profiles", "*.ovpn *.conf"), ("OpenVPN", "*.ovpn"),
                       ("WireGuard", "*.conf")],
        )
        changed = 0
        for filename in filenames:
            if any(Path(p.config_path).resolve() == Path(filename).resolve() for p in self.profiles):
                messagebox.showinfo("Already imported", f"{Path(filename).name} is already in the library.", parent=self)
                continue
            try:
                parsed = parse_config(filename)
            except (ConfigError, OSError) as error:
                messagebox.showerror("Invalid VPN profile", f"{Path(filename).name}\n\n{error}", parent=self)
                continue
            dialog = ProfileDialog(self, filename)
            if dialog.result is None:
                continue
            name, provider, country = dialog.result
            p = VPNProfile.create(config_path=filename, name=name, provider=provider,
                                  country=country, protocol=parsed.protocol,
                                  endpoint_host=parsed.host, endpoint_port=parsed.port)
            self.profiles.append(p)
            changed += 1
            self._log(f"Imported profile: {p.name} ({p.protocol}).")
            if parsed.warnings:
                messagebox.showwarning("Profile warning", "\n".join(parsed.warnings), parent=self)
        if changed:
            self.store.save(self.profiles)
            self._category = "all"
            self.search_var.set("")
            self._refresh()
            self.status_var.set(f"Imported {changed} profile{'s' if changed != 1 else ''}.")
            self._poll_states_once()

    def _edit(self) -> None:
        p = self._selected()
        if not p or self.busy:
            return
        dialog = ProfileDialog(self, p.config_path, profile=p)
        if dialog.result is None:
            return
        p.name, p.provider, p.country = dialog.result
        self.store.save(self.profiles)
        self._log(f"Updated display metadata for {p.name}.")
        self._refresh()

    def _remove(self) -> None:
        p = self._selected()
        if not p or self.busy:
            return
        if not messagebox.askyesno("Remove profile", f"Remove '{p.name}' from the list?\n\nThe original .conf/.ovpn file will NOT be deleted.", parent=self):
            return
        def done(active: bool):
            if active:
                messagebox.showwarning("Active profile", "Disconnect the tunnel before removing this profile.", parent=self)
                return
            self.profiles = [item for item in self.profiles if item.id != p.id]
            self.states.pop(p.id, None)
            self.store.save(self.profiles)
            self._log(f"Removed profile: {p.name}. Original file preserved.")
            self.status_var.set(f"Removed {p.name} from library.")
            self._refresh()
        self._run_async(lambda: self.backend.active(p), done)

    def _connect(self) -> None:
        p = self._selected()
        if not p or self.busy:
            return
        user = password = ""
        try:
            parsed = parse_config(p.config_path)
            if parsed.needs_credentials:
                answer = simpledialog.askstring("VPN username", "VPN username (not stored):", parent=self)
                if not answer:
                    return
                user = answer
                answer = simpledialog.askstring("VPN password", "VPN password (not stored):", parent=self, show="*")
                if not answer:
                    return
                password = answer
        except (ConfigError, OSError) as error:
            messagebox.showerror("Invalid profile", str(error), parent=self)
            return
        if p.protocol == "WireGuard" and self.proton_status.adapter_up:
            messagebox.showwarning("Another VPN may be connected",
                                   "A Proton VPN adapter is currently active. Disconnect Proton VPN in its official app before starting a separate WireGuard profile.", parent=self)
            return
        self.ip_var.set("Not checked")
        self.ip_location_var.set("Recheck after connecting")
        self.status_var.set(f"Connecting to {p.name}... Windows WireGuard verifies handshake (up to 22s) and restores routing on failure.")
        self._log(f"Connecting: {p.name}.")
        def connect_checked():
            for other in self.profiles:
                if other.id != p.id and self.backend.active(other):
                    raise VPNError("Another registered VPN tunnel is active. Disconnect it before connecting this one.")
            return self.backend.connect_verified(p, user, password)
        def done(result: ConnectionAttempt):
            self.store.save(self.profiles)
            self.ip_var.set("Not checked")
            self.status_var.set(f"{p.name}: {result.message}")
            self._log(f"{p.name}: {result.message}")
            self._refresh()
            if result.recovered:
                messagebox.showwarning("WireGuard · no handshake — recovered", result.message, parent=self)
            elif result.recovery_failed:
                messagebox.showerror("WireGuard · manual recovery needed", result.message, parent=self)
        self._run_async(connect_checked, done)

    def _disconnect(self) -> None:
        p = self._selected()
        if not p or self.busy:
            return
        if self.states.get(p.id) == "Inactive":
            self.status_var.set(f"{p.name} is already inactive.")
            return
        self.status_var.set(f"Disconnecting {p.name}...")
        self._log(f"Disconnecting: {p.name}.")
        def done(msg):
            self.status_var.set(f"{p.name}: {msg}")
            self._log(f"Disconnect action completed: {p.name}.")
            # An earlier public-IP result is not proof of the current route.
            self.ip_var.set("Not checked")
            self.ip_location_var.set("Recheck after connecting")
            self._refresh()
        self._run_async(lambda: self.backend.disconnect(p), done)

    def _check_ip(self) -> None:
        if self.busy:
            return
        self.status_var.set("Checking public IP through IP location services...")
        def done(info: dict[str, str]):
            self.ip_var.set(info.get("ip", "Unknown"))
            city = info.get("city", "Unknown")
            country = info.get("country", "Unknown")
            self.ip_location_var.set(f"{country} · {city}")
            self.status_var.set(f"Public IP checked via {info.get('source', 'external service')}. Not a DNS/IPv6 leak test.")
            self._log(f"Public IP checked: {country}, {city}. Not a leak test.")
        self._run_async(self.backend.public_ip, done)

    def _test(self) -> None:
        p = self._selected()
        if not p or self.busy:
            return
        self.status_var.set(f"Checking TCP response: {p.name}...")
        def done(value: float):
            p.latency_ms = value
            self.store.save(self.profiles)
            self.status_var.set(f"{p.name}: TCP response {value:.1f} ms (not VPN speed).")
            self._log(f"TCP response measured for {p.name}: {value:.1f} ms.")
            self._refresh()
        self._run_async(lambda: self.backend.latency(p), done)

    def _open_config_folder(self) -> None:
        p = self._selected()
        if not p:
            return
        directory = Path(p.config_path).parent
        if not directory.exists():
            messagebox.showerror("Missing folder", f"Folder not found: {directory}", parent=self)
            return
        try:
            if os.name == "nt":
                os.startfile(str(directory))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(directory)])
            else:
                subprocess.Popen(["xdg-open", str(directory)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            messagebox.showerror("Cannot open folder", str(error), parent=self)

    def _show_proton_tab(self) -> None:
        self.details_tabs.select(self.proton_tab)

    def _refresh_proton_panel(self) -> None:
        state = self.proton_status
        self.proton_state_var.set(state.label)
        self.proton_detail_var.set(state.explanation + ("  (Detection limited: " + state.error + ")" if state.error else ""))
        self.proton_install_var.set("Installation: " + ("Installed" if state.installed else "Not installed" if state.supported else "Windows only"))
        self.proton_process_var.set("Application: " + ("Running" if state.running else "Not running"))
        self.proton_adapter_var.set("Tunnel adapter: " + ("Up*" if state.adapter_up else "Not confirmed"))
        if hasattr(self, "proton_download_banner"):
            if state.supported and not state.installed:
                if not self.proton_download_banner.winfo_manager():
                    self.proton_download_banner.pack(side="right", padx=(0, 8))
            elif self.proton_download_banner.winfo_manager():
                self.proton_download_banner.pack_forget()
        self.proton_missing_var.set(
            "Proton VPN is not installed. Download and install the official Windows app, then sign in there: "
            + PROTON_DOWNLOAD_URL if state.supported and not state.installed else
            "Proton VPN installed. Sign in and manage the official app separately from imported WireGuard profiles." if state.installed else
            "Official Proton VPN download: " + PROTON_DOWNLOAD_URL)
        if hasattr(self, "proton_status_label"):
            colors = PALETTES[self.theme_var.get()]
            self.proton_status_label.configure(fg=colors["green"] if state.adapter_up else colors["text"])

    def _locate_proton(self) -> None:
        """Support non-standard installations without handling Proton credentials."""
        if os.name != "nt":
            messagebox.showinfo("Proton VPN", "Windows-only Proton app detection.", parent=self)
            return
        chosen = filedialog.askopenfilename(
            title="Select the installed Proton VPN launcher (not the downloaded installer)",
            filetypes=[("Applications", "*.exe"), ("All files", "*.*")], parent=self)
        if not chosen:
            return
        target = Path(chosen)
        if target.name.casefold() not in PROTON_PROCESS_NAMES or not target.is_file():
            messagebox.showwarning("Unsupported Proton path",
                                   "Select ProtonVPN.Launcher.exe or ProtonVPN.Client.exe from the installed Proton VPN folder.\nDo not select ProtonVPN_v5.1.7_x64.exe (the installer).", parent=self)
            return
        try:
            self.prefs.set_proton_path(str(target))
            self.proton_app_path = str(target)
        except OSError as error:
            messagebox.showerror("Save failed", str(error), parent=self)
            return
        self.status_var.set("Proton VPN location saved; checking application status...")
        self._log("User selected an installed Proton VPN application path (no credentials accessed).")
        self._refresh_now()

    def _download_proton(self) -> None:
        webbrowser.open(PROTON_DOWNLOAD_URL)
        self.status_var.set("Official Proton VPN download page opened: " + PROTON_DOWNLOAD_URL)

    def _proton_missing_notice(self) -> None:
        if self._closed or self.proton_status.installed:
            return
        if messagebox.askyesno("Proton VPN not installed",
                               "Proton VPN is not installed or could not be detected.\n\n"
                               "Download it from the official Proton website:\n"
                               + PROTON_DOWNLOAD_URL + "\n\n"
                               "Open the official download page now?\n"
                               "(If already installed, use Locate Proton App instead.)", parent=self):
            self._download_proton()

    def _open_proton(self) -> None:
        if os.name != "nt":
            webbrowser.open(PROVIDERS["Proton VPN"])
            self.status_var.set("Official Proton VPN website opened; native monitoring is Windows-only.")
            return
        # Always re-detect path: Proton can be installed/updated while xVPN is open.
        try:
            # Fast install-path probe on UI thread; process/adapter checks run in the background.
            path = find_proton_app(self.proton_app_path)
            if path is None:
                choice = messagebox.askyesno("Proton VPN not installed",
                    "Proton VPN could not be found.\n\n"
                    "Download official Proton VPN from:\n" + PROTON_DOWNLOAD_URL +
                    "\n\nOpen the official download page?\n"
                    "(Choose No if already installed, then use Locate Proton App.)", parent=self)
                if choice:
                    self._download_proton()
                self._show_proton_tab()
                return
            message = launch_proton_app(ProtonStatus(supported=True, installed=True, app_path=str(path)))
            self.status_var.set(message)
            self._log("Opened Proton VPN official application; sign-in and tunnel controls remain in that app.")
            self._show_proton_tab()
            self.after(2500, self._refresh_now)
        except (OSError, RuntimeError) as error:
            messagebox.showerror("Proton VPN", str(error), parent=self)

    def _proton_configs(self) -> None:
        webbrowser.open(PROTON_CONFIG_URL)
        self._show_proton_tab()
        self.status_var.set("Proton account page opened. Download a WireGuard .conf file, then Add Profile in xVPN.")
        self._log("Proton WireGuard configuration instructions requested. Authentication stays in your browser.")

    def _setup(self) -> None:
        """Scrollable instructions, with buttons pinned to the bottom on small displays."""
        w = tk.Toplevel(self)
        w.title("xVPN · Setup and help")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(760, max(480, sw - 70))
        height = min(590, max(340, sh - 110))
        w.geometry(f"{width}x{height}")
        w.minsize(min(width, 480), min(height, 340))
        w.transient(self)
        footer = ttk.Frame(w, padding=(14, 9))
        footer.pack(side="bottom", fill="x")
        c = PALETTES[self.theme_var.get()]
        frame = ttk.Frame(w, padding=(17, 12))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Get connected in three steps", font=("Segoe UI", 17, "bold")).pack(anchor="w", pady=(0, 7))
        status = self.backend.tool_status()
        instructions = (
            "1. Download an authorized WireGuard .conf or OpenVPN .ovpn file from your provider.\n"
            "2. Click Add Profile and select the file (the original is not moved).\n"
            "3. Connect, then Check IP to confirm which country your public IP uses.\n\n"
            "OFFICIAL PROTON VPN APP\n"
            "Use Open Proton / Sign in. The official app controls authentication and connection.\n"
            "The app and imported WireGuard profiles are two SEPARATE connection modes.\n"
            "Never connect them at the same time. xVPN never reads your Proton password.\n\n"
            "SLOW MANUAL WIREGUARD CONNECTION?\n"
            "A successful handshake proves an authenticated peer, NOT healthy web traffic.\n"
            "Different countries and servers can have very different performance.\n"
            "Compare the same country in the official app and in manual WireGuard.\n"
            "Choose a WireGuard profile, then Connection > WireGuard diagnostics and MTU test.\n"
            "If the handshake is fine but pages stall, try a separate MTU 1360 test profile,\n"
            "then MTU 1280 if necessary. These are experiments, not guaranteed speed fixes.\n"
            "xVPN does NOT modify the provider-issued original .conf file.\n"
            "New files contain VPN private keys: keep them private.\n\n"
            f"WireGuard installed: {'Yes' if status.wireguard else 'No'}    "
            f"OpenVPN installed: {'Yes' if status.openvpn else 'No'}    "
            f"NetworkManager: {'Yes' if status.network_manager else 'No'}\n\n"
            "Windows tunnel control requires administrator permission.\n"
            "Linux NetworkManager may show its own authorization prompt.\n"
            "New Windows WireGuard tunnels are rolled back if no handshake arrives.\n"
            "Existing tunnels are never auto-disconnected by the handshake check.\n"
            "Check IP contacts external geo-IP services only at your request.\n"
            "Check IP is NOT a speed test, nor a complete DNS/IPv6 leak test.\n"
            "Import configs only from trusted providers; never share private keys."
        )
        display = tk.Text(frame, wrap="word", height=14, bg=c['card'], fg=c['text'],
                          font=("Segoe UI", 10), relief="flat", padx=9, pady=8,
                          insertbackground=c['text'], borderwidth=0)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=display.yview)
        display.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        display.pack(side="left", fill="both", expand=True)
        display.insert("1.0", instructions)
        display.configure(state="disabled")
        ttk.Button(footer, text="Add profile...", command=self._import).pack(side="left", padx=(0, 7))
        ttk.Button(footer, text="Official websites", command=self._providers).pack(side="left", padx=(0, 7))
        if os.name == "nt":
            ttk.Button(footer, text="Restart as administrator", command=self._elevate).pack(side="left")
        ttk.Button(footer, text="Close", command=w.destroy).pack(side="right")

    def _diagnostics(self) -> None:
        """User-triggered, read-only local diagnosis; never silently alters routing."""
        profile = self._selected()
        if profile is None:
            return
        if profile.protocol != 'WireGuard':
            messagebox.showinfo('Diagnostics', 'Select an imported WireGuard .conf profile.', parent=self)
            return
        def inspect():
            settings = wireguard_settings(profile.config_path)
            running = self.backend.active(profile)
            handshake = self.backend.wireguard_handshake(profile) if running else None
            transfer = self.backend.wireguard_transfer(profile) if running else None
            return settings, running, handshake, transfer
        def show(result):
            settings, running, handshake, transfer = result
            c = PALETTES[self.theme_var.get()]
            w = tk.Toplevel(self)
            w.title('WireGuard diagnostics · ' + profile.name)
            width = min(750, max(480, self.winfo_screenwidth() - 70))
            height = min(530, max(345, self.winfo_screenheight() - 110))
            w.geometry(f'{width}x{height}')
            w.minsize(min(480, width), min(330, height))
            w.transient(self)
            footer = ttk.Frame(w, padding=(14, 10))
            footer.pack(side='bottom', fill='x')
            frame = ttk.Frame(w, padding=(15, 12))
            frame.pack(fill='both', expand=True)
            ttk.Label(frame, text='WireGuard connection diagnostics',
                      font=('Segoe UI', 16, 'bold')).pack(anchor='w', pady=(0, 8))
            if handshake:
                hand = handshake.state + (f' ({handshake.age_seconds}s ago)' if handshake.age_seconds is not None else '')
            else:
                hand = 'Not checked (tunnel is inactive)'
            rx = (f'{transfer[0]:,} received / {transfer[1]:,} sent bytes' if transfer else 'Unavailable')
            diagnosis = (
                f'Profile: {profile.name}\n'
                f'Provider: {profile.provider}    Country label: {profile.country}\n'
                f'Tunnel running: {"Yes" if running else "No"}\n'
                f'Handshake: {hand}\n'
                f'WireGuard transfer: {rx}\n'
                f'Endpoint: {settings["endpoint"]}\n'
                f'MTU: {settings["mtu"]}\n'
                f'DNS servers: {settings["dns"]}\n'
                f'Allowed IP routes: {settings["routes"]}\n\n'
                'WHAT THESE NUMBERS MEAN\n'
                'Handshake OK alone does not prove speed, DNS, or successful browsing.\n'
                'RX = 0 with TX > 0 may mean no VPN response or no useful data received.\n'
                'A very slow US server while the official app uses Japan is not a fair comparison.\n'
                'If websites hang with handshake OK, an MTU/path issue is one possibility.\n'
                'Try a separate MTU 1360 config, then 1280, and compare actual browsing.\n'
                'You can use the original config again at any time.\n'
                'Only one VPN tunnel should be active during testing.\n\n'
                'SECURITY: This report omits the WireGuard private key and peer public key.\n'
                'MTU test copies contain secrets: do not upload or share them.'
            )
            body = tk.Text(frame, wrap='word', bg=c['card'], fg=c['text'],
                           font=('Consolas', 10), relief='flat', padx=10, pady=8)
            bar = ttk.Scrollbar(frame, command=body.yview)
            body.configure(yscrollcommand=bar.set)
            bar.pack(side='right', fill='y')
            body.pack(side='left', fill='both', expand=True)
            body.insert('1.0', diagnosis)
            body.configure(state='disabled')
            ttk.Button(footer, text='Create MTU test copy...',
                       command=lambda: self._make_mtu_profile(profile, w)).pack(side='left')
            ttk.Button(footer, text='Open Proton speed guide',
                       command=lambda: webbrowser.open('https://protonvpn.com/support/increase-vpn-speeds')).pack(side='left', padx=8)
            ttk.Button(footer, text='Close', command=w.destroy).pack(side='right')
        self._run_async(inspect, show)

    def _make_mtu_profile(self, original: VPNProfile, parent: tk.Misc) -> None:
        mtu = simpledialog.askinteger('MTU experiment',
            'Create a NEW WireGuard test profile. Original .conf stays unchanged.\n\n'
            'Try MTU 1360 first; try 1280 if needed. This may help packet-size issues, '
            'but will not fix a slow or distant server.\n\nEnter test MTU (1280–1420):',
            parent=parent, initialvalue=1360, minvalue=1280, maxvalue=1420)
        if mtu is None:
            return
        try:
            output = make_mtu_test_copy(original.config_path, self.store.path.parent / 'mtu-test-configs', mtu)
            parsed = parse_config(output)
            variant = VPNProfile.create(config_path=str(output), name=f'{original.name} · MTU {mtu}',
                                        provider=original.provider, country=original.country,
                                        protocol='WireGuard', endpoint_host=parsed.host,
                                        endpoint_port=parsed.port)
            self.profiles.append(variant)
            self.store.save(self.profiles)
            self.status_var.set(f'MTU {mtu} test profile created. Original unchanged. Disconnect the original before connecting the test profile.')
            self._log(f'Created MTU {mtu} test copy for {original.name}; no keys logged.')
            self._refresh()
            if self.tree.exists(variant.id):
                self.tree.selection_set(variant.id)
                self.tree.see(variant.id)
            messagebox.showinfo('MTU test copy created',
                f'New profile: {variant.name}\n\n'
                'The original file was not modified. Disconnect any active VPN first. '
                'Then connect the test copy and use Check IP and actual browsing to compare.\n\n'
                'The new .conf includes the WireGuard private key. Keep it private.', parent=parent)
        except (ConfigError, ValueError, OSError) as error:
            messagebox.showerror('Could not create MTU test', str(error), parent=parent)

    def _providers(self) -> None:
        w = tk.Toplevel(self)
        w.title("Official VPN providers and clients")
        w.geometry("575x300")
        f = ttk.Frame(w, padding=18)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Official download websites", style="DetailTitle.TLabel").pack(anchor="w", pady=(0, 9))
        ttk.Label(f, text="VPN provider accounts and supported config files are separate from this manager.",
                  style="Muted.TLabel", wraplength=520).pack(anchor="w", pady=(0, 10))
        for name, url in PROVIDERS.items():
            row = ttk.Frame(f)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=name, width=20).pack(side="left")
            ttk.Label(row, text=url, style="Muted.TLabel").pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="Open", command=lambda link=url: webbrowser.open(link), style="Small.TButton").pack(side="right")

    def _about(self) -> None:
        messagebox.showinfo("About xVPN Manager", f"xVPN Manager {VERSION}\n\n"
                            "Official Proton VPN monitor/launcher and WireGuard / OpenVPN profile manager.\n"
                            "Free, open-source application; no VPN servers included.\n\n"
                            "Inspired by the clear list, filters and detail views of desktop managers.\n"
                            "VPN connectivity must be verified on your own computer.", parent=self)

    def _elevate(self) -> None:
        if os.name != "nt":
            messagebox.showinfo("Permissions", "Linux uses NetworkManager or the system permission dialog.", parent=self)
            return
        if self.busy or self.backend.processes:
            messagebox.showinfo("Busy", "Finish active operations and disconnect OpenVPN first.", parent=self)
            return
        executable = str(Path(sys.executable).with_name("pythonw.exe"))
        app_file = str(Path(__file__).resolve().parents[1] / "app.py")
        code = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", executable, subprocess.list2cmdline([app_file]), None, 1,
        )
        if code > 32:
            self._closed = True
            self.destroy()
        else:
            messagebox.showerror("Restart cancelled", "Administrator restart was not completed.", parent=self)

    def _close(self) -> None:
        if self.busy:
            messagebox.showinfo("Operation in progress", "Finish the current operation before closing.", parent=self)
            return
        if not messagebox.askokcancel("Exit xVPN Manager", "Close xVPN Manager?\n\n"
                                       "WireGuard and NetworkManager tunnels remain active.\n"
                                       "OpenVPN processes launched by xVPN will stop.\n"
                                       "Disconnect first if you want to end a VPN session.", parent=self):
            return
        self._closed = True
        self.backend.shutdown()
        self.destroy()


def run() -> None:
    app = VPNManagerApp()
    app.mainloop()
