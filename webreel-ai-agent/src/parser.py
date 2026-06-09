import os
import json
import re

from .models import ParsedAction

# Use Gemini (google-genai SDK) if available, else fall back to Azure AI (GitHub Models)
try:
    from google import genai
    from google.genai import types as genai_types
    _BACKEND = "gemini"
except ImportError:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage, UserMessage
    from azure.core.credentials import AzureKeyCredential
    _BACKEND = "azure"

AZURE_ENDPOINT = "https://models.github.ai/inference"
AZURE_MODEL = "meta/Llama-4-Scout-17B-16E-Instruct"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

SYSTEM_PROMPT = """Bạn là AI parser chuyển đổi lệnh ngôn ngữ tự nhiên thành các bước thao tác UI trên trình duyệt.

QUY TẮC:
1. Tách mỗi câu lệnh thành các action riêng lẻ, rõ ràng.
2. Giữ nguyên mô tả "target" bằng tiếng Việt - đây là mô tả cho Vision AI nhận diện.
3. Trả về JSON object với key "actions" chứa array. KHÔNG thêm bất kỳ text nào ngoài JSON.
4. Nếu URL không có scheme, tự thêm "https://".
5. Với các form tìm kiếm (Google, YouTube, etc.), dùng action "key" với "Enter" thay vì click nút tìm kiếm.

CÁC ACTION HỖ TRỢ:
- navigate: Mở URL (cần có "url")
- click: Click vào element (cần có "target" - mô tả element bằng tiếng Việt)
- type: Gõ text (cần có "text" và "target")
- key: Nhấn phím (cần có "key" - ví dụ: "Enter", "Escape", "Tab")
- scroll: Cuộn trang (cần có "direction": "up" hoặc "down")
- pause: Đợi (cần có "ms" tính bằng milliseconds)

VÍ DỤ 1:
Input: "Mở google.com, gõ 'hello world' vào ô tìm kiếm, tìm kiếm"
Output:
{
  "actions": [
    {"action": "navigate", "url": "https://google.com"},
    {"action": "type", "text": "hello world", "target": "ô tìm kiếm Google"},
    {"action": "key", "key": "Enter"}
  ]
}

VÍ DỤ 2:
Input: "Mở vnexpress.net, click bài viết đầu tiên, cuộn xuống xem nội dung"
Output:
{
  "actions": [
    {"action": "navigate", "url": "https://vnexpress.net"},
    {"action": "click", "target": "bài viết đầu tiên trong danh sách tin tức"},
    {"action": "scroll", "direction": "down"}
  ]
}

VÍ DỤ 3:
Input: "Vào github.com, đăng nhập với tài khoản test@email.com"
Output:
{
  "actions": [
    {"action": "navigate", "url": "https://github.com/login"},
    {"action": "type", "text": "test@email.com", "target": "ô nhập username hoặc email"},
    {"action": "click", "target": "nút Sign in"}
  ]
}

VÍ DỤ 4:
Input: "Tìm kiếm Python trên Google"
Output:
{
  "actions": [
    {"action": "navigate", "url": "https://google.com"},
    {"action": "type", "text": "Python", "target": "ô tìm kiếm Google"},
    {"action": "key", "key": "Enter"}
  ]
}"""


def _call_llm(prompt: str) -> str:
    """Goi LLM backend hien co (Gemini -> Azure fallback)."""
    if _BACKEND == "gemini":
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.1,
                max_output_tokens=1000,
            ),
        )
        return response.text
    else:
        client = ChatCompletionsClient(
            endpoint=AZURE_ENDPOINT,
            credential=AzureKeyCredential(os.environ["GITHUB_TOKEN"]),
        )
        response = client.complete(
            messages=[SystemMessage(SYSTEM_PROMPT), UserMessage(prompt)],
            model=AZURE_MODEL,
            temperature=0.1,
            max_tokens=1000,
        )
        return response.choices[0].message.content


def parse_natural_language(user_input: str) -> list[ParsedAction]:
    """
    Parse natural language input into a list of structured actions.

    Args:
        user_input: User command in Vietnamese or English.

    Returns:
        List of ParsedAction objects.
    """
    content = _call_llm(user_input)
    # Extract JSON block in case the model wraps it in markdown code fences
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        content = match.group(0)
    data = json.loads(content)

    actions = []
    for item in data.get("actions", []):
        actions.append(ParsedAction(**item))

    return actions
