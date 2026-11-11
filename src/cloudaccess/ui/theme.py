"""浅色现代主题：调色板、全局 QSS 与厂商头像绘制。"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen

# ---------- 调色板 ----------

BG = "#F3F5F9"
PANEL = "#FFFFFF"
PANEL_2 = "#F8FAFC"
BORDER = "#E5E9F2"
TEXT = "#1F2937"
TEXT_2 = "#6B7280"
TEXT_3 = "#9CA3AF"
ACCENT = "#3B82F6"
ACCENT_HOVER = "#2563EB"
ACCENT_PRESSED = "#1D4ED8"
ACCENT_SOFT = "#EFF6FF"
SUCCESS = "#16A34A"
SUCCESS_SOFT = "#DCFCE7"
WARN = "#D97706"
WARN_SOFT = "#FEF3C7"
DANGER = "#DC2626"
DANGER_SOFT = "#FEE2E2"
INPUT_BG = "#F1F5F9"

RADIUS = 10


def apply_theme(app) -> None:
    """为整个应用安装全局 QSS。"""
    app.setStyleSheet(GLOBAL_QSS)


GLOBAL_QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    font-size: 13px;
}}
QWidget:disabled {{ color: {TEXT_3}; }}

QToolTip {{
    background: {PANEL};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
}}

/* ---------- 标题栏 ---------- */
#TitleBar {{
    background: {PANEL};
    border-bottom: 1px solid {BORDER};
}}
#TitleLabel {{
    background: transparent;
    color: {TEXT};
    font-size: 13px;
    font-weight: 600;
}}
#TitleButton {{
    background: transparent;
    border: none;
    border-radius: 6px;
    color: {TEXT_2};
    font-size: 14px;
    min-width: 34px; max-width: 34px;
    min-height: 26px; max-height: 26px;
}}
#TitleButton:hover {{ background: {INPUT_BG}; color: {TEXT}; }}
#TitleButton[class="close"]:hover {{ background: {DANGER}; color: white; }}

/* ---------- 按钮 ---------- */
QPushButton {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; background: {ACCENT_SOFT}; }}
QPushButton:pressed {{ background: {ACCENT_SOFT}; }}

#PrimaryButton {{
    background: {ACCENT}; color: white; border: none; font-weight: 600;
}}
#PrimaryButton:hover {{ background: {ACCENT_HOVER}; }}
#PrimaryButton:pressed {{ background: {ACCENT_PRESSED}; }}
#PrimaryButton:disabled {{ background: {BORDER}; color: {TEXT_3}; }}

#DangerButton {{
    background: white; color: {DANGER}; border: 1px solid #FECACA; font-weight: 600;
}}
#DangerButton:hover {{ background: {DANGER_SOFT}; border-color: {DANGER}; }}

#SoftButton {{
    background: {ACCENT_SOFT}; color: {ACCENT}; border: 1px solid #BFDBFE; font-weight: 600;
}}
#SoftButton:hover {{ background: #DBEAFE; border-color: {ACCENT}; }}

/* ---------- 输入框 ---------- */
QLineEdit {{
    background: {INPUT_BG};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 7px 12px;
    color: {TEXT};
}}
QLineEdit:focus {{ background: white; border: 1px solid {ACCENT}; }}

/* ---------- 侧栏 ---------- */
#Sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
#SidebarTitle {{
    background: transparent; color: {TEXT_2}; font-size: 12px; font-weight: 600;
}}
#AccountList {{
    background: transparent; border: none;
}}
#AccountList::item {{ border: none; margin: 0; padding: 0; }}
#AccountList::item:selected {{ background: transparent; }}

/* ---------- 服务器面板 ---------- */
#ServerPanel {{ background: {BG}; }}
#PanelHeader {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
#PanelTitle {{ background: transparent; font-size: 15px; font-weight: 700; }}
#PanelSubtitle {{ background: transparent; color: {TEXT_2}; font-size: 12px; }}

#ServerTable {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
    gridline-color: transparent;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
}}
#ServerTable QHeaderView::section {{
    background: {PANEL_2};
    color: {TEXT_2};
    font-weight: 600;
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 9px 10px;
}}
#ServerTable QTableCornerButton::section {{
    background: {PANEL_2}; border: none;
}}
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 4px 2px;
}}
QScrollBar::handle:vertical {{ background: #CBD5E1; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_3}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

/* ---------- 对话框 ---------- */
#Dialog {{ background: {PANEL}; }}
#DialogTitle {{ font-size: 16px; font-weight: 700; background: transparent; }}
#VendorCard {{
    background: {PANEL_2}; border: 2px solid {BORDER}; border-radius: 12px;
}}
#VendorCard:checked {{
    border: 2px solid {ACCENT}; background: {ACCENT_SOFT};
}}
#VendorCard:hover:!checked {{ border-color: #B6C3D9; }}
#VendorName {{ background: transparent; font-weight: 600; border: none; }}
#VendorName:checked {{ color: {ACCENT}; }}
#FormLabel {{ background: transparent; color: {TEXT_2}; font-size: 12px; }}
#HintLabel {{ background: transparent; color: {TEXT_3}; font-size: 11px; }}
#StatusChip {{
    border-radius: 999px; padding: 2px 10px; font-size: 12px; font-weight: 600;
    background: {INPUT_BG}; color: {TEXT_2};
}}
"""


def paint_vendor_avatar(
    painter: QPainter,
    rect: QRectF,
    color: str,
    initial: str,
    selected: bool = False,
) -> None:
    """绘制圆形厂商头像：纯色圆 + 白色首字母。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = rect.width() / 2
    center = rect.center()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(center, r, r)
    font = QFont()
    font.setPixelSize(int(rect.height() * 0.48))
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QPen(QColor("white")))
    painter.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, initial)
    painter.restore()
