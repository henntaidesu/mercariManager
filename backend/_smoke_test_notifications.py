import os

os.environ.setdefault("SSL_MITM_AUTO_START", "0")
from src.db_manage.database import DatabaseManager
from src.use_web.notifications.units.notifications_query import (
    _PINNED_KINDS,
    list_notifications,
)

db = DatabaseManager()

print("=== kind counts in DB ===")
rows = db.execute_query(
    "SELECT [kind], COUNT(*) FROM [notifications] GROUP BY [kind] ORDER BY 2 DESC"
)
for r in rows:
    print(" ", r[0], "->", r[1])

print()
print("=== list_notifications(only_unread=True, exclude_kinds='Like') ===")
res = list_notifications(only_unread=True, exclude_kinds="Like", page=1, page_size=200)
seen_kinds = {}
for it in res.get("items", []):
    k = it.get("kind") or "(null)"
    seen_kinds[k] = seen_kinds.get(k, 0) + 1
for k, n in sorted(seen_kinds.items(), key=lambda x: -x[1]):
    print(" ", k, "->", n)
print("Total returned by COUNT:", res["total"])

print()
print("=== first 8 rows (verify pinning) ===")
for i, it in enumerate(res.get("items", [])[:8]):
    print(
        f"  [{i}] kind={it.get('kind')!r} created={it.get('mercari_created')} "
        f"id={it.get('id')}"
    )

print()
print("=== Sanity: list_notifications WITHOUT exclude_kinds ===")
res2 = list_notifications(only_unread=True, page=1, page_size=200)
seen2 = {}
for it in res2.get("items", []):
    k = it.get("kind") or "(null)"
    seen2[k] = seen2.get(k, 0) + 1
for k, n in sorted(seen2.items(), key=lambda x: -x[1]):
    print(" ", k, "->", n)
print("Total:", res2["total"])
