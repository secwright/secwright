from secwright.grading.diff import parse_diff

MODIFIED = """\
diff -ruN -x .git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
 def f(x):
-    return x
+    if x is None:
+        raise ValueError
+    return x

"""

CREATED_AND_DELETED = """\
diff -ruN a/new.py b/new.py
--- a/new.py
+++ b/new.py
@@ -0,0 +1,2 @@
+a = 1
+b = 2
diff -ruN a/old.py b/old.py
--- a/old.py
+++ b/old.py
@@ -1,3 +0,0 @@
-x = 1
-y = 2
-z = 3
"""

# Removed content that itself starts with "-- " and added content starting with "++ ".
TRICKY = """\
--- a/notes.sql
+++ b/notes.sql
@@ -1,2 +1,2 @@
--- a SQL comment
+++ not a header
 SELECT 1;
"""


def test_modified_file_counts():
    [c] = parse_diff(MODIFIED)
    assert (c.path, c.added, c.removed, c.created, c.deleted) == ("src/app.py", 3, 1, False, False)


def test_created_and_deleted_files():
    new, old = parse_diff(CREATED_AND_DELETED)
    assert new.path == "new.py" and new.created and not new.deleted and new.added == 2
    assert old.path == "old.py" and old.deleted and not old.created and old.removed == 3


def test_content_that_looks_like_headers():
    [c] = parse_diff(TRICKY)
    assert (c.path, c.added, c.removed) == ("notes.sql", 1, 1)


def test_empty_diff():
    assert parse_diff("") == []
