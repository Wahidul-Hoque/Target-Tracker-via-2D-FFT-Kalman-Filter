"""Centralized desktop design tokens and ttk styles."""
from tkinter import ttk

BG = '#0b1220'
PANEL = '#131f31'
CARD = '#1a2a40'
TEXT = '#e5edf7'
MUTED = '#91a6be'
ACCENT = '#53ddd0'
RED = '#ff7988'
GREEN = '#79e2a5'
BLUE = '#69a9ff'
AMBER = '#f4c474'


def apply_theme(root):
    root.configure(bg=BG)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=BG, foreground=TEXT, font=('Helvetica', 10))
    style.configure('TFrame', background=BG)
    style.configure('Card.TFrame', background=PANEL)
    style.configure('TLabel', background=BG, foreground=TEXT)
    style.configure('Muted.TLabel', foreground=MUTED)
    style.configure('Title.TLabel', font=('Helvetica', 25, 'bold'))
    style.configure('Card.TLabel', background=PANEL)
    style.configure('Metric.TLabel', background=PANEL, foreground=ACCENT, font=('Courier', 16, 'bold'))
    style.configure('TButton', background=CARD, foreground=TEXT, borderwidth=0, padding=(14, 10), font=('Helvetica', 10, 'bold'))
    style.map('TButton', background=[('active', '#29445e'), ('disabled', PANEL)], foreground=[('disabled', '#566c86')])
    style.configure('Accent.TButton', background=ACCENT, foreground=BG)
    style.map('Accent.TButton', background=[('active', '#8cf0e6'), ('disabled', PANEL)])
    style.configure('TNotebook', background=BG, borderwidth=0)
    style.configure('TNotebook.Tab', background=PANEL, foreground=MUTED, padding=(22, 12))
    style.map('TNotebook.Tab', background=[('selected', CARD)], foreground=[('selected', ACCENT)])
    style.configure('TScale', background=PANEL, troughcolor=CARD)
    style.configure('TCheckbutton', background=PANEL, foreground=TEXT)
