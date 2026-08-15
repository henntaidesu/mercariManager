# -*- coding: utf-8 -*-
"""雅虎通知（あなた宛のお知らせ）同步。"""

from .notice_sync import sync_yahoo_notifications
from .order_completion import apply_yahoo_receipt_notices

__all__ = ["sync_yahoo_notifications", "apply_yahoo_receipt_notices"]
