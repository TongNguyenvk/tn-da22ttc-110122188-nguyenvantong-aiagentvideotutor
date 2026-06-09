from playwright.sync_api import Page

# JavaScript injected into the browser to extract a unique CSS selector
# for the element at a given (x, y) coordinate.
_SELECTOR_JS = """
(coords) => {
    const { x, y } = coords;
    const el = document.elementFromPoint(x, y);
    if (!el) return null;

    // Strategy 1: ID
    if (el.id) {
        return '#' + el.id;
    }

    // Strategy 2: data-testid / data-id / aria-label
    for (const attr of ['data-testid', 'data-id', 'data-cy']) {
        const val = el.getAttribute(attr);
        if (val) return `[${attr}="${val}"]`;
    }

    // Strategy 3: Unique class combination
    if (el.className && typeof el.className === 'string') {
        const classes = el.className.trim().split(/\\s+/).filter(c => c.length > 0);
        if (classes.length > 0) {
            const candidate = el.tagName.toLowerCase() + '.' + classes.join('.');
            if (document.querySelectorAll(candidate).length === 1) {
                return candidate;
            }
        }
    }

    // Strategy 4: Tag + visible text (for buttons and links < 50 chars)
    const text = el.textContent?.trim();
    if (text && text.length > 0 && text.length < 50) {
        const tag = el.tagName.toLowerCase();
        if (['button', 'a', 'span', 'label'].includes(tag)) {
            const escaped = text.replace(/"/g, '\\"').substring(0, 30);
            const candidate = `${tag}:has-text("${escaped}")`;
            try {
                // Playwright supports :has-text; validate count via querySelectorAll fallback
                const matches = Array.from(document.querySelectorAll(tag))
                    .filter(e => e.textContent?.trim().startsWith(escaped.substring(0, 15)));
                if (matches.length === 1) return candidate;
            } catch (_) {}
        }
    }

    // Strategy 5: Build structural path using nth-of-type
    function buildPath(node) {
        if (!node || node === document.body) return 'body';
        if (node.id) return '#' + node.id;

        const parent = node.parentElement;
        if (!parent) return node.tagName.toLowerCase();

        const sameTagSiblings = Array.from(parent.children)
            .filter(c => c.tagName === node.tagName);

        const tag = node.tagName.toLowerCase();
        const suffix = sameTagSiblings.length > 1
            ? `:nth-of-type(${sameTagSiblings.indexOf(node) + 1})`
            : '';

        return buildPath(parent) + ' > ' + tag + suffix;
    }

    return buildPath(el);
}
"""


def extract_selector_from_coordinates(page: Page, x: int, y: int) -> str | None:
    """
    Use document.elementFromPoint() to identify the DOM element at (x, y)
    and return a unique CSS selector for it.

    Args:
        page: Active Playwright Page.
        x: Horizontal pixel coordinate.
        y: Vertical pixel coordinate.

    Returns:
        CSS selector string, or None if no element found.
    """
    return page.evaluate(_SELECTOR_JS, {"x": x, "y": y})


def validate_selector(
    page: Page,
    selector: str,
    expected_x: int,
    expected_y: int,
    tolerance: int = 60,
) -> bool:
    """
    Verify that the selector resolves to an element whose center is close
    to the expected coordinates.

    Args:
        page: Active Playwright Page.
        selector: CSS selector to validate.
        expected_x: Expected center X.
        expected_y: Expected center Y.
        tolerance: Max allowed pixel distance.

    Returns:
        True if the selector is valid and close enough.
    """
    try:
        # :has-text selectors are Playwright-only; use query_selector safely
        element = page.query_selector(selector)
        if not element:
            return False

        box = element.bounding_box()
        if not box:
            return False

        center_x = box["x"] + box["width"] / 2
        center_y = box["y"] + box["height"] / 2
        distance = ((center_x - expected_x) ** 2 + (center_y - expected_y) ** 2) ** 0.5

        return distance <= tolerance
    except Exception:
        return False


