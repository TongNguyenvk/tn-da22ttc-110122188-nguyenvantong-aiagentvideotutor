"""
Parser: browser-use history -> webreel config + tts_script.

Returns TWO outputs in one pass:
1. A schema-v1-compliant webreel config (no post-processing needed)
2. A tts_script list for direct TTS generation

This replaces both old bu_to_webreel.py AND ai_reviewer.py.

SCHEMA V1 COMPLIANCE:
- additionalProperties: false on EVERY step type
- Only allowed keys per step type (no custom keys)
- selector: string | string[] (array fallback supported)
- stepClick/moveTo: requires either "text" or "selector"
- stepPause: requires "action" + "ms", optional "description"/"label"
- stepNavigate: requires "action" + "url"
- stepType: requires "action" + "text"
- stepKey: requires "action" + "key"
- stepScroll: requires "action" (x/y/selector optional)
"""

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Selector extraction (reused from bu_to_webreel.py, battle-tested)
# ---------------------------------------------------------------------------

def _extract_text_from_element(element_str: str | None) -> str | None:
    if not element_str or not isinstance(element_str, str):
        return None
    ax_match = re.search(r"ax_name='([^']+)'", element_str)
    if ax_match:
        return ax_match.group(1)
    return None


def _extract_selector_from_element(element_str: str | None) -> str | list[str] | None:
    """
    Extract a schema-compliant selector from DOMInteractedElement string.
    Returns string | string[] | None.
    """
    if not element_str or not isinstance(element_str, str):
        return None

    # 1. Parse attributes
    attrs_match = re.search(r"attributes=\{([^}]+)\}", element_str)
    attrs: dict[str, str] = {}
    if attrs_match:
        pairs = re.findall(r"'([^']+)':\s*'([^']*)'", attrs_match.group(1))
        attrs = dict(pairs)

    # 2. Tag name
    tag_match = re.search(r"node_name='(\w+)'", element_str)
    tag = tag_match.group(1).lower() if tag_match else ""

    # 3. XPath
    xpath_match = re.search(r"x_path='([^']+)'", element_str)
    if xpath_match:
        raw_xpath = xpath_match.group(1)
        if raw_xpath.startswith('/'):
            xpath_selector = f"xpath={raw_xpath}"
        else:
            xpath_selector = f"xpath=/{raw_xpath}"
    else:
        xpath_selector = None

    css_selector = None

    # Priority 1: #id (skip dynamic IDs)
    if attrs.get("id"):
        dynamic_id_pattern = r"(:r\d+:|_r_\d+_|^r\d+$|-[0-9a-f]{5,}$)"
        if not re.search(dynamic_id_pattern, attrs["id"]):
            css_selector = f"#{attrs['id']}"

    # Priority 2: <a> tags -> href attribute selector
    if not css_selector and tag == "a" and attrs.get("href"):
        href = attrs["href"]
        try:
            from urllib.parse import unquote
            href_clean = unquote(href).split('?')[0].split('#')[0]
            if href_clean and href_clean != '/':
                css_selector = f"a[href^='{href_clean}']"
            elif attrs.get("title"):
                css_selector = f"a[title='{attrs['title']}']"
            else:
                css_selector = f"a[href='{unquote(href)}']"
        except Exception:
            css_selector = f"a[href='{href}']"

    # Priority 3: [name=...]
    if not css_selector and attrs.get("name") and tag in ("input", "textarea", "select", "button"):
        css_selector = f"{tag}[name='{attrs['name']}']"

    # Priority 4: [aria-label=...]
    if not css_selector and attrs.get("aria-label"):
        css_selector = f"{tag}[aria-label='{attrs['aria-label']}']"

    # Priority 5: [role=...][type=...]
    if not css_selector and attrs.get("role") and attrs.get("type"):
        css_selector = f"{tag}[role='{attrs['role']}'][type='{attrs['type']}']"

    # Priority 6: tag fallback (but skip generic tags AND form inputs without attributes)
    # IMPORTANT: Don't use bare "input"/"textarea"/"select" as fallback because they're too generic
    # If we only have xpath for form inputs, use xpath only (no unreliable fallback)
    if not css_selector and tag and tag not in ("div", "span", "section", "article", "main", "header", "footer", "input", "textarea", "select", "button"):
        css_selector = tag

    # Return xpath-only if no reliable CSS selector found
    # This prevents webreel from using unreliable fallbacks like bare "input" tag
    if xpath_selector and css_selector:
        return [xpath_selector, css_selector]
    elif xpath_selector:
        return xpath_selector
    elif css_selector:
        return css_selector

    # Return None instead of "*" to signal "no usable selector"
    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def convert_history_to_config_and_script(
    history_data: dict[str, Any],
    video_name: str = "demo",
    cdp_url: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """
    Parse browser-use history into a webreel config AND a tts_script list.

    Returns:
        (config, tts_script) where:
        - config: schema-v1-compliant webreel JSON config
        - tts_script: list of {"text": "...", "narration_index": i} dicts
    """
    steps: list[dict[str, Any]] = []
    tts_script: list[dict[str, str]] = []

    # Get start URL
    start_url = ""
    urls = history_data.get("urls", [])
    if urls:
        for url in urls:
            if url and url != "about:blank":
                start_url = url
                break
        if not start_url and urls:
            start_url = urls[0]

    is_google_search = "google.com" in start_url.lower() if start_url else False

    # Initial page load pause
    if start_url and start_url != "about:blank":
        steps.append({
            "action": "pause",
            "ms": 3000,  # Increased from 2000ms to let Chrome fully render
            "description": "Wait for initial page to load"
        })

    actions = history_data.get("model_actions", [])
    navigated_to_start = False
    last_input_selector = None
    last_input_text = None
    narration_counter = 0
    last_narration_text = ""  # For deduplication

    for i, action_item in enumerate(actions):

        # ===== SAVE_NARRATION -> standalone pause + tts_script entry =====
        if "save_narration" in action_item:
            narration_data = action_item["save_narration"]
            text = narration_data.get("text", "") if isinstance(narration_data, dict) else str(narration_data)
            if text.strip():
                # Dedup: skip if >80% similar to the previous narration
                clean_text = text.strip()
                if last_narration_text:
                    overlap = len(set(clean_text.split()) & set(last_narration_text.split()))
                    total = max(len(set(clean_text.split())), 1)
                    similarity = overlap / total
                    if similarity > 0.8:
                        logger.info(f"[V3 Parser] Skipping duplicate narration (similarity={similarity:.0%}): {clean_text[:50]}...")
                        continue

                idx = narration_counter
                narration_counter += 1
                last_narration_text = clean_text

                # Add to tts_script for Phase 3
                tts_script.append({
                    "text": clean_text,
                    "narration_index": idx,
                })

                # Create a placeholder pause in the config (ms will be replaced by injector)
                steps.append({
                    "action": "pause",
                    "ms": 1000,
                    "description": f"[NARRATION:{idx}] {clean_text}"
                })

                logger.info(f"[V3 Parser] Narration {idx}: {clean_text[:50]}...")
            continue

        # ===== Get element info =====
        element_str = str(action_item.get("interacted_element", ""))

        # ===== NAVIGATE =====
        if "navigate" in action_item:
            nav_data = action_item["navigate"]
            url = nav_data.get("url", "") if isinstance(nav_data, dict) else str(nav_data)

            if url and (url != start_url or navigated_to_start):
                steps.append({
                    "action": "navigate",
                    "url": url,
                    "description": f"Navigate to {url}"
                })
                steps.append({
                    "action": "pause",
                    "ms": 3000,
                    "description": "Wait for page to load"
                })
            elif url == start_url:
                navigated_to_start = True

        # ===== CLICK =====
        elif "click" in action_item:
            selector = _extract_selector_from_element(element_str)
            if selector is not None:  # Explicit None check (skip if no usable selector)
                element_text = _extract_text_from_element(element_str)
                click_desc = f"Click on {element_text}" if element_text else "Click element"

                # Check if this is a checkbox input (type="checkbox")
                is_checkbox = False
                if "type='checkbox'" in element_str or 'type="checkbox"' in element_str:
                    is_checkbox = True

                if is_checkbox:
                    # For checkbox: use Space key instead of click to avoid double-click issue
                    steps.append({
                        "action": "moveTo",
                        "selector": selector,
                    })
                    steps.append({
                        "action": "key",
                        "key": " ",
                        "target": selector,
                        "label": "✓",
                        "description": click_desc
                    })
                else:
                    # Normal click: moveTo before click for natural cursor animation
                    steps.append({
                        "action": "moveTo",
                        "selector": selector,
                    })
                    steps.append({
                        "action": "click",
                        "selector": selector,
                        "description": click_desc
                    })
                
                # Wait for result
                steps.append({
                    "action": "pause",
                    "ms": 2000,
                    "description": "Wait after click"
                })
            else:
                logger.warning(f"[V3 Parser] Skipping click: no valid selector found")

        # ===== INPUT (type text) =====
        elif "input" in action_item:
            inp_data = action_item["input"]
            text = inp_data.get("text", "") if isinstance(inp_data, dict) else ""
            selector = _extract_selector_from_element(element_str)

            if text and selector:
                clean_text = text.replace('\n', '')

                # Deduplicate
                if selector == last_input_selector and clean_text == last_input_text:
                    continue
                last_input_selector = selector
                last_input_text = clean_text

                # Focus: click on input first
                steps.append({
                    "action": "click",
                    "selector": selector,
                    "description": "Focus input field"
                })
                steps.append({
                    "action": "pause",
                    "ms": 300,
                })

                # Type
                has_enter = '\n' in text
                clean_text = text.replace('\n', '')

                if clean_text:
                    steps.append({
                        "action": "type",
                        "text": clean_text,
                        "selector": selector,
                        "charDelay": 50,
                        "description": f"Type '{clean_text[:30]}'"
                    })

                # Handle Enter
                should_press_enter = has_enter
                if not should_press_enter and i + 1 < len(actions):
                    next_action = actions[i + 1]
                    if "send_keys" in next_action:
                        keys = next_action.get("send_keys", {}).get("keys", "")
                        if keys.lower() == "enter":
                            should_press_enter = True

                if should_press_enter:
                    steps.append({"action": "pause", "ms": 1000})
                    if is_google_search:
                        steps.append({"action": "moveTo", "selector": "input[name='btnK']"})
                        steps.append({"action": "click", "selector": "input[name='btnK']"})
                    else:
                        steps.append({"action": "key", "key": "Enter", "target": selector})
                    steps.append({"action": "pause", "ms": 4000})

        # ===== SELECT_DROPDOWN =====
        elif "select_dropdown" in action_item:
            dropdown_data = action_item["select_dropdown"]
            value = dropdown_data.get("text", "") if isinstance(dropdown_data, dict) else str(dropdown_data)
            selector = _extract_selector_from_element(element_str)

            if value and selector:
                # Use webreel's native select action
                steps.append({
                    "action": "select",
                    "selector": selector,
                    "value": value,
                    "description": f"Select '{value}' from dropdown"
                })
                steps.append({
                    "action": "pause",
                    "ms": 300,
                })

        # ===== WAIT =====
        elif "wait" in action_item:
            wait_data = action_item["wait"]
            seconds = wait_data.get("seconds", 1) if isinstance(wait_data, dict) else 1
            ms = int(float(seconds) * 1000)
            steps.append({"action": "pause", "ms": ms})

        # ===== SCROLL =====
        elif "scroll" in action_item:
            scroll_data = action_item["scroll"]
            if isinstance(scroll_data, dict):
                # browser-use format: {down: bool, pages: float, index: int|None}
                if "pages" in scroll_data:
                    pages = float(scroll_data.get("pages", 1.0))
                    down = scroll_data.get("down", True)
                    # Convert pages to pixels (1 page = viewport height = 1080px)
                    pixels = int(pages * 1080)
                    if not down:
                        pixels = -pixels
                    steps.append({"action": "scroll", "y": pixels})
                    steps.append({"action": "pause", "ms": 1500,
                                  "description": f"Wait after scroll {'down' if down else 'up'} {pages} pages"})
                    logger.info(f"[V3 Parser] Scroll: {'down' if down else 'up'} {pages} pages -> {pixels}px")
                # Legacy fallback: {amount: int}
                elif "amount" in scroll_data:
                    steps.append({"action": "scroll", "y": scroll_data["amount"]})
                    steps.append({"action": "pause", "ms": 1000})
                # Selector-based scroll
                elif "selector" in scroll_data:
                    steps.append({"action": "scroll", "selector": scroll_data["selector"]})
                    steps.append({"action": "pause", "ms": 1000})
                # Bare direction fallback: {down: bool} without pages
                elif "down" in scroll_data:
                    down = scroll_data.get("down", True)
                    pixels = 1080 if down else -1080
                    steps.append({"action": "scroll", "y": pixels})
                    steps.append({"action": "pause", "ms": 1500})

        # ===== SEND_KEYS (standalone, not following input) =====
        elif "send_keys" in action_item:
            keys_data = action_item["send_keys"]
            keys = keys_data.get("keys", "") if isinstance(keys_data, dict) else str(keys_data)
            if keys:
                steps.append({"action": "key", "key": keys})

        # ===== EXTRACT -> scroll to show content =====
        elif "extract" in action_item:
            for _ in range(3):
                steps.append({"action": "scroll", "y": 500})
                steps.append({"action": "pause", "ms": 2000})

        # ===== done, write_file, etc. -> SKIP =====

    # Add tail pause to prevent video cut-off
    steps.append({
        "action": "pause",
        "ms": 5000,
        "description": "Final tail pause"
    })

    # Build config (100% schema v1 compliant)
    video_config: dict[str, Any] = {
        "url": start_url,
        "viewport": {
            "width": 1920,
            "height": 1080
        },
        "defaultDelay": 300,
        "steps": steps
    }
    
    # Add cdpUrl if provided
    if cdp_url:
        video_config["cdpUrl"] = cdp_url
    
    config: dict[str, Any] = {
        "$schema": "https://webreel.dev/schema/v1.json",
        "videos": {
            video_name: video_config
        }
    }

    logger.info(f"[V3 Parser] Generated {len(steps)} steps, {len(tts_script)} narration segments")
    return config, tts_script
