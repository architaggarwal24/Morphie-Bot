"""UX details in the browser UI (skeletons, undo toasts, command menu, ...).

Same idea as test_frontend_contract.py: no browser, just checks that chatbot.html, app.js and app.css agree
and that each behaviour is actually wired up. (The behaviour itself was also exercised in headless Chromium while building these.)"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src"
HTML = (ROOT / "templates" / "chatbot.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    start = JS.index(f"function {name}(")
    nxt = re.search(r"\n  (?:async )?function \w+\(", JS[start + 10:])
    return JS[start:start + 10 + nxt.start()] if nxt else JS[start:]


# ---- 1. skeleton loaders ----

def test_skeleton_rows_come_from_the_same_builder_as_loaded_rows():
    assert "function buildDocRow(" in JS
    assert JS.count("function buildDocRow(") == 1
    assert "buildDocRow(null" in JS          # skeleton variant
    assert "buildDocRow(d" in JS             # loaded variant


def test_skeletons_only_appear_after_a_delay_of_about_300ms():
    assert re.search(r"SKELETON_DELAY_MS\s*=\s*300\b", JS)
    assert "setTimeout" in _function_body("loadDocuments") and "SKELETON_DELAY_MS" in _function_body("loadDocuments")


def test_skeleton_styles_exist_and_stop_shimmering_for_reduced_motion():
    assert ".is-skeleton" in CSS and ".mp-skeleton" in CSS or ".is-skeleton" in CSS
    shimmer_rule = CSS.index(".is-skeleton .mp-list-item__title,")
    after = CSS[shimmer_rule:]
    reduced = after[after.index("prefers-reduced-motion"):]   # must come after the rule it overrides
    assert "is-skeleton" in reduced and "animation: none" in reduced


# ---- 2. optimistic updates ----

def test_deleting_a_document_updates_the_screen_before_the_request_and_rolls_back_on_failure():
    body = _function_body("deleteDocument")
    assert body.index("allDocuments.splice(") < body.index("callApi("), "the row must leave the list before the request is sent"
    assert "splice(index, 0" in body, "a failed request must put the document back where it was"
    assert "showToast(" in body, "and tell the person"


def test_chat_never_targets_a_document_that_is_being_deleted():
    body = _function_body("getSelectedDocumentIds")
    assert "allDocuments" in body, "all-documents mode must list ids from the current (optimistic) list, not send null"


def test_payments_are_not_optimistic():
    assert "payment" not in JS.lower()


# ---- 3. command menu ----

def test_the_page_has_an_accessible_command_menu():
    assert re.search(r'<div id="commandMenu"[^>]*role="dialog"[^>]*aria-modal="true"[^>]*hidden', HTML)
    field = re.search(r'<input id="cmdInput"[^>]*>', HTML).group(0)
    assert 'role="combobox"' in field and 'aria-controls="cmdList"' in field and 'aria-autocomplete="list"' in field
    assert re.search(r'<ul id="cmdList"[^>]*role="listbox"', HTML)


def test_cmd_or_ctrl_k_opens_the_menu_and_it_works_from_the_keyboard_alone():
    assert re.search(r'commandMenu: \{ key: "k", mod: true', JS) and "metaKey" in JS and "ctrlKey" in JS
    body = _function_body("onCommandKeydown")
    for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
        assert f'"{key}"' in body, key
    assert "aria-activedescendant" in JS and 'role", "option"' in JS


def test_the_menu_lists_every_page_and_action():
    for action_id in ("newChat", "chat", "documents", "upload", "theme", "settings"):
        assert re.search(rf'id:\s*"{action_id}"', JS), action_id


def test_escape_in_the_menu_does_not_also_close_the_documents_panel_behind_it():
    assert "stopPropagation" in _function_body("onCommandKeydown")


def test_command_menu_styles_exist():
    for cls in (".mp-cmd__card", ".mp-cmd__input", ".mp-cmd__item", ".mp-cmd__item[aria-selected=\"true\"]"):
        assert cls in CSS, cls


# ---- 4. shortcut hints ----

def _shortcut_ids() -> set[str]:
    block = JS[JS.index("var SHORTCUTS = {"):]
    block = block[:block.index("\n  };")]
    return set(re.findall(r"^    (\w+): \{", block, re.M))


def test_there_is_one_shortcut_registry_and_it_names_the_platform_modifier():
    assert {"commandMenu", "newChat", "focusInput"} <= _shortcut_ids()
    assert "IS_MAC" in JS and "\u2318" in JS or "⌘" in JS
    body = _function_body("formatShortcut")
    assert "⌘" in body and "Ctrl" in body and "⇧" in body and "Shift" in body


def test_shortcuts_do_not_fire_while_typing_and_ignore_ime_composition():
    assert "function isTypingTarget(" in JS
    assert "e.isComposing" in JS
    assert re.search(r"if \(typing && !def\.mod\) return;", JS), "plain keys must never fire inside a field"


def test_every_hint_in_the_page_points_at_a_real_shortcut():
    used = set(re.findall(r'data-shortcut="(\w+)"', HTML))
    assert used and used <= _shortcut_ids(), used - _shortcut_ids()


def test_shortcuts_are_shown_in_the_command_menu_tooltips_and_buttons():
    menu = _function_body("buildCommandActions")
    for action_id in _shortcut_ids() - {"commandMenu"}:   # the menu's own chord is shown on the Search button instead
        assert f'shortcut: "{action_id}"' in menu, action_id
    assert "mp-kbd" in JS and ".mp-kbd" in CSS
    assert "function applyShortcutHints(" in JS and "aria-keyshortcuts" in JS


# ---- 5. undo toasts ----

def test_toasts_are_status_regions_and_can_carry_an_undo_button():
    body = _function_body("showToast")
    assert 'setAttribute("role", "status")' in body
    assert "options.action" in body and 'el("button"' in body


def test_nothing_asks_for_confirmation_first():
    assert not re.search(r"\bconfirm\(", JS) and "window.prompt" not in JS


def test_deleting_a_document_waits_5_to_10_seconds_for_an_undo_before_the_request_is_sent():
    ms = int(re.search(r"UNDO_MS\s*=\s*(\d+)", JS).group(1))
    assert 5000 <= ms <= 10000
    body = _function_body("deleteDocument")
    assert "UNDO_MS" in body and '"Undo"' in body
    assert re.search(r"setTimeout\(\s*send\b", body), "the request (send) is what the timer delays"


def test_a_pending_delete_is_never_lost_when_the_tab_closes_or_a_file_is_uploaded():
    assert '"pagehide"' in JS and "keepalive" in JS
    assert "flushPendingDeletes()" in _function_body("uploadFile")


def test_removing_the_saved_key_offers_undo_too():
    clear = JS[JS.index('getElementById("settingsClearBtn")'):]
    clear = clear[:clear.index("});")]
    assert '"Undo"' in clear and "saveLlm(" in clear


def test_toasts_stack_instead_of_overlapping_and_fade_with_a_transition():
    assert ".toast-stack" in CSS and ".toast.is-visible" in CSS and "transition" in CSS[CSS.index(".toast {"):CSS.index(".toast.is-visible")]


# ---- 6. stale-while-revalidate ----

def test_the_cached_documents_list_is_shown_first_and_a_failed_refresh_keeps_it():
    body = _function_body("loadDocuments")
    assert "if (docsLoaded) renderDocsList();" in body, "cached list is painted before the request goes out"
    assert re.search(r"if \(!result\.ok\) \{\s*if \(!docsLoaded\)", body), "a failed background refresh must not wipe what is on screen"


def test_older_responses_never_overwrite_newer_ones():
    body = _function_body("loadDocuments")
    assert re.search(r"requestId !== docsRequestId", body)


def test_the_data_is_refetched_when_the_window_regains_focus_or_the_network_returns():
    body = _function_body("revalidate")
    assert "loadDocuments()" in body and "loadStatus()" in body
    for event in ('"focus"', '"online"', '"visibilitychange"'):
        assert f"addEventListener({event}" in JS, event


def test_only_harmless_lists_use_stale_data_never_anything_that_costs_money():
    assert "balance" not in JS.lower() and "stock" not in JS.lower()


# ---- 9. view transitions ----

def test_same_page_changes_go_through_one_helper_that_skips_unsupported_and_reduced_motion():
    body = _function_body("withTransition")
    assert "document.startViewTransition" in body and "prefers-reduced-motion" in body
    for name in ("toggleTheme", "renderDocsListAnimated"):
        assert "withTransition(" in _function_body(name), name
    assert "withTransition(" in JS[JS.index('getElementById("newChatBtn")'):]


def test_moving_rows_share_a_view_transition_name_and_are_named_uniquely():
    assert "viewTransitionName" in _function_body("buildDocRow") and "docTransitionName" in JS


def test_view_transitions_are_short_never_block_input_and_stop_for_reduced_motion():
    block = CSS[CSS.index("::view-transition-group(*)"):]
    durations = [float(x) for x in re.findall(r"animation-duration:\s*([\d.]+)s", block[:600])]
    assert durations and max(durations) < 0.3
    assert JS.count("startViewTransition(") == 1, "one helper only, so it can't creep into typing, streaming or scrolling"
    assert "appendToken" not in _function_body("withTransition")
    reduced = block[block.index("prefers-reduced-motion"):]
    assert "::view-transition-old(*)" in reduced and "animation: none" in reduced
    assert "@view-transition" not in CSS, "single-page app: there are no page-to-page navigations to animate"


# ---- 13. hit slop / tap targets ----

def test_touch_screens_get_48px_targets_which_also_covers_the_44pt_ios_minimum():
    block = CSS[CSS.index("@media (pointer: coarse)"):]
    assert "--mp-tap: 48px" in block
    for selector in (".mp-header-btn", ".mp-panel-close", ".mp-composer-btn", ".mp-btn--sm", ".mp-list-item__check", ".mp-nav-item", ".toast__action"):
        assert selector in block, selector
    assert "min-height: var(--mp-tap)" in block and "min-width: var(--mp-tap)" in block


def test_document_checkboxes_sit_in_a_label_so_the_whole_label_is_the_tap_target():
    body = _function_body("buildDocRow")
    assert 'el("label", "mp-list-item__check")' in body and "aria-label" in body


# ---- 14. safe-area insets ----

def test_the_page_extends_under_the_notch_and_pads_what_is_tappable_with_env_insets():
    assert 'name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"' in HTML
    def rule(selector: str) -> str:
        start = CSS.index(selector + " {")
        return CSS[start:CSS.index("}", start)]
    assert "env(safe-area-inset-top" in rule("#chatHeader") and "env(safe-area-inset-top" in rule(".mp-panel-head")
    assert "env(safe-area-inset-bottom" in rule("#composerWrap") and "env(safe-area-inset-bottom" in rule(".toast-stack")
    assert "env(safe-area-inset-bottom" in rule("#sidebar") and "env(safe-area-inset-left" in rule("#sidebar")
    assert "env(safe-area-inset-bottom" in rule(".mp-panel-body")
    assert "env(safe-area-inset-top" in rule(".mp-modal") and "env(safe-area-inset-bottom" in rule(".mp-modal")
    assert "env(safe-area-inset-left" in rule("#composerWrap") and "env(safe-area-inset-right" in rule("#chat")


# ---- 17. balanced headlines ----

def test_headings_are_balanced_and_paragraphs_avoid_orphans():
    assert re.search(r"h1,\s*h2,\s*h3,\s*h4\s*\{[^}]*text-wrap:\s*balance", CSS)
    pretty = re.search(r"([^{}]*)\{[^}]*text-wrap:\s*pretty", CSS).group(1)
    for selector in ("p", ".mp-modal__note", ".mp-composer-hint"):
        assert selector in [s.strip() for s in pretty.split(",")], selector


def test_streaming_chat_bubbles_are_not_re_balanced_while_text_arrives():
    bubble_rules = re.findall(r"[^{}]*\.mp-bubble[^{}]*\{[^}]*text-wrap[^}]*\}", CSS)
    assert bubble_rules == []


# ---- 18. continuous corners ----

def test_every_rounded_box_gets_a_squircle_next_to_its_border_radius_and_pills_and_dots_do_not():
    declared = re.findall(r"border-radius:\s*var\(--mp-radius-(?:sm|md|lg)\);(\s*corner-shape:\s*squircle;)?", CSS)
    assert len(declared) >= 15 and all(declared), "a token radius without its squircle"
    assert not re.search(r"(?:radius-pill|50%)\);?\s*corner-shape", CSS) and not re.search(r"50%;\s*corner-shape", CSS)
    assert "@supports" not in CSS[CSS.index("corner-shape") - 200:CSS.index("corner-shape")], "browsers that don't know it simply ignore the line"


# ---- 19. (client half only) no double submit while an upload runs ----

def test_the_upload_controls_are_disabled_while_a_request_runs_and_always_come_back():
    body = _function_body("uploadFile")
    assert "if (uploading) return;" in body and "uploadBtn.disabled = true" in body
    assert "finally" in body and "uploadBtn.disabled = false" in body.split("finally")[1]
    assert ".mp-dropzone.is-busy" in CSS
