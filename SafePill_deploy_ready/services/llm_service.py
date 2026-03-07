import json
import os
from typing import Dict, List, Optional


def _env_enabled(name: str, default: str = "0") -> bool:
    value = str(os.getenv(name, default) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _clean_list(items: Optional[List[str]]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items or []:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _extract_json_object(raw: str) -> Optional[Dict]:
    text = str(raw or "").strip()
    if not text:
        return None

    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def generate_llm_guidance(payload: Dict) -> Optional[Dict]:
    """환경변수가 켜진 경우에만 LLM으로 복약 안내 문구를 생성한다.

    - SAFEPILL_ENABLE_LLM=1 일 때만 동작
    - OPENAI_API_KEY 또는 SAFEPILL_OPENAI_API_KEY 필요
    - 실패하면 None 반환 (서버는 템플릿 설명으로 자동 폴백)
    """
    if not _env_enabled("SAFEPILL_ENABLE_LLM"):
        return None

    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SAFEPILL_OPENAI_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except Exception:
        return None

    subject = str(payload.get("subject") or "이 약").strip() or "이 약"
    risk = str(payload.get("risk") or "특이사항 없음").strip() or "특이사항 없음"
    reason = str(payload.get("reason_text") or "").strip()
    new_active_ingredients = _clean_list(payload.get("new_active_ingredients"))
    current_active_ingredients = _clean_list(payload.get("current_active_ingredients"))
    overlap_active_ingredients = _clean_list(payload.get("overlap_active_ingredients"))
    compare_basis = _clean_list(payload.get("compare_basis"))
    selected_current_labels = _clean_list(payload.get("selected_current_labels"))

    client = OpenAI(api_key=api_key)
    model = os.getenv("SAFEPILL_LLM_MODEL", "gpt-4o-mini")

    system_prompt = (
        "당신은 다정하지만 과장하지 않는 한국어 복약 도우미입니다. "
        "반드시 제공된 사실만 사용하고, 병용 판정 자체를 새로 만들지 말고 이미 계산된 risk와 reason만 풀어서 설명하세요. "
        "출력은 반드시 JSON 하나만 반환하세요."
    )

    user_payload = {
        "subject": subject,
        "risk": risk,
        "reason_text": reason,
        "new_active_ingredients": new_active_ingredients,
        "current_active_ingredients": current_active_ingredients,
        "overlap_active_ingredients": overlap_active_ingredients,
        "compare_basis": compare_basis,
        "selected_current_labels": selected_current_labels,
        "output_schema": {
            "friendly_summary": "1~2문장 요약",
            "action_items": ["사용자 행동 지침 2~4개"],
            "explanation_lines": ["쉬운 말 설명 2~4개"]
        }
    }

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        )
        content = response.choices[0].message.content or ""
    except Exception:
        return None

    data = _extract_json_object(content)
    if not data:
        return None

    friendly_summary = str(data.get("friendly_summary") or "").strip()
    action_items = _clean_list(data.get("action_items") if isinstance(data.get("action_items"), list) else [])
    explanation_lines = _clean_list(data.get("explanation_lines") if isinstance(data.get("explanation_lines"), list) else [])

    if not friendly_summary and not action_items and not explanation_lines:
        return None

    return {
        "mode": "llm",
        "friendly_summary": friendly_summary,
        "action_items": action_items[:4],
        "explanation_lines": explanation_lines[:4],
    }
