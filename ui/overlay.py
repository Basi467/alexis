"""Minimal always-on-top status overlay: a small borderless card, bottom-right
of the screen, showing the current state (sleeping / awake / listening /
thinking / speaking) and a rolling transcript. Alexis is voice-only by design,
but that means a screen recording of it just shows silence with no visual
feedback -- this exists purely to make it watchable (demos, screen recordings)
and to give visible confirmation during normal use, not as a control surface
(there are no buttons besides close; voice remains the only input).

Built on customtkinter (a themed layer over Tkinter) for rounded corners and a
modern dark card look instead of a plain Tk window. Runs its own mainloop on a
dedicated thread since main.py's conversation loop is synchronous and must not
block on UI work. State/transcript updates are pushed across via a thread-safe
queue and drained with root.after() polling on the UI thread -- the standard
safe way to touch Tkinter/CTk widgets from code running on another thread.
"""
import logging
import queue
import threading

import customtkinter as ctk

logger = logging.getLogger(__name__)

_update_queue: "queue.Queue" = queue.Queue(maxsize=200)
_root: ctk.CTk | None = None

MAX_TRANSCRIPT_LINES = 12
WIDTH, HEIGHT = 340, 320
MARGIN = 20
TASKBAR_CLEARANCE = 60

STATE_COLORS = {
    "sleeping": "#5b5b66",
    "awake": "#22c55e",
    "listening": "#3b82f6",
    "thinking": "#f59e0b",
    "speaking": "#a855f7",
}
STATE_LABELS = {
    "sleeping": 'Sleeping — say "Alexis"',
    "awake": "Awake",
    "listening": "Listening…",
    "thinking": "Thinking…",
    "speaking": "Speaking…",
}


def _make_draggable(widget, root: ctk.CTk) -> None:
    def start(event) -> None:
        root._drag_x = event.x_root - root.winfo_x()
        root._drag_y = event.y_root - root.winfo_y()

    def move(event) -> None:
        root.geometry(f"+{event.x_root - root._drag_x}+{event.y_root - root._drag_y}")

    widget.bind("<ButtonPress-1>", start)
    widget.bind("<B1-Motion>", move)


def _on_close() -> None:
    global _root
    root = _root
    _root = None
    try:
        root.destroy()
    except Exception:
        pass


def _build_window() -> None:
    global _root

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    root = ctk.CTk(fg_color="#0b0b0e")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.96)

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = screen_w - WIDTH - MARGIN
    y = screen_h - HEIGHT - MARGIN - TASKBAR_CLEARANCE
    root.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

    # Starts hidden -- Alexis spends almost all its time asleep waiting for the
    # wake word, and there's nothing useful to show then. Popping up only while
    # actually engaged (awake/listening/thinking/speaking) also means no window
    # flash at startup before the first real state update arrives.
    root.withdraw()

    card = ctk.CTkFrame(root, corner_radius=18, fg_color="#17171c",
                         border_width=1, border_color="#2a2a32")
    card.pack(fill="both", expand=True, padx=6, pady=6)

    accent = ctk.CTkFrame(card, width=5, corner_radius=3, fg_color=STATE_COLORS["sleeping"])
    accent.pack(side="left", fill="y", padx=(10, 8), pady=12)

    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)

    top_bar = ctk.CTkFrame(body, fg_color="transparent")
    top_bar.pack(fill="x")

    brand_label = ctk.CTkLabel(top_bar, text="ALEXIS", font=("Segoe UI", 10, "bold"),
                                text_color="#7d7d88")
    brand_label.pack(side="left")

    close_btn = ctk.CTkLabel(top_bar, text="✕", font=("Segoe UI", 12),
                              text_color="#5c5c66", cursor="hand2")
    close_btn.pack(side="right")
    close_btn.bind("<Button-1>", lambda e: _on_close())

    status_row = ctk.CTkFrame(body, fg_color="transparent")
    status_row.pack(fill="x", pady=(6, 8))

    dot_label = ctk.CTkLabel(status_row, text="●", font=("Segoe UI", 13),
                              text_color=STATE_COLORS["sleeping"])
    dot_label.pack(side="left", padx=(0, 6))

    status_label = ctk.CTkLabel(status_row, text=STATE_LABELS["sleeping"],
                                 font=("Segoe UI", 13, "bold"), text_color="#f2f2f5",
                                 anchor="w")
    status_label.pack(side="left", fill="x", expand=True)

    divider = ctk.CTkFrame(body, height=1, fg_color="#2a2a32")
    divider.pack(fill="x", pady=(0, 8))

    transcript = ctk.CTkTextbox(body, fg_color="#111114", text_color="#c9c9d1",
                                 font=("Segoe UI", 10), corner_radius=10,
                                 border_width=0, wrap="word")
    transcript.pack(fill="both", expand=True)
    transcript.configure(state="disabled")

    for draggable in (card, body, top_bar, brand_label, status_row, dot_label, status_label):
        _make_draggable(draggable, root)

    root._accent = accent
    root._dot_label = dot_label
    root._status_label = status_label
    root._transcript = transcript
    _root = root

    def poll_queue() -> None:
        if _root is None:
            return
        try:
            while True:
                kind, payload = _update_queue.get_nowait()
                if kind == "state":
                    _apply_state(payload)
                elif kind == "transcript":
                    _apply_transcript(*payload)
        except queue.Empty:
            pass
        try:
            root.after(50, poll_queue)
        except Exception:
            pass

    root.after(50, poll_queue)
    root.mainloop()


def _apply_state(state: str) -> None:
    if _root is None:
        return
    color = STATE_COLORS.get(state, "#5b5b66")
    label = STATE_LABELS.get(state, state)
    _root._accent.configure(fg_color=color)
    _root._dot_label.configure(text_color=color)
    _root._status_label.configure(text=label)

    if state == "sleeping":
        _root.withdraw()
    else:
        _root.deiconify()
        _root.attributes("-topmost", True)
        _root.lift()


def _apply_transcript(speaker: str, text: str) -> None:
    if _root is None:
        return
    widget = _root._transcript
    widget.configure(state="normal")
    widget.insert("end", f"{speaker}: {text}\n\n")
    line_count = int(widget.index("end-1c").split(".")[0])
    if line_count > MAX_TRANSCRIPT_LINES * 2:
        widget.delete("1.0", "3.0")
    widget.see("end")
    widget.configure(state="disabled")


def start() -> None:
    """Starts the overlay on a background thread. Must never raise -- a failure
    here (no display, Tkinter/CTk unavailable, whatever) should only mean the
    recording has no visual aid, not that the assistant fails to start."""
    try:
        threading.Thread(target=_build_window, daemon=True, name="alexis-overlay").start()
    except Exception:
        logger.exception("Failed to start status overlay -- continuing without it.")


def set_state(state: str) -> None:
    try:
        _update_queue.put_nowait(("state", state))
    except queue.Full:
        pass
    except Exception:
        logger.exception("Failed to queue overlay state update.")


def add_transcript(speaker: str, text: str) -> None:
    try:
        _update_queue.put_nowait(("transcript", (speaker, text)))
    except queue.Full:
        pass
    except Exception:
        logger.exception("Failed to queue overlay transcript update.")
