# Card Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a thumbnail-first card result view with quick filters, richer sorting, and right-side detail synchronization for PromptVault search results.

**Architecture:** Extend the existing entry list API so it can return card-summary fields and sort/filter metadata, then replace the current row list in the manager UI with a card grid that drives the existing detail panel. Keep implementation incremental so the current detail rendering and assemble flow remain reusable.

**Tech Stack:** Python, aiohttp, SQLite/FTS, vanilla JavaScript, existing PromptVault UI/CSS

---

### Task 1: Add card-summary fields to the backend list response

**Files:**
- Modify: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\promptvault\db.py`
- Modify: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\promptvault\api.py`
- Test: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\tests\test_card_search.py`

**Step 1: Write the failing test**

```python
def test_search_entries_returns_card_summary_fields():
    store.create_entry({...})
    items = store.search_entries(limit=10)
    assert "favorite" in items[0]
    assert "score" in items[0]
    assert "positive_preview" in items[0]
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_card_search -v`
Expected: FAIL because summary fields are missing.

**Step 3: Write minimal implementation**

- Expand `search_entries()` to include `favorite`, `score`, and a positive prompt preview.
- Keep existing callers compatible.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_card_search -v`
Expected: PASS

**Step 5: Commit**

```bash
git add promptvault/db.py promptvault/api.py tests/test_card_search.py
git commit -m "feat: add card summary fields to search results"
```

### Task 2: Add sorting and quick-filter parameters

**Files:**
- Modify: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\promptvault\db.py`
- Modify: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\promptvault\api.py`
- Test: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\tests\test_card_search.py`

**Step 1: Write the failing test**

```python
def test_search_entries_supports_favorite_filter_and_score_sort():
    ...
    items = store.search_entries(sort="score_desc", favorite_only=True)
    assert len(items) == 1
    assert items[0]["id"] == "entry_high_score"
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_card_search -v`
Expected: FAIL because filter/sort args are unsupported.

**Step 3: Write minimal implementation**

- Add query args for quick filters and sort mode.
- Support at least `favorite_only`, `has_thumbnail`, `sort=updated_desc|score_desc`.

**Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_card_search -v`
Expected: PASS

**Step 5: Commit**

```bash
git add promptvault/db.py promptvault/api.py tests/test_card_search.py
git commit -m "feat: add card search filters and sorting"
```

### Task 3: Replace row list with thumbnail-first cards

**Files:**
- Modify: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\web\comfyui\promptvault.js`
- Modify: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\web\comfyui\promptvault.css`

**Step 1: Write the failing test**

No automated UI test exists. Add a narrow smoke test if the repo gains a JS test runner; otherwise document manual verification targets before coding.

**Step 2: Run verification to confirm the gap**

Run: `rg -n "promptvault.js|promptvault.css" web/comfyui`
Expected: existing row-based layout only.

**Step 3: Write minimal implementation**

- Replace `.pv-row` rendering in `reloadList()` with card rendering.
- Make thumbnail the primary visual region.
- Preserve single-click selection and detail loading.

**Step 4: Run verification**

Run: open ComfyUI manager manually
Expected:
- cards render in a grid
- selected card updates the right detail panel
- selected state is visually obvious

**Step 5: Commit**

```bash
git add web/comfyui/promptvault.js web/comfyui/promptvault.css
git commit -m "feat: add thumbnail-first search cards"
```

### Task 4: Add quick-filter bar and sort selector to the manager UI

**Files:**
- Modify: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\web\comfyui\promptvault.js`
- Modify: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\web\comfyui\promptvault.css`

**Step 1: Write the failing test**

If no UI test harness exists, document manual checks before implementation.

**Step 2: Verify the current UI lacks these controls**

Run: `rg -n "favorite|sort|thumbnail|filter" web/comfyui/promptvault.js`
Expected: no quick-filter chip row for result cards.

**Step 3: Write minimal implementation**

- Add filter chips: `仅收藏`, `高评分`, `有缩略图`, `当前模型可用`
- Add a sort selector with at least `综合排序`, `最近更新`, `评分优先`
- Send selected values to `/promptvault/entries`

**Step 4: Run verification**

Run: manual UI verification
Expected:
- filter chips toggle on/off
- sort selector changes card order
- status bar reflects active filter/sort state

**Step 5: Commit**

```bash
git add web/comfyui/promptvault.js web/comfyui/promptvault.css
git commit -m "feat: add quick filters and sorting controls"
```

### Task 5: Add match reasons and richer detail context

**Files:**
- Modify: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\promptvault\db.py`
- Modify: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\web\comfyui\promptvault.js`
- Test: `I:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_PromptVault\tests\test_card_search.py`

**Step 1: Write the failing test**

```python
def test_search_entries_reports_match_reasons():
    ...
    items = store.search_entries(q="portrait")
    assert "match_reasons" in items[0]
```

**Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_card_search -v`
Expected: FAIL because match reasons are not returned.

**Step 3: Write minimal implementation**

- Build lightweight `match_reasons` from matched title, tags, and content.
- Show them in both card metadata and right detail panel.

**Step 4: Run test and verification**

Run: `python -m unittest tests.test_card_search -v`
Expected: PASS

Run: manual UI verification
Expected: cards and detail panel show non-empty reasons where relevant.

**Step 5: Commit**

```bash
git add promptvault/db.py web/comfyui/promptvault.js tests/test_card_search.py
git commit -m "feat: show match reasons in card search"
```

### Task 6: Verify end-to-end behavior

**Files:**
- Verify only

**Step 1: Run backend tests**

Run: `python -m unittest tests.test_import_export tests.test_card_search -v`
Expected: PASS

**Step 2: Run Python syntax verification**

Run: `python -m compileall promptvault`
Expected: successful compilation with no syntax errors.

**Step 3: Run manual UI verification**

Check:
- card layout works with and without thumbnails
- clicking a card updates the right detail panel
- filters combine correctly
- sorting remains stable between refreshes
- favorite/high-score cards are easy to identify

**Step 4: Commit**

```bash
git add .
git commit -m "feat: complete card-based prompt search improvements"
```