# JavaScript to find the nearest input/textarea element at or near coordinates
_INPUT_SELECTOR_JS = """
(coords) => {
    const { x, y } = coords;
    const el = document.elementFromPoint(x, y);
    if (!el) return null;

    // Helper: check if input is a text-type input (not button/submit/hidden)
    function isTextInput(elem) {
        if (elem.tagName === 'TEXTAREA') return true;
        if (elem.tagName === 'INPUT') {
            const type = (elem.getAttribute('type') || 'text').toLowerCase();
            // Include text-like input types only
            const textTypes = ['text', 'search', 'email', 'password', 'tel', 'url', 'number'];
            return textTypes.includes(type);
        }
        return false;
    }

    // Helper: get unique selector for an element
    function getSelector(elem) {
        if (elem.id) return '#' + elem.id;
        
        // For inputs, prefer name attribute (but only for text inputs)
        if (elem.getAttribute('name') && isTextInput(elem)) {
            return `${elem.tagName.toLowerCase()}[name="${elem.getAttribute('name')}"]`;
        }
        
        for (const attr of ['data-testid', 'data-id', 'aria-label']) {
            const val = elem.getAttribute(attr);
            if (val) return `${elem.tagName.toLowerCase()}[${attr}="${val}"]`;
        }
        
        if (elem.className && typeof elem.className === 'string') {
            const classes = elem.className.trim().split(/\\s+/).filter(c => c.length > 0);
            if (classes.length > 0) {
                const candidate = elem.tagName.toLowerCase() + '.' + classes.join('.');
                if (document.querySelectorAll(candidate).length === 1) {
                    return candidate;
                }
            }
        }
        
        // Fallback: tag + type for inputs
        if (elem.tagName === 'INPUT') {
            const type = elem.getAttribute('type') || 'text';
            return `input[type="${type}"]`;
        }
        if (elem.tagName === 'TEXTAREA') {
            return 'textarea';
        }
        
        return null;
    }

    // Check if the element itself is a text input
    if (isTextInput(el)) {
        return getSelector(el);
    }

    // Look for text inputs inside the element
    const inputs = el.querySelectorAll('input, textarea');
    const textInputs = Array.from(inputs).filter(isTextInput);
    if (textInputs.length === 1) {
        return getSelector(textInputs[0]);
    }
    if (textInputs.length > 1) {
        // Return the first visible one
        for (const inp of textInputs) {
            const rect = inp.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                return getSelector(inp);
            }
        }
    }

    // Look in parent elements for a containing text input
    let parent = el.parentElement;
    for (let depth = 0; depth < 5 && parent; depth++) {
        const parentInputs = parent.querySelectorAll('input, textarea');
        const parentTextInputs = Array.from(parentInputs).filter(isTextInput);
        if (parentTextInputs.length === 1) {
            return getSelector(parentTextInputs[0]);
        }
        if (parentTextInputs.length > 0) {
            // Find the closest text input to the click coordinates
            let closest = null;
            let minDist = Infinity;
            for (const inp of parentTextInputs) {
                const rect = inp.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                const cx = rect.left + rect.width / 2;
                const cy = rect.top + rect.height / 2;
                const dist = Math.sqrt((cx - x) ** 2 + (cy - y) ** 2);
                if (dist < minDist) {
                    minDist = dist;
                    closest = inp;
                }
            }
            if (closest && minDist < 200) {
                return getSelector(closest);
            }
        }
        parent = parent.parentElement;
    }

    // Fallback: search entire document for text inputs near the click point
    const allInputs = document.querySelectorAll('input, textarea');
    const allTextInputs = Array.from(allInputs).filter(isTextInput);
    let closest = null;
    let minDist = Infinity;
    for (const inp of allTextInputs) {
        const rect = inp.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        const cx = rect.left + rect.width / 2;
        const cy = rect.top + rect.height / 2;
        const dist = Math.sqrt((cx - x) ** 2 + (cy - y) ** 2);
        if (dist < minDist) {
            minDist = dist;
            closest = inp;
        }
    }
    
    if (closest && minDist < 100) {
        return getSelector(closest);
    }

    return null;
}
"""


def extract_input_selector(page: Page, x: int, y: int) -> str | None:
    """
    Find the nearest input/textarea element at or near the given coordinates.
    
    This is specifically designed for 'type' actions where we need to find
    an actual input element, not a wrapper div.

    Args:
        page: Active Playwright Page.
        x: Horizontal pixel coordinate.
        y: Vertical pixel coordinate.

    Returns:
        CSS selector for an input/textarea element, or None if not found.
    """
    return page.evaluate(_INPUT_SELECTOR_JS, {"x": x, "y": y})
