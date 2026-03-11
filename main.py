"""
Device Data Viewer — Desktop application for querying device data
from the oncall.collection_datas_archive table with statistics & graphs.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, timedelta
import csv
import threading
import statistics
from collections import defaultdict
import calendar
import time
import mysql.connector
from tkcalendar import DateEntry
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
import matplotlib.dates as mdates
import matplotlib.ticker


# ── Database configuration ────────────────────────────────────────────
DB_CONFIG = {
    "host": "replace_this",
    "port": 0000, #replace with your port number
    "user": "replace_this",
    "password": "replace_this",
    "database": "replace_this",
}

COLUMNS = ("id", "device_id", "device_time", "server_time", "sat", "hgb", "probe")

ALLOWED_DEVICES = [
    "T2-0083",
    "T2-0084",
    "T2-0086",
    "T2-0087",
    "T2-0186",
    "T2-0187",
]


class DeviceDataViewer(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title("Device Data Viewer — Statistics")
        self.geometry("1200x800")
        self.minsize(1000, 650)
        self.configure(bg="#f0f0f0")

        self._rows: list[tuple] = []
        self._device_list: list[str] = []

        self._build_ui()
        self._load_device_list()

    # ── UI Construction ───────────────────────────────────────────────
    def _build_ui(self):
        # Top filter frame
        filter_frame = ttk.LabelFrame(self, text="Query Filters", padding=10)
        filter_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        row1 = ttk.Frame(filter_frame)
        row1.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(row1, text="Device ID:").pack(side=tk.LEFT, padx=(0, 5))
        self.device_var = tk.StringVar(value="All Devices")
        self.device_combo = ttk.Combobox(
            row1, textvariable=self.device_var, width=20, state="readonly"
        )
        self.device_combo["values"] = ["All Devices"]
        self.device_combo.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row1, text="From:").pack(side=tk.LEFT, padx=(0, 5))
        self.start_date = DateEntry(
            row1, width=12, date_pattern="yyyy-mm-dd",
            year=datetime.now().year, month=datetime.now().month, day=1,
        )
        self.start_date.pack(side=tk.LEFT, padx=(0, 5))

        self.start_hour = ttk.Spinbox(row1, from_=0, to=23, width=3, format="%02.0f")
        self.start_hour.set("00")
        self.start_hour.pack(side=tk.LEFT)
        ttk.Label(row1, text=":").pack(side=tk.LEFT)
        self.start_min = ttk.Spinbox(row1, from_=0, to=59, width=3, format="%02.0f")
        self.start_min.set("00")
        self.start_min.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(row1, text="To:").pack(side=tk.LEFT, padx=(0, 5))
        self.end_date = DateEntry(row1, width=12, date_pattern="yyyy-mm-dd")
        self.end_date.pack(side=tk.LEFT, padx=(0, 5))

        self.end_hour = ttk.Spinbox(row1, from_=0, to=23, width=3, format="%02.0f")
        self.end_hour.set("23")
        self.end_hour.pack(side=tk.LEFT)
        ttk.Label(row1, text=":").pack(side=tk.LEFT)
        self.end_min = ttk.Spinbox(row1, from_=0, to=59, width=3, format="%02.0f")
        self.end_min.set("59")
        self.end_min.pack(side=tk.LEFT, padx=(0, 15))

        self.fetch_btn = ttk.Button(row1, text="Fetch Data", command=self._on_fetch)
        self.fetch_btn.pack(side=tk.LEFT, padx=(10, 5))

        self.export_btn = ttk.Button(
            row1, text="Export CSV", command=self._export_csv, state=tk.DISABLED
        )
        self.export_btn.pack(side=tk.LEFT, padx=(0, 5))

        # Status bar
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=10, pady=(0, 5))
        self.status_var = tk.StringVar(value="Ready — select filters and click Fetch Data")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(status_frame, mode="determinate", length=250)
        self.progress.pack(side=tk.RIGHT)

        # ── Main content: tabbed notebook ─────────────────────────────
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Tab 1 — Summary statistics
        self.stats_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.stats_frame, text="  Summary Statistics  ")
        self._build_stats_tab()

        # Tab 2 — Time-series charts
        self.charts_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.charts_frame, text="  Time Series  ")

        # Tab 3 — Distribution histograms
        self.hist_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.hist_frame, text="  Distributions  ")



    def _build_stats_tab(self):
        # Overall stats table
        cols = ("Metric", "SAT", "HGB")
        self.stats_tree = ttk.Treeview(self.stats_frame, columns=cols, show="headings", height=10)
        for c in cols:
            self.stats_tree.heading(c, text=c)
            self.stats_tree.column(c, width=200 if c == "Metric" else 160, anchor=tk.CENTER)
        self.stats_tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Per-device breakdown
        ttk.Label(self.stats_frame, text="Per-Device Breakdown",
                  font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=10)

        dev_cols = ("Device", "Records", "SAT Mean", "HGB Mean")
        dev_container = ttk.Frame(self.stats_frame)
        dev_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.dev_stats_tree = ttk.Treeview(dev_container, columns=dev_cols, show="headings", height=8)
        for c in dev_cols:
            self.dev_stats_tree.heading(c, text=c)
            self.dev_stats_tree.column(c, width=110, anchor=tk.CENTER)
        dev_vsb = ttk.Scrollbar(dev_container, orient=tk.VERTICAL, command=self.dev_stats_tree.yview)
        self.dev_stats_tree.configure(yscrollcommand=dev_vsb.set)
        self.dev_stats_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        dev_vsb.pack(side=tk.LEFT, fill=tk.Y)

    # ── Load device list ────────────────────────────────────────────────
    def _load_device_list(self):
        self._device_list = ALLOWED_DEVICES
        self.device_combo["values"] = ["All Devices"] + ALLOWED_DEVICES
        self.status_var.set(f"Ready — {len(ALLOWED_DEVICES)} devices available")

    # ── Fetch data ────────────────────────────────────────────────────
    def _on_fetch(self):
        try:
            start_dt = datetime.combine(
                self.start_date.get_date(),
                datetime.strptime(
                    f"{int(self.start_hour.get()):02d}:{int(self.start_min.get()):02d}:00",
                    "%H:%M:%S",
                ).time(),
            )
            end_dt = datetime.combine(
                self.end_date.get_date(),
                datetime.strptime(
                    f"{int(self.end_hour.get()):02d}:{int(self.end_min.get()):02d}:59",
                    "%H:%M:%S",
                ).time(),
            )
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter valid date/time values.")
            return

        if start_dt > end_dt:
            messagebox.showerror("Invalid Range", "Start date/time must be before end date/time.")
            return

        device = self.device_var.get()
        device_filter = None if device == "All Devices" else device

        self.fetch_btn.config(state=tk.DISABLED)
        self.export_btn.config(state=tk.DISABLED)
        self.progress["value"] = 0
        self.status_var.set("Querying database…")

        threading.Thread(
            target=self._fetch_worker,
            args=(start_dt, end_dt, device_filter),
            daemon=True,
        ).start()

    @staticmethod
    def _week_chunks(start_dt: datetime, end_dt: datetime):
        """Yield (chunk_start, chunk_end) pairs, one per 7-day window."""
        cur = start_dt
        while cur <= end_dt:
            chunk_end = min(cur + timedelta(days=6, hours=23, minutes=59, seconds=59) - timedelta(
                hours=cur.hour, minutes=cur.minute, seconds=cur.second),
                end_dt)
            # simpler: advance 6 days then cap at end-of-day
            day_end = (cur + timedelta(days=6)).replace(hour=23, minute=59, second=59)
            chunk_end = min(day_end, end_dt)
            yield cur, chunk_end
            cur = chunk_end + timedelta(seconds=1)

    def _fetch_worker(self, start_dt: datetime, end_dt: datetime, device_id: str | None):

        chunks = list(self._week_chunks(start_dt, end_dt))
        # Query one device at a time — smaller result sets, uses index better
        devices = [device_id] if device_id else ALLOWED_DEVICES
        tasks = [(c_start, c_end, dev) for (c_start, c_end) in chunks for dev in devices]
        total_tasks = len(tasks)
        all_rows: list[tuple] = []

        for idx, (c_start, c_end, dev) in enumerate(tasks, 1):
            label = f"{dev} {c_start.strftime('%b %d')}–{c_end.strftime('%b %d')}"
            self.after(0, lambda i=idx, t=total_tasks, lb=label, n=len(all_rows):
                       self.status_var.set(
                           f"Fetching {lb}  ({i}/{t}) — {n:,} rows so far"))

            query = (
                "SELECT id, device_id, device_time, server_time, sat, hgb, probe "
                "FROM collection_datas_archive "
                "WHERE device_id = %s AND device_time BETWEEN %s AND %s "
                "ORDER BY device_time"
            )
            params = [dev, c_start, c_end]

            success = False
            for attempt in range(3):
                try:
                    conn = mysql.connector.connect(
                        **DB_CONFIG, connection_timeout=30, read_timeout=600,
                    )
                    cursor = conn.cursor()
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
                    cursor.close()
                    conn.close()
                    all_rows.extend(rows)
                    success = True
                    break
                except mysql.connector.Error:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    if attempt < 2:
                        self.after(0, lambda lb=label, a=attempt:
                                   self.status_var.set(
                                       f"Retrying {lb} ({a + 1}/2)…"))
                        time.sleep(3 * (attempt + 1))

            if not success:
                self.after(0, lambda lb=label:
                           self._query_error(f"Failed after 3 attempts on {lb}"))
                return

            pct = int(idx / total_tasks * 100)
            self.after(0, lambda p=pct: self.progress.configure(value=p))

            if idx < total_tasks:
                time.sleep(0.5)

        # Sort by device_time across all devices
        all_rows.sort(key=lambda r: r[2])
        self.after(0, lambda: self._display_results(all_rows))

    # ── Display results ───────────────────────────────────────────────
    def _display_results(self, rows: list[tuple]):
        self.progress["value"] = 100
        self.fetch_btn.config(state=tk.NORMAL)

        self._rows = rows
        count = len(rows)
        self.status_var.set(f"Returned {count:,} row{'s' if count != 1 else ''}")

        if not count:
            messagebox.showinfo("No Data", "No records found for the selected filters.")
            return

        self.export_btn.config(state=tk.NORMAL)

        # Parse columns
        device_ids = [r[1] for r in rows]
        times = [
            r[2] if isinstance(r[2], datetime)
            else datetime.strptime(str(r[2]), "%Y-%m-%d %H:%M:%S")
            for r in rows
        ]
        sats = [float(r[4]) for r in rows]
        hgbs = [float(r[5]) for r in rows]
        probes = [float(r[6]) for r in rows]

        self._update_summary_stats(device_ids, sats, hgbs, probes)
        self._update_timeseries(times, sats, hgbs)
        self._update_histograms(sats, hgbs, probes)

    def _query_error(self, msg: str):
        self.progress["value"] = 0
        self.fetch_btn.config(state=tk.NORMAL)
        self.status_var.set("Query failed")
        messagebox.showerror("Database Error", msg)

    # ── Tab 1: Summary Statistics ─────────────────────────────────────
    def _update_summary_stats(self, device_ids, sats, hgbs, probes):
        for item in self.stats_tree.get_children():
            self.stats_tree.delete(item)
        for item in self.dev_stats_tree.get_children():
            self.dev_stats_tree.delete(item)

        def _f(v):
            return f"{v:.4f}"

        rows = [
            ("Count", str(len(sats)), str(len(hgbs))),
            ("Mean", _f(statistics.mean(sats)), _f(statistics.mean(hgbs))),
            ("Min", _f(min(sats)), _f(min(hgbs))),
            ("Max", _f(max(sats)), _f(max(hgbs))),
        ]

        for r in rows:
            self.stats_tree.insert("", tk.END, values=r)

        # Per-device breakdown
        buckets = defaultdict(lambda: {"sat": [], "hgb": [], "probe": []})
        for did, s, h, p in zip(device_ids, sats, hgbs, probes):
            buckets[did]["sat"].append(s)
            buckets[did]["hgb"].append(h)
            buckets[did]["probe"].append(p)

        for did in sorted(buckets):
            b = buckets[did]
            n = len(b["sat"])
            self.dev_stats_tree.insert("", tk.END, values=(
                did, n,
                _f(statistics.mean(b["sat"])),
                _f(statistics.mean(b["hgb"])),
            ))

    # ── Tab 2: Time-series charts ─────────────────────────────────────
    def _update_timeseries(self, times, sats, hgbs):
        for w in self.charts_frame.winfo_children():
            w.destroy()

        # Normalize SAT: divide by 100 to get 0–1 range (like OncallDataForm)
        sats_norm = [s / 100.0 for s in sats]

        # Thin out if too many points (pick every Nth point, no averaging)
        n = len(times)
        max_pts = 5000
        if n > max_pts:
            step = n // max_pts
            indices = range(0, n, step)
            times_p = [times[i] for i in indices]
            sats_p = [sats_norm[i] for i in indices]
            hgbs_p = [hgbs[i] for i in indices]
        else:
            times_p, sats_p, hgbs_p = times, sats_norm, hgbs

        # Use sequential index for X-axis (like C# IsXValueIndexed = true)
        # This eliminates gaps and makes lines clean
        x_indices = list(range(len(times_p)))

        # Build tick labels at regular intervals
        num_ticks = min(40, len(times_p))
        tick_step = max(1, len(times_p) // num_ticks)
        tick_positions = list(range(0, len(times_p), tick_step))
        tick_labels = [times_p[i].strftime("%m/%d %H:%M") for i in tick_positions]

        fig = Figure(figsize=(11, 5), dpi=96)
        fig.subplots_adjust(left=0.08, right=0.92, top=0.92, bottom=0.22)

        ax1 = fig.add_subplot(1, 1, 1)

        # SAT on primary Y-axis (blue)
        ax1.plot(x_indices, sats_p, linewidth=1, color="blue", label="Sat")
        ax1.set_ylabel("Saturation", fontsize=11)
        ax1.set_ylim(0, 1)
        ax1.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(xmax=1.0))
        ax1.set_yticks([0, 0.25, 0.50, 0.75, 1.00])
        ax1.grid(True, alpha=0.3)

        # HGB (tGb) on secondary Y-axis (orange/yellow)
        ax2 = ax1.twinx()
        ax2.plot(x_indices, hgbs_p, linewidth=1, color="#FFC800", label="tGb")
        ax2.set_ylabel("Total Relative Hemoglobin", fontsize=11)
        ax2.set_ylim(0, 0.5)
        ax2.set_yticks([0, 0.1, 0.2, 0.3, 0.4, 0.5])
        ax2.yaxis.grid(False)

        # X-axis labels
        ax1.set_xticks(tick_positions)
        ax1.set_xticklabels(tick_labels, rotation=90, fontsize=7)
        ax1.set_xlabel("Device Date and Time", fontsize=11)
        ax1.set_xlim(0, len(times_p) - 1)

        # Title
        device = self.device_var.get()
        if device != "All Devices":
            fig.suptitle(f"Data for {device}", fontsize=14, fontweight="bold")
        else:
            fig.suptitle("Time Series — All Devices", fontsize=14, fontweight="bold")

        # Combined legend
        lines1, labels1 = ax1.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=9)

        canvas = FigureCanvasTkAgg(fig, master=self.charts_frame)
        canvas.draw()
        toolbar = NavigationToolbar2Tk(canvas, self.charts_frame)
        toolbar.update()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ── Tab 3: Distribution histograms ────────────────────────────────
    def _update_histograms(self, sats, hgbs, probes):
        for w in self.hist_frame.winfo_children():
            w.destroy()

        fig = Figure(figsize=(11, 5), dpi=96)
        fig.subplots_adjust(wspace=0.35, left=0.06, right=0.97, top=0.92, bottom=0.12)

        for i, (label, data, color) in enumerate([
            ("SAT", sats, "#1f77b4"),
            ("HGB", hgbs, "#ff7f0e"),
        ], 1):
            ax = fig.add_subplot(1, 2, i)
            bins = min(50, max(10, len(set(data)) // 2 or 10))
            ax.hist(data, bins=bins, color=color, edgecolor="white", alpha=0.85)
            ax.set_title(f"{label} Distribution")
            ax.set_xlabel(label)
            ax.set_ylabel("Frequency")
            ax.grid(True, alpha=0.3, axis="y")

            m = statistics.mean(data)
            med = statistics.median(data)
            ax.axvline(m, color="red", linestyle="--", linewidth=1, label=f"Mean: {m:.2f}")
            ax.axvline(med, color="black", linestyle=":", linewidth=1, label=f"Median: {med:.2f}")
            ax.legend(fontsize=7)

        canvas = FigureCanvasTkAgg(fig, master=self.hist_frame)
        canvas.draw()
        toolbar = NavigationToolbar2Tk(canvas, self.hist_frame)
        toolbar.update()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ── CSV Export ────────────────────────────────────────────────────
    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Export Data to CSV",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([c.upper() for c in COLUMNS])
                writer.writerows(self._rows)
            self.status_var.set(f"Exported {len(self._rows):,} rows to {path}")
        except OSError as exc:
            messagebox.showerror("Export Error", str(exc))


if __name__ == "__main__":
    app = DeviceDataViewer()
    app.mainloop()
