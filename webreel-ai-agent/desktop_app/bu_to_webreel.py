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

import os
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
    # Track xem da co action (ArrowRight/click/input/navigate) ke tu narration cuoi chua.
    # Neu chua (2 save_narration lien tiep, khong co action giua), narration moi se
    # ghi DE narration cuoi (vi agent thuong goi 2 save_narration cho cung 1 context
    # khi tu sua noi dung). Neu co action giua -> day la narration moi cho context moi.
    narration_advanced_since_last = True
    # Count actions since last narration to distinguish "rewrite on same context"
    # vs "new narration for new context"
    actions_since_last_narration = 0

    for i, action_item in enumerate(actions):

        # ===== SAVE_NARRATION -> standalone pause + tts_script entry =====
        if "save_narration" in action_item:
            narration_data = action_item["save_narration"]
            text = narration_data.get("text", "") if isinstance(narration_data, dict) else str(narration_data)
            if text.strip():
                clean_text = text.strip()

                # CASE 1: Hai save_narration LIEN TIEP tren cung context (chua co action giua).
                # Agent thuong tu sua loi narration vua noi -> noi dung sau chi tiet hon.
                # Ghi DE narration cuoi (giu narration sau) thay vi them moi.
                # CHI ap dung khi: (a) chua co action nao giua 2 narration, VA
                # (b) chua co ArrowRight/slide-advance (presentation mode).
                should_replace = (
                    not narration_advanced_since_last and
                    actions_since_last_narration == 0 and
                    tts_script and
                    steps
                )

                if should_replace:
                    prev_idx = tts_script[-1]["narration_index"]
                    logger.info(
                        f"[V3 Parser] Replacing previous narration {prev_idx} "
                        f"(agent rewrote on same context): {clean_text[:50]}..."
                    )
                    tts_script[-1]["text"] = clean_text
                    # Tim pause cuoi co tag [NARRATION:prev_idx] va cap nhat description
                    for step in reversed(steps):
                        if step.get("action") == "pause" and step.get("description", "").startswith(f"[NARRATION:{prev_idx}]"):
                            step["description"] = f"[NARRATION:{prev_idx}] {clean_text}"
                            break
                    last_narration_text = clean_text
                    continue

                # CASE 2: similarity-based dedup (fallback - khi co action giua nhung
                # narration moi gan giong narration cu, vd: agent retry sau loi khac).
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
                narration_advanced_since_last = False  # reset cho luot ke
                actions_since_last_narration = 0  # reset counter

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
            actions_since_last_narration += 1
            nav_data = action_item["navigate"]
            url = nav_data.get("url", "") if isinstance(nav_data, dict) else str(nav_data)

            if url and (url != start_url or navigated_to_start):
                steps.append({
                    "action": "navigate",
                    "url": url,
                    "description": f"Navigate to {url}"
                })
                
                # CRITICAL: OneDrive/Outlook URLs need 20 seconds to fully load PowerPoint Online
                # Regular pages only need 3 seconds
                is_onedrive_url = any(domain in url.lower() for domain in [
                    "onedrive.live.com", "outlook.live.com", "office.live.com",
                    "1drv.ms", "sharepoint.com"
                ])
                wait_ms = 20000 if is_onedrive_url else 3000
                
                steps.append({
                    "action": "pause",
                    "ms": wait_ms,
                    "description": f"Wait for page to load ({'OneDrive - 20s' if is_onedrive_url else '3s'})"
                })
            elif url == start_url:
                navigated_to_start = True

        # ===== CLICK =====
        elif "click" in action_item:
            actions_since_last_narration += 1
            selector = _extract_selector_from_element(element_str)
            element_text = _extract_text_from_element(element_str)
            
            # CRITICAL: Detect presentation-related clicks and convert to keyboard shortcuts
            # This prevents selector instability issues with PowerPoint Online buttons
            is_presentation_button = False
            if element_text:
                presentation_keywords = [
                    "slide show", "trình chiếu", "present", "slideshow",
                    "start presenting", "bắt đầu trình chiếu",
                    "next", "tiếp theo", "previous", "trước",
                    "exit", "thoát", "end show", "kết thúc"
                ]
                text_lower = element_text.lower()
                is_presentation_button = any(keyword in text_lower for keyword in presentation_keywords)
            
            # Also check selector for presentation-related IDs
            if not is_presentation_button and selector:
                selector_str = str(selector).lower()
                presentation_ids = [
                    "slideshow", "startslideshow", "nextslide", "previousslide",
                    "exitslideshow", "presentationmode"
                ]
                is_presentation_button = any(pid in selector_str for pid in presentation_ids)
            
            if is_presentation_button:
                # Convert presentation button clicks to keyboard shortcuts
                # OneDrive PowerPoint Online uses Shift+Ctrl+F5 to start slide show
                logger.info(f"[V3 Parser] Converting presentation button to keyboard shortcut: {element_text}")
                
                # Determine which key to use based on button text
                if element_text:
                    text_lower = element_text.lower()
                    if "start" in text_lower or "bắt đầu" in text_lower or "slide show" in text_lower or "trình chiếu" in text_lower or "trình bày" in text_lower:
                        # Start Slide Show -> Ctrl+F5 (OneDrive PowerPoint Online)
                        # CRITICAL: Must wait 8 seconds for presentation mode to be ready
                        steps.append({
                            "action": "pause",
                            "ms": 2000,
                            "description": "Wait before starting slide show"
                        })
                        steps.append({
                            "action": "key",
                            "key": "Control+F5",
                            "description": "Press Ctrl+F5 to start Slide Show"
                        })
                        steps.append({
                            "action": "pause",
                            "ms": 8000,
                            "description": "Wait 8 seconds for slide show to be ready"
                        })
                    elif "next" in text_lower or "tiếp theo" in text_lower:
                        # Next slide -> ArrowRight (Space doesn't work reliably in PowerPoint Online)
                        # CRITICAL: Must wait 2 seconds after each slide advance
                        steps.append({
                            "action": "key",
                            "key": "ArrowRight",
                            "description": "Press ArrowRight to advance slide"
                        })
                        steps.append({
                            "action": "pause",
                            "ms": 2000,
                            "description": "Wait 2 seconds after advancing slide"
                        })
                        narration_advanced_since_last = True
                    elif "previous" in text_lower or "trước" in text_lower or "back" in text_lower:
                        # Previous slide -> ArrowLeft
                        steps.append({
                            "action": "key",
                            "key": "ArrowLeft",
                            "description": "Press ArrowLeft to go back"
                        })
                        steps.append({
                            "action": "pause",
                            "ms": 1000,
                            "description": "Wait after going back"
                        })
                    elif "exit" in text_lower or "thoát" in text_lower or "end" in text_lower or "kết thúc" in text_lower:
                        # Exit slide show -> Escape
                        steps.append({
                            "action": "key",
                            "key": "Escape",
                            "description": "Press Escape to exit slide show"
                        })
                        steps.append({
                            "action": "pause",
                            "ms": 2000,
                            "description": "Wait after exiting slide show"
                        })
                    else:
                        # Generic presentation button -> Ctrl+F5 (most common for OneDrive)
                        steps.append({
                            "action": "pause",
                            "ms": 1000,
                            "description": "Wait before action"
                        })
                        steps.append({
                            "action": "key",
                            "key": "Control+F5",
                            "description": f"Press Ctrl+F5 for: {element_text}"
                        })
                        steps.append({
                            "action": "pause",
                            "ms": 3000,
                            "description": "Wait after key press"
                        })
                else:
                    # No text, but detected as presentation button -> Ctrl+F5
                    steps.append({
                        "action": "pause",
                        "ms": 1000,
                        "description": "Wait before starting"
                    })
                    steps.append({
                        "action": "key",
                        "key": "Control+F5",
                        "description": "Press Ctrl+F5 to start presentation"
                    })
                    steps.append({
                        "action": "pause",
                        "ms": 3000,
                        "description": "Wait for presentation to start"
                    })
            elif selector is not None:  # Normal click (not presentation-related)
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
            actions_since_last_narration += 1
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
            actions_since_last_narration += 1
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
            actions_since_last_narration += 1
            keys_data = action_item["send_keys"]
            keys = keys_data.get("keys", "") if isinstance(keys_data, dict) else str(keys_data)
            if keys:
                # CRITICAL: Detect presentation keyboard shortcuts and add proper wait times
                keys_lower = keys.lower()
                
                # Ctrl+F5 or Shift+Ctrl+F5 -> Start Slide Show (needs 8s wait)
                if "f5" in keys_lower and ("ctrl" in keys_lower or "control" in keys_lower):
                    steps.append({
                        "action": "key",
                        "key": keys,
                        "description": "Press Ctrl+F5 to start Slide Show"
                    })
                    steps.append({
                        "action": "pause",
                        "ms": 8000,
                        "description": "Wait 8 seconds for slide show to be ready"
                    })
                # ArrowRight -> Next slide (needs 2s wait)
                elif "arrowright" in keys_lower or keys == "ArrowRight":
                    steps.append({
                        "action": "key",
                        "key": "ArrowRight",
                        "description": "Press ArrowRight to advance slide"
                    })
                    steps.append({
                        "action": "pause",
                        "ms": 2000,
                        "description": "Wait 2 seconds after advancing slide"
                    })
                    narration_advanced_since_last = True
                # ArrowLeft -> Previous slide (needs 2s wait)
                elif "arrowleft" in keys_lower or keys == "ArrowLeft":
                    steps.append({
                        "action": "key",
                        "key": "ArrowLeft",
                        "description": "Press ArrowLeft to go back"
                    })
                    steps.append({
                        "action": "pause",
                        "ms": 2000,
                        "description": "Wait 2 seconds after going back"
                    })
                # Escape -> Exit slide show (needs 2s wait)
                elif "escape" in keys_lower or keys == "Escape":
                    steps.append({
                        "action": "key",
                        "key": "Escape",
                        "description": "Press Escape to exit slide show"
                    })
                    steps.append({
                        "action": "pause",
                        "ms": 2000,
                        "description": "Wait after exiting slide show"
                    })
                # Other keys -> no special wait
                else:
                    steps.append({"action": "key", "key": keys})

        # ===== EXTRACT -> scroll to show content =====
        elif "extract" in action_item:
            for _ in range(3):
                steps.append({"action": "scroll", "y": 500})
                steps.append({"action": "pause", "ms": 2000})

        # ===== done, write_file, etc. -> SKIP =====

    # ===== DEDUPLICATION: Remove consecutive duplicate key presses =====
    # This prevents agent loop spam (e.g., 16x Escape in a row)
    deduplicated_steps = []
    last_key_action = None
    consecutive_count = 0
    MAX_CONSECUTIVE_KEYS = 3  # Allow max 3 consecutive identical key presses
    
    for step in steps:
        # Track consecutive key presses
        if step.get("action") == "key":
            current_key = step.get("key")
            if current_key == last_key_action:
                consecutive_count += 1
                if consecutive_count > MAX_CONSECUTIVE_KEYS:
                    logger.warning(f"[V3 Parser] Skipping duplicate key press #{consecutive_count}: {current_key}")
                    continue  # Skip this duplicate
            else:
                last_key_action = current_key
                consecutive_count = 1
        else:
            # Reset counter on non-key actions
            last_key_action = None
            consecutive_count = 0
        
        deduplicated_steps.append(step)
    
    removed_count = len(steps) - len(deduplicated_steps)
    if removed_count > 0:
        logger.info(f"[V3 Parser] Removed {removed_count} duplicate key presses (agent loop spam)")
    
    steps = deduplicated_steps

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
        "theme": {
            "cursor": {
                "size": 24,
                "hotspot": "top-left"
            }
        },
        "defaultDelay": 300,
        "fps": int(os.getenv("WEBREEL_FPS", "12")),
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
